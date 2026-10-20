"""ADR source state, exposure gaps, patient boundaries and immutable run evidence."""

import datetime
import json

import httpx
import pytest
from fastapi import HTTPException

from app.ai.catalog import FEATURE_BY_KEY
from app.ai.context import patient_snapshot
from app.ai.governance import encode_json
from app.ai.knowledge import retrieval_query
from app.ai.models import AIFeatureConfig, AIFeedback, AIProvider, AIRun
from app.ai.runtime import claim_next_run, create_run, describe_run, execute_claimed
from app.ai.schemas import RunRequest
from app.models import AdverseReaction


@pytest.fixture
def adr_case(db_session, seed_data):
    for model in (AIFeedback, AIRun, AIFeatureConfig, AIProvider, AdverseReaction):
        db_session.query(model).delete()
    now = datetime.datetime.now()
    rows = [
        AdverseReaction(
            patient_id=seed_data["patient"].patient_id, pharmaceutical_id=seed_data["pharmaceutical"].pharmaceutical_id, symptom=seed_data["patient"].name + "的所选反应症状", report_time=now, status=2
        )
    ]
    for resolution in ("processed", "excluded"):
        rows.append(
            AdverseReaction(
                patient_id=seed_data["patient"].patient_id,
                pharmaceutical_id=seed_data["pharmaceutical"].pharmaceutical_id,
                symptom="其他非所选症状",
                report_time=now,
                status=2,
                status_resolution=resolution,
                status_reviewed_by=seed_data["super_admin_user"].user_id,
                status_reviewed_at=now,
            )
        )
    rows.append(AdverseReaction(patient_id=seed_data["patient"].patient_id, pharmaceutical_id=99999999, symptom="药品引用无法核实", report_time=now, status=0, severity=99))
    foreign = AdverseReaction(patient_id=seed_data["patient2"].patient_id, symptom="其他患者不应读取的反应", status=1, report_time=now)
    db_session.add_all([*rows, foreign])
    db_session.commit()
    return rows, foreign


def snapshot(db_session, seed_data, **references):
    return patient_snapshot(db_session, seed_data["super_admin_user"], FEATURE_BY_KEY["adr_signal"], seed_data["patient"].patient_id, source_refs=references)


def test_processed_excluded_and_legacy_unknown_remain_distinct_without_inferred_exposure(seed_data, db_session, adr_case):
    selected = adr_case[0][0]
    bundle = snapshot(db_session, seed_data, reaction_id=str(selected.reaction_id))
    source = bundle.data["adr_sources"]
    states = {item["recorded_state"] for item in source["reports"]}
    assert states == {"legacy_ambiguous", "processed", "excluded", "pending"}
    assert source["symptom_onset_time"] == source["administration_link"] == source["encounter_assignment"] == "not_recorded"
    unresolved = next(item for item in source["reports"] if item["pharmaceutical_id"] == 99999999)
    assert unresolved["drug_reference_resolved"] is False and unresolved["pharmaceutical_name"] is None and unresolved["recorded_severity"] == 99
    serialized = encode_json({"context": bundle.data, "evidence": bundle.evidence})
    for forbidden in (seed_data["patient"].name, "其他患者不应读取", "status_reviewed_by", "reporter_id"):
        assert forbidden not in serialized
    assert any("历史状态" in text for text in bundle.data["missing_data"])
    assert any(item["source_id"] == "adr:" + str(selected.reaction_id) for item in bundle.evidence)


def test_explicit_older_report_survives_bounded_history_and_retrieval_uses_selected_facts(seed_data, db_session, adr_case):
    selected = adr_case[0][0]
    for index in range(10):
        db_session.add(AdverseReaction(patient_id=selected.patient_id, symptom="近期其他反应" + str(index), report_time=selected.report_time + datetime.timedelta(days=index + 1), status=0))
    db_session.commit()
    bundle = snapshot(db_session, seed_data, reaction_id=str(selected.reaction_id))
    rows = bundle.data["adr_sources"]["reports"]
    assert len(rows) == 8 and rows[0]["reaction_id"] == selected.reaction_id and rows[0]["explicitly_selected"] is True
    assert any(item["source"] == "ADR上报与处理记录" for item in bundle.data["truncated_sources"])
    query = retrieval_query(FEATURE_BY_KEY["allergy_review"], {"reaction_id": str(selected.reaction_id)}, bundle.data)
    assert "所选反应症状" in query and "近期其他反应" not in query


def test_foreign_report_and_patient_inspection_cannot_cross_internal_boundaries(seed_data, db_session, adr_case):
    rows, foreign = adr_case
    with pytest.raises(HTTPException) as error:
        snapshot(db_session, seed_data, reaction_id=str(foreign.reaction_id))
    assert error.value.status_code == 404
    with pytest.raises(HTTPException) as error:
        patient_snapshot(db_session, seed_data["patient_user"], FEATURE_BY_KEY["patient_report_explanation"], rows[0].patient_id, source_refs={"reaction_id": str(rows[0].reaction_id)})
    assert error.value.status_code == 403
    without = patient_snapshot(db_session, seed_data["patient_user"], FEATURE_BY_KEY["patient_report_explanation"], rows[0].patient_id)
    assert "adr_sources" not in without.data


@pytest.mark.asyncio
async def test_pharmacist_can_inspect_authorized_report_without_model_or_side_effects(seed_data, db_session, adr_case, async_client, auth_headers):
    selected = adr_case[0][0]
    before = seed_data["patient"].allergy_history
    payload = {"feature_key": "adr_signal", "patient_id": selected.patient_id, "source_refs": {"reaction_id": str(selected.reaction_id)}}
    response = await async_client.post("/api/ai/context", headers=auth_headers(seed_data["pharmacist_user"].username), json=payload)
    assert response.status_code == 200, response.text
    assert response.json()["data"]["context"]["adr_sources"]["reports"][0]["reaction_id"] == selected.reaction_id
    assert db_session.query(AIRun).count() == 0
    db_session.refresh(seed_data["patient"])
    assert seed_data["patient"].allergy_history == before


@pytest.mark.asyncio
async def test_new_resolution_while_queued_stops_specialist_call_and_retains_unknown_original(seed_data, db_session, adr_case):
    selected = adr_case[0][0]
    key = "adr_signal"
    provider = AIProvider(
        name="adr-isolated",
        kind="specialist",
        api_base="http://localhost:11434",
        model="isolated",
        enabled=1,
        allows_patient_data=1,
        supported_features_json=encode_json([key]),
        validation_report="isolated test report",
        created_by=seed_data["super_admin_user"].user_id,
    )
    db_session.add(provider)
    db_session.flush()
    db_session.add(
        AIFeatureConfig(
            feature_key=key,
            enabled=1,
            provider_id=provider.provider_id,
            validation_status="validated",
            allowed_roles_json=encode_json(FEATURE_BY_KEY[key].default_roles),
            updated_by=seed_data["super_admin_user"].user_id,
        )
    )
    db_session.commit()
    run = create_run(db_session, seed_data["super_admin_user"], RunRequest(feature_key=key, patient_id=selected.patient_id, input={"reaction_id": str(selected.reaction_id)}))
    frozen = json.loads(run.input_json)
    selected.status_resolution = "processed"
    selected.resolution_note = "后来人工核实了处理结果"
    selected.status_reviewed_at = datetime.datetime.now()
    db_session.commit()
    calls = []
    await execute_claimed(*claim_next_run(db_session), transport=httpx.MockTransport(lambda request: (calls.append(request), httpx.Response(500))[1]))
    db_session.refresh(run)
    assert not calls and run.error_code == "TASK_CONTEXT_CHANGED"
    findings = describe_run(run)["adr_findings"]
    assert findings == frozen["payload"]["context"]["adr_sources"]
    assert findings["reports"][0]["recorded_state"] == "legacy_ambiguous"
