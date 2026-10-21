"""Same-case packaged task, split exact parts and permission-loss read controls."""

import hashlib
import json
from types import SimpleNamespace

import httpx
import pytest
from fastapi import HTTPException

from app.ai.models import AIFeatureConfig, AIPromptVersion
from app.ai.research_cohort_artifact_models import AIResearchCohortRunArtifact
from app.ai.research_cohort_cases import case_current
from app.ai.research_cohort_contract import canonical_json
from app.ai.research_cohort_execution import claim_research_run, execute_research_claimed
from app.ai.research_cohort_registry import review_registry_original
from app.ai.research_cohort_runtime import create_research_run, describe_research_run, read_research_part
from tests.test_ai_research_cohort_contract import BASIS
from tests.test_ai_research_cohort_execution import reply
from tests.test_ai_research_cohort_execution import runtime_case as runtime_case  # noqa: F401
from tests.test_ai_research_cohort_storage import artifact_foreign_keys as artifact_foreign_keys  # noqa: F401
from tests.test_ai_research_cohort_storage import capture_sql, task_body_selects
from tests.test_ai_research_cohort_storage import configured as configured  # noqa: F401
from tests.test_ai_research_cohort_storage import research_case as research_case  # noqa: F401
from tests.test_ai_research_cohort_storage import storage_rows as storage_rows  # noqa: F401


@pytest.mark.asyncio
async def test_actual_packaged_zero_prompt_dedicated_queue_split_result_and_withdrawal_no_super_raw_bypass(runtime_case, tmp_path):
    case, db = runtime_case, runtime_case["db"]
    db.get(AIFeatureConfig, "research_cohort").active_prompt_id = None
    db.commit()
    before = db.query(AIPromptVersion).count()
    current_case = case_current(db, case["actor"], case["case_id"])
    authorization = current_case["snapshot"]["capture"]["patient_authorizations"][0]["identity"]["source_record_id"]
    selected = {"research_cohort_case_id": case["case_id"], "question": "仅同案完整默认Task与逐患者权限验证🧪\r\n"}
    run_id = create_research_run(db, case["actor"], selected)
    queued = describe_research_run(db, case["actor"], run_id)
    db.commit()
    claimed = claim_research_run(db, run_id)
    running = describe_research_run(db, case["actor"], run_id)
    db.commit()
    outgoing = []

    def handler(incoming):
        assert all(not session.in_transaction() for session in case["sessions"])
        outgoing.append(
            {"method": incoming.method, "path": incoming.url.path, "raw_utf8": incoming.content.decode("utf-8", errors="strict"), "raw_sha256": hashlib.sha256(incoming.content).hexdigest()}
        )
        return httpx.Response(200, json=reply(case["source"]))

    assert await execute_research_claimed(run_id, claimed.lease_token, claim_event_id=claimed.claim_event_id, transport=httpx.MockTransport(handler), session_factory=case["factory"])
    succeeded = describe_research_run(db, case["actor"], run_id)
    parts = {part: read_research_part(db, case["actor"], run_id, part) for part in ("source", "scope", "result", "task")}
    artifact = db.get(AIResearchCohortRunArtifact, run_id)
    prompt = json.loads(artifact.prompt_snapshot_json)
    assert artifact.prompt_id is None and artifact.prompt_version == 0 and prompt["origin"] == "packaged_catalog"
    assert before == db.query(AIPromptVersion).count()
    assert len(outgoing) == 1 and queued["status"] == "queued" and running["status"] == "running" and succeeded["status"] == "succeeded"
    assert parts["source"] == current_case["public_source"] and parts["result"]["deterministic_evaluation"]["counts"] == parts["source"]["counts"]
    assert all(len(canonical_json(value).encode("utf-8")) <= 8 * 1024 * 1024 for value in parts.values())
    db.commit()
    review_registry_original(db, case["identities"]["super_admin_user"], "authorization", authorization, {"expected_revision": 2, "basis_note": BASIS}, revoke=True)
    super_id = case["identities"]["super_admin_user"].user_id
    denied = []
    statements, close = capture_sql(db)
    try:
        for actor, audit in ((SimpleNamespace(user_id=case["actor_id"]), False), (SimpleNamespace(user_id=super_id), True)):
            for part in ("source", "scope", "result", "task"):
                with pytest.raises(HTTPException) as error:
                    read_research_part(db, actor, run_id, part, audit_only=audit)
                assert error.value.status_code == 403
                denied.append({"reader": "super" if audit else "owner", "part": part, "status": error.value.status_code})
        owner_technical = describe_research_run(db, SimpleNamespace(user_id=case["actor_id"]), run_id)
        super_technical = describe_research_run(db, SimpleNamespace(user_id=super_id), run_id, audit_only=True)
    finally:
        close()
    assert not task_body_selects(statements)
    assert not owner_technical["clinical_parts_available"] and not super_technical["clinical_parts_available"]
    assert owner_technical["usage"] == super_technical["usage"] == succeeded["usage"]
    packet = {
        "scope": "Feature74 actual dedicated service SQLite/MockTransport; not Main/JWT/shared dispatch or real model",
        "selection": selected,
        "live_case": current_case,
        "queued": queued,
        "running": running,
        "succeeded": succeeded,
        "parts": parts,
        "frozen_prompt": prompt,
        "outgoing": outgoing,
        "owner_technical_after_withdrawal": owner_technical,
        "super_technical_after_withdrawal": super_technical,
        "withdrawal_denials": denied,
        "same_case_only": True,
    }
    (tmp_path / "actual-research-packaged-dedicated-packet.json").write_text(canonical_json(packet), encoding="utf-8")
