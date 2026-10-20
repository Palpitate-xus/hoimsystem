"""Independent final-read integrity and in-flight lease review over real source ORM."""

import hashlib
import json
import uuid

import pytest

from app.ai.governance import encode_json
from app.ai.models import AIFeedback, AIRun
from app.ai.runtime import claim_next_run, create_run, execute_claimed
from app.ai.sofa_models import AISofaRunResult
from app.ai.sofa_storage import bounded_result
from tests.test_ai_sofa_pipeline import RealSofaTransport, run_request
from tests.test_ai_sofa_pipeline import assessment_case as assessment_case
from tests.test_ai_sofa_pipeline import clean_ai_tasks as clean_ai_tasks
from tests.test_ai_sofa_pipeline import observation_case as observation_case
from tests.test_ai_sofa_pipeline import pipeline_case as pipeline_case
from tests.test_ai_sofa_pipeline import sofa_case as sofa_case
from tests.test_ai_sofa_pipeline import source_case as source_case


async def successful(db, case):
    run = create_run(db, case["doctor"], run_request(case))
    await execute_claimed(*claim_next_run(db), transport=RealSofaTransport(case["service"]))
    db.expire_all()
    run = db.get(AIRun, run.run_id)
    assert run.status == "succeeded", (run.error_code, run.error_message)
    return run


def rehash_blob(db, run, value):
    blob = db.get(AISofaRunResult, run.run_id)
    blob.result_json, blob.content_hash, blob.result_bytes = bounded_result(value)
    pointer = json.loads(run.result_json)
    pointer.update(content_hash=blob.content_hash, result_bytes=blob.result_bytes)
    run.result_json = encode_json(pointer)


@pytest.mark.asyncio
async def test_feedback_cannot_accept_a_damaged_sofa_blob(async_client, auth_headers, db_session, pipeline_case):
    case = pipeline_case
    run = await successful(db_session, case)
    db_session.get(AISofaRunResult, run.run_id).result_json = "{}"
    db_session.commit()
    response = await async_client.post(f"/api/ai/runs/{run.run_id}/feedback", headers=auth_headers(case["doctor"].username), json={"outcome": "accepted", "comment": "独立审核应拒损坏原结果"})
    assert response.status_code == 409, response.status_code
    assert db_session.query(AIFeedback).filter_by(run_id=run.run_id).count() == 0


@pytest.mark.asyncio
async def test_rehashed_prompt_claim_still_must_match_original_run_prompt_hash(async_client, auth_headers, db_session, pipeline_case):
    case = pipeline_case
    run = await successful(db_session, case)
    snapshot = json.loads(run.input_json)
    snapshot["task_prompt"] = "这是一条从未执行过的伪造历史Prompt，原run.prompt_hash未改变。"
    run.input_json = encode_json(snapshot)
    value = json.loads(db_session.get(AISofaRunResult, run.run_id).result_json)
    value["sofa_analysis"]["instructions_digest"] = hashlib.sha256((snapshot["system_prompt"] + "\n\n" + snapshot["task_prompt"]).encode()).hexdigest()
    rehash_blob(db_session, run, value)
    db_session.commit()
    response = await async_client.get(f"/api/ai/runs/{run.run_id}", headers=auth_headers(case["doctor"].username))
    assert response.status_code in {403, 409}, response.status_code


@pytest.mark.asyncio
async def test_original_context_digest_verified_for_history_and_admin_trace(async_client, auth_headers, db_session, pipeline_case):
    case = pipeline_case
    run = await successful(db_session, case)
    snapshot = json.loads(run.input_json)
    snapshot["payload"]["context"]["missing_data"] = ["并非原冻结声明的伪造上下文说明"]
    run.input_json = encode_json(snapshot)
    db_session.commit()
    for username, path in [(case["doctor"].username, f"/api/ai/runs/{run.run_id}"), (case["seed"]["super_admin_user"].username, f"/api/ai/admin/runs/{run.run_id}")]:
        response = await async_client.get(path, headers=auth_headers(username))
        assert response.status_code in {403, 409}, response.status_code


@pytest.mark.asyncio
@pytest.mark.parametrize("transition", ["cancelled", "lease_replaced"])
async def test_inflight_new_lease_or_cancel_never_accepts_old_complete_blob(transition, db_session, pipeline_case):
    case = pipeline_case
    run = create_run(db_session, case["doctor"], run_request(case))
    claim = claim_next_run(db_session)

    def change():
        db_session.expire_all()
        current = db_session.get(AIRun, run.run_id)
        if transition == "cancelled":
            current.status = "cancelled"
        else:
            current.lease_token = str(uuid.uuid4())
        db_session.commit()

    wire = RealSofaTransport(case["service"], before=change)
    await execute_claimed(*claim, transport=wire)
    db_session.expire_all()
    stored = db_session.get(AIRun, run.run_id)
    assert stored.status == ("cancelled" if transition == "cancelled" else "running")
    assert stored.result_json == "{}" and db_session.get(AISofaRunResult, run.run_id) is None
    assert len(wire.requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field,value",
    [("context_digest", "0" * 64), ("clinical_context_fingerprint", "0" * 64), ("missing_data", ["伪造已完整数据声明"]), ("source_count", 1000), ("snapshot_time", "2000-01-01T00:00:00.000000Z")],
)
async def test_read_metadata_must_equal_the_original_frozen_context(field, value, async_client, auth_headers, db_session, pipeline_case):
    case = pipeline_case
    run = await successful(db_session, case)
    metadata = json.loads(run.context_metadata_json)
    metadata[field] = value
    run.context_metadata_json = encode_json(metadata)
    db_session.commit()
    response = await async_client.get(f"/api/ai/runs/{run.run_id}", headers=auth_headers(case["doctor"].username))
    assert response.status_code in {403, 409}, (field, response.status_code)


@pytest.mark.asyncio
async def test_read_evidence_cannot_add_unfrozen_private_records(async_client, auth_headers, db_session, pipeline_case):
    case = pipeline_case
    run = await successful(db_session, case)
    evidence = json.loads(run.evidence_json)
    evidence.append({"source_id": "synthetic-other-patient-record", "kind": "clinical_record", "title": "unfrozen", "content": "不属于本次冻结原件的私有记录"})
    run.evidence_json = encode_json(evidence)
    db_session.commit()
    response = await async_client.get(f"/api/ai/runs/{run.run_id}", headers=auth_headers(case["doctor"].username))
    assert response.status_code in {403, 409}, response.status_code
    assert "不属于本次冻结原件的私有记录" not in response.text


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["tools", "input_ref", "selected_ref"])
async def test_queued_untrusted_metadata_is_rejected_before_wire(change, db_session, pipeline_case):
    from app.ai.governance import digest

    case = pipeline_case
    run = create_run(db_session, case["doctor"], run_request(case))
    frozen = json.loads(run.input_json)
    if change == "tools":
        frozen["payload"]["tools"] = {"triage_rules": {"emergency": True, "emergency_message": "伪造工具警告不得注入完整SOFA固定结果"}}
    elif change == "input_ref":
        frozen["payload"]["input"]["sofa_assessment_id"] = str(uuid.uuid4())
    else:
        frozen["payload"]["context"]["selected_sources"]["sofa_assessment_id"] = str(uuid.uuid4())
        # Even an attacker-updated outer digest must not override the typed original binding.
        run.context_digest = digest(frozen["payload"]["context"])
        metadata = json.loads(run.context_metadata_json)
        metadata["context_digest"] = run.context_digest
        metadata["clinical_context_fingerprint"] = digest({key: value for key, value in frozen["payload"]["context"].items() if key != "snapshot_time"})
        run.context_metadata_json = encode_json(metadata)
    run.input_json = encode_json(frozen)
    db_session.commit()
    wire = RealSofaTransport(case["service"])
    await execute_claimed(*claim_next_run(db_session), transport=wire)
    db_session.expire_all()
    stored = db_session.get(AIRun, run.run_id)
    assert stored.status == "failed" and not wire.requests, (change, stored.status)
    assert db_session.get(AISofaRunResult, run.run_id) is None
