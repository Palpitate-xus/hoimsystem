"""Actual synthetic SQL safe Source through bounded mocked text-provider HTTP.

No shared runtime dispatch, worker, real model service or hospital data is claimed.
"""

import copy
import hashlib
import json
from types import SimpleNamespace

import httpx
import pytest

from app.ai.catalog import FEATURE_BY_KEY
from app.ai.gateway import AIExecutionError
from app.ai.models import AIProvider
from app.ai.review_curation import create_excerpt, load_review_source, review_excerpt
from app.ai.satisfaction_context import expand_context, public_payload, satisfaction_context
from app.ai.satisfaction_draft import MAX_BYTES, canonical_json
from app.ai.satisfaction_gateway import generate_satisfaction, matches_satisfaction_request, request
from app.ai.satisfaction_prompt import SATISFACTION_SYSTEM_PROMPT, SATISFACTION_TASK_PROMPT
from app.ai.satisfaction_sources import revoke_case
from app.ai.schemas import ReviewExcerptReview, ReviewExcerptWrite
from tests.test_ai_satisfaction_sources import BASIS, published
from tests.test_ai_satisfaction_sources import satisfaction_case as satisfaction_case  # noqa: F401

SPEC = FEATURE_BY_KEY["feedback_analysis"]
CUSTOM_TASK = "自定义受审Task版本：只核对原摘录中的实际问题，不改变固定契约。\ufeff\r\n🧪"


def provider(kind="chat"):
    return AIProvider(
        kind=kind, model="synthetic-reviewed-themes", api_base="http://127.0.0.1:11434/v1", api_key_env="", api_key_encrypted="", max_output_tokens=4096, timeout_seconds=5, temperature=0
    )


@pytest.fixture
def gateway_case(db_session, satisfaction_case):
    db, case = db_session, satisfaction_case
    # Use original legacy writers, then actual whole Source capture/publication;
    # no hand-written positive Source wrapper or invented governance flags.
    original = load_review_source(db, case["review"].review_id)
    excerpt = create_excerpt(
        db,
        case["super_admin_user"],
        ReviewExcerptWrite(
            review_id=case["review"].review_id,
            expected_source_hash=original.fingerprint,
            redacted_text="\ufeff合成候诊顺序\r\n🧪需要人工补充解释。",
            change_note="隔离合成人工逐字检查，不代表医院真实验证。",
        ),
    )
    db.commit()
    case["excerpt"] = review_excerpt(
        db,
        case["super_admin_user"],
        excerpt.excerpt_id,
        ReviewExcerptReview(expected_revision=1, status="published", privacy_checked=True, faithfulness_checked=True, review_note="合成隐私和原意核查声明，不保证匿名。"),
    )
    db.commit()
    made = published(db, case)
    values = {"satisfaction_case_id": made["case_id"], "question": "请核对原摘录提到的顺序🧪。"}
    bundle = satisfaction_context(db, case["admin_user"], values)
    data = {"input": values, "context": expand_context(db, bundle.data, user=case["admin_user"], current=True), "tools": {}, "evidence": bundle.evidence}
    source = made["public_source"]
    selected = source["safe_snapshot"]["selected_excerpts"][0]
    draft = {
        "schema_version": "satisfaction_evidence_draft_v1",
        "satisfaction_source_id": source["source_id"],
        "safe_projection_hash": source["safe_projection_hash"],
        "coverage": "partial_themes_no_population_or_causality_claim",
        "themes": [
            {
                "title": "候诊顺序澄清",
                "observation": "这条已选择人工摘录提及顺序，实际情况仍需人工核对。",
                "clarification_question": "能否补充当次候诊顺序的可核实说明？",
                "cited_excerpt_tokens": [selected["excerpt_token"]],
                "citations": [{"excerpt_token": selected["excerpt_token"], "text_hash": selected["text_hash"], "start": 0, "end": len(selected["text"]), "quote": selected["text"]}],
            }
        ],
    }
    # The HTTP adapter does no SQL and does not retain this read transaction over
    # its await. Runtime is responsible for its own post-call current recheck.
    db.rollback()
    return {**case, "made": made, "data": data, "draft": draft}


def envelope(kind, draft):
    raw = draft if type(draft) is str else canonical_json(draft)
    if kind == "chat":
        return {"choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": raw}}], "usage": {"prompt_tokens": 13, "completion_tokens": 7}}
    return {
        "status": "completed",
        "output": [{"type": "message", "role": "assistant", "status": "completed", "content": [{"type": "output_text", "text": raw}]}],
        "usage": {"input_tokens": 13, "output_tokens": 7},
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["chat", "responses"])
@pytest.mark.parametrize("task", [SATISFACTION_TASK_PROMPT, CUSTOM_TASK])
async def test_actual_sql_safe_source_only_one_complete_call_and_actual_versioned_task(gateway_case, kind, task):
    case = gateway_case
    original = copy.deepcopy(case["data"])
    calls = []

    def handle(req):
        payload = json.loads(req.content)
        calls.append(payload)
        assert req.method == "POST" and payload["store"] is False and req.headers["content-type"] == "application/json"
        if kind == "chat":
            assert req.url.path == "/v1/chat/completions"
            assert set(payload) == {"model", "messages", "response_format", "temperature", "max_tokens", "store"}
            instructions = payload["messages"][0]["content"]
            visible = json.loads(payload["messages"][1]["content"])
        else:
            assert req.url.path == "/v1/responses"
            assert set(payload) == {"model", "instructions", "input", "text", "max_output_tokens", "store"}
            instructions, visible = payload["instructions"], json.loads(payload["input"])
            schema = payload["text"]["format"]["schema"]
            assert schema["additionalProperties"] is False
            assert set(schema["required"]) == {"schema_version", "satisfaction_source_id", "safe_projection_hash", "coverage", "themes"}
        assert instructions == SATISFACTION_SYSTEM_PROMPT + "\n\n" + task
        assert hashlib.sha256(instructions.encode()).hexdigest() == hashlib.sha256((SATISFACTION_SYSTEM_PROMPT + "\n\n" + task).encode()).hexdigest()
        assert visible == public_payload(case["data"]) and set(visible) == {"satisfaction_source", "question"}
        encoded = canonical_json(visible)
        for private in (case["review"].comment, case["patient"].name, case["patient"].identity, case["visit"].medical_record_id, case["made"]["snapshot"]["identity_secret"], BASIS):
            assert private not in encoded
        assert '"patient_id"' not in encoded and '"visit_id"' not in encoded and '"snapshot"' not in encoded
        assert "\ufeff" in encoded and "🧪" in encoded and "\\r\\n" in encoded
        return httpx.Response(200, json=envelope(kind, case["draft"]))

    result, inputs, outputs = await generate_satisfaction(provider(kind), SPEC, task, case["data"], transport=httpx.MockTransport(handle))
    assert len(calls) == 1 and (inputs, outputs) == (13, 7)
    assert result.satisfaction_analysis.model_dump(mode="json") == case["draft"] and case["data"] == original
    assert result.recorded_statistics.all_member_statistics.model_dump(mode="json") == case["made"]["public_source"]["safe_snapshot"]["all_member_statistics"]


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ["private_body", "raw_snapshot", "tools", "evidence", "source", "foreign_ref", "frozen_flags", "audit_revoke"])
async def test_mixed_source_or_raw_audit_payload_fails_before_any_http(gateway_case, mutation, db_session):
    case, calls = gateway_case, []
    data = copy.deepcopy(case["data"])
    if mutation == "private_body":
        data["raw_comment"] = "private patient comment"
    elif mutation == "raw_snapshot":
        data["context"]["satisfaction_case"]["snapshot"] = case["made"]["snapshot"]
    elif mutation == "tools":
        data["tools"] = {"write_review": True}
    elif mutation == "evidence":
        data["evidence"] = []
    elif mutation == "source":
        data["context"]["satisfaction_source"]["safe_snapshot"]["selected_excerpts"][0]["text"] += "新内容"
    elif mutation == "foreign_ref":
        data["input"]["coding_case_id"] = case["made"]["case_id"]
    elif mutation == "frozen_flags":
        data["context"]["satisfaction_case"]["can_revoke"] = True
    else:
        revoke_case(db_session, case["super_admin_user"], case["made"]["case_id"], {"expected_revision": 2, "basis_note": BASIS})
        data["context"] = expand_context(db_session, {k: v for k, v in case["data"]["context"].items() if k not in {"satisfaction_source", "satisfaction_case"}})
    with pytest.raises(AIExecutionError) as error:
        await generate_satisfaction(provider(), SPEC, CUSTOM_TASK, data, transport=httpx.MockTransport(lambda req: calls.append(req)))
    assert not calls and error.value.code == "SATISFACTION_SOURCE_REQUIRED"
    assert error.value.model_call_attempted is False and error.value.input_tokens is error.value.output_tokens is None


@pytest.mark.asyncio
@pytest.mark.parametrize("task", [None, False, [], " \r\n\t", "surrogate\ud800", "x" * 65536])
async def test_incomplete_or_oversize_actual_task_never_calls_provider(gateway_case, task):
    calls = []
    with pytest.raises(AIExecutionError) as error:
        await generate_satisfaction(provider(), SPEC, task, gateway_case["data"], transport=httpx.MockTransport(lambda req: calls.append(req)))
    assert not calls and error.value.model_call_attempted is False


def test_exact_task_text_byte_boundary_and_zero_tools(gateway_case):
    _, body = request(provider(), SPEC, "x" * 65535, gateway_case["data"])
    assert body["messages"][0]["content"].endswith("x" * 65535)
    assert not {"tools", "tool_choice", "functions", "function_call"} & body.keys()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["chat", "responses"])
@pytest.mark.parametrize("mutation", ["foreign_source", "false_quote", "invented_statistics", "full_coverage", "duplicate_draft", "refusal", "tool", "incomplete", "two_messages"])
async def test_paid_unusable_reply_retains_actual_usage_without_invented_statistics(gateway_case, kind, mutation):
    draft = copy.deepcopy(gateway_case["draft"])
    if mutation == "foreign_source":
        draft["satisfaction_source_id"] = "satisfaction_case:another"
    elif mutation == "false_quote":
        draft["themes"][0]["citations"][0]["quote"] += "新增"
    elif mutation == "invented_statistics":
        draft["satisfaction_rate"] = 100
    elif mutation == "full_coverage":
        draft["coverage"] = "all_patient_population_satisfied"
    elif mutation == "duplicate_draft":
        draft = canonical_json(draft).replace('"themes":', '"themes":[],"themes":', 1)
    response = envelope(kind, draft)
    if mutation in {"refusal", "tool", "incomplete", "two_messages"}:
        message = response["choices"][0]["message"] if kind == "chat" else response["output"][0]
        if mutation == "refusal":
            message["refusal"] = "synthetic refusal"
        elif mutation == "tool":
            message["tool_calls"] = []
        elif mutation == "incomplete":
            if kind == "chat":
                response["choices"][0]["finish_reason"] = "length"
            else:
                response["status"] = "incomplete"
        elif kind == "chat":
            response["choices"].append(copy.deepcopy(response["choices"][0]))
        else:
            response["output"].append(copy.deepcopy(response["output"][0]))
    calls = []

    def handle(req):
        calls.append(req)
        return httpx.Response(200, json=response)

    with pytest.raises(AIExecutionError) as error:
        await generate_satisfaction(provider(kind), SPEC, CUSTOM_TASK, gateway_case["data"], transport=httpx.MockTransport(handle))
    assert len(calls) == 1 and error.value.code == "INVALID_PROVIDER_RESPONSE" and error.value.model_call_attempted is True
    assert (error.value.input_tokens, error.value.output_tokens) == (13, 7)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["chat", "responses"])
@pytest.mark.parametrize("bad_count", [None, False, -1, 2.5, "7", 2000001])
async def test_usage_receipt_never_invents_missing_or_invalid_companion_count(gateway_case, kind, bad_count):
    response = envelope(kind, gateway_case["draft"])
    response["usage"]["completion_tokens" if kind == "chat" else "output_tokens"] = bad_count
    with pytest.raises(AIExecutionError) as error:
        await generate_satisfaction(provider(kind), SPEC, CUSTOM_TASK, gateway_case["data"], transport=httpx.MockTransport(lambda _: httpx.Response(200, json=response)))
    assert error.value.model_call_attempted is True and (error.value.input_tokens, error.value.output_tokens) == (13, None)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["chat", "responses"])
async def test_actual_zero_token_receipt_is_preserved_not_converted_to_missing(gateway_case, kind):
    response = envelope(kind, gateway_case["draft"])
    response["usage"] = {key: 0 for key in response["usage"]}
    _, inputs, outputs = await generate_satisfaction(provider(kind), SPEC, CUSTOM_TASK, gateway_case["data"], transport=httpx.MockTransport(lambda _: httpx.Response(200, json=response)))
    assert inputs == outputs == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["redirect", "timeout", "connection", "invalid_utf8", "oversize", "duplicate_json", "nonfinite"])
async def test_stream_transport_and_json_faults_are_bounded_with_one_attempt(gateway_case, fault):
    calls = []

    def handle(req):
        calls.append(req)
        if fault == "redirect":
            return httpx.Response(302, headers={"location": "https://unreachable.invalid/no-follow"})
        if fault == "timeout":
            raise httpx.ReadTimeout("synthetic timeout", request=req)
        if fault == "connection":
            raise httpx.ConnectError("synthetic no server", request=req)
        content = {"invalid_utf8": b"\xff", "oversize": b"x" * (MAX_BYTES + 1), "duplicate_json": b'{"usage":{},"usage":{}}', "nonfinite": b'{"usage":NaN}'}.get(fault)
        return httpx.Response(200, content=content)

    with pytest.raises(AIExecutionError) as error:
        await generate_satisfaction(provider(), SPEC, CUSTOM_TASK, gateway_case["data"], transport=httpx.MockTransport(handle))
    assert len(calls) == 1 and error.value.model_call_attempted is True
    assert error.value.input_tokens is error.value.output_tokens is None
    assert "unreachable.invalid" not in error.value.message and "usage" not in error.value.message
    if fault == "oversize":
        assert error.value.code == "RESPONSE_TOO_LARGE"


@pytest.mark.asyncio
async def test_request_entire_utf8_limit_precedes_model_call_even_with_oversize_config(gateway_case):
    model = provider()
    model.model = "x" * MAX_BYTES
    calls = []
    with pytest.raises(AIExecutionError) as error:
        await generate_satisfaction(model, SPEC, CUSTOM_TASK, gateway_case["data"], transport=httpx.MockTransport(lambda req: calls.append(req)))
    assert not calls and error.value.code == "SATISFACTION_REQUEST_LIMIT" and error.value.model_call_attempted is False


@pytest.mark.asyncio
async def test_missing_credential_or_unapproved_endpoint_stops_before_http(gateway_case):
    for model in (provider(),):
        model.api_key_env = "HOIM_SYNTHETIC_MISSING_SATISFACTION_KEY_70"
        with pytest.raises(AIExecutionError) as error:
            await generate_satisfaction(model, SPEC, CUSTOM_TASK, gateway_case["data"], transport=httpx.MockTransport(lambda _: pytest.fail("No call expected")))
        assert error.value.code == "PROVIDER_CONFIGURATION" and error.value.model_call_attempted is False
    model = provider()
    model.api_base = "http://not-allowed.invalid/v1"
    with pytest.raises(AIExecutionError) as error:
        await generate_satisfaction(model, SPEC, CUSTOM_TASK, gateway_case["data"], transport=httpx.MockTransport(lambda _: pytest.fail("No call expected")))
    assert error.value.code == "PROVIDER_CONFIGURATION" and error.value.model_call_attempted is False


def test_feature_or_retained_marker_classification_never_silently_downgrades(gateway_case):
    assert matches_satisfaction_request(SPEC, {})
    other = SimpleNamespace(number=1, key="other")
    for key in ("satisfaction_binding", "satisfaction_source", "satisfaction_case"):
        assert matches_satisfaction_request(other, {"context": {key: None}})
    assert matches_satisfaction_request(other, {"input": {"satisfaction_case_id": None}})
    assert not matches_satisfaction_request(other, {"input": {}, "context": {}})
    for spec, model in ((other, provider()), (SPEC, provider("specialist"))):
        with pytest.raises(AIExecutionError) as error:
            request(model, spec, CUSTOM_TASK, gateway_case["data"])
        assert error.value.code == "SATISFACTION_TEXT_PROVIDER_REQUIRED"
