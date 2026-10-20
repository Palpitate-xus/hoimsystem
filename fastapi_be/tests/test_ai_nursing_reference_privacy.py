"""Deterministic phone-shaped UUIDs must retain technical nursing provenance."""

import json

import pytest

from app.ai.context import minimize_identifiers
from app.ai.models import AIRun
from app.ai.runtime import claim_next_run, create_run, execute_claimed
from app.ai.schemas import RunRequest
from app.models import CriticalCareRecord, IcuScoreRecord, NursingAssessment, NursingPlan
from tests.test_ai_nursing_sources import all_refs
from tests.test_ai_nursing_sources import nursing_sources_case as nursing_sources_case
from tests.test_ai_runtime import clean_ai_tasks as clean_ai_tasks
from tests.test_ai_runtime import configure, successful_transport

PHONE = "13123456789"
REFERENCE = "12345678-1234-4234-8234-13123456789a"
UUID_COLLECTIONS = ("completed_nursing_assessments", "nursing_plans", "critical_care_records")


@pytest.mark.asyncio
@pytest.mark.parametrize("number,key,row_key", [(1, "nursing_assessment_id", "assessment"), (2, "nursing_plan_id", "plan"), (3, "critical_care_record_id", "critical"), (4, "icu_score_id", "score")])
async def test_phone_shaped_uuid_sources_survive_actual_queue_and_history_without_exempting_clinical_notes(
    number, key, row_key, db_session, seed_data, nursing_sources_case, async_client, auth_headers
):
    case = nursing_sources_case
    # The same substring occurs deterministically inside actual UUID PKs and
    # free clinical text. Every queue includes all three original collections,
    # including when the explicitly selected reference is an integer score.
    reference = f"{number:08d}-1234-4234-8234-{PHONE}a"
    case["assessment"].assessment_id = reference
    case["plan"].plan_id = reference
    case["critical"].record_id = reference
    case["assessment"].note = f"原人工评估联系{PHONE}，此自由文本须脱敏"
    case["plan"].measures = f"原护理措施联系{PHONE}，此自由文本须脱敏"
    case["critical"].note = f"原重症记录联系{PHONE}，此自由文本须脱敏"
    db_session.commit()
    configure(db_session, seed_data, "handover_summary")
    counts = {model.__tablename__: db_session.query(model).count() for model in (NursingAssessment, NursingPlan, CriticalCareRecord, IcuScoreRecord)}
    run = create_run(
        db_session,
        seed_data["doctor_user"],
        RunRequest(feature_key="handover_summary", patient_id=case["current"].patient_id, encounter_ref=case["current"].admission_id, input={key: all_refs(case)[key]}),
    )
    sent = []
    await execute_claimed(*claim_next_run(db_session), transport=successful_transport(sent))
    db_session.refresh(run)
    assert run.status == "succeeded", run.error_message
    assert len(sent) == 1
    context = json.loads(run.input_json)["payload"]["context"]
    assert context["selected_sources"] == {key: all_refs(case)[key]}
    for collection in UUID_COLLECTIONS:
        rows = [item for item in context[collection] if item["source_id"] == f"{collection}:{reference}"]
        assert len(rows) == 1
        note = rows[0]["measures" if collection == "nursing_plans" else "note"]
        assert PHONE not in note and "[手机号已隐藏]" in note
        assert any(item["source_id"] == f"{collection}:{reference}" for item in json.loads(run.evidence_json))
    assert counts == {model.__tablename__: db_session.query(model).count() for model in (NursingAssessment, NursingPlan, CriticalCareRecord, IcuScoreRecord)}
    preserved = (run.input_json, run.result_json, run.context_digest)
    ordinary = await async_client.get(f"/api/ai/runs/{run.run_id}", headers=auth_headers(seed_data["doctor_user"].username))
    assert ordinary.status_code == 200, ordinary.text
    assert ordinary.json()["data"]["nursing_findings"]["selected_sources"] == {key: all_refs(case)[key]}
    case[row_key].admission_id = case["other"].admission_id
    db_session.commit()
    assert (await async_client.get(f"/api/ai/runs/{run.run_id}", headers=auth_headers(seed_data["doctor_user"].username))).status_code == 403
    audit = await async_client.get(f"/api/ai/runs/{run.run_id}", headers=auth_headers(seed_data["super_admin_user"].username))
    assert audit.status_code == 200, audit.text
    db_session.refresh(run)
    assert (run.input_json, run.result_json, run.context_digest) == preserved
    assert db_session.get(AIRun, run.run_id).status == "succeeded"


@pytest.mark.parametrize("prefix", UUID_COLLECTIONS)
def test_only_known_canonical_uuid_source_field_is_opaque(prefix):
    source = prefix + ":" + REFERENCE
    result = minimize_identifiers({"source_id": source, "note": source})
    assert result["source_id"] == source
    assert PHONE not in result["note"] and "[手机号已隐藏]" in result["note"]


@pytest.mark.parametrize(
    "source",
    [
        "false_collection:" + REFERENCE,
        "completed_nursing_assessments:" + REFERENCE.upper(),
        "nursing_plans:" + REFERENCE + "a",
        "critical_care_records:" + PHONE,
        "nursing_plans:" + REFERENCE + ":extra",
        "recorded_icu_scores:" + PHONE,
        PHONE,
    ],
)
def test_unknown_prefix_or_noncanonical_reference_does_not_bypass_text_minimization(source):
    result = minimize_identifiers({"source_id": source})
    assert PHONE not in result["source_id"] and "[手机号已隐藏]" in result["source_id"]
