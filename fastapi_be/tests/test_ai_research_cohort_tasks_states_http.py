"""Actual same-Case Main task states, metadata directory and withdrawal reads."""

import hashlib
import json

import httpx
import pytest

from app.ai.models import AIFeatureConfig
from app.ai.research_cohort_contract import canonical_json
from app.ai.research_cohort_draft import citation_catalog
from app.ai.research_cohort_execution import claim_research_run, execute_research_claimed
from app.ai.research_cohort_registry import review_registry_original
from tests.test_ai_research_cohort_contract import BASIS
from tests.test_ai_research_cohort_execution import reply
from tests.test_ai_research_cohort_execution import runtime_case as runtime_case  # noqa: F401
from tests.test_ai_research_cohort_storage import artifact_foreign_keys as artifact_foreign_keys  # noqa: F401
from tests.test_ai_research_cohort_storage import capture_sql, task_body_selects
from tests.test_ai_research_cohort_storage import configured as configured  # noqa: F401
from tests.test_ai_research_cohort_storage import research_case as research_case  # noqa: F401
from tests.test_ai_research_cohort_storage import storage_rows as storage_rows  # noqa: F401
from tests.test_ai_research_cohort_tasks_http import BASE
from tests.test_ai_research_cohort_tasks_http import actual_task_routes as actual_task_routes  # noqa: F401


@pytest.mark.asyncio
async def test_actual_main_same_case_all_states_directory20_and_research_withdrawal_never_restore_task_text(runtime_case, async_client, auth_headers, actual_task_routes, tmp_path):
    case, db = runtime_case, runtime_case["db"]
    db.get(AIFeatureConfig, "research_cohort").active_prompt_id = None
    db.commit()
    ordinary = auth_headers(case["actor"].username)
    super_headers = auth_headers(case["identities"]["super_admin_user"].username)
    wire = []

    async def call(method, path, *, headers=ordinary, expected=200, **kwargs):
        response = await async_client.request(method, path, headers=headers, **kwargs)
        wire.append({"method": method, "path": path, "status": response.status_code, "raw_utf8": response.content.decode("utf-8"), "raw_sha256": hashlib.sha256(response.content).hexdigest()})
        assert response.status_code == expected, response.text
        return response.json()["data"] if expected == 200 else {"status": response.status_code}

    live = await call("GET", "/api/ai/research-cohort/cases/" + case["case_id"])
    selected = {"research_cohort_case_id": case["case_id"], "question": "同案五状态原问题\ufeff\r\n🧪"}
    queued = await call("POST", BASE, json=selected)
    identifier = queued["run_id"]
    db.commit()
    claim = claim_research_run(db, identifier)
    running = await call("GET", BASE + "/" + identifier)
    outgoing = []

    def model(incoming):
        assert all(not session.in_transaction() for session in case["sessions"])
        outgoing.append({"path": incoming.url.path, "raw_utf8": incoming.content.decode("utf-8"), "raw_sha256": hashlib.sha256(incoming.content).hexdigest()})
        value = reply(case["source"])
        draft = json.loads(value["choices"][0]["message"]["content"])
        target = next(t for t in citation_catalog(case["source"])["targets"] if t["category"] == "recorded_evidence_quote")
        draft["questions"] = [
            {
                "category": "recorded_evidence_question",
                "title": "核对原记录证据",
                "observation": "本次原记录只代表已声明的有限资料。",
                "clarification_question": "是否需要按固定条件人工核对本条原文？",
                "citations": [{"target_token": target["target_token"], "text_hash": target["text_hash"], "start": 0, "end": len(target["text"]), "quote": target["text"]}],
            }
        ]
        value["choices"][0]["message"]["content"] = canonical_json(draft)
        return httpx.Response(200, json=value)

    assert await execute_research_claimed(identifier, claim.lease_token, claim_event_id=claim.claim_event_id, transport=httpx.MockTransport(model), session_factory=case["factory"])
    success = await call("GET", BASE + "/" + identifier)
    parts = {part: await call("GET", BASE + "/" + identifier + "/parts/" + part) for part in ("source", "scope", "result", "task")}
    failed_queued = await call("POST", BASE, json=selected)
    db.commit()
    failed_claim = claim_research_run(db, failed_queued["run_id"])
    assert await execute_research_claimed(
        failed_claim.run_id, failed_claim.lease_token, claim_event_id=failed_claim.claim_event_id, transport=httpx.MockTransport(lambda incoming: httpx.Response(503)), session_factory=case["factory"]
    )
    failed = await call("GET", BASE + "/" + failed_claim.run_id)
    assert failed["status"] == "failed" and failed["usage"] == {"input_tokens": None, "output_tokens": None, "complete": False, "model_call_attempted": True}
    failed_parts = {part: await call("GET", BASE + "/" + failed_claim.run_id + "/parts/" + part) for part in ("source", "scope", "task")}
    cancelled_queued = await call("POST", BASE, json=selected)
    cancelled = await call("POST", BASE + "/" + cancelled_queued["run_id"] + "/cancel")
    assert cancelled["status"] == "cancelled" and cancelled["usage"]["model_call_attempted"] is False
    cancelled_parts = {part: await call("GET", BASE + "/" + cancelled["run_id"] + "/parts/" + part) for part in ("source", "scope", "task")}
    directory = await call("GET", BASE + "?case_id=" + case["case_id"] + "&page=1&size=20")
    assert directory["size"] == 20 and directory["total"] == 3
    pending = await call("POST", BASE, json=selected)
    authorization = live["snapshot"]["capture"]["patient_authorizations"][0]["identity"]["source_record_id"]
    review_registry_original(db, case["identities"]["super_admin_user"], "authorization", authorization, {"expected_revision": 2, "basis_note": BASIS}, revoke=True)
    statements, close = capture_sql(db)
    try:
        denials = []
        for headers, query in ((ordinary, ""), (super_headers, "?audit_only=true")):
            for part in ("source", "scope", "result", "task"):
                denials.append(await call("GET", BASE + "/" + identifier + "/parts/" + part + query, headers=headers, expected=403))
        after_owner = await call("GET", BASE + "/" + identifier)
        after_super = await call("GET", BASE + "/" + identifier + "?audit_only=true", headers=super_headers)
        super_cancelled = await call("POST", BASE + "/" + pending["run_id"] + "/cancel", headers=super_headers)
        assert not after_owner["clinical_parts_available"] and not after_super["clinical_parts_available"] and super_cancelled["usage"]["model_call_attempted"] is False
    finally:
        close()
    assert not task_body_selects(statements)
    packet = {
        "scope": "Feature74 actual product Main/JWT HTTP and dedicated real SQL claim/execute via HTTPMock. One Case, independent succeeded/failed/cancelled task IDs; not one invented terminal sequence, not shared dispatcher or real model.",
        "same_case_only": True,
        "selection": selected,
        "live_case": live,
        "queued": queued,
        "running": running,
        "succeeded": success,
        "parts": parts,
        "failed": {"metadata": failed, "parts": failed_parts},
        "cancelled": {"metadata": cancelled, "parts": cancelled_parts},
        "directory": directory,
        "after_withdrawal": {"owner": after_owner, "super": after_super, "super_cancelled": super_cancelled, "denials": denials, "task_body_selects": 0},
        "actual_http": wire,
        "model_outgoing": outgoing,
    }
    (tmp_path / "actual-research-main-five-states.json").write_text(canonical_json(packet), encoding="utf-8")
