"""Actual shared Main/JWT packets for independently read research task parts."""

import hashlib
import json

import httpx
import pytest

from app.ai.research_cohort_cases import case_current, create_case, preview_input, review_case
from app.ai.research_cohort_contract import canonical_json
from app.ai.research_cohort_draft import citation_catalog
from app.ai.research_cohort_execution import claim_research_run, execute_research_claimed
from app.ai.research_cohort_registry import create_registry_original, review_registry_original
from tests.test_ai_research_cohort_contract import BASIS
from tests.test_ai_research_cohort_execution import reply
from tests.test_ai_research_cohort_storage import capture_sql, task_body_selects
from tests.test_ai_research_cohort_tasks_http import actual_task_routes as actual_task_routes  # noqa: F401
from tests.test_ai_research_cohort_tasks_http import artifact_foreign_keys as artifact_foreign_keys  # noqa: F401
from tests.test_ai_research_cohort_tasks_http import configured as configured  # noqa: F401
from tests.test_ai_research_cohort_tasks_http import research_case as research_case  # noqa: F401
from tests.test_ai_research_cohort_tasks_http import runtime_case as runtime_case  # noqa: F401
from tests.test_ai_research_cohort_tasks_http import storage_rows as storage_rows  # noqa: F401


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["chat", "responses"])
async def test_actual_current_shared_trace_independent_super_parts_and_withdrawal_packets(runtime_case, async_client, auth_headers, actual_task_routes, tmp_path, kind):
    from app.ai.models import AIProvider

    case, db = runtime_case, runtime_case["db"]
    db.get(AIProvider, case["values"]["provider_id"]).kind = kind
    db.commit()
    # Technical Super identity supplied no project ACL in the original fixture.
    # Record a real independent ACL review, then explicitly recapture the Case:
    # adding this root must invalidate the old manifest, never rewrite its flags.
    prior = case_current(db, case["actor"], case["case_id"])
    scope = prior["snapshot"]["capture"]["scope_original"]
    acl = create_registry_original(
        db,
        case["identities"]["super_admin_user"],
        "acl",
        {
            "scope_id": scope["identity"]["scope_id"],
            "scope_content_hash": scope["content_hash"],
            "scope_governance_hash": scope["governance_hash"],
            "user_id": case["identities"]["super_admin_user"].user_id,
            "permission": "read_capture",
            "valid_from": scope["payload"]["valid_from"],
            "valid_until": scope["payload"]["valid_until"],
            "basis_note": BASIS,
        },
    )
    review_registry_original(db, case["identities"]["reviewer"], "acl", acl["source_record_id"], {"expected_revision": 1, "decision": "publish", "basis_note": BASIS})
    assert case_current(db, case["actor"], prior["case_id"])["eligible"] is False
    preview = preview_input(db, case["actor"], prior["snapshot"]["request"])
    made = create_case(db, case["actor"], {"request": preview["request"], "expected_collection_digest": preview["expected_collection_digest"], "basis_note": BASIS})
    review_case(db, case["identities"]["super_admin_user"], made["case_id"], {"expected_revision": 1, "decision": "publish", "basis_note": BASIS})
    fresh = case_current(db, case["actor"], made["case_id"])
    assert fresh["eligible"] and fresh["case_id"] != prior["case_id"]
    case["case_id"], case["source"] = fresh["case_id"], fresh["public_source"]
    owner = auth_headers(case["actor"].username)
    super_headers = auth_headers(case["identities"]["super_admin_user"].username)
    wire = []

    async def call(method, path, *, headers=owner, expected=200, **kwargs):
        response = await async_client.request(method, path, headers=headers, **kwargs)
        wire.append(
            {
                "method": method,
                "path": path,
                "status": response.status_code,
                "raw_utf8": response.content.decode("utf-8"),
                "bytes": len(response.content),
                "sha256": hashlib.sha256(response.content).hexdigest(),
            }
        )
        assert response.status_code == expected, response.text
        return response.json()["data"] if expected == 200 else {"status": response.status_code}

    selected = {"research_cohort_case_id": case["case_id"], "question": "共享入口实际原问题\ufeff\r\n🧪，只核对本项目原记录。"}
    source = await call("GET", "/api/ai/research-cohort/cases/" + case["case_id"])
    queued = await call("POST", "/api/ai/research-cohort/tasks", json=selected)
    identifier = queued["run_id"]
    claim = claim_research_run(db, identifier)
    outgoing = []

    def model(request):
        assert all(not session.in_transaction() for session in case["sessions"])
        outgoing.append({"path": request.url.path, "raw_utf8": request.content.decode("utf-8"), "sha256": hashlib.sha256(request.content).hexdigest()})
        response = reply(case["source"], kind)
        text = response["choices"][0]["message"]["content"] if kind == "chat" else response["output"][0]["content"][0]["text"]
        draft = json.loads(text)
        target = next(value for value in citation_catalog(case["source"])["targets"] if value["category"] == "recorded_evidence_quote")
        draft["questions"] = [
            {
                "category": "recorded_evidence_question",
                "title": "共享任务原文核对",
                "observation": "当前完整项目原记录只支持部分待核问题。",
                "clarification_question": "请人工核对这段原文是否满足本次明确记录条件？",
                "citations": [{"target_token": target["target_token"], "text_hash": target["text_hash"], "start": 0, "end": len(target["text"]), "quote": target["text"]}],
            }
        ]
        if kind == "chat":
            response["choices"][0]["message"]["content"] = canonical_json(draft)
        else:
            response["output"][0]["content"][0]["text"] = canonical_json(draft)
        return httpx.Response(200, json=response)

    assert await execute_research_claimed(identifier, claim.lease_token, claim_event_id=claim.claim_event_id, transport=httpx.MockTransport(model), session_factory=case["factory"])
    base = "/api/ai/research-cohort/tasks/" + identifier
    packet = {
        "kind": kind,
        "selection": selected,
        "case": source,
        "queued": queued,
        "requester": {"username": case["actor"].username},
        "super_user": {"username": case["identities"]["super_admin_user"].username},
    }
    packet["shared_owner"] = await call("GET", "/api/ai/runs/" + identifier)
    packet["shared_super"] = await call("GET", "/api/ai/runs/" + identifier, headers=super_headers)
    packet["trace"] = await call("GET", "/api/ai/admin/runs/" + identifier, headers=super_headers)
    assert packet["trace"]["schema_version"] == "research_cohort_split_trace_v1"
    for label, headers, suffix in (("owner", owner, ""), ("super", super_headers, "?audit_only=true")):
        packet["metadata_" + label] = await call("GET", base + suffix, headers=headers)
        packet["parts_" + label] = {part: await call("GET", base + "/parts/" + part + suffix, headers=headers) for part in ("source", "scope", "task", "result")}
    packet["directory_owner"] = await call("GET", "/api/ai/runs?feature_key=research_cohort")
    packet["directory_super"] = await call("GET", "/api/ai/admin/runs?feature_key=research_cohort", headers=super_headers)
    authorization = source["snapshot"]["capture"]["patient_authorizations"][0]["identity"]["source_record_id"]
    review_registry_original(db, case["identities"]["super_admin_user"], "authorization", authorization, {"expected_revision": 2, "basis_note": BASIS}, revoke=True)
    statements, close = capture_sql(db)
    try:
        packet["withdrawn_shared_owner"] = await call("GET", "/api/ai/runs/" + identifier, expected=403)
        packet["withdrawn_trace"] = await call("GET", "/api/ai/admin/runs/" + identifier, headers=super_headers, expected=403)
        packet["withdrawn_metadata_super"] = await call("GET", base + "?audit_only=true", headers=super_headers)
        for part in ("source", "scope", "task", "result"):
            await call("GET", base + "/parts/" + part + "?audit_only=true", headers=super_headers, expected=403)
    finally:
        close()
    assert task_body_selects(statements) == []
    packet.update(outbound=outgoing, actual_http=wire, withdrawn_task_text_selects=0)
    (tmp_path / f"actual-research-shared-main-{kind}.json").write_text(canonical_json(packet), encoding="utf-8")
