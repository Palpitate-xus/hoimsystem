"""A source-row request can retrieve relevant reviewed knowledge without an extra typed question."""

import datetime
import json

from app.ai.catalog import FEATURE_BY_KEY
from app.ai.governance import digest
from app.ai.knowledge import retrieval_query
from app.ai.models import AIFeatureConfig, AIKnowledgeDocument, AIProvider, utcnow
from app.ai.runtime import create_run
from app.ai.schemas import RunRequest
from app.models import LabObservation, LabOrder, LabResult


def test_query_uses_selected_clinical_terms_and_does_not_promote_historical_diagnoses():
    spec = FEATURE_BY_KEY["lab_interpretation"]
    query = retrieval_query(
        spec,
        {"lab_result_id": "opaque-lab-id"},
        {
            "reviewed_observations": [{"lab_result_id": "opaque-lab-id", "display": "血钾", "code": "LOCAL_K"}],
            "outpatient_records": [{"source_id": "outpatient:old", "current_encounter": False, "diagnosis_text": "不属于本次选择的历史诊断"}],
        },
    )
    assert "血钾" in query
    assert "opaque-lab-id" not in query
    assert "不属于本次选择的历史诊断" not in query


def test_lab_run_retrieves_reviewed_evidence_from_real_selected_result_without_question(seed_data, db_session):
    now = utcnow()
    user_id = seed_data["super_admin_user"].user_id
    provider = AIProvider(name="contextual-retrieval-test", kind="chat", api_base="http://localhost:11434/v1", model="isolated-model", enabled=1, allows_patient_data=1, created_by=user_id)
    db_session.add(provider)
    db_session.flush()
    db_session.add(
        AIFeatureConfig(feature_key="lab_interpretation", provider_id=provider.provider_id, enabled=1, validation_status="validated", allowed_roles_json='["doctor","super_admin"]', updated_by=user_id)
    )
    content = "血钾资料的隔离检索测试：核对原始单位和采样时间。本文不提供真实诊疗建议。"
    knowledge = AIKnowledgeDocument(
        title="检索边界测试材料",
        version="test",
        source_uri="hospital://test-only",
        content=content,
        content_hash=digest(content),
        feature_keys_json='["lab_interpretation"]',
        status="published",
        reviewed_by=user_id,
        reviewed_at=now,
        created_by=user_id,
    )
    db_session.add(knowledge)
    order = LabOrder(patient_id=seed_data["patient"].patient_id, doctor_id=seed_data["doctor"].doctor_id, check_type="测试项目", create_time=now)
    db_session.add(order)
    db_session.flush()
    report = LabResult(lab_order_id=order.lab_order_id, result="原报告正文", report_time=now, audit_status=1, audit_time=now)
    db_session.add(report)
    db_session.flush()
    db_session.add(
        LabObservation(
            lab_result_id=report.lab_result_id, code="LOCAL_K", display="血钾", value_num="4.2", unit="mmol/L", collected_at=datetime.datetime(2026, 10, 20), method="测试方法", specimen_type="血清"
        )
    )
    db_session.commit()
    run = create_run(db_session, seed_data["doctor_user"], RunRequest(feature_key="lab_interpretation", patient_id=order.patient_id, input={"lab_result_id": report.lab_result_id}))
    assert run.status == "queued"
    evidence = json.loads(run.evidence_json)
    assert any(item.get("document_id") == knowledge.document_id for item in evidence)
