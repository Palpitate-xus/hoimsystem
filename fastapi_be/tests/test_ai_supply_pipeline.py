"""Actual reviewed originals→durable queue→native ASGI→complete SQL result."""

import inspect
import json

import httpx
import pytest
from sqlalchemy import text

from app.ai.governance import encode_json
from app.ai.models import AIAuditEvent, AIFeatureConfig, AIFeedback, AIProvider, AIRun
from app.ai.runtime import claim_next_run, execute_claimed
from app.ai.supply_config import SupplySettings, runtime_descriptor
from app.ai.supply_contract import canonical_json, hash_content
from app.ai.supply_series_models import AISupplyRunResult
from app.ai.supply_server import create_supply_app
from tests.test_ai_runtime import configure
from tests.test_ai_supply_series import complete_published, published
from tests.test_ai_supply_series import series_case as series_case
from tests.test_ai_supply_sources import NOTE, source_request
from tests.test_ai_supply_sources import supply_case as supply_case

KEY = "synthetic-supply-pipeline-private-key-1234567890"


class NativeSupplyTransport(httpx.AsyncBaseTransport):
    def __init__(self, app, before=None):
        self.inner, self.before, self.requests = httpx.ASGITransport(app=app), before, []

    async def handle_async_request(self, request):
        self.requests.append(json.loads(request.content))
        if self.before:
            returned = self.before()
            if inspect.isawaitable(returned):
                await returned
        return await self.inner.handle_async_request(request)


@pytest.fixture(autouse=True)
def clear_supply_tasks(db_session):
    for model in (AIFeedback, AISupplyRunResult, AIRun, AIFeatureConfig, AIProvider):
        db_session.query(model).delete()
    db_session.commit()


def configured_case(db, seed, case, row, monkeypatch):
    monkeypatch.setenv("AI_PROVIDER_LOCAL_SUPPLY_API_KEY", KEY)
    settings = SupplySettings(AI_PROVIDER_LOCAL_SUPPLY_API_KEY=KEY)
    provider, feature = configure(db, seed, "supply_forecast")
    provider.kind, provider.model = "specialist", runtime_descriptor(settings)["model_version"]
    provider.api_base, provider.api_key_env = "http://127.0.0.1:8822", "AI_PROVIDER_LOCAL_SUPPLY_API_KEY"
    provider.supported_features_json, provider.timeout_seconds = encode_json(["supply_forecast"]), 110
    provider.allows_patient_data = False
    provider.validation_report = "Synthetic engineering only; no operational deployment or outcome validation."
    db.commit()
    return {**case, "seed": seed, "series": row, "provider": provider, "feature": feature, "service": create_supply_app(settings)}


@pytest.fixture
def pipeline_case(db_session, seed_data, series_case, monkeypatch):
    row = published(db_session, series_case)
    return configured_case(db_session, seed_data, series_case, row, monkeypatch)


def request(case, horizon=7, **extra):
    return {"feature_key": "supply_forecast", "input": {"supply_series_id": case["series"].series_id, "horizon_days": horizon, "question": "SYNTH_PRIVATE_QUESTION"}, **extra}


@pytest.mark.asyncio
async def test_real_336_originals_both_horizons_queue_native_results_and_frozen_audit(async_client, auth_headers, db_session, seed_data, series_case, monkeypatch, tmp_path):
    from app.ai.supply_series import series_proof

    db = db_session
    row = complete_published(db, series_case)
    case = configured_case(db, seed_data, series_case, row, monkeypatch)
    stock_before = (case["drug"].stock, case["drug"].price, case["consumable"].stock)
    packets = {"synthetic_only": True, "scope": "actual reviewed 336 daily originals, SQL queue and native ASGI; no clinical or operational effect validation", "horizons": {}}
    headers = auth_headers(case["admin"].username)
    for horizon in (7, 14):
        preview = await async_client.post("/api/ai/operational-context", headers=headers, json={"feature_key": "supply_forecast", "input": request(case, horizon)["input"]})
        assert preview.status_code == 200, preview.text
        response = await async_client.post("/api/ai/runs", headers=headers, json=request(case, horizon))
        assert response.status_code == 200, response.text
        queued = response.json()
        run_id = queued["data"]["run_id"]
        assert queued["data"]["status"] == "queued" and "supply_findings" not in queued["data"]
        claim = claim_next_run(db)
        assert claim and claim[0] == run_id
        running = await async_client.get(f"/api/ai/runs/{run_id}", headers=headers)
        assert running.status_code == 200 and running.json()["data"]["status"] == "running", running.text
        wire = NativeSupplyTransport(case["service"])
        await execute_claimed(*claim, transport=wire)
        db.expire_all()
        run = db.get(AIRun, run_id)
        assert run.status == "succeeded", (run.error_code, run.error_message)
        assert len(wire.requests) == 1 and "SYNTH_PRIVATE" not in canonical_json(wire.requests)
        assert set(wire.requests[0]["input"]) == {"context", "horizon_days"}
        detail = await async_client.get(f"/api/ai/runs/{run_id}", headers=headers)
        assert detail.status_code == 200, detail.text
        data = detail.json()["data"]
        analysis = data["result"]["supply_analysis"]
        assert analysis["horizon_days"] == horizon and analysis["planned_pair_count"] == 28 * horizon
        assert all(target["status"] == "complete" for target in analysis["targets"])
        assert all(model["eligible_origin_count"] == 28 for target in analysis["targets"] for model in target["models"])
        blob = db.query(AISupplyRunResult).filter_by(run_id=run_id).one()
        assert blob.content_hash == hash_content(data["result"]) and blob.result_bytes == len(blob.result_json.encode()) > 65535
        assert json.loads(run.result_json)["schema_version"] == "supply_result_ref_v1"
        assert db.query(AIAuditEvent).filter_by(action="run.supply_result.accept", target=run_id).count() == 1
        audit = await async_client.get(f"/api/ai/admin/runs/{run_id}", headers=auth_headers(case["super"].username))
        assert audit.status_code == 200 and audit.json()["data"]["snapshot_complete"], audit.text
        feedback = await async_client.post(f"/api/ai/runs/{run_id}/feedback", headers=headers, json={"outcome": "accepted", "comment": "合成工程复核，不代表真实预测效果"})
        assert feedback.status_code == 200, feedback.text
        packets["horizons"][str(horizon)] = {
            "preview": preview.json(),
            "queued": queued,
            "running": running.json(),
            "detail": detail.json(),
            "audit": audit.json(),
            "outbound": wire.requests[0],
            "stored_result_reference": json.loads(run.result_json),
        }
    assert stock_before == (case["drug"].stock, case["drug"].price, case["consumable"].stock)
    assert len(series_proof(row)[1]["observations"]) == 336
    (tmp_path / "actual-supply-pipeline-packets.json").write_text(json.dumps(packets, ensure_ascii=False, indent=2))


async def queued_and_claimed(client, headers, db, case, **extra):
    response = await client.post("/api/ai/runs", headers=headers, json=request(case, **extra))
    assert response.status_code == 200, response.text
    claim = claim_next_run(db)
    assert claim and claim[0] == response.json()["data"]["run_id"]
    return claim


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["doctor_user", "nurse_user", "cashier_user", "patient_user"])
async def test_disallowed_business_roles_cannot_queue_supply_originals(role, async_client, auth_headers, db_session, pipeline_case):
    response = await async_client.post("/api/ai/runs", headers=auth_headers(pipeline_case["seed"][role].username), json=request(pipeline_case))
    assert response.status_code == 403 and db_session.query(AIRun).count() == 0, response.text


@pytest.mark.asyncio
@pytest.mark.parametrize("case_name", ["patient", "encounter", "quantity", "unit", "parameters", "mixed_reference", "bool_horizon", "string_horizon"])
async def test_client_cannot_override_scope_original_quantities_or_fixed_profile(case_name, async_client, auth_headers, db_session, pipeline_case):
    body = request(pipeline_case)
    if case_name == "patient":
        body["patient_id"] = pipeline_case["seed"]["patient"].patient_id
    elif case_name == "encounter":
        body["encounter_ref"] = "outpatient:1"
    else:
        field, value = {
            "quantity": ("quantity", "999"),
            "unit": ("unit_token", "a" * 64),
            "parameters": ("parameters", {}),
            "mixed_reference": ("bed_series_id", pipeline_case["series"].series_id),
            "bool_horizon": ("horizon_days", True),
            "string_horizon": ("horizon_days", "7"),
        }[case_name]
        body["input"][field] = value
    response = await async_client.post("/api/ai/runs", headers=auth_headers(pipeline_case["admin"].username), json=body)
    assert response.status_code == 422 and db_session.query(AIRun).count() == 0, response.text


@pytest.mark.asyncio
async def test_super_preview_remains_separate_from_business_enablement_and_validation(async_client, auth_headers, db_session, pipeline_case):
    case, db = pipeline_case, db_session
    case["feature"].enabled, case["feature"].validation_status = False, "unreviewed"
    db.commit()
    denied = await async_client.post("/api/ai/runs", headers=auth_headers(case["admin"].username), json=request(case))
    assert denied.status_code == 409 and db.query(AIRun).count() == 0
    claim = await queued_and_claimed(async_client, auth_headers(case["super"].username), db, case, preview=True)
    wire = NativeSupplyTransport(case["service"])
    await execute_claimed(*claim, transport=wire)
    db.expire_all()
    run = db.get(AIRun, claim[0])
    assert run.status == "succeeded", (run.error_code, run.error_message)
    assert case["feature"].enabled == 0 and case["feature"].validation_status == "unreviewed"
    result = json.loads(db.query(AISupplyRunResult).filter_by(run_id=run.run_id).one().result_json)
    assert all(target["status"] == "input_unknown" for target in result["supply_analysis"]["targets"])


@pytest.mark.asyncio
@pytest.mark.parametrize("when", ["queued", "inflight"])
@pytest.mark.parametrize("change", ["new_draft_nonwinner", "revoke_unit", "actor_role", "provider_revision", "feature_revision"])
async def test_current_collection_authority_or_configuration_changes_never_accept_old_result(when, change, async_client, auth_headers, db_session, pipeline_case):
    from app.ai import supply_sources as facts

    case, db = pipeline_case, db_session
    headers = auth_headers(case["admin"].username)
    claim = await queued_and_claimed(async_client, headers, db, case)

    def mutate():
        if change == "new_draft_nonwinner":
            facts.create_source(db, case["pharmacist"], source_request(case, case["unit"]))
        elif change == "revoke_unit":
            unit = case["unit"]
            facts.review_source(db, case["super"], "unit", unit.unit_definition_id, {"expected_revision": unit.revision, "expected_content_hash": unit.content_hash, "basis_note": NOTE}, revoke=True)
        elif change == "actor_role":
            case["admin"].user_role = "doctor"
        elif change == "provider_revision":
            case["provider"].revision += 1
        else:
            case["feature"].revision += 1
        db.commit()

    if when == "queued":
        mutate()
    wire = NativeSupplyTransport(case["service"], before=mutate if when == "inflight" else None)
    await execute_claimed(*claim, transport=wire)
    db.expire_all()
    run = db.get(AIRun, claim[0])
    assert run.status == "failed", (run.error_code, run.error_message)
    assert len(wire.requests) == (0 if when == "queued" else 1)
    assert run.result_json == "{}" and db.query(AISupplyRunResult).count() == 0
    assert db.query(AIAuditEvent).filter_by(action="run.supply_result.accept", target=run.run_id).count() == 0


@pytest.mark.asyncio
async def test_real_inflight_cancel_retains_native_usage_without_accepting_forecast(async_client, auth_headers, db_session, pipeline_case):
    case, db = pipeline_case, db_session
    headers = auth_headers(case["admin"].username)
    claim = await queued_and_claimed(async_client, headers, db, case)

    async def cancel():
        response = await async_client.post(f"/api/ai/runs/{claim[0]}/cancel", headers=headers)
        assert response.status_code == 200, response.text

    wire = NativeSupplyTransport(case["service"], before=cancel)
    await execute_claimed(*claim, transport=wire)
    db.expire_all()
    run = db.get(AIRun, claim[0])
    assert run.status == "cancelled" and run.finish_time is not None and len(wire.requests) == 1
    assert run.result_json == "{}" and db.query(AISupplyRunResult).count() == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["audit_sql_abort", "source_changed_by_blob_insert"])
async def test_real_sql_acceptance_fault_rolls_back_blob_pointer_audit_and_source_change(fault, async_client, auth_headers, db_session, pipeline_case):
    from app.ai.supply_source_models import AISupplyDailyQuantity

    case, db = pipeline_case, db_session
    claim = await queued_and_claimed(async_client, auth_headers(case["admin"].username), db, case)
    root = case["rows"][0]
    original_json = root.payload_json
    trigger = "supply_owned_pipeline_acceptance_fault"
    if fault == "audit_sql_abort":
        ddl = f"CREATE TRIGGER {trigger} BEFORE INSERT ON hoimsystem_ai_audit_event WHEN NEW.action = 'run.supply_result.accept' BEGIN SELECT RAISE(ABORT, 'synthetic supply audit rejection'); END"
    else:
        ddl = f"CREATE TRIGGER {trigger} AFTER INSERT ON hoimsystem_ai_supply_run_result BEGIN UPDATE hoimsystem_ai_supply_daily_quantity SET payload_json = '{{}}' WHERE source_record_id = '{root.source_record_id}'; END"
    db.execute(text(ddl))
    db.commit()
    try:
        wire = NativeSupplyTransport(case["service"])
        await execute_claimed(*claim, transport=wire)
        db.expire_all()
        run = db.get(AIRun, claim[0])
        assert len(wire.requests) == 1 and run.status == "failed" and run.error_code == "RESULT_STORAGE_ERROR", (run.status, run.error_code, run.error_message)
        assert run.result_json == "{}" and db.query(AISupplyRunResult).count() == 0
        assert db.query(AIAuditEvent).filter_by(action="run.supply_result.accept", target=run.run_id).count() == 0
        assert db.get(AISupplyDailyQuantity, root.source_record_id).payload_json == original_json
    finally:
        db.rollback()
        db.execute(text(f"DROP TRIGGER IF EXISTS {trigger}"))
        db.commit()
