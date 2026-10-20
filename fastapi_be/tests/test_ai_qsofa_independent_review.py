"""Independent source-to-worker review of qSOFA integration and old mode.

Uses the real source ORM, compact context, gateway and offline ASGI rule service.
No clinical database or live inference endpoint is used.
"""

import copy
import json

import httpx
import pytest
from fastapi import HTTPException

from app import inpatient_gcs
from app.ai.catalog import FEATURE_BY_KEY
from app.ai.context import patient_snapshot
from app.ai.governance import encode_json
from app.ai.models import AIRun
from app.ai.qsofa_config import QsofaSettings, runtime_descriptor
from app.ai.qsofa_server import create_qsofa_app
from app.ai.qsofa_sources import create_assessment
from app.ai.runtime import authorize_run, claim_next_run, create_run, describe_run, execute_claimed
from app.ai.schemas import RunRequest
from app.models import Admission, InpatientGcsObservation, InpatientObservation, MedicalRecord, NursingRecord, Prescription
from app.routers import inpatient_gcs as gcs_routes
from tests.test_ai_qsofa_sources import NOTE, body, extra_gcs, gcs_payload
from tests.test_ai_qsofa_sources import case as case
from tests.test_ai_qsofa_sources import observation_case as observation_case
from tests.test_ai_runtime import clean_ai_tasks as clean_ai_tasks
from tests.test_ai_runtime import configure

KEY = "synthetic-independent-qsofa-service-key-no-live-secret"


@pytest.fixture
def review_case(db_session, case, clean_ai_tasks, monkeypatch):
    monkeypatch.setenv("AI_PROVIDER_LOCAL_QSOFA_API_KEY", KEY)
    service_config = QsofaSettings(AI_PROVIDER_LOCAL_QSOFA_API_KEY=KEY)
    provider, config = configure(db_session, case["seed"], "sepsis_risk")
    provider.kind, provider.model = "specialist", runtime_descriptor(service_config)["model_version"]
    provider.api_base, provider.api_key_env = "http://localhost:8816", "AI_PROVIDER_LOCAL_QSOFA_API_KEY"
    provider.supported_features_json = encode_json(["sepsis_risk"])
    provider.validation_report = "Synthetic engineering source review only; clinical validation not provided."
    provider.timeout_seconds = 30
    db_session.commit()
    case.update(provider=provider, feature=config, service=create_qsofa_app(service_config))
    return case


def register_assessment(db, case, **changes):
    case["assessment"] = create_assessment(db, case["doctor"], body(case, **changes))
    db.commit()
    return case["assessment"]


def request_for(case, **changes):
    return RunRequest(feature_key="sepsis_risk", patient_id=case["patient_id"], encounter_ref=case["admission_id"], input={"observation_window_id": case["window"].window_id, "qsofa_assessment_id": case["assessment"].assessment_id, "question": "此私有问题不得外发，也不能使低计数被称为排除感染", **changes})


class ActualService(httpx.AsyncBaseTransport):
    def __init__(self, app, *, during=None, alter=None):
        self.inner = httpx.ASGITransport(app=app)
        self.calls = []
        self.during, self.alter = during, alter

    async def handle_async_request(self, request):
        self.calls.append(json.loads(request.content))
        if self.during:
            self.during()
        response = await self.inner.handle_async_request(request)
        if self.alter:
            value = json.loads(await response.aread())
            self.alter(value)
            return httpx.Response(response.status_code, json=value, request=request)
        return response


async def execute(db, case, transport):
    run = create_run(db, case["doctor"], request_for(case))
    claim = claim_next_run(db)
    assert claim[0] == run.run_id
    await execute_claimed(*claim, transport=transport)
    db.expire_all()
    return db.get(AIRun, run.run_id)


@pytest.mark.asyncio
async def test_actual_conflicting_gcs_group_keeps_two_known_positive_criteria_and_omits_all_narrative(db_session, review_case, monkeypatch):
    case = review_case
    components = copy.deepcopy(gcs_payload(case)["components"])
    components["verbal"]["score"] = 4
    other = extra_gcs(db_session, case, monkeypatch, components=components)
    register_assessment(db_session, case)
    originals = (case["point"].payload_json, case["gcs"].payload_json, other.payload_json)
    clinical = {model.__tablename__: db_session.query(model).count() for model in (Admission, MedicalRecord, Prescription, InpatientObservation, InpatientGcsObservation)}
    bundle = patient_snapshot(db_session, case["doctor"], FEATURE_BY_KEY["sepsis_risk"], case["patient_id"], case["admission_id"], request_for(case).input)
    private = bundle.data["qsofa_assessment"]["snapshot"]
    assert len(private["gcs_group"]) == 2
    assert private["point"]["payload"] == {"measurements": bundle.data["qsofa_source"]["measurements"]}
    assert all(set(item["payload"]) == {"components", "anchor_point", "same_exam_confirmed"} for item in private["gcs_group"])
    assert private["provenance_note_hashes"]["infection_basis_note"] and "infection_basis_note" not in private["attestation"]
    transport = ActualService(case["service"])
    run = await execute(db_session, case, transport)
    assert run.status == "succeeded", run.error_message
    result = json.loads(run.result_json)
    analysis = result["qsofa_analysis"]
    assert analysis["total_score"] is None and analysis["observed_subtotal"] == 2 and analysis["scored_count"] == 2
    assert analysis["threshold_status"] == "at_least_two" and analysis["criteria"][2]["status"] == "conflict"
    assert analysis["source_binding"]["gcs"]["observed_at"] != analysis["source_binding"]["observed_at"]
    assert analysis["source_binding"]["clinical_statements_recorded_at"] > analysis["source_binding"]["as_of"]
    assert transport.calls[0]["input"] == {"context": {"qsofa_source": bundle.data["qsofa_source"]}}
    wire = encode_json(transport.calls[0]["input"])
    assert all(text not in wire for text in (NOTE, "patient_id", "admission_id", "note", "此私有问题", "原始点测备注"))
    assert (case["point"].payload_json, case["gcs"].payload_json, other.payload_json) == originals
    assert clinical == {model.__tablename__: db_session.query(model).count() for model in (Admission, MedicalRecord, Prescription, InpatientObservation, InpatientGcsObservation)}


@pytest.mark.asyncio
async def test_original_feature42_window_mode_still_executes_its_own_schema_without_qsofa_coercion(db_session, review_case):
    case = review_case
    case["provider"].model = "synthetic-existing-external-sepsis-adapter"
    db_session.commit()
    request = RunRequest(feature_key="sepsis_risk", patient_id=case["patient_id"], encounter_ref=case["admission_id"], input={"observation_window_id": case["window"].window_id})
    run = create_run(db_session, case["doctor"], request)
    calls = []

    def external(request):
        task = json.loads(request.content)
        calls.append(task)
        assert task["schema_version"] == "1" and "qsofa_source" not in task["input"]["context"]
        source_id = task["input"]["evidence"][0]["source_id"]
        return httpx.Response(200, json={"schema_version": "1", "feature_key": "sepsis_risk", "model_version": case["provider"].model, "applicable": True, "result": {"summary": "合成已有模型的独立测试结果", "sections": [{"title": "原窗口依据", "content": "这是旧协议工程回归测试", "source_ids": [source_id]}], "warnings": [], "missing_data": []}})

    await execute_claimed(*claim_next_run(db_session), transport=httpx.MockTransport(external))
    db_session.expire_all()
    stored = db_session.get(AIRun, run.run_id)
    assert stored.status == "succeeded", stored.error_message
    assert len(calls) == 1 and "qsofa_analysis" not in json.loads(stored.result_json)
    assert "qsofa_findings" not in describe_run(stored)


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["none", "not_testable", "not_recorded", "limited", "unknown"])
async def test_real_gcs_absence_or_interpretation_limits_keep_two_positive_originals_and_raw_components(db_session, review_case, monkeypatch, mode):
    case = review_case
    changes = {}
    if mode == "none":
        changes = {"gcs_observation": None, "gcs_interpretability": "unknown", "gcs_review_note": None}
    elif mode in {"limited", "unknown"}:
        changes = {"gcs_interpretability": mode}
    else:
        # Use the actual source withdrawal and registration operations. An
        # earlier complete original must not silently contradict selected NT.
        monkeypatch.setattr(gcs_routes, "utcnow", lambda: case["now"])
        gcs_routes.revoke(
            case["gcs"].gcs_observation_id,
            inpatient_gcs.GcsRevoke(patient_id=case["patient_id"], admission_id=case["admission_id"], expected_revision=1, reason=NOTE),
            db_session,
            case["doctor"],
        )
        components = copy.deepcopy(gcs_payload(case)["components"])
        components["verbal"] = {"score": None, "absent_reason": mode}
        selected = extra_gcs(db_session, case, monkeypatch, components=components)
        changes = {"gcs_observation": {"gcs_observation_id": selected.gcs_observation_id, "expected_content_hash": selected.content_hash}}
    register_assessment(db_session, case, **changes)
    transport = ActualService(case["service"])
    run = await execute(db_session, case, transport)
    assert run.status == "succeeded", run.error_message
    analysis = json.loads(run.result_json)["qsofa_analysis"]
    assert analysis["total_score"] is None and analysis["observed_subtotal"] == 2 and analysis["scored_count"] == 2
    assert analysis["score_is_lower_bound"] and analysis["threshold_status"] == "at_least_two"
    mentation = analysis["criteria"][2]
    assert mentation["score"] is None
    source = transport.calls[0]["input"]["context"]["qsofa_source"]
    assert source["measurements"]["respiratory_rate"]["value"] == "22.00000000"
    assert source["measurements"]["systolic_bp"]["value"] == "100.00000000"
    if mode == "none":
        assert source["gcs"] is None and mentation["raw_value"] is None and mentation["observed_at"] is None
    else:
        assert source["gcs"]["conflict"] is False
        raw = source["gcs"]["components"]
        assert raw["eye"] == {"score": 4, "absent_reason": None} and raw["motor"] == {"score": 6, "absent_reason": None}
        assert source["gcs"]["observed_at"] != source["observed_at"]
        if mode in {"not_testable", "not_recorded"}:
            assert raw["verbal"] == {"score": None, "absent_reason": mode} and mentation["raw_value"] is None
        else:
            assert raw["verbal"]["score"] == 5 and mentation["raw_value"] == "15"


@pytest.mark.asyncio
async def test_actual_nurse_reuses_doctor_signed_assessment_with_original_admission_care_and_receives_own_result(db_session, review_case):
    case = review_case
    register_assessment(db_session, case)
    nurse = case["seed"]["nurse_user"]
    care = NursingRecord(patient_id=case["patient_id"], admission_id=case["admission_id"], nurse_id=nurse.user_id, record_time=case["now"], create_time=case["now"], note="合成既有原住院护理照护，不是AI推理写入")
    db_session.add(care)
    db_session.commit()
    original_assessment = (case["assessment"].snapshot_json, case["assessment"].created_by, case["assessment"].content_hash)
    run = create_run(db_session, nurse, request_for(case))
    transport = ActualService(case["service"])
    await execute_claimed(*claim_next_run(db_session), transport=transport)
    db_session.expire_all()
    stored = db_session.get(AIRun, run.run_id)
    assert stored.status == "succeeded" and stored.requested_by == nurse.user_id, stored.error_message
    authorize_run(db_session, nurse, stored)
    frozen = describe_run(stored)["qsofa_findings"]["qsofa_assessment"]
    assert frozen["snapshot"]["author_qualification"]["actor_id"] == case["doctor"].user_id != nurse.user_id
    assert (case["assessment"].snapshot_json, case["assessment"].created_by, case["assessment"].content_hash) == original_assessment
    assert db_session.get(NursingRecord, care.record_id).note == "合成既有原住院护理照护，不是AI推理写入"
    db_session.delete(care)
    db_session.commit()
    with pytest.raises(HTTPException) as denied:
        authorize_run(db_session, nurse, stored)
    assert denied.value.status_code == 403
    authorize_run(db_session, case["seed"]["super_admin_user"], stored)


def test_all_evidence_context_indexes_resolve_original_binding_and_private_projection(db_session, review_case):
    case = review_case
    register_assessment(db_session, case)
    bundle = patient_snapshot(db_session, case["doctor"], FEATURE_BY_KEY["sepsis_risk"], case["patient_id"], case["admission_id"], request_for(case).input)
    assert len(bundle.evidence) == 5
    identifiers = []
    for evidence in bundle.evidence:
        path = json.loads(evidence["content"])["context_path"]
        target = {"context": bundle.data}
        for part in path.split("."):
            target = target[part]
        assert target["source_id"] == evidence["source_id"]
        identifiers.append(target["source_id"])
        assert NOTE not in evidence["content"]
    assert len(set(identifiers)) == 5
    projected = bundle.data["qsofa_assessment"]
    assert projected["context_projection"] == "qsofa_review_v1"
    assert projected["snapshot"]["point"]["content_hash"] == bundle.data["qsofa_source"]["point_content_hash"]
    assert projected["snapshot"]["gcs_observation"]["content_hash"] == bundle.data["qsofa_source"]["gcs"]["content_hash"]
