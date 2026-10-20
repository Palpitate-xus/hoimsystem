"""Explicit incident selection, minimal disclosure and recorded-versus-verified RCA boundaries."""

import datetime
import json

import httpx
import pytest
from fastapi import HTTPException

from app.ai.catalog import FEATURE_BY_KEY
from app.ai.context import patient_snapshot
from app.ai.governance import encode_json
from app.ai.models import AIFeatureConfig, AIFeedback, AIProvider, AIRun
from app.ai.runtime import claim_next_run, create_run, describe_run, execute_claimed
from app.ai.schemas import RunRequest
from app.models import AdverseEvent, AdverseEventRca


@pytest.fixture(autouse=True)
def clean_incidents(db_session):
    for model in (AIFeedback, AIRun, AIFeatureConfig, AIProvider, AdverseEventRca, AdverseEvent):
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
    refs = {"adverse_event_id": reference if reference is not None else str(event.event_id)} if event or reference is not None else {}
    return patient_snapshot(db_session, user or seed_data["super_admin_user"], FEATURE_BY_KEY["incident_rca"], seed_data["patient"].patient_id, encounter, refs)


def test_incident_snapshot_contains_only_selected_report_and_rca_with_unknown_verification(seed_data, db_session, incident_case):
    event, rca, _, _ = incident_case
    bundle = snapshot(db_session, seed_data, event)
    assert bundle.data["incident_record"]["recorded_status"] == 2
    assert bundle.data["incident_source_scope"]["encounter_assignment"] == "not_recorded"
    assert bundle.data["incident_source_scope"]["root_cause_verification"] == "not_recorded"
    assert bundle.data["incident_rca_records"][0]["verification_status"] == "not_recorded"
    assert bundle.data["incident_rca_records"][0]["recorded_pdca_stage"] == "A"
    serialized = encode_json({"context": bundle.data, "evidence": bundle.evidence})
    for forbidden in (
        "其他患者事件",
        "其他患者根因文本",
        "outpatient_records",
        "structured_records",
        "prescriptions",
        "latest_vitals",
        '"age"',
        '"sex"',
        seed_data["patient"].name,
        seed_data["patient"].identity,
        "reporter_id",
        "analyst_id",
    ):
        assert forbidden not in serialized
    assert {row["source_id"] for row in bundle.evidence} == {"adverse-event:" + str(event.event_id), "incident-rca:" + str(rca.rca_id)}


def test_other_patient_unlinked_event_and_encounter_guess_are_rejected(seed_data, db_session, incident_case):
    event, _, other, unlinked = incident_case
    for selected in (other, unlinked):
        with pytest.raises(HTTPException) as error:
            snapshot(db_session, seed_data, selected)
        assert error.value.status_code == 404
    with pytest.raises(HTTPException) as error:
        snapshot(db_session, seed_data, event, encounter="explicit-encounter-without-event-link")
    assert error.value.status_code == 422


def test_event_id_validation_is_bounded_and_patient_role_cannot_inspect_internal_event(seed_data, db_session, incident_case):
    event = incident_case[0]
    for reference in (event.event_id, True, "01", "0", "-1", "2147483648", "1" * 5000, "１２", {}, []):
        with pytest.raises(HTTPException) as error:
            snapshot(db_session, seed_data, reference=reference)
        assert error.value.status_code == 422
    with pytest.raises(HTTPException) as error:
        snapshot(db_session, seed_data, event, user=seed_data["patient_user"])
    assert error.value.status_code == 403


def configure(db_session, seed_data):
    provider = AIProvider(name="rca-isolated", kind="chat", api_base="http://localhost:11434/v1", model="isolated", enabled=1, allows_patient_data=1, created_by=seed_data["super_admin_user"].user_id)
    db_session.add(provider)
    db_session.flush()
    db_session.add(
        AIFeatureConfig(
            feature_key="incident_rca",
            enabled=1,
            provider_id=provider.provider_id,
            allowed_roles_json=encode_json(FEATURE_BY_KEY["incident_rca"].default_roles),
            updated_by=seed_data["super_admin_user"].user_id,
        )
    )
    db_session.commit()


def test_no_selection_inspects_only_missing_data_and_cannot_create_billable_task(seed_data, db_session, incident_case):
    bundle = snapshot(db_session, seed_data)
    assert not bundle.evidence and "incident_record" not in bundle.data
    configure(db_session, seed_data)
    with pytest.raises(HTTPException) as error:
        create_run(db_session, seed_data["super_admin_user"], RunRequest(feature_key="incident_rca", patient_id=seed_data["patient"].patient_id))
    assert error.value.status_code == 409
    assert db_session.query(AIRun).count() == 0


@pytest.mark.asyncio
async def test_saved_rca_change_while_queued_prevents_inference_and_retains_old_sources(seed_data, db_session, incident_case):
    event, rca, _, _ = incident_case
    configure(db_session, seed_data)
    run = create_run(db_session, seed_data["super_admin_user"], RunRequest(feature_key="incident_rca", patient_id=event.patient_id, input={"adverse_event_id": str(event.event_id)}))
    frozen = json.loads(run.input_json)
    rca.root_cause = "后来修改的分析"
    db_session.commit()
    calls = []
    await execute_claimed(*claim_next_run(db_session), transport=httpx.MockTransport(lambda request: (calls.append(request), httpx.Response(500))[1]))
    db_session.refresh(run)
    assert not calls and run.status == "failed" and run.error_code == "TASK_CONTEXT_CHANGED"
    findings = describe_run(run, include_result=True)["incident_findings"]
    assert findings["incident_rca_records"] == frozen["payload"]["context"]["incident_rca_records"]
    assert "后来修改的分析" not in encode_json(findings)


@pytest.mark.asyncio
async def test_preview_uses_published_reference_key_without_provider_or_task(seed_data, db_session, incident_case, async_client, auth_headers):
    event, _, _, _ = incident_case
    payload = {"feature_key": "incident_rca", "patient_id": event.patient_id, "source_refs": {"adverse_event_id": str(event.event_id)}}
    response = await async_client.post("/api/ai/context", json=payload, headers=auth_headers("super01"))
    assert response.status_code == 200
    assert response.json()["data"]["context"]["incident_record"]["event_id"] == event.event_id
    assert db_session.query(AIRun).count() == 0
    result = await async_client.get("/api/ai/features", headers=auth_headers("super01"))
    spec = next(item for item in result.json()["data"] if item["key"] == "incident_rca")
    assert "adverse_event_id" in spec["source_reference_keys"]
