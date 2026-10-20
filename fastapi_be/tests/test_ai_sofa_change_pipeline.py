"""Both complete daily originals are reloaded before independent change execution."""

import json

import pytest

from app.ai import sofa_change_sources as changes
from app.ai import sofa_sources as daily
from app.ai.models import AIRun
from app.ai.runtime import claim_next_run, create_run, execute_claimed
from app.ai.schemas import RunRequest
from app.ai.sofa_models import AISofaRunResult
from tests.test_ai_sofa_change_sources import baseline_ref, body, observed_baseline
from tests.test_ai_sofa_pipeline import RealSofaTransport
from tests.test_ai_sofa_pipeline import assessment_case as assessment_case
from tests.test_ai_sofa_pipeline import clean_ai_tasks as clean_ai_tasks
from tests.test_ai_sofa_pipeline import observation_case as observation_case
from tests.test_ai_sofa_pipeline import pipeline_case as pipeline_case
from tests.test_ai_sofa_pipeline import sofa_case as sofa_case
from tests.test_ai_sofa_pipeline import source_case as source_case
from tests.test_inpatient_infection_episodes import payload as infection_payload
from tests.test_inpatient_respiratory_contract import NOTE


@pytest.fixture
def change_pipeline_case(db_session, pipeline_case):
    from app import inpatient_support_common as common

    case = pipeline_case
    case["current"] = case["assessment"]
    case["infection"] = common.create_source(
        db_session,
        case["doctor"],
        "infection_episode",
        {
            "patient_id": case["patient_id"],
            "admission_id": case["admission"].admission_id,
            "payload": infection_payload(case),
        },
    )
    db_session.commit()
    return case


def register(db, case, mode):
    if mode == "observed":
        case["baseline"] = observed_baseline(db, case)
        baseline = baseline_ref(case["baseline"])
    elif mode in ("conditional_zero", "unconfirmed_zero"):
        baseline = {
            "mode": "conditional_zero",
            "no_known_preexisting_organ_dysfunction": mode == "conditional_zero",
            "preinfection_baseline_assumption_confirmed": mode == "conditional_zero",
            "basis_note": NOTE,
        }
    else:
        baseline = {"mode": "unknown", "basis_note": NOTE}
    row = changes.create_change_assessment(db, case["doctor"], body(case, baseline=baseline))
    db.commit()
    return row


def request(case, row):
    return RunRequest(
        feature_key="sepsis_risk",
        patient_id=case["patient_id"],
        encounter_ref=case["admission"].admission_id,
        input={"sofa_change_assessment_id": row.change_assessment_id, "question": "SYNTH_PRIVATE_CHANGE_QUESTION"},
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["observed", "conditional_zero", "unconfirmed_zero", "unknown"])
async def test_actual_change_context_queue_real_service_complete_blob_and_authorized_history(mode, async_client, auth_headers, db_session, change_pipeline_case):
    case = change_pipeline_case
    row = register(db_session, case, mode)
    req = request(case, row)
    headers = auth_headers(case["doctor"].username)
    preview = await async_client.post(
        "/api/ai/context",
        headers=headers,
        json={
            "feature_key": "sepsis_risk",
            "patient_id": req.patient_id,
            "encounter_ref": req.encounter_ref,
            "source_refs": {"sofa_change_assessment_id": row.change_assessment_id},
        },
    )
    assert preview.status_code == 200, preview.text
    source = preview.json()["data"]["context"]["sofa_change_source"]
    run = create_run(db_session, case["doctor"], req)
    assert "sofa_change_source" not in json.loads(run.input_json)["payload"]["context"]
    transport = RealSofaTransport(case["service"])
    await execute_claimed(*claim_next_run(db_session), transport=transport)
    db_session.expire_all()
    stored = db_session.get(AIRun, run.run_id)
    assert stored.status == "succeeded", (stored.error_code, stored.error_message)
    assert transport.requests[0]["input"] == {"context": {"sofa_change_source": source}}
    assert all(value not in json.dumps(transport.requests[0]["input"], ensure_ascii=False) for value in ("patient_id", "admission_id", "basis_note", "SYNTH_PRIVATE_CHANGE_QUESTION", NOTE))
    response = await async_client.get(f"/api/ai/runs/{run.run_id}", headers=headers)
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    result = data["result"]
    assert "sofa_analysis" not in result
    native = result["sofa_change_analysis"]
    assert native["source_binding"]["projection_hash"] == row.projection_hash
    assert native["baseline_analysis"]["mode"] == ("conditional_zero" if mode == "unconfirmed_zero" else mode)
    assert native["diagnosis_provided"] is native["historical_prediction"] is native["treatment_provided"] is False
    if mode == "unconfirmed_zero":
        assert native["baseline_analysis"]["assumed_total_score"] is None and native["baseline_analysis"]["upper_bound"] == 24
    elif mode == "unknown":
        assert native["baseline_analysis"]["lower_bound"] == 0 and native["baseline_analysis"]["upper_bound"] == 24
    elif mode == "observed":
        assert native["baseline_analysis"]["analysis"]["source_binding"]["projection_hash"] == case["baseline"].projection_hash
    assert data["sofa_change_findings"]["sofa_change_source"] == source
    assert result == json.loads(db_session.get(AISofaRunResult, run.run_id).result_json)


def revoke(db, case, target):
    if target in ("current", "baseline"):
        daily.revoke_assessment(db, case["doctor"], case[target], 1, "合成独立两期原评估撤销，必须阻断旧变化结果。")
    else:
        row = case["infection"]
        row.status, row.revision, row.revoked_at = "revoked", 2, case["now"]
        row.revoked_by, row.revoke_reason = case["doctor"].user_id, "合成感染原声明撤销，不能继续使用旧变化归因。"
    db.commit()


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["queued", "inflight", "history"])
@pytest.mark.parametrize("target", ["current", "baseline", "infection"])
async def test_any_original_daily_or_infection_revocation_rejects_all_execution_and_read_phases(phase, target, async_client, auth_headers, db_session, change_pipeline_case):
    case = change_pipeline_case
    row = register(db_session, case, "observed")
    run = create_run(db_session, case["doctor"], request(case, row))
    if phase == "queued":
        revoke(db_session, case, target)
    transport = RealSofaTransport(case["service"], before=(lambda: revoke(db_session, case, target)) if phase == "inflight" else None)
    await execute_claimed(*claim_next_run(db_session), transport=transport)
    db_session.expire_all()
    stored = db_session.get(AIRun, run.run_id)
    if phase != "history":
        assert stored.status == "failed" and stored.result_json == "{}"
        assert db_session.get(AISofaRunResult, run.run_id) is None
        assert len(transport.requests) == (0 if phase == "queued" else 1)
        return
    assert stored.status == "succeeded", stored.error_message
    revoke(db_session, case, target)
    ordinary = await async_client.get(f"/api/ai/runs/{run.run_id}", headers=auth_headers(case["doctor"].username))
    assert ordinary.status_code == 403, ordinary.text
    audit = await async_client.get(f"/api/ai/runs/{run.run_id}", headers=auth_headers(case["seed"]["super_admin_user"].username))
    assert audit.status_code == 200, audit.text
    assert audit.json()["data"]["sofa_change_findings"]["sofa_change_assessment"]["eligible"] is False
