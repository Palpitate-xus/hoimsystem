"""Completed AI history must recheck attached, unselected nursing originals."""

import json

import pytest

from app.ai.runtime import claim_next_run, create_run, execute_claimed
from app.ai.schemas import RunRequest
from app.models import NursingRecord
from tests.test_ai_nursing_sources import nursing_sources_case as nursing_sources_case
from tests.test_ai_runtime import clean_ai_tasks as clean_ai_tasks
from tests.test_ai_runtime import configure, successful_transport

ATTACHED_SOURCES = [
    ("completed_nursing_assessments", "assessment", "assessment_id", "nursing_assessment_id", "assessments"),
    ("nursing_plans", "plan", "plan_id", "nursing_plan_id", "plans"),
    ("critical_care_records", "critical", "record_id", "critical_care_record_id", "critical_records"),
    ("recorded_icu_scores", "score", "score_id", "icu_score_id", "scores"),
    ("nursing_records", "nursing_record", "record_id", None, None),
]


@pytest.fixture
def history_case(nursing_sources_case, seed_data, db_session):
    """Add the existing nursing-body source without changing the shared fixture."""
    case = dict(nursing_sources_case)
    case["nursing_record"] = NursingRecord(
        admission_id=case["current"].admission_id,
        patient_id=case["current"].patient_id,
        nurse_id=seed_data["nurse_user"].user_id,
        record_time=case["now"],
        create_time=case["now"],
        note="合成回归：自动附随的原护理正文",
    )
    db_session.add(case["nursing_record"])
    db_session.commit()
    return case


@pytest.mark.asyncio
@pytest.mark.parametrize("collection,row_key,primary_key,reference_key,review_collection", ATTACHED_SOURCES, ids=[item[1] for item in ATTACHED_SOURCES])
@pytest.mark.parametrize("reference_mode", ("none", "another_type"))
@pytest.mark.parametrize("change", ("delete", "reassign", "content"))
async def test_completed_history_rechecks_every_attached_nursing_original(
    collection,
    row_key,
    primary_key,
    reference_key,
    review_collection,
    reference_mode,
    change,
    async_client,
    auth_headers,
    seed_data,
    db_session,
    history_case,
):
    case = history_case
    configure(db_session, seed_data, "handover_summary")
    row = case[row_key]
    source_id = collection + ":" + str(getattr(row, primary_key))
    refs = {}
    if reference_mode == "another_type":
        refs = {"critical_care_record_id": case["critical"].record_id} if row_key == "score" else {"icu_score_id": str(case["score"].score_id)}
    assert reference_key not in refs, "The mutated row must be attached history, not an explicit selection"

    run = create_run(
        db_session,
        seed_data["doctor_user"],
        RunRequest(feature_key="handover_summary", patient_id=case["current"].patient_id, encounter_ref=case["current"].admission_id, input=refs),
    )
    context = json.loads(run.input_json)["payload"]["context"]
    assert context["selected_sources"] == refs
    original = next(item for item in context[collection] if item["source_id"] == source_id)
    assert original["admission_id"] == case["current"].admission_id
    review_row = None
    if review_collection is not None:
        review_row = next(item for item in context["nursing_source_review"][review_collection] if item["source_id"] == source_id)
        assert review_row["explicitly_selected"] is False
        assert review_row["admission_id"] == case["current"].admission_id
    else:
        # The existing nursing body is citable payload/evidence, rather than a
        # new separately rendered nursing_source_review collection.
        assert reference_key is None
        evidence = next(item for item in json.loads(run.evidence_json) if item["source_id"] == source_id)
        assert json.loads(evidence["content"]) == {key: value for key, value in original.items() if key != "source_id"}

    sent = []
    claim = claim_next_run(db_session)
    assert claim is not None and claim[0] == run.run_id
    await execute_claimed(*claim, transport=successful_transport(sent))
    db_session.refresh(run)
    assert run.status == "succeeded", run.error_message
    assert len(sent) == 1
    assert next(item for item in sent[0]["context"][collection] if item["source_id"] == source_id) == original
    frozen_input, frozen_result, frozen_digest = run.input_json, run.result_json, run.context_digest
    path = "/api/ai/runs/" + run.run_id
    ordinary_headers = auth_headers(seed_data["doctor_user"].username)

    # An unchanged completed result remains readable before the source mutation.
    before = await async_client.get(path, headers=ordinary_headers)
    assert before.status_code == 200, before.text
    frozen_findings = before.json()["data"]["nursing_findings"]
    if review_collection is not None:
        assert next(item for item in frozen_findings[review_collection] if item["source_id"] == source_id) == review_row

    if change == "delete":
        db_session.delete(row)
    elif change == "reassign":
        row.patient_id = case["foreign"].patient_id
        row.admission_id = case["foreign"].admission_id
    elif row_key == "score":
        row.detail_json = '{"eye":1,"verbal":1,"motor":1}'
    elif row_key == "plan":
        row.measures = "合成回归：附随护理计划原措施已改变"
    else:
        row.note = "合成回归：附随原记录内容已改变"
    db_session.commit()

    denied = await async_client.get(path, headers=ordinary_headers)
    assert denied.status_code == 403, denied.text
    audit = await async_client.get(path, headers=auth_headers(seed_data["super_admin_user"].username))
    assert audit.status_code == 200, audit.text
    assert audit.json()["data"]["nursing_findings"] == frozen_findings
    assert audit.json()["data"]["result"] == before.json()["data"]["result"]
    db_session.refresh(run)
    assert (run.input_json, run.result_json, run.context_digest) == (frozen_input, frozen_result, frozen_digest)
    assert run.status == "succeeded" and len(sent) == 1
