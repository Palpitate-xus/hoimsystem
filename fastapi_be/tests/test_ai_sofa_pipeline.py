"""Actual originals, durable queue, independent ASGI math and complete result storage."""

import datetime
import json

import httpx
import pytest
from fastapi import HTTPException

from app import inpatient_support_common as common
from app.ai import governance, sofa_sources
from app.ai.catalog import FEATURE_BY_KEY, describe_feature
from app.ai.context import patient_snapshot
from app.ai.governance import describe_config, encode_json
from app.ai.models import AIAuditEvent, AIRun
from app.ai.runtime import claim_next_run, create_run, execute_claimed
from app.ai.schemas import RunRequest
from app.ai.sofa_config import SofaSettings, runtime_descriptor
from app.ai.sofa_context import expand_context
from app.ai.sofa_models import AISofaRunResult
from app.ai.sofa_server import create_sofa_app
from app.ai.sofa_storage import RESULT_BYTES, bounded_result
from app.inpatient_observations import utc_text
from app.models import Admission, Doctor, MedicalRecord, Prescription
from tests.test_ai_runtime import clean_ai_tasks as clean_ai_tasks
from tests.test_ai_runtime import configure
from tests.test_ai_sofa_sources import assessment_case as assessment_case
from tests.test_ai_sofa_sources import manifest, period, register, request
from tests.test_ai_sofa_sources import observation_case as observation_case
from tests.test_ai_sofa_sources import sofa_case as sofa_case
from tests.test_ai_sofa_sources import source_case as source_case
from tests.test_inpatient_respiratory_contract import NOTE, map_payload

KEY = "synthetic-sofa-pipeline-independent-key-no-live-credential"


class RealSofaTransport(httpx.AsyncBaseTransport):
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
def pipeline_case(db_session, assessment_case, clean_ai_tasks, monkeypatch):
    # The production worker always opens separate sessions against this synthetic DB.
    case = assessment_case
    db_session.query(AISofaRunResult).delete()
    case["assessment"] = register(db_session, case)
    monkeypatch.setenv("AI_PROVIDER_LOCAL_SOFA_API_KEY", KEY)
    config = SofaSettings(AI_PROVIDER_LOCAL_SOFA_API_KEY=KEY)
    provider, feature = configure(db_session, case["seed"], "sepsis_risk")
    provider.kind, provider.model = "specialist", runtime_descriptor(config)["model_version"]
    provider.api_base, provider.api_key_env = "http://localhost:8818", "AI_PROVIDER_LOCAL_SOFA_API_KEY"
    provider.supported_features_json = encode_json(["sepsis_risk"])
    provider.validation_report = "Synthetic source and exact arithmetic engineering checks only, not clinical validation."
    provider.timeout_seconds = 30
    db_session.commit()
    case.update(provider=provider, feature=feature, service=create_sofa_app(config))
    return case


def run_request(case):
    return RunRequest(
        feature_key="sepsis_risk",
        patient_id=case["patient_id"],
        encounter_ref=case["admission"].admission_id,
        input={"sofa_assessment_id": case["assessment"].assessment_id, "question": "SYNTH_PRIVATE_SOFA_QUESTION_不能改变原件或评分"},
    )


@pytest.mark.asyncio
async def test_real_daily_context_short_queue_wire_blob_history_trace_feedback_and_export(async_client, auth_headers, db_session, pipeline_case):
    case = pipeline_case
    headers = auth_headers(case["doctor"].username)
    before = {model.__tablename__: db_session.query(model).count() for model in (Admission, MedicalRecord, Prescription)}
    response = await async_client.post(
        "/api/ai/context",
        headers=headers,
        json={
            "feature_key": "sepsis_risk",
            "patient_id": case["patient_id"],
            "encounter_ref": case["admission"].admission_id,
            "source_refs": {"sofa_assessment_id": case["assessment"].assessment_id},
        },
    )
    assert response.status_code == 200, response.text
    context = response.json()["data"]["context"]
    assert context["sofa_assessment"]["snapshot"]["attestation"] == case["request"]
    assert context["sofa_source"] == json.loads(case["assessment"].projection_json)
    run = create_run(db_session, case["doctor"], run_request(case))
    frozen = json.loads(run.input_json)
    assert "sofa_source" not in frozen["payload"]["context"] and "sofa_assessment" not in frozen["payload"]["context"]
    assert frozen["payload"]["context"]["sofa_binding"]["projection_hash"] == case["assessment"].projection_hash
    transport = RealSofaTransport(case["service"])
    await execute_claimed(*claim_next_run(db_session), transport=transport)
    db_session.expire_all()
    stored = db_session.get(AIRun, run.run_id)
    assert stored.status == "succeeded", (stored.error_code, stored.error_message)
    assert len(transport.requests) == 1
    wire = transport.requests[0]
    assert wire["schema_version"] == "9" and wire["store"] is False
    assert wire["input"] == {"context": {"sofa_source": context["sofa_source"]}}
    assert all(value not in encode_json(wire["input"]) for value in ("patient_id", "admission_id", "basis_note", "SYNTH_PRIVATE_SOFA_QUESTION", NOTE))
    pointer = json.loads(stored.result_json)
    blob = db_session.get(AISofaRunResult, run.run_id)
    assert pointer["schema_version"] == "sofa_result_ref_v1" and pointer["content_hash"] == blob.content_hash
    assert db_session.query(AIAuditEvent).filter_by(target=run.run_id, action="run.sofa_result.accept").count() == 1
    detail = await async_client.get(f"/api/ai/runs/{run.run_id}", headers=headers)
    assert detail.status_code == 200, detail.text
    data = detail.json()["data"]
    assert data["result"] == json.loads(blob.result_json)
    assert data["result"]["sofa_analysis"]["source_binding"]["projection_hash"] == case["assessment"].projection_hash
    assert data["sofa_findings"]["sofa_source"] == context["sofa_source"]
    assert data["sofa_findings"]["sofa_assessment"] == context["sofa_assessment"]
    assert "observation_window" not in frozen["payload"]["context"]
    feedback = await async_client.post(f"/api/ai/runs/{run.run_id}/feedback", headers=headers, json={"outcome": "modified", "comment": "合成完整原件与未知范围人工复核，不构成临床验证"})
    assert feedback.status_code == 200, feedback.text
    trace = await async_client.get(f"/api/ai/admin/runs/{run.run_id}", headers=auth_headers(case["seed"]["super_admin_user"].username))
    assert trace.status_code == 200, trace.text
    assert trace.json()["data"]["frozen_request"]["payload"]["context"]["sofa_source"] == context["sofa_source"]
    assert before == {model.__tablename__: db_session.query(model).count() for model in (Admission, MedicalRecord, Prescription)}


def mutate(db, case, change):
    if change == "assessment_revoke":
        sofa_sources.revoke_assessment(db, case["doctor"], case["assessment"], 1, "合成完整原件临床复核撤销，执行和普通历史均应重新核对。")
    elif change == "private_note":
        value = json.loads(case["assessment"].snapshot_json)
        value["attestation"]["note"] += "合成冻结原文改动"
        case["assessment"].snapshot_json = encode_json(value)
    elif change == "parent":
        case["lab_report"].audit_status = 0
    elif change == "doctor":
        actual = json.loads(case["assessment"].snapshot_json)["author_qualification"]
        db.get(Doctor, actual["doctor_id"]).user_id = case["seed"]["nurse_user"].user_id
    elif change == "care":
        case["admission"].doctor_id = None
    else:
        raise AssertionError(change)
    db.commit()


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["queued", "inflight", "history"])
@pytest.mark.parametrize("change", ["assessment_revoke", "private_note", "parent", "doctor", "care"])
async def test_changed_originals_block_queue_reply_and_ordinary_history(phase, change, async_client, auth_headers, db_session, pipeline_case):
    case = pipeline_case
    run = create_run(db_session, case["doctor"], run_request(case))
    if phase == "queued":
        mutate(db_session, case, change)
    transport = RealSofaTransport(case["service"], before=(lambda: mutate(db_session, case, change)) if phase == "inflight" else None)
    await execute_claimed(*claim_next_run(db_session), transport=transport)
    db_session.expire_all()
    stored = db_session.get(AIRun, run.run_id)
    if phase != "history":
        assert stored.status == "failed" and stored.result_json == "{}"
        assert db_session.get(AISofaRunResult, run.run_id) is None
        assert len(transport.requests) == (0 if phase == "queued" else 1)
        return
    assert stored.status == "succeeded", (stored.error_code, stored.error_message)
    mutate(db_session, case, change)
    denied = await async_client.get(f"/api/ai/runs/{run.run_id}", headers=auth_headers(case["doctor"].username))
    assert denied.status_code == 403, denied.text
    audit = await async_client.get(f"/api/ai/runs/{run.run_id}", headers=auth_headers(case["seed"]["super_admin_user"].username))
    if change == "private_note":
        assert audit.status_code == 403
    else:
        assert audit.status_code == 200, audit.text
        assert audit.json()["data"]["sofa_findings"]["sofa_assessment"]["eligible"] is False


@pytest.mark.asyncio
async def test_full_large_original_and_result_cross_old_text_limit_without_truncation(async_client, auth_headers, db_session, pipeline_case):
    case = pipeline_case
    for index in range(220):
        common.create_source(
            db_session,
            case["doctor"],
            "map",
            {
                **{key: period(case)[key] for key in ("patient_id", "admission_id")},
                "payload": map_payload(observed_at=utc_text(case["start"] + datetime.timedelta(seconds=index)), note="合成完整大原件" + str(index)),
            },
        )
    db_session.commit()
    full = manifest(db_session, case)
    values = request(case, full)
    values.update(rule_profile_id=case["profile"].rule_profile_id, expected_rule_profile_hash=case["profile"].content_hash)
    case["assessment"] = register(db_session, case, values=values)
    assert len(case["assessment"].snapshot_json.encode()) > 65535
    run = create_run(db_session, case["doctor"], run_request(case))
    assert all(len(value.encode()) <= 65535 for value in (run.input_json, run.context_metadata_json, run.evidence_json))
    transport = RealSofaTransport(case["service"])
    await execute_claimed(*claim_next_run(db_session), transport=transport)
    db_session.expire_all()
    stored = db_session.get(AIRun, run.run_id)
    assert stored.status == "succeeded", (stored.error_code, stored.error_message)
    blob = db_session.get(AISofaRunResult, run.run_id)
    assert blob.result_bytes == len(blob.result_json.encode()) > 65535
    assert len(stored.result_json.encode()) < 1024
    detail = await async_client.get(f"/api/ai/runs/{run.run_id}", headers=auth_headers(case["doctor"].username))
    assert detail.status_code == 200, detail.text
    assert detail.json()["data"]["result"] == json.loads(blob.result_json)
    assert len(detail.json()["data"]["sofa_findings"]["sofa_source"]["map_observations"]) == 221


@pytest.mark.asyncio
async def test_actual_sql_audit_failure_rolls_back_blob_pointer_and_accepted_state(monkeypatch, db_session, pipeline_case):
    case = pipeline_case
    run = create_run(db_session, case["doctor"], run_request(case))
    original = governance.audit

    def reject_blob_audit(db, actor_id, action, target, detail=None):
        if action == "run.sofa_result.accept":
            db.add(AIAuditEvent(actor_id=actor_id, action=None, target=target, detail_json="{}"))
        else:
            original(db, actor_id, action, target, detail)

    monkeypatch.setattr(governance, "audit", reject_blob_audit)
    await execute_claimed(*claim_next_run(db_session), transport=RealSofaTransport(case["service"]))
    db_session.expire_all()
    stored = db_session.get(AIRun, run.run_id)
    assert stored.status == "failed" and stored.error_code == "RESULT_STORAGE_ERROR"
    assert stored.result_json == "{}" and db_session.get(AISofaRunResult, run.run_id) is None
    assert db_session.query(AIAuditEvent).filter_by(target=run.run_id, action="run.sofa_result.accept").count() == 0


def test_daily_short_binding_refuses_recomputed_hash_of_changed_original_and_other_feature_modes(db_session, pipeline_case):
    case = pipeline_case
    bundle = patient_snapshot(db_session, case["doctor"], FEATURE_BY_KEY["sepsis_risk"], case["patient_id"], case["admission"].admission_id, run_request(case).input)
    bundle.data["sofa_binding"]["projection_hash"] = "0" * 64
    with pytest.raises(HTTPException) as mismatch:
        expand_context(db_session, bundle.data, user=case["doctor"], current=True)
    assert mismatch.value.status_code == 409
    for key in ("patient_summary", "deterioration_risk", "aki_risk", "handover_summary"):
        assert "sofa_assessment_id" not in describe_feature(FEATURE_BY_KEY[key])["source_reference_keys"]
        with pytest.raises(HTTPException) as error:
            patient_snapshot(db_session, case["doctor"], FEATURE_BY_KEY[key], case["patient_id"], case["admission"].admission_id, run_request(case).input)
        assert error.value.status_code == 422
    assert describe_config(db_session, FEATURE_BY_KEY["sepsis_risk"], case["feature"])["input_mode"] == "sofa1"


def test_complete_result_utf8_exact_byte_boundary_preserves_zero_false_null():
    base = {"original": "", "zero": "0", "false": False, "unknown": None}
    size = len(encode_json(base).encode())
    base["original"] = "中" * ((RESULT_BYTES - size) // 3) + "a" * ((RESULT_BYTES - size) % 3)
    serialized, _, actual = bounded_result(base)
    assert actual == RESULT_BYTES and json.loads(serialized) == base
    with pytest.raises(HTTPException) as error:
        bounded_result({**base, "original": base["original"] + "a"})
    assert error.value.status_code == 422


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["body", "missing_blob", "lease", "rehashed_false_score", "rehashed_false_explanation"])
async def test_result_reads_reject_damaged_or_rehashed_false_complete_blobs(change, async_client, auth_headers, db_session, pipeline_case):
    from app.ai.sofa_contract import hash_content

    case = pipeline_case
    run = create_run(db_session, case["doctor"], run_request(case))
    await execute_claimed(*claim_next_run(db_session), transport=RealSofaTransport(case["service"]))
    db_session.expire_all()
    stored = db_session.get(AIRun, run.run_id)
    assert stored.status == "succeeded", stored.error_message
    blob = db_session.get(AISofaRunResult, run.run_id)
    if change == "body":
        blob.result_json = "{}"
    elif change == "missing_blob":
        db_session.delete(blob)
    elif change == "lease":
        blob.lease_token = "00000000-0000-4000-8000-000000000000"
    else:
        value = json.loads(blob.result_json)
        if change == "rehashed_false_score":
            value["sofa_analysis"]["known_subtotal"] = 24
        else:
            value["summary"] = "伪造完整结果，自动诊断并开立治疗"
        blob.result_json, blob.content_hash, blob.result_bytes = bounded_result(value)
        pointer = json.loads(stored.result_json)
        pointer.update(content_hash=hash_content(value), result_bytes=blob.result_bytes)
        stored.result_json = encode_json(pointer)
    db_session.commit()
    response = await async_client.get(f"/api/ai/runs/{run.run_id}", headers=auth_headers(case["doctor"].username))
    assert response.status_code == 409, response.text
    assert "sofa_analysis" not in response.json()


def test_setup_requires_independent_sofa_rule_without_manufacturing_clinical_validation(db_session, pipeline_case):
    from app.ai.readiness import setup_reports

    case = pipeline_case
    report = setup_reports(db_session, {"sepsis_risk": case["feature"]})["sepsis_risk"]
    assert not any(issue["code"] == "SOFA1_RULE_PROFILE_REQUIRED" for issue in report["issues"])
    case["profile"].payload_json = "{}"
    db_session.commit()
    report = setup_reports(db_session, {"sepsis_risk": case["feature"]})["sepsis_risk"]
    assert any(issue["code"] == "SOFA1_RULE_PROFILE_REQUIRED" for issue in report["issues"])
    assert case["feature"].validation_status == "validated"
