"""Legacy incident rows remain records; native77 requires governed Case sources.

The old positive generic patient snapshot is deliberately no longer a runnable
RCA Source. Its actual legacy rows are retained while dedicated native tasks
capture complete immutable evidence and independently checked purpose grants.
"""

import datetime

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import Select, event, inspect, text

from app.ai import rca_evidence_contract as c
from app.ai import rca_evidence_grants as grants
from app.ai import rca_evidence_receipts as receipts
from app.ai import rca_evidence_storage as storage
from app.ai.catalog import FEATURE_BY_KEY
from app.ai.context import patient_snapshot
from app.ai.models import AIFeatureConfig, AIFeedback, AIProvider, AIRun
from app.ai.rca_evidence_models import RCA_EVIDENCE_MODELS
from app.ai.rca_evidence_run_models import AIRcaEvidenceRunArtifact, AIRcaEvidenceRunResult
from app.ai.runtime import claim_next_run, create_run
from app.ai.schemas import RunRequest
from app.models import AdverseEvent, AdverseEventRca


@pytest.fixture(autouse=True)
def clean_incidents(db_session):
    # This module intentionally retains workflow state between its cases. New
    # actual FK children must be removed before the original legacy fixtures.
    for model in (AIRcaEvidenceRunResult, AIRcaEvidenceRunArtifact, *reversed(RCA_EVIDENCE_MODELS), AIFeedback, AIRun, AIFeatureConfig, AIProvider, AdverseEventRca, AdverseEvent):
        db_session.query(model).delete()
    db_session.commit()


@pytest.fixture
def incident_case(seed_data, db_session):
    now = datetime.datetime.now()
    event = AdverseEvent(
        patient_id=seed_data["patient"].patient_id,
        description=seed_data["patient"].name + "上报的跌倒情况",
        event_type="跌倒",
        severity=2,
        status=2,
        report_time=now,
        handle_result="已记录处理，未独立核实",
        reporter_id=seed_data["doctor_user"].user_id,
    )
    other = AdverseEvent(patient_id=seed_data["patient2"].patient_id, description="其他患者事件不得读取", report_time=now)
    unlinked = AdverseEvent(patient_id=None, description="未关联患者事件不得绑定当前患者", report_time=now)
    db_session.add_all([event, other, unlinked])
    db_session.flush()
    rca = AdverseEventRca(
        event_id=event.event_id,
        event_summary="原分析摘要",
        timeline="仅记录班次，未记录明确发生时刻",
        root_cause="尚待证据核实的原根因文本",
        corrective_actions="原建议措施",
        pdca_cycle="A",
        responsible_dept="原记录责任科室",
        completed_date=now.date(),
        effect_evaluation="未提供效果指标",
        create_time=now,
    )
    db_session.add_all([rca, AdverseEventRca(event_id=other.event_id, event_summary="外部RCA", root_cause="其他患者根因文本", corrective_actions="不可读取", create_time=now)])
    db_session.commit()
    return event, rca, other, unlinked


def snapshot(db_session, seed_data, event=None, *, encounter=None, user=None, reference=None):
    refs = {"adverse_event_id": reference if reference is not None else str(inspect(event).identity[0])} if event or reference is not None else {}
    return patient_snapshot(db_session, user or seed_data["super_admin_user"], FEATURE_BY_KEY["incident_rca"], inspect(seed_data["patient"]).identity[0], encounter, refs)


def denied_without_legacy_text(db, callback):
    columns = []

    def observe(query):
        if query.is_select and isinstance(query.statement, Select):
            columns.extend(column.key for column in query.statement.selected_columns)

    event.listen(db, "do_orm_execute", observe)
    try:
        with pytest.raises(HTTPException) as failure:
            callback()
        assert failure.value.status_code == 422
    finally:
        event.remove(db, "do_orm_execute", observe)
    assert not {"description", "root_cause", "event_summary", "handle_result", "original_json", "case_json"}.intersection(columns)


def test_selected_legacy_incident_does_not_bypass_governed_native_case_or_read_body(seed_data, db_session, incident_case):
    report, rca, *_ = incident_case
    denied_without_legacy_text(db_session, lambda: snapshot(db_session, seed_data, report))
    assert db_session.get(AdverseEventRca, inspect(rca).identity[0]).root_cause == "尚待证据核实的原根因文本"
    assert db_session.query(AIRun).count() == 0


def test_other_patient_unlinked_event_and_encounter_guess_are_rejected(seed_data, db_session, incident_case):
    report, _, other, unlinked = incident_case
    for selected in (other, unlinked):
        denied_without_legacy_text(db_session, lambda: snapshot(db_session, seed_data, selected))
    denied_without_legacy_text(db_session, lambda: snapshot(db_session, seed_data, report, encounter="explicit-encounter-without-event-link"))


@pytest.mark.asyncio
async def test_legacy_event_ids_cannot_select_a_native_source_and_patient_cannot_use_dedicated_api(seed_data, db_session, incident_case, async_client, auth_headers):
    report = incident_case[0]
    for reference in (report.event_id, True, "01", "0", "-1", "2147483648", "1" * 5000, "１２", {}, []):
        denied_without_legacy_text(db_session, lambda: snapshot(db_session, seed_data, reference=reference))
    response = await async_client.post(
        "/api/ai/rca-evidence/context", headers=auth_headers(seed_data["patient_user"].username), json={"rca_evidence_case_id": "00000000-0000-0000-0000-000000000001", "preview": True}
    )
    assert response.status_code == 403
    assert db_session.query(AIRun).count() == 0


@pytest.mark.asyncio
async def test_no_selection_or_patient_scope_cannot_create_billable_task(seed_data, db_session, incident_case, async_client, auth_headers):
    denied_without_legacy_text(db_session, lambda: snapshot(db_session, seed_data))
    with pytest.raises(ValidationError):
        RunRequest(feature_key="incident_rca", patient_id=seed_data["patient"].patient_id)
    for body in (
        {"feature_key": "incident_rca", "input": {}, "preview": True},
        {"feature_key": "incident_rca", "patient_id": seed_data["patient"].patient_id, "input": {"adverse_event_id": str(incident_case[0].event_id)}},
    ):
        response = await async_client.post("/api/ai/runs", headers=auth_headers("super01"), json=body)
        assert response.status_code == 422, response.text
    assert db_session.query(AIRun).count() == 0


def test_saved_legacy_rca_change_invalidates_queued_native_case_without_rewriting_frozen_sources(seed_data, db_session, incident_case, monkeypatch):
    from app.config import settings
    from tests.test_ai_rca_evidence_configuration import configured
    from tests.test_ai_rca_evidence_grants import NOW

    monkeypatch.setattr(settings, "AI_PROVIDER_ALLOWED_HOSTS", "synthetic.invalid")
    monkeypatch.setattr(grants, "utcnow", lambda: NOW)
    report, rca, *_ = incident_case
    case = {"db": db_session, "actor": seed_data["super_admin_user"], "event_id": report.event_id, "patient_id": report.patient_id}
    seeded, value, _ = configured(case)
    seed_id = inspect(seeded.run).identity[0]
    db_session.execute(text("DELETE FROM hoimsystem_ai_rca_evidence_run_artifact WHERE run_id=:id"), {"id": seed_id})
    db_session.execute(text("DELETE FROM hoimsystem_ai_run WHERE run_id=:id"), {"id": seed_id})
    db_session.commit()
    run = create_run(db_session, case["actor"], RunRequest(feature_key="incident_rca", input={"rca_evidence_case_id": value.binding.case_id}, preview=True))
    identifier = inspect(run).identity[0]
    rca.root_cause = "后来修改的分析"
    db_session.commit()
    assert claim_next_run(db_session) is None
    attempt = receipts.technical_header(db_session, identifier)
    receipt = receipts.read_receipt(db_session, attempt)
    assert receipt.status == "failed" and receipt.usage.model_call_attempted is False
    assert receipt.usage.input_tokens == receipt.usage.output_tokens == 0 and attempt.artifact["dispatch_event_id"] is None
    assert db_session.get(AIRcaEvidenceRunResult, identifier) is None
    with pytest.raises(HTTPException) as failure:
        storage.load_task(db_session, case["actor"], identifier)
    assert failure.value.status_code == 409
    frozen = c.canonical(storage.case_piece(db_session, case["actor"], identifier, frozen_audit=True))
    assert "尚待证据核实的原根因文本" in frozen and "后来修改的分析" not in frozen
    assert db_session.get(AdverseEventRca, inspect(rca).identity[0]).root_cause == "后来修改的分析"


@pytest.mark.asyncio
async def test_generic_preview_refuses_legacy_id_and_catalog_declares_unique_case_source(seed_data, db_session, incident_case, async_client, auth_headers):
    report = incident_case[0]
    payload = {"feature_key": "incident_rca", "patient_id": report.patient_id, "source_refs": {"adverse_event_id": str(report.event_id)}}
    response = await async_client.post("/api/ai/context", json=payload, headers=auth_headers("super01"))
    assert response.status_code == 422
    assert db_session.query(AIRun).count() == 0
    result = await async_client.get("/api/ai/features", headers=auth_headers("super01"))
    spec = next(item for item in result.json()["data"] if item["key"] == "incident_rca")
    assert spec["source_reference_keys"] == ["rca_evidence_case_id"] and spec["input_mode"] == "rca_evidence"
