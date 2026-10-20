"""Real frozen originals through the actual arithmetic service, worker and history."""

import json

import httpx
import pytest
from fastapi import HTTPException

from app.ai.catalog import FEATURE_BY_KEY
from app.ai.context import patient_snapshot
from app.ai.governance import describe_config, encode_json
from app.ai.models import AIRun
from app.ai.qsofa_config import QsofaSettings, runtime_descriptor
from app.ai.qsofa_server import create_qsofa_app
from app.ai.qsofa_sources import create_assessment
from app.ai.runtime import claim_next_run, create_run, execute_claimed
from app.ai.schemas import RunRequest
from app.models import Admission, Doctor, MedicalRecord, Prescription
from tests.test_ai_qsofa_sources import NOTE, body, extra_gcs
from tests.test_ai_qsofa_sources import case as case
from tests.test_ai_qsofa_sources import observation_case as observation_case
from tests.test_ai_runtime import clean_ai_tasks as clean_ai_tasks
from tests.test_ai_runtime import configure

KEY = "synthetic-qsofa-worker-key-with-no-live-credential"


class RealQsofaTransport(httpx.AsyncBaseTransport):
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
def qsofa_case(db_session, case, clean_ai_tasks, monkeypatch):
    case["assessment"] = create_assessment(db_session, case["doctor"], body(case))
    db_session.commit()
    monkeypatch.setenv("AI_PROVIDER_LOCAL_QSOFA_API_KEY", KEY)
    config = QsofaSettings(AI_PROVIDER_LOCAL_QSOFA_API_KEY=KEY)
    provider, feature = configure(db_session, case["seed"], "sepsis_risk")
    provider.kind, provider.model = "specialist", runtime_descriptor(config)["model_version"]
    provider.api_base, provider.api_key_env = "http://localhost:8816", "AI_PROVIDER_LOCAL_QSOFA_API_KEY"
    provider.supported_features_json = encode_json(["sepsis_risk"])
    provider.validation_report = "Synthetic source arithmetic engineering checks only, not clinical validation."
    provider.timeout_seconds = 30
    db_session.commit()
    case.update(provider=provider, feature=feature, service=create_qsofa_app(config))
    return case


def request_for(case):
    return RunRequest(
        feature_key="sepsis_risk",
        patient_id=case["patient_id"],
        encounter_ref=case["admission_id"],
        input={"observation_window_id": case["window"].window_id, "qsofa_assessment_id": case["assessment"].assessment_id, "question": "自由问题不能外发或改变原床旁计数"},
    )


@pytest.mark.asyncio
async def test_actual_context_queue_service_and_history_preserve_originals_and_separate_review_clock(async_client, auth_headers, db_session, qsofa_case):
    case = qsofa_case
    before = {model.__tablename__: db_session.query(model).count() for model in (Admission, MedicalRecord, Prescription)}
    response = await async_client.post(
        "/api/ai/context",
        headers=auth_headers(case["doctor"].username),
        json={
            "feature_key": "sepsis_risk",
            "patient_id": case["patient_id"],
            "encounter_ref": case["admission_id"],
            "source_refs": {key: value for key, value in request_for(case).input.items() if key != "question"},
        },
    )
    assert response.status_code == 200, response.text
    context = response.json()["data"]["context"]
    source, frozen = context["qsofa_source"], context["qsofa_assessment"]
    assert "observation_window" not in context and frozen["context_projection"] == "qsofa_review_v1"
    assert source["clinical_statements_recorded_at"] == source["evaluation_at"] > source["as_of"]
    assert source["gcs"]["observed_at"] != source["observed_at"] and source["historical_prediction"] is False
    assert "recipe" not in frozen["snapshot"]["rule_profile"]
    assert "infection_basis_note" not in frozen["snapshot"]["attestation"]
    assert frozen["snapshot"]["provenance_note_hashes"]["scope_evidence_hash"] == source["scope_evidence_hash"]
    assert "same_exam_basis_note" not in frozen["snapshot"]["gcs_observation"]["payload"]
    assert NOTE not in encode_json(context)
    run = create_run(db_session, case["doctor"], request_for(case))
    transport = RealQsofaTransport(case["service"])
    await execute_claimed(*claim_next_run(db_session), transport=transport)
    db_session.expire_all()
    stored = db_session.get(AIRun, run.run_id)
    assert stored.status == "succeeded", stored.error_message
    assert len(transport.requests) == 1
    wire = transport.requests[0]
    assert wire["schema_version"] == "8" and wire["store"] is False
    assert wire["input"] == {"context": {"qsofa_source": source}}
    assert all(value not in encode_json(wire["input"]) for value in ("patient_id", "admission_id", NOTE, "自由问题", "原始点测备注"))
    detail = await async_client.get(f"/api/ai/runs/{run.run_id}", headers=auth_headers(case["doctor"].username))
    assert detail.status_code == 200, detail.text
    data = detail.json()["data"]
    analysis = data["result"]["qsofa_analysis"]
    assert analysis["source_binding"] == source and analysis["total_score"] == 2
    assert analysis["threshold_status"] == "at_least_two" and analysis["scored_count"] == 3
    assert analysis["diagnosis_provided"] is False and analysis["probability_provided"] is False
    assert analysis["clinical_validation"] == "not_provided"
    assert data["qsofa_findings"] == {"qsofa_source": source, "qsofa_assessment": frozen}
    assert before == {model.__tablename__: db_session.query(model).count() for model in (Admission, MedicalRecord, Prescription)}


def mutate(db, case, change, monkeypatch):
    if change in {"assessment_revoke", "profile_revoke", "gcs_revoke"}:
        row = case[{"assessment_revoke": "assessment", "profile_revoke": "profile", "gcs_revoke": "gcs"}[change]]
        row.status, row.revision = "revoked", row.revision + 1
        if change == "profile_revoke":
            row.published_key = None
        row.revoked_at, row.revoked_by, row.revoke_reason = case["now"], case["seed"]["super_admin_user"].user_id, "Synthetic original evidence withdrawal"
    elif change == "assessment_note":
        value = json.loads(case["assessment"].snapshot_json)
        value["attestation"]["infection_basis_note"] = "Changed original clinical evidence omitted from the compact payload"
        case["assessment"].snapshot_json = encode_json(value)
    elif change in {"point_note", "gcs_anchor"}:
        row = case["point"] if change == "point_note" else case["gcs"]
        value = json.loads(row.payload_json)
        if change == "point_note":
            value["note"] = "Changed full original point note omitted from compact context"
        else:
            value["same_exam_basis_note"] = "Changed original same-exam evidence omitted from compact context"
        row.payload_json = encode_json(value)
    elif change == "doctor_identity":
        signed = json.loads(case["assessment"].snapshot_json)["author_qualification"]
        db.get(Doctor, signed["doctor_id"]).user_id = case["seed"]["nurse_user"].user_id
    elif change == "gcs_membership":
        extra_gcs(db, case, monkeypatch)
    elif change == "care":
        case["admission"].doctor_id = None
    else:
        raise AssertionError(change)
    db.commit()


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["queued", "inflight", "history"])
@pytest.mark.parametrize("change", ["assessment_revoke", "profile_revoke", "gcs_revoke", "assessment_note", "point_note", "gcs_anchor", "doctor_identity", "gcs_membership", "care"])
async def test_changed_original_scope_or_governance_blocks_queue_reply_and_ordinary_history(phase, change, monkeypatch, async_client, auth_headers, db_session, qsofa_case):
    case = qsofa_case
    run = create_run(db_session, case["doctor"], request_for(case))
    if phase == "queued":
        mutate(db_session, case, change, monkeypatch)
    transport = RealQsofaTransport(case["service"], before=(lambda: mutate(db_session, case, change, monkeypatch)) if phase == "inflight" else None)
    await execute_claimed(*claim_next_run(db_session), transport=transport)
    db_session.expire_all()
    stored = db_session.get(AIRun, run.run_id)
    if phase != "history":
        assert stored.status == "failed" and stored.result_json == "{}"
        assert len(transport.requests) == (0 if phase == "queued" else 1)
        return
    assert stored.status == "succeeded", stored.error_message
    mutate(db_session, case, change, monkeypatch)
    denied = await async_client.get(f"/api/ai/runs/{run.run_id}", headers=auth_headers(case["doctor"].username))
    assert denied.status_code == 403, denied.text
    audit = await async_client.get(f"/api/ai/runs/{run.run_id}", headers=auth_headers(case["seed"]["super_admin_user"].username))
    assert audit.status_code == 200, audit.text
    assert audit.json()["data"]["qsofa_findings"]["qsofa_source"]["assessment_id"] == case["assessment"].assessment_id


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["total", "source_value", "criterion", "threshold", "diagnosis", "prompt", "probability", "false_claim"])
async def test_gateway_recomputes_every_fixed_criterion_and_explanation(change, db_session, qsofa_case):
    case = qsofa_case
    run = create_run(db_session, case["doctor"], request_for(case))

    def alter(value):
        analysis = value["qsofa_analysis"]
        if change == "total":
            analysis["total_score"] = 3
        elif change == "source_value":
            analysis["source_binding"]["measurements"]["respiratory_rate"]["value"] = "99"
        elif change == "criterion":
            analysis["criteria"][0]["score"] = 0
        elif change == "threshold":
            analysis["threshold_status"] = "below_two_in_complete_data"
        elif change == "diagnosis":
            analysis["diagnosis_provided"] = True
        elif change == "prompt":
            analysis["instructions_digest"] = "0" * 64
        elif change == "probability":
            value["result"]["probability"] = 0.99
        else:
            value["result"]["summary"] = "伪造确诊脓毒症并自动治疗"

    await execute_claimed(*claim_next_run(db_session), transport=RealQsofaTransport(case["service"], alter=alter))
    db_session.expire_all()
    stored = db_session.get(AIRun, run.run_id)
    assert stored.status == "failed" and stored.result_json == "{}"
    assert stored.error_code in {"QSOFA_BINDING_MISMATCH", "INVALID_OUTPUT"}


@pytest.mark.asyncio
async def test_originals_recorded_after_cutoff_cannot_leak_existence_into_old_assessment(monkeypatch, db_session, qsofa_case):
    case = qsofa_case
    run = create_run(db_session, case["doctor"], request_for(case))
    extra_gcs(db_session, case, monkeypatch, recorded=case["now"])
    await execute_claimed(*claim_next_run(db_session), transport=RealQsofaTransport(case["service"]))
    db_session.expire_all()
    assert db_session.get(AIRun, run.run_id).status == "succeeded"


@pytest.mark.parametrize("feature", ["deterioration_risk", "aki_risk", "patient_summary"])
def test_original_qsofa_reference_is_exclusive_to_feature_42(feature, db_session, qsofa_case):
    case = qsofa_case
    with pytest.raises(HTTPException) as caught:
        patient_snapshot(db_session, case["doctor"], FEATURE_BY_KEY[feature], case["patient_id"], case["admission_id"], request_for(case).input)
    assert caught.value.status_code == 422


def test_original_window_provider_mode_remains_explicit_without_silently_using_qsofa(db_session, qsofa_case):
    case = qsofa_case
    assert describe_config(db_session, FEATURE_BY_KEY["sepsis_risk"], case["feature"])["input_mode"] == "qsofa"
    request = request_for(case)
    request.input.pop("qsofa_assessment_id")
    with pytest.raises(HTTPException) as caught:
        create_run(db_session, case["doctor"], request)
    assert caught.value.status_code == 422
    case["provider"].model = "external-sepsis-model-requiring-own-validation"
    db_session.commit()
    assert describe_config(db_session, FEATURE_BY_KEY["sepsis_risk"], case["feature"])["input_mode"] == "observation_window"
    legacy = patient_snapshot(db_session, case["doctor"], FEATURE_BY_KEY["sepsis_risk"], case["patient_id"], case["admission_id"], request.input)
    assert legacy.data["scope"] == "inpatient_observation_window" and "qsofa_source" not in legacy.data
    with pytest.raises(HTTPException) as mismatch:
        create_run(db_session, case["doctor"], request_for(case))
    assert mismatch.value.status_code == 422


@pytest.mark.parametrize("change", [None, "profile_revoke", "corrupt_profile"])
def test_readiness_requires_its_independent_rule_and_never_sets_clinical_validation(change, monkeypatch, db_session, qsofa_case):
    from app.ai.readiness import setup_reports

    case = qsofa_case
    if change == "profile_revoke":
        mutate(db_session, case, change, monkeypatch)
    elif change == "corrupt_profile":
        case["profile"].payload_json += " "
        db_session.commit()
    before = (case["feature"].validation_status, case["feature"].validation_note)
    report = setup_reports(db_session, {"sepsis_risk": case["feature"]})["sepsis_risk"]
    assert ("QSOFA_RULE_PROFILE_REQUIRED" in {item["code"] for item in report["issues"]}) is (change is not None)
    assert (case["feature"].validation_status, case["feature"].validation_note) == before
