"""Real governed sources, actual fixed AKI service, queue and historical access guards."""

import datetime
import json

import httpx
import pytest
from fastapi import HTTPException

from app.ai.aki_config import AkiSettings, runtime_descriptor
from app.ai.aki_server import create_aki_app
from app.ai.aki_sources import create_assessment
from app.ai.catalog import FEATURE_BY_KEY
from app.ai.context import patient_snapshot
from app.ai.governance import describe_config, encode_json
from app.ai.models import AIRun
from app.ai.runtime import claim_next_run, create_run, execute_claimed
from app.ai.schemas import RunRequest
from app.models import Admission, InpatientUrineInterval, MedicalRecord, Prescription
from tests.test_ai_aki_sources import body, rewindow, urine_payload
from tests.test_ai_aki_sources import case as case
from tests.test_ai_aki_sources import laboratory_case as laboratory_case
from tests.test_ai_aki_sources import observation_case as observation_case
from tests.test_ai_observation_windows import urine
from tests.test_ai_runtime import clean_ai_tasks as clean_ai_tasks
from tests.test_ai_runtime import configure

KEY = "synthetic-aki-pipeline-key-with-no-live-credential"


class RealAkiTransport(httpx.AsyncBaseTransport):
    def __init__(self, app, *, before=None, alter=None):
        self.inner = httpx.ASGITransport(app=app)
        self.requests = []
        self.before, self.alter = before, alter

    async def handle_async_request(self, request):
        self.requests.append(json.loads(request.content))
        if self.before:
            self.before()
        response = await self.inner.handle_async_request(request)
        if self.alter:
            value = json.loads(await response.aread())
            self.alter(value)
            return httpx.Response(response.status_code, json=value, request=request)
        return response


@pytest.fixture
def aki_case(db_session, case, clean_ai_tasks, monkeypatch):
    case["assessment"] = create_assessment(db_session, case["doctor"], body(case))
    db_session.commit()
    monkeypatch.setenv("AI_PROVIDER_LOCAL_AKI_API_KEY", KEY)
    config = AkiSettings(AI_PROVIDER_LOCAL_AKI_API_KEY=KEY)
    descriptor = runtime_descriptor(config)
    provider, feature = configure(db_session, case["seed"], "aki_risk")
    provider.kind, provider.model = "specialist", descriptor["model_version"]
    provider.api_base, provider.api_key_env = "http://localhost:8815", "AI_PROVIDER_LOCAL_AKI_API_KEY"
    provider.supported_features_json = encode_json(["aki_risk"])
    provider.validation_report = "Synthetic deterministic source arithmetic engineering only; not clinical validation."
    provider.timeout_seconds = 30
    db_session.commit()
    case.update(provider=provider, feature=feature, service=create_aki_app(config))
    return case


def request_for(case):
    return RunRequest(
        feature_key="aki_risk",
        patient_id=case["patient_id"],
        encounter_ref=case["admission"].admission_id,
        input={"observation_window_id": case["window"].window_id, "aki_assessment_id": case["assessment"].assessment_id, "question": "自由问题不能改变分期或外发原临床依据"},
    )


@pytest.mark.asyncio
async def test_actual_queue_service_and_compact_source_keep_supported_stage_and_all_original_values(async_client, auth_headers, db_session, aki_case):
    case = aki_case
    before = {model.__tablename__: db_session.query(model).count() for model in (Admission, MedicalRecord, Prescription)}
    response = await async_client.post(
        "/api/ai/context",
        headers=auth_headers(case["doctor"].username),
        json={
            "feature_key": "aki_risk",
            "patient_id": case["patient_id"],
            "encounter_ref": case["admission"].admission_id,
            "source_refs": {key: value for key, value in request_for(case).input.items() if key != "question"},
        },
    )
    assert response.status_code == 200, response.text
    context = response.json()["data"]["context"]
    source, frozen = context["aki_source"], context["aki_assessment"]
    assert "observation_window" not in context
    assert frozen["context_projection"] == "aki_review_v1"
    assert "recipe" not in frozen["snapshot"]["rule_profile"]
    assert "age_basis_note" not in frozen["snapshot"]["attestation"]
    assert frozen["snapshot"]["provenance_note_hashes"]["age_basis_note"]
    assert frozen["snapshot"]["index_creatinine"]["snapshot"]["original"]["observation"]["value_num"] == source["index_creatinine"]["value"]
    run = create_run(db_session, case["doctor"], request_for(case))
    transport = RealAkiTransport(case["service"])
    await execute_claimed(*claim_next_run(db_session), transport=transport)
    db_session.expire_all()
    stored = db_session.get(AIRun, run.run_id)
    assert stored.status == "succeeded", stored.error_message
    assert len(transport.requests) == 1
    wire = transport.requests[0]
    assert wire["schema_version"] == "7" and wire["store"] is False
    assert wire["input"] == {"context": {"aki_source": source}}
    assert "patient_id" not in encode_json(wire["input"]) and "age_basis_note" not in encode_json(wire["input"])
    assert "自由问题" not in encode_json(wire["input"])
    detail = await async_client.get(f"/api/ai/runs/{run.run_id}", headers=auth_headers(case["doctor"].username))
    assert detail.status_code == 200, detail.text
    data = detail.json()["data"]
    analysis = data["result"]["aki_analysis"]
    assert analysis["source_binding"] == source and analysis["minimum_stage"] == 2
    assert analysis["detection"] == "met" and analysis["stage_is_lower_bound"] is True and analysis["aki_excluded"] is False
    assert analysis["clinical_validation"] == "not_provided"
    assert data["aki_findings"]["aki_assessment"] == frozen and data["aki_findings"]["aki_source"] == source
    assert before == {model.__tablename__: db_session.query(model).count() for model in (Admission, MedicalRecord, Prescription)}


def mutate(db, case, change):
    if change in {"assessment_revoke", "profile_revoke"}:
        row = case["assessment"] if change == "assessment_revoke" else case["profile"]
        row.status, row.revision = "revoked", 2 if change == "assessment_revoke" else 3
        if change == "profile_revoke":
            row.published_key = None
        row.revoked_at, row.revoked_by, row.revoke_reason = case["now"], case["seed"]["super_admin_user"].user_id, "Synthetic original source withdrawn for engineering test"
    elif change == "assessment_body":
        value = json.loads(case["assessment"].snapshot_json)
        value["attestation"]["age_basis_note"] = "Changed original clinical provenance note omitted from compact context"
        case["assessment"].snapshot_json = encode_json(value)
    elif change == "lab_parent":
        case["index"]["report"].result = "Changed original parent text omitted from the AKI projection"
    elif change == "urine_body":
        value = json.loads(case["urines"][0].payload_json)
        value["note"] = "Changed original urine note omitted from the AKI projection"
        case["urines"][0].payload_json = encode_json(value)
    elif change == "care":
        case["admission"].doctor_id = None
    else:
        raise AssertionError(change)
    db.commit()


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["queued", "inflight", "history"])
@pytest.mark.parametrize("change", ["assessment_revoke", "profile_revoke", "assessment_body", "lab_parent", "urine_body", "care"])
async def test_changed_original_scope_or_governance_blocks_queue_receipt_and_ordinary_old_result(phase, change, async_client, auth_headers, db_session, aki_case):
    case = aki_case
    run = create_run(db_session, case["doctor"], request_for(case))
    if phase == "queued":
        mutate(db_session, case, change)
    transport = RealAkiTransport(case["service"], before=(lambda: mutate(db_session, case, change)) if phase == "inflight" else None)
    await execute_claimed(*claim_next_run(db_session), transport=transport)
    db_session.expire_all()
    stored = db_session.get(AIRun, run.run_id)
    if phase != "history":
        assert stored.status == "failed" and stored.result_json == "{}"
        assert len(transport.requests) == (0 if phase == "queued" else 1)
        return
    assert stored.status == "succeeded", stored.error_message
    mutate(db_session, case, change)
    denied = await async_client.get(f"/api/ai/runs/{run.run_id}", headers=auth_headers(case["doctor"].username))
    assert denied.status_code == 403, denied.text
    audit = await async_client.get(f"/api/ai/runs/{run.run_id}", headers=auth_headers(case["seed"]["super_admin_user"].username))
    assert audit.status_code == 200, audit.text
    assert audit.json()["data"]["aki_findings"]["aki_source"]["assessment_id"] == case["assessment"].assessment_id


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["stage", "source_value", "criterion", "duration", "aki_excluded", "prompt", "probability", "false_claim"])
async def test_gateway_recomputes_every_criterion_source_time_and_fixed_explanation(change, db_session, aki_case):
    case = aki_case
    run = create_run(db_session, case["doctor"], request_for(case))

    def alter(value):
        analysis = value["aki_analysis"]
        if change == "stage":
            analysis["minimum_stage"] = 3
        elif change == "source_value":
            analysis["source_binding"]["index_creatinine"]["value"] = "999"
        elif change == "criterion":
            analysis["criteria"][0]["status"] = "met"
        elif change == "duration":
            analysis["criteria"][3]["evidence"]["elapsed_microseconds"] = 1
        elif change == "aki_excluded":
            analysis["aki_excluded"] = True
        elif change == "prompt":
            analysis["instructions_digest"] = "0" * 64
        elif change == "probability":
            value["result"]["probability"] = 0.99
        else:
            value["result"]["summary"] = "伪造临床确诊，应该自动透析"

    await execute_claimed(*claim_next_run(db_session), transport=RealAkiTransport(case["service"], alter=alter))
    db_session.expire_all()
    stored = db_session.get(AIRun, run.run_id)
    assert stored.status == "failed" and stored.result_json == "{}"
    assert stored.error_code in {"AKI_BINDING_MISMATCH", "INVALID_OUTPUT"}


@pytest.mark.parametrize("feature", ["deterioration_risk", "sepsis_risk", "patient_summary"])
def test_aki_reference_cannot_be_consumed_by_other_features(feature, db_session, aki_case):
    case = aki_case
    with pytest.raises(HTTPException) as caught:
        patient_snapshot(db_session, case["doctor"], FEATURE_BY_KEY[feature], case["patient_id"], case["admission"].admission_id, request_for(case).input)
    assert caught.value.status_code == 422


def test_actual_aki_mode_is_distinct_and_original_window_mode_remains_available(db_session, aki_case):
    case = aki_case
    assert describe_config(db_session, FEATURE_BY_KEY["aki_risk"], case["feature"])["input_mode"] == "aki"
    request = request_for(case)
    request.input.pop("aki_assessment_id")
    with pytest.raises(HTTPException) as caught:
        create_run(db_session, case["doctor"], request)
    assert caught.value.status_code == 422
    case["provider"].model = "external-kidney-prediction-model"
    db_session.commit()
    assert describe_config(db_session, FEATURE_BY_KEY["aki_risk"], case["feature"])["input_mode"] == "observation_window"
    legacy = patient_snapshot(db_session, case["doctor"], FEATURE_BY_KEY["aki_risk"], case["patient_id"], case["admission"].admission_id, request.input)
    assert legacy.data["scope"] == "inpatient_observation_window" and "aki_source" not in legacy.data
    # This real three-lab fixture exceeds the TEXT task envelope when the
    # legacy whole-window mode repeats all evidence. Preserve its honest guard.
    with pytest.raises(HTTPException) as capacity:
        create_run(db_session, case["doctor"], request)
    assert capacity.value.status_code == 422 and "65535" in capacity.value.detail
    assert db_session.query(AIRun).count() == 0
    with pytest.raises(HTTPException) as mismatch:
        create_run(db_session, case["doctor"], request_for(case))
    assert mismatch.value.status_code == 422


@pytest.mark.asyncio
async def test_complete_twenty_four_hourly_originals_fit_without_dropping_sources_or_facts(db_session, aki_case):
    case = aki_case
    db_session.query(InpatientUrineInterval).delete()
    case["urines"] = [
        urine(db_session, case, start=case["end"] - datetime.timedelta(hours=24 - index), end=case["end"] - datetime.timedelta(hours=23 - index), payload=urine_payload("1.00")) for index in range(24)
    ]
    db_session.commit()
    rewindow(db_session, case)
    case["assessment"] = create_assessment(db_session, case["doctor"], body(case))
    db_session.commit()
    run = create_run(db_session, case["doctor"], request_for(case))
    frozen = json.loads(run.input_json)["payload"]["context"]
    assert len(frozen["aki_source"]["urine_intervals"]) == len(frozen["aki_assessment"]["snapshot"]["urine_intervals"]) == 24
    assert all(item["volume_ml"] == "1.00" for item in frozen["aki_source"]["urine_intervals"])
    assert len(run.input_json.encode()) <= 65535 and len(run.evidence_json.encode()) <= 65535
    await execute_claimed(*claim_next_run(db_session), transport=RealAkiTransport(case["service"]))
    db_session.expire_all()
    stored = db_session.get(AIRun, run.run_id)
    assert stored.status == "succeeded", stored.error_message
    analysis = json.loads(stored.result_json)["aki_analysis"]
    assert analysis["minimum_stage"] == 3 and len(analysis["source_binding"]["urine_intervals"]) == 24


@pytest.mark.parametrize("change", [None, "profile_revoke", "corrupt_profile"])
def test_readiness_requires_this_current_rule_without_claiming_clinical_effects(change, db_session, aki_case):
    from app.ai.readiness import setup_reports

    case = aki_case
    if change == "profile_revoke":
        mutate(db_session, case, change)
    elif change == "corrupt_profile":
        case["profile"].payload_json += " "
        db_session.commit()
    original_validation = (case["feature"].validation_status, case["feature"].validation_note)
    report = setup_reports(db_session, {"aki_risk": case["feature"]})["aki_risk"]
    assert ("AKI_RULE_PROFILE_REQUIRED" in {item["code"] for item in report["issues"]}) is (change is not None)
    assert (case["feature"].validation_status, case["feature"].validation_note) == original_validation


def test_fixed_aki_service_cannot_be_reused_as_another_model_or_protocol(db_session, aki_case):
    from app.ai.governance import provider_feature_issues

    provider = aki_case["provider"]
    for key in ("patient_summary", "sepsis_risk", "deterioration_risk", "visit_forecast"):
        assert "AKI_SCOPE_MISMATCH" in {item["code"] for item in provider_feature_issues(FEATURE_BY_KEY[key], provider)}
    provider.kind = "chat"
    assert "AKI_SCOPE_MISMATCH" in {item["code"] for item in provider_feature_issues(FEATURE_BY_KEY["aki_risk"], provider)}
