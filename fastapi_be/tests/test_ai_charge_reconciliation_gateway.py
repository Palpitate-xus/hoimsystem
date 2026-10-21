"""Real synthetic SQL projection through one mocked provider HTTP call."""

import copy
import json

import httpx
import pytest

from app.ai import charge_reconciliation_context as context
from app.ai.catalog import FEATURE_BY_KEY
from app.ai.charge_reconciliation_draft import MAX_BYTES
from app.ai.charge_reconciliation_gateway import request
from app.ai.charge_reconciliation_prompt import CHARGE_RECONCILIATION_SYSTEM_PROMPT
from app.ai.gateway import AIExecutionError, _request, generate
from app.ai.models import AIProvider
from tests.test_ai_charge_reconciliation_context import bundle, payload, selected
from tests.test_ai_charge_reconciliation_sources import NOTE, published
from tests.test_ai_charge_reconciliation_sources import charge_case as _charge_case

charge_case = _charge_case
SPEC = FEATURE_BY_KEY["charge_reconciliation"]


def provider(kind="chat"):
    return AIProvider(kind=kind, model="synthetic-text", api_base="http://127.0.0.1:11434/v1", api_key_env="", api_key_encrypted="", max_output_tokens=4096, timeout_seconds=5, temperature=0)


def data_for(case):
    value = published(case)
    short = bundle(case, value)
    expanded = context.expand_context(case["db"], short.data, user=case["super_admin_user"], current=True)
    data = payload(expanded, selected(case, value))
    row = expanded["charge_source"]["charges"][0]
    draft = {
        "schema_version": "charge_reconciliation_draft_v1",
        "source_id": value["source_id"],
        "source_projection_hash": value["projection_hash"],
        "coverage": "partial_questions_no_completeness_or_correctness_claim",
        "observations": [
            {
                "kind": "association_question",
                "referenced_source_ids": [row["source_id"]],
                "review_note": "请核对这条记录的实际关联依据。",
                "clarification_question": "是否存在尚未提供的逐项执行依据？",
                "citations": [{"source_id": row["source_id"], "field": "item_name", "start": 0, "end": len(row["item_name"]), "quote": row["item_name"]}],
            }
        ],
    }
    return data, draft, value


def envelope(kind, draft):
    text = draft if isinstance(draft, str) else json.dumps(draft, ensure_ascii=False)
    if kind == "chat":
        return {"choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": text}}], "usage": {"prompt_tokens": 13, "completion_tokens": 7}}
    return {
        "status": "completed",
        "output": [{"type": "message", "role": "assistant", "status": "completed", "content": [{"type": "output_text", "text": text}]}],
        "usage": {"input_tokens": 13, "output_tokens": 7},
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["chat", "responses"])
async def test_one_actual_projection_call_keeps_private_case_local_and_exact_system_task(charge_case, kind):
    case = charge_case
    data, draft, value = data_for(case)
    original = copy.deepcopy(data)
    calls = []

    def handle(req):
        packet = json.loads(req.content)
        calls.append(packet)
        if kind == "chat":
            assert req.url.path == "/v1/chat/completions"
            assert set(packet) == {"model", "messages", "response_format", "temperature", "max_tokens"}
            assert packet["messages"][0]["content"] == CHARGE_RECONCILIATION_SYSTEM_PROMPT + "\n\n" + SPEC.task_prompt
            visible = json.loads(packet["messages"][1]["content"])
        else:
            assert req.url.path == "/v1/responses" and packet["store"] is False
            assert set(packet) == {"model", "instructions", "input", "text", "max_output_tokens", "store"}
            assert packet["instructions"] == CHARGE_RECONCILIATION_SYSTEM_PROMPT + "\n\n" + SPEC.task_prompt
            schema = packet["text"]["format"]["schema"]
            assert packet["text"]["format"]["strict"] is True
            assert schema["additionalProperties"] is False and set(schema["required"]) == {"schema_version", "source_id", "source_projection_hash", "coverage", "observations"}
            visible = json.loads(packet["input"])
        assert visible == context.public_payload(data)
        encoded = json.dumps(visible, ensure_ascii=False)
        for private in (
            case["patient"].name,
            case["patient"].identity,
            case["admission"].admission_id,
            value["snapshot"]["identity_secret"],
            NOTE,
            "private-only-patient",
            "private-only-drug",
            '"snapshot"',
        ):
            assert private not in encoded
        return httpx.Response(200, json=envelope(kind, draft))

    result, inputs, outputs = await generate(provider(kind), SPEC, SPEC.task_prompt, data, transport=httpx.MockTransport(handle))
    assert len(calls) == 1 and (inputs, outputs) == (13, 7)
    assert result.charge_analysis.model_dump(mode="json") == draft
    assert "覆盖范围不完整" in result.summary and data == original


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["chat", "responses"])
@pytest.mark.parametrize("mutation", ["foreign_source", "changed_quote", "new_amount", "complete_coverage", "duplicate_key"])
async def test_unaccepted_model_draft_retains_paid_usage_without_financial_output(charge_case, kind, mutation):
    data, draft, _ = data_for(charge_case)
    if mutation == "foreign_source":
        draft["source_id"] = "charge_case:another"
    elif mutation == "changed_quote":
        draft["observations"][0]["citations"][0]["quote"] += "追加"
    elif mutation == "new_amount":
        draft["refund_amount"] = "123.00"
    elif mutation == "complete_coverage":
        draft["coverage"] = "all_charges_correct"
    else:
        draft = json.dumps(draft).replace('"observations":', '"observations":[],"observations":', 1)
    calls = []

    def handle(req):
        calls.append(req)
        return httpx.Response(200, json=envelope(kind, draft))

    with pytest.raises(AIExecutionError) as caught:
        await generate(provider(kind), SPEC, SPEC.task_prompt, data, transport=httpx.MockTransport(handle))
    assert len(calls) == 1 and caught.value.code == "INVALID_PROVIDER_RESPONSE"
    assert (caught.value.input_tokens, caught.value.output_tokens) == (13, 7)
    assert caught.value.model_call_attempted is True


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["chat", "responses"])
async def test_missing_companion_usage_remains_unknown_with_actual_input_preserved(charge_case, kind):
    data, draft, _ = data_for(charge_case)
    response = envelope(kind, draft)
    del response["usage"]["completion_tokens" if kind == "chat" else "output_tokens"]
    with pytest.raises(AIExecutionError) as caught:
        await generate(provider(kind), SPEC, SPEC.task_prompt, data, transport=httpx.MockTransport(lambda _: httpx.Response(200, json=response)))
    assert (caught.value.input_tokens, caught.value.output_tokens) == (13, None)
    assert caught.value.model_call_attempted is True


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ["extra_private_body", "tool", "changed_evidence", "source_change", "frozen_audit", "foreign_selection"])
async def test_mixed_or_unverified_payload_makes_zero_provider_calls(charge_case, mutation):
    data, _, _ = data_for(charge_case)
    if mutation == "extra_private_body":
        data["patient_body"] = "private synthetic data"
    elif mutation == "tool":
        data["tools"] = {"execute_refund": True}
    elif mutation == "changed_evidence":
        data["evidence"] = []
    elif mutation == "source_change":
        data["context"]["charge_source"]["charges"][0]["total_amount"] = "199.00"
    elif mutation == "frozen_audit":
        data["context"]["charge_case"]["eligible"] = False
        data["context"]["charge_case"]["audit_only"] = True
    else:
        data["input"]["coding_case_id"] = data["input"]["charge_case_id"]
    calls = []
    with pytest.raises(AIExecutionError) as caught:
        await generate(provider(), SPEC, SPEC.task_prompt, data, transport=httpx.MockTransport(lambda req: calls.append(req)))
    assert not calls and caught.value.code == "CHARGE_SOURCE_REQUIRED"
    assert caught.value.model_call_attempted is False
    assert caught.value.input_tokens is caught.value.output_tokens is None


@pytest.mark.parametrize("attack", ["other_feature", "specialist", "missing_source"])
def test_generic_request_helper_cannot_fall_back_from_charge_contract(charge_case, attack):
    data, _, _ = data_for(charge_case)
    spec, model = SPEC, provider()
    if attack == "other_feature":
        spec = FEATURE_BY_KEY["patient_summary"]
    elif attack == "specialist":
        model.kind = "specialist"
    else:
        data = {"context": {}, "input": {}, "tools": {}, "evidence": []}
    with pytest.raises(AIExecutionError):
        _request(model, spec, spec.task_prompt, data)


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["redirect", "timeout", "invalid_utf8", "oversize"])
async def test_provider_transport_faults_are_bounded_and_never_automatically_retried(charge_case, fault):
    data, _, _ = data_for(charge_case)
    calls = []

    def handle(req):
        calls.append(req)
        if fault == "redirect":
            return httpx.Response(302, headers={"location": "https://synthetic.invalid/no-follow"})
        if fault == "timeout":
            raise httpx.ReadTimeout("synthetic timeout", request=req)
        return httpx.Response(200, content=b"\xff" if fault == "invalid_utf8" else b"x" * (MAX_BYTES + 1))

    with pytest.raises(AIExecutionError) as caught:
        await generate(provider(), SPEC, SPEC.task_prompt, data, transport=httpx.MockTransport(handle))
    assert len(calls) == 1
    assert caught.value.model_call_attempted is True
    assert caught.value.input_tokens is caught.value.output_tokens is None
    assert caught.value.code == {"redirect": "PROVIDER_HTTP_ERROR", "timeout": "PROVIDER_TIMEOUT", "invalid_utf8": "INVALID_PROVIDER_RESPONSE", "oversize": "RESPONSE_TOO_LARGE"}[fault]


def test_request_budget_includes_fixed_contract_and_actual_task_prompt(charge_case):
    data, _, _ = data_for(charge_case)
    with pytest.raises(AIExecutionError) as caught:
        request(provider(), SPEC, "界" * (MAX_BYTES // 3), data)
    assert caught.value.code == "CHARGE_REQUEST_LIMIT"
