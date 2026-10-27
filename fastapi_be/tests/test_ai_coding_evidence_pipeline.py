"""Actual synthetic JWT queue, full original proof and atomic typed draft storage."""

# ruff: noqa: F811 -- imported pytest fixtures are injected by their names.

import datetime
import json
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import text

from app.ai import coding_evidence_context, models, runtime
from app.ai.coding_evidence_models import AICodingRunResult
from app.ai.coding_evidence_sources import canonical_json, hash_content, review
from app.ai.models import AIAuditEvent, AIFeatureConfig, AIFeedback, AIProvider, AIRun
from app.ai.runtime import claim_next_run, execute_claimed
from app.models import DrgGrouping, HomeIcdBinding
from tests.test_ai_coding_evidence_context import draft_for
from tests.test_ai_coding_evidence_gateway import envelope
from tests.test_ai_coding_evidence_sources import NOTE, NOW, case, published  # noqa: F401
from tests.test_ai_runtime import configure
from tests.test_coding_evidence_legacy_writes import coding_case  # noqa: F401


@pytest.fixture(autouse=True)
def clear_coding_tasks(db_session):
    for model in (AIFeedback, AICodingRunResult, AIRun, AIFeatureConfig, AIProvider):
        db_session.query(model).delete()
    db_session.commit()


@pytest.fixture
def pipeline_case(db_session, case, monkeypatch):
    class Clock(datetime.datetime):
        @classmethod
        def now(cls, tz=None):
            aware = NOW.replace(tzinfo=datetime.UTC)
            return aware.astimezone(tz) if tz else aware.replace(tzinfo=None)

    monkeypatch.setattr(coding_evidence_context, "datetime", Clock)
    monkeypatch.setattr(models, "datetime", SimpleNamespace(datetime=Clock, UTC=datetime.UTC))
    monkeypatch.setattr(runtime, "utcnow", lambda: NOW)
    case["home"].operation_summary = "\ufeff原文🧪\r\n仅合成操作说明，仍待人工核实。"
    db_session.commit()
    row = published(db_session, case)
    provider, feature = configure(db_session, case, "drg_evidence_review")
    return {**case, "source": row, "provider": provider, "feature": feature}


def request(c):
    return {"feature_key": "drg_evidence_review", "patient_id": c["patient"].patient_id, "encounter_ref": c["admission"].admission_id, "input": {"coding_case_id": c["source"].case_snapshot_id}}


def draft_transport(c, before=None):
    packets = []

    def handle(outbound):
        packet = json.loads(outbound.content)
        kind = c["provider"].kind
        model = json.loads(packet["messages"][1]["content"] if kind == "chat" else packet["input"][0]["content"])
        packets.append(packet)
        if before:
            before()
        draft = draft_for(model["coding_source"], model["source_projection_hash"]).model_dump(mode="json")
        return httpx.Response(200, json=envelope(kind, draft))

    return httpx.MockTransport(handle), packets


async def queue(client, headers, db, c):
    queued = await client.post("/api/ai/runs", headers=headers, json=request(c))
    assert queued.status_code == 200, queued.text
    claim = claim_next_run(db)
    assert claim and claim[0] == queued.json()["data"]["run_id"]
    return claim, queued.json()


def assert_unaccepted(db, run_id):
    db.expire_all()
    row = db.get(AIRun, run_id)
    assert row.result_json == "{}" and db.query(AICodingRunResult).filter_by(run_id=run_id).count() == 0
    assert db.query(AIAuditEvent).filter_by(action="run.coding_result.accept", target=run_id).count() == 0
    return row


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["chat", "responses"])
async def test_actual_jwt_queue_complete_draft_history_feedback_and_frozen_super_audit(async_client, auth_headers, db_session, pipeline_case, kind, tmp_path):
    db, c = db_session, pipeline_case
    c["provider"].kind = kind
    db.commit()
    headers = auth_headers(c["doctor_user"].username)
    before = (db.query(HomeIcdBinding).count(), db.query(DrgGrouping).count(), c["home"].status, c["home"].total_fee)
    preview = await async_client.post(
        "/api/ai/context",
        headers=headers,
        json={"feature_key": "drg_evidence_review", "patient_id": c["patient"].patient_id, "encounter_ref": c["admission"].admission_id, "source_refs": request(c)["input"]},
    )
    assert preview.status_code == 200, preview.text
    assert set(preview.json()["data"]["context"]) >= {"coding_source", "coding_case", "coding_binding"}
    claim, queued = await queue(async_client, headers, db, c)
    assert "coding_findings" not in queued["data"]
    running = await async_client.get(f"/api/ai/runs/{claim[0]}", headers=headers)
    assert running.status_code == 200 and running.json()["data"]["status"] == "running", running.text
    transport, packets = draft_transport(c)
    await execute_claimed(*claim, transport=transport)
    db.expire_all()
    row = db.get(AIRun, claim[0])
    assert row.status == "succeeded", (row.error_code, row.error_message)
    detail = await async_client.get(f"/api/ai/runs/{claim[0]}", headers=headers)
    assert detail.status_code == 200, detail.text
    data = detail.json()["data"]
    assert set(data["coding_findings"]) == {"coding_source", "coding_case", "coding_binding"}
    assert data["result"]["coding_analysis"]["claims"] and "待复核" in data["result"]["summary"]
    assert data["result"]["coding_analysis"]["claims"][0]["citations"][0]["quote"] == "\ufeff原文🧪\r\n仅合成操作说明，仍待人工核实。"
    blob = db.get(AICodingRunResult, claim[0])
    assert blob.content_hash == hash_content(data["result"]) and blob.result_bytes == len(blob.result_json.encode())
    assert json.loads(row.result_json)["schema_version"] == "coding_result_ref_v1"
    assert db.query(AIAuditEvent).filter_by(action="run.coding_result.accept", target=claim[0]).count() == 1
    assert len(packets) == 1 and c["patient"].identity not in canonical_json(packets)
    history = await async_client.get(
        "/api/ai/runs",
        headers=headers,
        params={"feature_key": "drg_evidence_review", "coding_case_id": c["source"].case_snapshot_id, "patient_id": c["patient"].patient_id, "encounter_ref": c["admission"].admission_id},
    )
    assert history.status_code == 200 and [x["run_id"] for x in history.json()["data"]] == [claim[0]], history.text
    feedback = await async_client.post(f"/api/ai/runs/{claim[0]}/feedback", headers=headers, json={"outcome": "accepted", "comment": "合成工程核对，未作临床或编码确认"})
    assert feedback.status_code == 200, feedback.text
    review(db, c["super_admin_user"], "case", c["source"].case_snapshot_id, {"expected_revision": 2, "expected_content_hash": c["source"].content_hash, "basis_note": NOTE}, revoke=True)
    db.commit()
    denied = await async_client.get(f"/api/ai/runs/{claim[0]}", headers=headers)
    assert denied.status_code == 409, denied.text
    audit = await async_client.get(f"/api/ai/admin/runs/{claim[0]}", headers=auth_headers(c["super_admin_user"].username))
    assert audit.status_code == 200, audit.text
    assert audit.json()["data"]["coding_findings"]["coding_case"]["status"] == "revoked"
    assert audit.json()["data"]["frozen_request"]["payload"]["context"]["coding_source"] == data["coding_findings"]["coding_source"]
    assert before == (db.query(HomeIcdBinding).count(), db.query(DrgGrouping).count(), c["home"].status, c["home"].total_fee)
    (tmp_path / f"actual-coding-pipeline-{kind}.json").write_text(
        json.dumps(
            {
                "scope": "synthetic actual JWT/SQLite/worker with MockTransport text model; not clinical outcome or real model inference",
                "preview": preview.json(),
                "queued": queued,
                "running": running.json(),
                "detail": detail.json(),
                "audit": audit.json(),
                "outbound": packets[0],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("when", ["queued", "inflight"])
@pytest.mark.parametrize("change", ["home", "dictionary", "new_binding", "linked_rule", "revoke", "actor_role", "provider_revision", "feature_disabled"])
async def test_changed_complete_original_authority_or_config_rejects_old_draft(async_client, auth_headers, db_session, pipeline_case, when, change):
    db, c = db_session, pipeline_case
    claim, _ = await queue(async_client, auth_headers(c["doctor_user"].username), db, c)

    def mutate():
        if change == "home":
            c["home"].discharge_diagnosis += " 发生改变"
        elif change == "dictionary":
            c["diagnosis"].name += " 新名称"
        elif change == "new_binding":
            db.add(
                HomeIcdBinding(home_id=c["home"].home_id, kind="operation", icd_code=c["operation"].code, icd_name=c["operation"].name, is_primary=0, coder_id=c["doctor_user"].user_id, code_time=NOW)
            )
        elif change == "linked_rule":
            c["rule"].version = "changed local version"
        elif change == "revoke":
            review(db, c["super_admin_user"], "case", c["source"].case_snapshot_id, {"expected_revision": 2, "expected_content_hash": c["source"].content_hash, "basis_note": NOTE}, revoke=True)
        elif change == "actor_role":
            c["doctor_user"].user_role = "patient"
        elif change == "provider_revision":
            c["provider"].revision += 1
        else:
            c["feature"].enabled = 0
        db.commit()

    if when == "queued":
        mutate()
    transport, packets = draft_transport(c, before=mutate if when == "inflight" else None)
    await execute_claimed(*claim, transport=transport)
    row = assert_unaccepted(db, claim[0])
    assert row.status == "failed" and len(packets) == (1 if when == "inflight" else 0)


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["metadata", "blob_delete", "audit_delete", "audit_abort"])
async def test_actual_postwrite_fault_rolls_back_result_pointer_blob_and_success_audit(async_client, auth_headers, db_session, pipeline_case, fault):
    db, c = db_session, pipeline_case
    claim, _ = await queue(async_client, auth_headers(c["doctor_user"].username), db, c)
    body = {
        "metadata": "AFTER INSERT ON hoimsystem_ai_coding_run_result BEGIN UPDATE hoimsystem_ai_run SET context_metadata_json='{}' WHERE run_id=NEW.run_id; END",
        "blob_delete": "AFTER INSERT ON hoimsystem_ai_coding_run_result BEGIN DELETE FROM hoimsystem_ai_coding_run_result WHERE run_id=NEW.run_id; END",
        "audit_delete": "AFTER INSERT ON hoimsystem_ai_audit_event WHEN NEW.action='run.coding_result.accept' BEGIN DELETE FROM hoimsystem_ai_audit_event WHERE event_id=NEW.event_id; END",
        "audit_abort": "BEFORE INSERT ON hoimsystem_ai_audit_event WHEN NEW.action='run.coding_result.accept' BEGIN SELECT RAISE(ABORT,'synthetic audit failure'); END",
    }[fault]
    db.execute(text("CREATE TRIGGER synthetic_coding_fault " + body))
    db.commit()
    try:
        transport, _ = draft_transport(c)
        await execute_claimed(*claim, transport=transport)
        row = assert_unaccepted(db, claim[0])
        assert row.status == "failed" and row.error_code == "RESULT_STORAGE_ERROR"
    finally:
        db.rollback()
        db.execute(text("DROP TRIGGER IF EXISTS synthetic_coding_fault"))
        db.commit()


@pytest.mark.asyncio
@pytest.mark.parametrize("variant", ["queued_feature", "succeeded_feature", "succeeded_blob_identity"])
async def test_removing_coding_markers_cannot_downgrade_to_generic_read_or_execution(async_client, auth_headers, db_session, pipeline_case, variant):
    db, c = db_session, pipeline_case
    headers = auth_headers(c["doctor_user"].username)
    claim, _ = await queue(async_client, headers, db, c)
    if variant != "queued_feature":
        transport, _ = draft_transport(c)
        await execute_claimed(*claim, transport=transport)
        db.expire_all()
        assert db.get(AIRun, claim[0]).status == "succeeded"
    review(db, c["super_admin_user"], "case", c["source"].case_snapshot_id, {"expected_revision": 2, "expected_content_hash": c["source"].content_hash, "basis_note": NOTE}, revoke=True)
    row = db.get(AIRun, claim[0])
    snapshot = json.loads(row.input_json)
    snapshot["payload"]["input"].pop("coding_case_id")
    for name in ("coding_binding", "coding_source", "coding_case", "selected_sources"):
        snapshot["payload"]["context"].pop(name, None)
    row.input_json = canonical_json(snapshot)
    if variant != "queued_feature":
        row.result_json = canonical_json({"summary": "此伪造通用说明绝不能显示", "sections": [], "warnings": [], "missing_data": []})
    if variant == "succeeded_blob_identity":
        row.feature_key = "patient_summary"
    db.commit()
    for actor in (c["doctor_user"], c["super_admin_user"]):
        response = await async_client.get(f"/api/ai/runs/{claim[0]}", headers=auth_headers(actor.username))
        assert response.status_code == 409 and "此伪造通用说明" not in response.text, response.text
    trace = await async_client.get(f"/api/ai/admin/runs/{claim[0]}", headers=auth_headers(c["super_admin_user"].username))
    assert trace.status_code == 409 and "此伪造通用说明" not in trace.text, trace.text
    if variant == "queued_feature":
        transport, packets = draft_transport(c)
        await execute_claimed(*claim, transport=transport)
        assert not packets and assert_unaccepted(db, claim[0]).status == "failed"
    else:
        feedback = await async_client.post(f"/api/ai/runs/{claim[0]}/feedback", headers=headers, json={"outcome": "accepted", "comment": "不能确认损坏任务"})
        assert feedback.status_code == 409 and db.query(AIFeedback).filter_by(run_id=claim[0]).count() == 0


@pytest.mark.asyncio
async def test_every_original_provider_and_validation_field_is_required_for_complete_task_audit(async_client, auth_headers, db_session, pipeline_case):
    db, c = db_session, pipeline_case
    headers = auth_headers(c["doctor_user"].username)
    claim, _ = await queue(async_client, headers, db, c)
    row = db.get(AIRun, claim[0])
    original = row.input_json
    snapshot = json.loads(original)
    count = 0
    for container in ("provider_snapshot", "feature_validation"):
        for key in snapshot[container]:
            # Retry policy was added later: its absence is the preserved legacy
            # single-attempt frame, while all original fields remain required.
            if container == "provider_snapshot" and key == "max_attempts":
                continue
            changed = json.loads(original)
            del changed[container][key]
            row.input_json = canonical_json(changed)
            db.commit()
            response = await async_client.get(f"/api/ai/runs/{claim[0]}", headers=headers)
            assert response.status_code == 409, (container, key, response.text)
            count += 1
    row.input_json = original
    db.commit()
    control = await async_client.get(f"/api/ai/runs/{claim[0]}", headers=headers)
    assert count == 17 and control.status_code == 200, control.text


def test_unsaved_legacy_run_default_absence_preserves_strict_coding_markers(db_session):
    from app.ai.coding_evidence_storage import is_coding_run

    legacy = AIRun(feature_key="charge_reconciliation", input_json='{"payload":{"input":{},"context":{}}}')
    assert legacy.run_id is None and legacy.result_json is None
    assert is_coding_run(db_session, legacy) is False
    legacy.input_json = '{"payload":{"input":{"coding_case_id":null},"context":{}}}'
    assert is_coding_run(db_session, legacy) is True
    legacy.input_json = '{"payload":{"input":{},"context":{}}}'
    legacy.feature_key = "drg_evidence_review"
    assert is_coding_run(db_session, legacy) is True


@pytest.mark.asyncio
async def test_legacy_missing_retry_policy_preserves_frozen_audit_but_cannot_execute_current_three_attempt_provider(async_client, auth_headers, db_session, pipeline_case):
    db, case = db_session, pipeline_case
    headers = auth_headers(case["doctor_user"].username)
    claim, _ = await queue(async_client, headers, db, case)
    row = db.get(AIRun, claim[0])
    snapshot = json.loads(row.input_json)
    assert snapshot["provider_snapshot"].pop("max_attempts") == 3
    legacy_raw = canonical_json(snapshot)
    row.input_json = legacy_raw
    db.commit()
    response = await async_client.get(f"/api/ai/runs/{claim[0]}", headers=headers)
    assert response.status_code == 200
    transport, packets = draft_transport(case)
    await execute_claimed(*claim, transport=transport)
    db.expire_all()
    actual = db.get(AIRun, claim[0])
    assert not packets and actual.status == "failed" and actual.input_json == legacy_raw
