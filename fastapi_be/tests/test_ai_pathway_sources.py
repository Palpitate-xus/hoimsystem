"""Selected hospital pathway provenance, care scope, review gates and durable task invalidation."""

import datetime
import json
import uuid

import httpx
import pytest
from fastapi import HTTPException

from app.ai.catalog import FEATURE_BY_KEY
from app.ai.context import patient_snapshot
from app.ai.governance import digest, encode_json
from app.ai.knowledge import retrieval_query
from app.ai.models import AIFeatureConfig, AIFeedback, AIKnowledgeDocument, AIProvider, AIRun, utcnow
from app.ai.pathway_knowledge import PATHWAY_URI_PREFIX, import_content, pathway_hash
from app.ai.runtime import authorize_run, claim_next_run, create_run, describe_run, execute_claimed
from app.ai.schemas import RunRequest
from app.diagnosis_review import DiagnosisReviewWrite, record_diagnosis_review, source_facts
from app.models import Admission, ClinicalPathway, PathwayEnrollment, StructuredMedicalRecord


@pytest.fixture
def pathway_case(db_session, seed_data):
    for model in (AIFeedback, AIRun, AIFeatureConfig, AIProvider, AIKnowledgeDocument, PathwayEnrollment, ClinicalPathway):
        db_session.query(model).delete()
    now = utcnow()
    path = ClinicalPathway(
        name="明确选择的院内路径",
        disease_code="TEST-ONLY",
        disease_name="所选测试病种",
        steps='{"inclusion":"原纳入条件","exclusion":"原排除条件","steps":["未审核措施不得传入患者资料"]}',
        expected_days=7,
        status=0,
        create_time=now,
    )
    admission = Admission(
        patient_id=seed_data["patient"].patient_id, doctor_id=seed_data["doctor"].doctor_id, department_id=seed_data["department"].department_id, admission_time=now, status=1, create_time=now
    )
    db_session.add_all([path, admission])
    db_session.flush()
    enrollment = PathwayEnrollment(
        pathway_id=path.pathway_id,
        patient_id=admission.patient_id,
        admission_id=admission.admission_id,
        status=2,
        enroll_date=now.date(),
        variation_type="系统变异",
        variation_reason=seed_data["patient"].name + "的原变异说明",
        completed_items=0,
        total_items=0,
        create_time=now,
    )
    record = StructuredMedicalRecord(
        admission_id=admission.admission_id,
        patient_id=admission.patient_id,
        doctor_id=seed_data["doctor"].doctor_id,
        diagnosis="本次医生复核诊断",
        status=1,
        sign_time=now,
        create_time=now,
        update_time=now,
    )
    db_session.add_all([enrollment, record])
    db_session.commit()
    return path, admission, enrollment, record


def snapshot(db_session, seed_data, pathway_case, key="response_review", encounter=True, user=None, **references):
    _, admission, _, _ = pathway_case
    return patient_snapshot(db_session, user or seed_data["super_admin_user"], FEATURE_BY_KEY[key], admission.patient_id, admission.admission_id if encounter else None, references)


def publish_pathway(db_session, seed_data, path, keys=("treatment_pathway", "response_review"), department_id=None):
    content = import_content(path)
    item = AIKnowledgeDocument(
        title="已审核路径测试",
        version=str(uuid.uuid4()),
        source_uri=PATHWAY_URI_PREFIX + str(path.pathway_id),
        source_kind="clinical_pathway",
        source_reference_id=path.pathway_id,
        source_snapshot_hash=pathway_hash(path),
        content=content,
        content_hash=digest(content),
        category="clinical",
        feature_keys_json=encode_json(list(keys)),
        department_id=department_id,
        status="published",
        reviewed_by=seed_data["super_admin_user"].user_id,
        reviewed_at=utcnow(),
        created_by=seed_data["super_admin_user"].user_id,
    )
    db_session.add(item)
    db_session.commit()
    return item


def configure(db_session, seed_data, key="treatment_pathway"):
    provider = AIProvider(
        name="isolated-pathway", api_base="http://localhost:11434/v1", kind="chat", model="isolated-test", enabled=1, allows_patient_data=1, created_by=seed_data["super_admin_user"].user_id
    )
    db_session.add(provider)
    db_session.flush()
    db_session.add(
        AIFeatureConfig(
            feature_key=key,
            provider_id=provider.provider_id,
            enabled=1,
            allowed_roles_json=encode_json(FEATURE_BY_KEY[key].default_roles),
            validation_status="validated",
            validation_note="隔离测试，不构成临床验证",
            updated_by=seed_data["super_admin_user"].user_id,
        )
    )
    db_session.commit()


def confirm_diagnosis(db_session, seed_data, record):
    record_diagnosis_review(
        db_session,
        seed_data["doctor_user"],
        DiagnosisReviewWrite(
            source_kind="structured", source_id=record.record_id, source_hash=digest(source_facts(record)), expected_revision=0, certainty="confirmed", reason="隔离测试：由责任医生明确复核本次诊断"
        ),
    )


def request_for(pathway_case, key="treatment_pathway"):
    _, admission, enrollment, _ = pathway_case
    return RunRequest(feature_key=key, patient_id=admission.patient_id, encounter_ref=admission.admission_id, input={"pathway_enrollment_id": str(enrollment.enrollment_id)})


def test_unreviewed_steps_withheld_and_enrollment_is_not_a_historical_template_or_treatment_interval(seed_data, db_session, pathway_case):
    path, _, enrollment, _ = pathway_case
    bundle = snapshot(db_session, seed_data, pathway_case, pathway_enrollment_id=str(enrollment.enrollment_id))
    source = bundle.data["pathway_sources"]
    row, template = source["enrollments"][0], source["current_templates"][0]
    assert source["selected_pathway_id"] == path.pathway_id
    assert row["counter_state"] == "unknown" and row["completion_rate"] is None and row["completed_items"] == row["total_items"] == 0
    assert row["actual_item_execution"] == row["enrollment_template_version"] == "not_recorded"
    assert row["encounter_assignment"] == "current_encounter" and row["recorded_status"] == 2
    assert template["reviewed_knowledge"] is None and template["steps_in_patient_context"] is False
    serialized = encode_json({"context": bundle.data, "evidence": bundle.evidence})
    assert "未审核措施不得传入患者资料" not in serialized and seed_data["patient"].name not in serialized
    assert bundle.data["current_confirmed_diagnoses"] == []


@pytest.mark.parametrize(
    "completed,total,state,rate", [(None, 5, "unknown", None), (0, 5, "known", 0), (5, 5, "known", 100), (6, 5, "invalid", None), (-1, 5, "invalid", None), (2, 0, "unknown", None)]
)
def test_saved_counters_preserve_unknown_zero_and_inconsistent_values(completed, total, state, rate, seed_data, db_session, pathway_case):
    enrollment = pathway_case[2]
    enrollment.completed_items, enrollment.total_items = completed, total
    db_session.commit()
    row = snapshot(db_session, seed_data, pathway_case).data["pathway_sources"]["enrollments"][0]
    assert row["completed_items"] == completed and row["total_items"] == total and row["counter_state"] == state and row["completion_rate"] == rate


def test_explicit_older_enrollment_is_retained_and_only_selected_path_terms_drive_retrieval(seed_data, db_session, pathway_case):
    path, admission, selected, _ = pathway_case
    other = ClinicalPathway(name="不应影响所选路径检索", steps='["其他"]', status=0, create_time=utcnow())
    db_session.add(other)
    db_session.flush()
    for index in range(8):
        db_session.add(
            PathwayEnrollment(
                pathway_id=other.pathway_id,
                patient_id=admission.patient_id,
                admission_id=admission.admission_id,
                status=3,
                enroll_date=selected.enroll_date + datetime.timedelta(days=index + 1),
                completed_items=1,
                total_items=1,
                create_time=utcnow(),
            )
        )
    db_session.commit()
    bundle = snapshot(db_session, seed_data, pathway_case, pathway_enrollment_id=str(selected.enrollment_id))
    rows = bundle.data["pathway_sources"]["enrollments"]
    assert len(rows) == 6 and rows[0]["enrollment_id"] == selected.enrollment_id and rows[0]["explicitly_selected"] is True
    assert any(item["source"] == "临床路径入径记录" for item in bundle.data["truncated_sources"])
    query = retrieval_query(FEATURE_BY_KEY["response_review"], {"pathway_enrollment_id": str(selected.enrollment_id)}, bundle.data)
    assert path.name in query and other.name not in query


def test_path_and_enrollment_must_agree_and_foreign_or_invalid_admission_links_fail_closed(seed_data, db_session, pathway_case):
    path, admission, selected, _ = pathway_case
    foreign = PathwayEnrollment(pathway_id=path.pathway_id, patient_id=seed_data["patient2"].patient_id, status=1, enroll_date=utcnow().date(), create_time=utcnow())
    other = ClinicalPathway(name="另一个模板", steps='["其他"]', status=0, create_time=utcnow())
    db_session.add_all([foreign, other])
    db_session.commit()
    with pytest.raises(HTTPException) as error:
        snapshot(db_session, seed_data, pathway_case, pathway_enrollment_id=str(foreign.enrollment_id))
    assert error.value.status_code == 404
    with pytest.raises(HTTPException) as error:
        snapshot(db_session, seed_data, pathway_case, pathway_id=str(other.pathway_id), pathway_enrollment_id=str(selected.enrollment_id))
    assert error.value.status_code == 422
    selected.admission_id = "missing-admission"
    db_session.commit()
    with pytest.raises(HTTPException) as error:
        snapshot(db_session, seed_data, pathway_case, encounter=False, pathway_enrollment_id=str(selected.enrollment_id))
    assert error.value.status_code == 422
    foreign_admission = Admission(patient_id=seed_data["patient2"].patient_id, admission_time=utcnow())
    db_session.add(foreign_admission)
    db_session.flush()
    selected.admission_id = foreign_admission.admission_id
    db_session.commit()
    with pytest.raises(HTTPException) as error:
        snapshot(db_session, seed_data, pathway_case, encounter=False, pathway_enrollment_id=str(selected.enrollment_id))
    assert error.value.status_code == 422
    assert snapshot(db_session, seed_data, pathway_case, encounter=False).data["pathway_sources"]["enrollments"] == []


def test_selected_admission_is_checked_even_without_encounter_header_and_history_access_is_rechecked(seed_data, db_session, pathway_case):
    _, admission, selected, _ = pathway_case
    configure(db_session, seed_data, "response_review")
    user = seed_data["doctor_user"]
    req = request_for(pathway_case, "response_review").model_copy(update={"encounter_ref": None})
    run = create_run(db_session, user, req)
    assert describe_run(run)["pathway_findings"]["source_admission_refs"] == [admission.admission_id]
    admission.doctor_id = None
    db_session.commit()
    with pytest.raises(HTTPException) as error:
        authorize_run(db_session, user, run)
    assert error.value.status_code == 403
    with pytest.raises(HTTPException) as error:
        snapshot(db_session, seed_data, pathway_case, encounter=False, user=user, pathway_enrollment_id=str(selected.enrollment_id))
    assert error.value.status_code == 403


def test_pathway_references_are_canonical_and_internal_to_staff(seed_data, db_session, pathway_case):
    path, admission, _, _ = pathway_case
    for key in ("pathway_id", "pathway_enrollment_id"):
        for invalid in (True, 1, "01", "0", "-1", "２", "1" * 1000):
            with pytest.raises(HTTPException) as error:
                snapshot(db_session, seed_data, pathway_case, **{key: invalid})
            assert error.value.status_code == 422
    with pytest.raises(HTTPException) as error:
        patient_snapshot(db_session, seed_data["patient_user"], FEATURE_BY_KEY["patient_report_explanation"], admission.patient_id, source_refs={"pathway_id": str(path.pathway_id)})
    assert error.value.status_code == 403
    with pytest.raises(HTTPException) as error:
        snapshot(db_session, seed_data, pathway_case, key="charge_reconciliation", pathway_id=str(path.pathway_id))
    assert error.value.status_code == 422


@pytest.mark.asyncio
async def test_preview_and_options_are_read_only_and_review_availability_uses_encounter_department(seed_data, db_session, pathway_case, async_client, auth_headers):
    path, admission, selected, _ = pathway_case
    publish_pathway(db_session, seed_data, path, department_id=admission.department_id)
    headers = auth_headers(seed_data["doctor_user"].username)
    endpoint = "/api/ai/pathway-options"
    params = {"feature_key": "treatment_pathway", "patient_id": admission.patient_id}
    without = await async_client.get(endpoint, headers=headers, params=params)
    assert without.status_code == 200, without.text
    assert without.json()["data"]["items"][0]["reviewed_for_current_scope"] is False
    with_encounter = await async_client.get(endpoint, headers=headers, params={**params, "encounter_ref": admission.admission_id})
    assert with_encounter.json()["data"]["items"][0]["reviewed_for_current_scope"] is True
    assert "steps" not in with_encounter.json()["data"]["items"][0]
    response = await async_client.post(
        "/api/ai/context",
        headers=headers,
        json={"feature_key": "treatment_pathway", "patient_id": admission.patient_id, "encounter_ref": admission.admission_id, "source_refs": {"pathway_enrollment_id": str(selected.enrollment_id)}},
    )
    assert response.status_code == 200, response.text
    assert response.json()["data"]["context"]["pathway_sources"]["current_templates"][0]["reviewed_knowledge"]
    assert any(item["source_id"] == "pathway-enrollment:" + str(selected.enrollment_id) for item in response.json()["data"]["evidence"])
    assert db_session.query(AIRun).count() == 0 and selected.status == 2


@pytest.mark.asyncio
async def test_business_pathway_edits_preserve_steps_and_status_and_enrollment_rejects_broken_links(seed_data, db_session, pathway_case, async_client, auth_headers):
    path, admission, enrollment, _ = pathway_case
    headers = auth_headers(seed_data["doctor_user"].username)
    created = await async_client.post("/api/clinicalPathway/create", headers=headers, json={"name": "停用模板", "steps": '["原值"]', "status": 1, "expected_days": 7})
    assert created.status_code == 200, created.text
    row = db_session.query(ClinicalPathway).filter_by(name="停用模板").one()
    assert row.status == 1 and row.steps == '["原值"]' and row.source_revision == 1
    delete_used = await async_client.post("/api/clinicalPathway/delete", headers=headers, json={"pathway_id": path.pathway_id})
    assert delete_used.status_code == 409 and db_session.get(ClinicalPathway, path.pathway_id) is not None
    foreign = Admission(patient_id=seed_data["patient2"].patient_id, admission_time=utcnow())
    db_session.add(foreign)
    db_session.commit()
    before = db_session.query(PathwayEnrollment).count()
    for reference in ("missing-admission", foreign.admission_id, 3):
        response = await async_client.post("/api/pathwayEnrollment/enroll", headers=headers, json={"pathway_id": path.pathway_id, "patient_id": admission.patient_id, "admission_id": reference})
        assert response.status_code == 422, response.text
    assert db_session.query(PathwayEnrollment).count() == before
    enrollment.completed_items = None
    db_session.commit()
    response = await async_client.get("/api/pathwayEnrollment/getList", headers=headers)
    result = next(item for item in response.json()["data"] if item["enrollment_id"] == enrollment.enrollment_id)
    assert result["completed_items"] is None and result["completion_rate"] is None and result["counter_state"] == "unknown"


def test_treatment_requires_physician_confirmation_and_exact_selected_path_review_despite_other_knowledge(seed_data, db_session, pathway_case):
    path, _, _, record = pathway_case
    configure(db_session, seed_data)
    with pytest.raises(HTTPException) as error:
        create_run(db_session, seed_data["doctor_user"], request_for(pathway_case))
    assert error.value.status_code == 409 and "已确认" in error.value.detail
    confirm_diagnosis(db_session, seed_data, record)
    text = "治疗路径推荐：这是另一份已审核资料，不是所选路径的核验版本。"
    db_session.add(
        AIKnowledgeDocument(
            title="其他通用指南",
            version="v1",
            source_uri="hospital://test/general",
            category="clinical",
            content=text,
            content_hash=digest(text),
            feature_keys_json='["treatment_pathway"]',
            status="published",
            reviewed_by=seed_data["super_admin_user"].user_id,
            reviewed_at=utcnow(),
            created_by=seed_data["super_admin_user"].user_id,
        )
    )
    db_session.commit()
    with pytest.raises(HTTPException) as error:
        create_run(db_session, seed_data["doctor_user"], request_for(pathway_case))
    assert error.value.status_code == 409 and "所选临床路径" in error.value.detail
    published = publish_pathway(db_session, seed_data, path)
    run = create_run(db_session, seed_data["doctor_user"], request_for(pathway_case))
    evidence = json.loads(run.evidence_json)
    assert any(item.get("document_id") == published.document_id for item in evidence)


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["steps", "counter", "retire"])
async def test_source_or_counter_change_while_queued_stops_inference_and_keeps_frozen_findings(change, seed_data, db_session, pathway_case):
    path, _, enrollment, record = pathway_case
    configure(db_session, seed_data)
    confirm_diagnosis(db_session, seed_data, record)
    document = publish_pathway(db_session, seed_data, path)
    run = create_run(db_session, seed_data["doctor_user"], request_for(pathway_case))
    frozen = describe_run(run)["pathway_findings"]
    if change == "steps":
        path.steps = '["排队后变更的新措施"]'
    elif change == "counter":
        enrollment.total_items = 5
    else:
        document.status = "retired"
    db_session.commit()
    calls = []
    await execute_claimed(*claim_next_run(db_session), transport=httpx.MockTransport(lambda request: (calls.append(request), httpx.Response(500))[1]))
    db_session.refresh(run)
    assert calls == [] and run.status == "failed" and run.error_code in {"TASK_CONTEXT_CHANGED", "TASK_NO_LONGER_AUTHORIZED"}
    assert describe_run(run)["pathway_findings"] == frozen and run.result_json == "{}"


@pytest.mark.asyncio
@pytest.mark.parametrize("wrong_citation,inflight_change", [(False, False), (True, False), (False, True)])
async def test_selected_path_citation_is_required_and_source_change_during_inference_discards_result(wrong_citation, inflight_change, seed_data, db_session, pathway_case):
    path, _, _, record = pathway_case
    configure(db_session, seed_data)
    confirm_diagnosis(db_session, seed_data, record)
    publish_pathway(db_session, seed_data, path)
    generic = "治疗路径推荐：另一份通用资料，不能替代所选路径引用。"
    db_session.add(
        AIKnowledgeDocument(
            title="通用资料",
            version="test",
            source_uri="hospital://test/general",
            content=generic,
            content_hash=digest(generic),
            category="clinical",
            feature_keys_json='["treatment_pathway"]',
            status="published",
            reviewed_by=seed_data["super_admin_user"].user_id,
            reviewed_at=utcnow(),
            created_by=seed_data["super_admin_user"].user_id,
        )
    )
    db_session.commit()
    run = create_run(db_session, seed_data["doctor_user"], request_for(pathway_case))
    calls = []

    def handle(request):
        payload = json.loads(json.loads(request.content)["messages"][-1]["content"])
        calls.append(payload)
        knowledge = [item for item in payload["evidence"] if item.get("kind") == "knowledge"]
        item = next(item for item in knowledge if (item.get("source_kind") == "clinical_pathway") != wrong_citation)
        if inflight_change:
            path.status = 1
            db_session.commit()
        output = {"summary": "隔离测试结果", "sections": [{"title": "路径核对", "content": "资料仍待医生核实", "source_ids": [item["source_id"]]}], "warnings": [], "missing_data": []}
        return httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {"content": json.dumps(output)}}], "usage": {"prompt_tokens": 5, "completion_tokens": 7}})

    await execute_claimed(*claim_next_run(db_session), transport=httpx.MockTransport(handle))
    db_session.refresh(run)
    assert len(calls) == 1 and (run.input_tokens, run.output_tokens) == (5, 7)
    assert run.status == ("failed" if wrong_citation or inflight_change else "succeeded")
    if wrong_citation:
        assert run.error_code == "PATHWAY_CITATION_MISSING" and run.result_json == "{}"
    if inflight_change:
        assert run.error_code == "TASK_NO_LONGER_AUTHORIZED" and run.result_json == "{}"
