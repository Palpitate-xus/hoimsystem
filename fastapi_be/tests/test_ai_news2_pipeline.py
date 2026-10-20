"""Actual source, queue, fixed NEWS2 service and ordinary/Super result guards."""

import datetime
import json

import httpx
import pytest
from fastapi import HTTPException

from app.ai.catalog import FEATURE_BY_KEY
from app.ai.context import patient_snapshot
from app.ai.governance import describe_config, encode_json
from app.ai.models import AINews2Assessment, AIRiskRuleProfile, AIRun
from app.ai.news2_config import News2Settings, runtime_descriptor
from app.ai.news2_contract import recipe_digest
from app.ai.news2_server import create_news2_app
from app.ai.news2_sources import create_assessment
from app.ai.observation_windows import snapshot_current
from app.ai.risk_rule_profiles import create_profile
from app.ai.runtime import claim_next_run, create_run, execute_claimed
from app.ai.schemas import RunRequest
from app.inpatient_observations import canonical_json, frozen_content_hash
from app.models import Admission, MedicalRecord, Prescription
from app.routers.ai_risk_rules import ProfilePublish, publish_profile
from tests.test_ai_observation_windows import create
from tests.test_ai_observation_windows import observation_case as observation_case
from tests.test_ai_runtime import clean_ai_tasks as clean_ai_tasks
from tests.test_ai_runtime import configure

KEY = "synthetic-news2-pipeline-key-with-no-live-credential"
NOTE = "合成实施与适用性核实依据，独立数值工程测试，不代表临床验证或真实病人。"


class RealNews2Transport(httpx.AsyncBaseTransport):
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
def news2_case(db_session, observation_case, clean_ai_tasks, monkeypatch):
    case = observation_case
    db_session.query(AINews2Assessment).delete()
    db_session.query(AIRiskRuleProfile).delete()
    values = {"respiratory_rate": ("21", "/min"), "spo2": ("95", "%"), "systolic_bp": ("105", "mm[Hg]"), "pulse_rate": ("110", "/min"), "temperature": ("38.10", "Cel"), "heart_rate": ("0", "/min")}
    payload = {
        "measurements": {key: {"value": value, "unit": unit, "absent_reason": None} for key, (value, unit) in values.items()},
        "supplemental_oxygen": "no",
        "oxygen_device": None,
        "consciousness": {"system": "ACVPU", "code": "alert"},
        "note": "仅原来源可见而不外发的备注：" + case["seed"]["patient"].name,
    }
    case["point"].payload_json = canonical_json(payload)
    case["point"].content_hash = frozen_content_hash(case["point"], payload)
    db_session.commit()
    window = create(db_session, case)
    profile = create_profile(
        db_session,
        case["seed"]["super_admin_user"],
        {"name": "合成NEWS2实施", "rule_id": "news2_2017", "expected_recipe_digest": recipe_digest(), "evidence_reference": "synthetic-reviewed-rule-reference", "rationale": NOTE},
    )
    db_session.commit()
    publish_profile(
        profile.rule_profile_id,
        ProfilePublish(expected_revision=1, expected_recipe_digest=recipe_digest(), implementation_terms_confirmed=True, review_note=NOTE, review_evidence_reference="synthetic-implementation-review"),
        db_session,
        case["seed"]["super_admin_user"],
    )
    assessment = create_assessment(
        db_session,
        case["doctor"],
        {
            "patient_id": case["patient_id"],
            "admission_id": case["admission"].admission_id,
            "window_id": window.window_id,
            "expected_window_hash": window.content_hash,
            "point_id": case["point"].observation_id,
            "expected_point_hash": case["point"].content_hash,
            "rule_profile_id": profile.rule_profile_id,
            "expected_rule_profile_hash": profile.content_hash,
            "age_at_observation_years": 40,
            "age_basis_note": NOTE,
            "pregnancy_status": "not_pregnant",
            "pregnancy_basis_note": NOTE,
            "spo2_scale": 1,
            "scale2_review": None,
        },
    )
    db_session.commit()
    monkeypatch.setenv("AI_PROVIDER_LOCAL_NEWS2_API_KEY", KEY)
    config = News2Settings(AI_PROVIDER_LOCAL_NEWS2_API_KEY=KEY)
    descriptor = runtime_descriptor(config)
    provider, feature = configure(db_session, case["seed"], "deterioration_risk")
    provider.kind, provider.model = "specialist", descriptor["model_version"]
    provider.api_base, provider.api_key_env = "http://localhost:8814", "AI_PROVIDER_LOCAL_NEWS2_API_KEY"
    provider.supported_features_json = encode_json(["deterioration_risk"])
    provider.validation_report = "Synthetic engineering fixture only, not clinical validation."
    provider.timeout_seconds = 30
    db_session.commit()
    return {**case, "window": window, "profile": profile, "assessment": assessment, "provider": provider, "feature": feature, "service": create_news2_app(config)}


def request_for(case, **changes):
    return RunRequest(
        feature_key="deterioration_risk",
        patient_id=case["patient_id"],
        encounter_ref=case["admission"].admission_id,
        input={"observation_window_id": case["window"].window_id, "news2_assessment_id": case["assessment"].assessment_id, "question": "这个自由问题不能改变固定分数，也不应外发"},
        **changes,
    )


@pytest.mark.asyncio
async def test_actual_news2_queue_uses_frozen_explicit_source_and_fixed_arithmetic(async_client, auth_headers, db_session, news2_case):
    case = news2_case
    before = {model.__tablename__: db_session.query(model).count() for model in (Admission, MedicalRecord, Prescription)}
    context = await async_client.post(
        "/api/ai/context",
        headers=auth_headers(case["doctor"].username),
        json={
            "feature_key": "deterioration_risk",
            "patient_id": case["patient_id"],
            "encounter_ref": case["admission"].admission_id,
            "source_refs": {key: value for key, value in request_for(case).input.items() if key != "question"},
        },
    )
    assert context.status_code == 200, context.text
    supplied = context.json()["data"]["context"]["news2_source"]
    assert "heart_rate" not in supplied["measurements"]
    run = create_run(db_session, case["doctor"], request_for(case))
    transport = RealNews2Transport(case["service"])
    await execute_claimed(*claim_next_run(db_session), transport=transport)
    db_session.expire_all()
    stored = db_session.get(AIRun, run.run_id)
    assert stored.status == "succeeded", stored.error_message
    assert len(transport.requests) == 1
    wire = transport.requests[0]
    assert wire["schema_version"] == "6" and wire["store"] is False
    assert wire["input"] == {"context": {"news2_source": supplied}}
    assert "question" not in encode_json(wire["input"]) and "仅原来源可见" not in encode_json(wire)
    assert "patient_id" not in encode_json(wire) and "age_basis_note" not in encode_json(wire)
    response = await async_client.get(f"/api/ai/runs/{run.run_id}", headers=auth_headers(case["doctor"].username))
    assert response.status_code == 200
    data = response.json()["data"]
    analysis = data["result"]["news2_analysis"]
    assert analysis["total_score"] == analysis["observed_subtotal"] == 6
    assert analysis["calculation_status"] == "computed" and analysis["classification"] == "medium"
    assert [item["score"] for item in analysis["components"]] == [2, 1, 1, 1, 1, 0, 0]
    assert analysis["source_binding"] == supplied and analysis["clinical_validation"] == "not_provided"
    frozen = data["news2_findings"]["news2_assessment"]
    assert frozen["patient_id"] == case["patient_id"]
    for key in ("assessment_id", "window_id", "window_content_hash", "point_id", "rule_profile_id", "rule_profile_content_hash", "recipe_digest", "observed_at", "source_id", "content_hash"):
        assert frozen[key] == supplied[key]
    assert frozen["point_content_hash"] == case["point"].content_hash
    assert frozen["governance_hash"] == supplied["source_governance_hash"]
    assert frozen["snapshot"]["point"]["payload"]["measurements"]["pulse_rate"] == supplied["measurements"]["pulse_rate"]
    assert data["news2_findings"]["news2_source"] == supplied
    assert before == {model.__tablename__: db_session.query(model).count() for model in (Admission, MedicalRecord, Prescription)}


def mutate(db, case, change):
    if change == "assessment_revoke":
        row = case["assessment"]
        row.status, row.revision = "revoked", 2
        row.revoked_at, row.revoked_by, row.revoke_reason = datetime.datetime.now(datetime.UTC).replace(tzinfo=None), case["doctor"].user_id, NOTE
    elif change == "profile_revoke":
        row = case["profile"]
        row.status, row.revision, row.published_key = "revoked", 3, None
        row.revoked_at, row.revoked_by, row.revoke_reason = datetime.datetime.now(datetime.UTC).replace(tzinfo=None), case["seed"]["super_admin_user"].user_id, NOTE
    elif change == "assessment_body":
        value = json.loads(case["assessment"].snapshot_json)
        value["attestation"]["age_basis_note"] = "Changed the previously frozen source attestation"
        case["assessment"].snapshot_json = canonical_json(value)
    elif change == "point_body":
        value = json.loads(case["point"].payload_json)
        value["note"] = "An omitted original note still changes source integrity"
        case["point"].payload_json = canonical_json(value)
    elif change == "care":
        case["admission"].doctor_id = None
    else:
        raise AssertionError(change)
    db.commit()


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["queued", "inflight", "history"])
@pytest.mark.parametrize("change", ["assessment_revoke", "profile_revoke", "assessment_body", "point_body", "care"])
async def test_actual_source_changes_stop_queue_discard_inflight_and_revoke_ordinary_history(phase, change, async_client, auth_headers, db_session, news2_case):
    case = news2_case
    run = create_run(db_session, case["doctor"], request_for(case))
    transport = RealNews2Transport(case["service"], before=(lambda: mutate(db_session, case, change)) if phase == "inflight" else None)
    if phase == "queued":
        mutate(db_session, case, change)
    await execute_claimed(*claim_next_run(db_session), transport=transport)
    db_session.expire_all()
    stored = db_session.get(AIRun, run.run_id)
    if phase != "history":
        assert stored.status == "failed" and json.loads(stored.result_json) == {}, stored.error_message
        assert len(transport.requests) == (0 if phase == "queued" else 1)
    else:
        assert stored.status == "succeeded", stored.error_message
        mutate(db_session, case, change)
    ordinary = await async_client.get(f"/api/ai/runs/{run.run_id}", headers=auth_headers(case["doctor"].username))
    assert ordinary.status_code == 403
    frozen = await async_client.get(f"/api/ai/runs/{run.run_id}", headers=auth_headers(case["seed"]["super_admin_user"].username))
    assert frozen.status_code == 200
    assert frozen.json()["data"]["news2_findings"]["news2_source"]["assessment_id"] == case["assessment"].assessment_id


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["component", "total", "subtotal", "minimum_band", "source", "prompt", "probability", "explanation"])
async def test_untrusted_service_cannot_change_rule_values_bindings_or_add_diagnosis_claims(field, db_session, news2_case):
    case = news2_case

    def alter(value):
        analysis = value["news2_analysis"]
        if field == "component":
            analysis["components"][0]["score"] = 1
        elif field == "total":
            analysis["total_score"] = 5
        elif field == "subtotal":
            analysis["observed_subtotal"] = 5
        elif field == "minimum_band":
            analysis["minimum_classification"] = "low"
        elif field == "source":
            analysis["source_binding"]["age_at_observation_years"] = 41
        elif field == "prompt":
            analysis["instructions_digest"] = "0" * 64
        elif field == "probability":
            analysis["sepsis_probability"] = 0.99
        elif field == "explanation":
            value["result"]["summary"] = "A forged claim of 99 percent disease probability"

    run = create_run(db_session, case["doctor"], request_for(case))
    transport = RealNews2Transport(case["service"], alter=alter)
    await execute_claimed(*claim_next_run(db_session), transport=transport)
    db_session.expire_all()
    stored = db_session.get(AIRun, run.run_id)
    assert stored.status == "failed" and json.loads(stored.result_json) == {}
    assert stored.error_code in {"NEWS2_BINDING_MISMATCH", "INVALID_OUTPUT"}


def test_news2_source_requires_the_news2_adapter_and_cannot_replace_other_risk_inputs(db_session, news2_case):
    case = news2_case
    spec = FEATURE_BY_KEY["deterioration_risk"]
    assert describe_config(db_session, spec, case["feature"])["input_mode"] == "news2"
    case["provider"].model = "a-separate-prediction-model"
    db_session.commit()
    assert describe_config(db_session, spec, case["feature"])["input_mode"] == "observation_window"
    with pytest.raises(HTTPException) as error:
        create_run(db_session, case["doctor"], request_for(case))
    assert error.value.status_code == 422
    for key in ("sepsis_risk", "aki_risk", "patient_summary"):
        with pytest.raises(HTTPException) as error:
            patient_snapshot(db_session, case["doctor"], FEATURE_BY_KEY[key], case["patient_id"], case["admission"].admission_id, request_for(case).input)
        assert error.value.status_code == 422


def test_unreviewed_news2_is_super_preview_only_and_missing_reference_never_falls_back(db_session, news2_case):
    case = news2_case
    incomplete = request_for(case).model_copy(update={"input": {"observation_window_id": case["window"].window_id}})
    with pytest.raises(HTTPException) as error:
        create_run(db_session, case["doctor"], incomplete)
    assert error.value.status_code == 422
    case["feature"].enabled, case["feature"].validation_status = 0, "unreviewed"
    db_session.commit()
    with pytest.raises(HTTPException) as error:
        create_run(db_session, case["doctor"], request_for(case))
    assert error.value.status_code == 409
    run = create_run(db_session, case["seed"]["super_admin_user"], request_for(case, preview=True))
    assert run.preview == 1 and run.status == "queued"
    assert case["feature"].enabled == 0 and case["feature"].validation_status == "unreviewed"


def test_plain_window_mode_remains_supported_without_attaching_news2(db_session, news2_case):
    case = news2_case
    case["provider"].model = "a-separate-prediction-model"
    db_session.commit()
    request = request_for(case).model_copy(update={"input": {"observation_window_id": case["window"].window_id}})
    run = create_run(db_session, case["doctor"], request)
    assert "news2_source" not in json.loads(run.input_json)["payload"]["context"]
    assert snapshot_current(db_session, case["doctor"], case["window"])["schema_version"] == "inpatient_window_v2"


@pytest.mark.parametrize("change", [None, "profile_revoke", "corrupt_profile"])
def test_readiness_checks_current_rule_profile_without_approving_clinical_effects(change, db_session, news2_case):
    from app.ai.readiness import setup_reports

    case = news2_case
    if change == "profile_revoke":
        mutate(db_session, case, change)
    elif change == "corrupt_profile":
        case["profile"].payload_json = case["profile"].payload_json.replace("合成NEWS2实施", "篡改NEWS2实施")
        db_session.commit()
    report = setup_reports(db_session, {"deterioration_risk": case["feature"]})["deterioration_risk"]
    assert ("NEWS2_RULE_PROFILE_REQUIRED" in {item["code"] for item in report["issues"]}) is (change is not None)
    assert case["feature"].validation_note == "隔离测试配置，不用于临床启用"
    assert case["feature"].validation_status == "validated"


def test_news2_provider_cannot_be_reused_as_a_different_model(db_session, news2_case):
    from app.ai.governance import provider_feature_issues

    case = news2_case
    for key in ("patient_summary", "sepsis_risk", "aki_risk", "visit_forecast"):
        issues = provider_feature_issues(FEATURE_BY_KEY[key], case["provider"])
        assert "NEWS2_SCOPE_MISMATCH" in {item["code"] for item in issues}
