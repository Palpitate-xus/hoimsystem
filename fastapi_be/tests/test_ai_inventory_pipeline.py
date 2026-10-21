"""Actual synthetic originals→scenario→JWT API→durable worker→native ASGI→SQL proof.

Business clocks are controlled by the actual Source/Scenario fixture. This is
engineering validation using synthetic SQL, never a hospital deployment.
"""

import datetime
import inspect
import json
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import text

from app.ai import inventory_context, models, runtime
from app.ai.governance import encode_json
from app.ai.inventory_config import InventorySettings, runtime_descriptor
from app.ai.inventory_contract import canonical_json, hash_content
from app.ai.inventory_scenario_models import AIInventoryRunResult
from app.ai.inventory_server import create_inventory_app
from app.ai.models import AIAuditEvent, AIFeatureConfig, AIFeedback, AIProvider, AIRun
from app.ai.runtime import claim_next_run, execute_claimed
from app.models import PurchaseOrder
from tests.test_ai_inventory_scenarios import candidate, published, source_request
from tests.test_ai_inventory_scenarios import inventory_case as inventory_case
from tests.test_ai_runtime import configure

KEY = "synthetic-inventory-pipeline-private-key-1234567890"


class NativeInventoryTransport(httpx.AsyncBaseTransport):
    def __init__(self, app, before=None):
        self.inner, self.before, self.requests = httpx.ASGITransport(app=app), before, []

    async def handle_async_request(self, request):
        self.requests.append(json.loads(await request.aread()))
        if self.before:
            result = self.before()
            if inspect.isawaitable(result):
                await result
        return await self.inner.handle_async_request(request)


@pytest.fixture(autouse=True)
def clear_inventory_tasks(db_session):
    for model in (AIFeedback, AIInventoryRunResult, AIRun, AIFeatureConfig, AIProvider):
        db_session.query(model).delete()
    db_session.commit()


@pytest.fixture
def pipeline_case(db_session, seed_data, inventory_case, monkeypatch):
    case = inventory_case

    class BusinessClock(datetime.datetime):
        @classmethod
        def now(cls, tz=None):
            value = case["now"].replace(tzinfo=datetime.UTC)
            return value.astimezone(tz) if tz is not None else value.replace(tzinfo=None)

    monkeypatch.setattr(inventory_context, "datetime", BusinessClock)
    monkeypatch.setattr(models, "datetime", SimpleNamespace(datetime=BusinessClock, UTC=datetime.UTC))
    for module in (models, runtime):
        monkeypatch.setattr(module, "utcnow", lambda: case["now"])
    row = published(db_session, case)
    monkeypatch.setenv("AI_PROVIDER_LOCAL_INVENTORY_API_KEY", KEY)
    settings = InventorySettings(AI_PROVIDER_LOCAL_INVENTORY_API_KEY=KEY)
    provider, feature = configure(db_session, seed_data, "inventory_optimization")
    provider.kind, provider.model = "specialist", runtime_descriptor(settings)["model_version"]
    provider.api_base, provider.api_key_env = "http://127.0.0.1:8823", "AI_PROVIDER_LOCAL_INVENTORY_API_KEY"
    provider.supported_features_json, provider.timeout_seconds = encode_json(["inventory_optimization"]), 110
    provider.allows_patient_data = False
    provider.validation_report = "Synthetic engineering only; no operational deployment or outcome validation."
    db_session.commit()
    return {**case, "clock_case": case, "seed": seed_data, "scenario": row, "provider": provider, "feature": feature, "service": create_inventory_app(settings)}


def request(case, **extra):
    return {"feature_key": "inventory_optimization", "input": {"inventory_scenario_id": case["scenario"].scenario_id, "question": "SYNTH_PRIVATE_QUESTION"}, **extra}


@pytest.mark.asyncio
async def test_actual_queue_native_complete_result_frozen_audit_and_feedback(async_client, auth_headers, db_session, pipeline_case, tmp_path):
    case, db = pipeline_case, db_session
    before = (case["drug"].stock, case["drug"].price, case["batch"].stock, db.query(PurchaseOrder).count())
    headers = auth_headers(case["admin"].username)
    preview = await async_client.post("/api/ai/operational-context", headers=headers, json={"feature_key": "inventory_optimization", "input": request(case)["input"]})
    assert preview.status_code == 200, preview.text
    response = await async_client.post("/api/ai/runs", headers=headers, json=request(case))
    assert response.status_code == 200, response.text
    queued = response.json()
    run_id = queued["data"]["run_id"]
    assert queued["data"]["status"] == "queued" and "inventory_findings" not in queued["data"]
    claim = claim_next_run(db)
    assert claim and claim[0] == run_id
    running = await async_client.get(f"/api/ai/runs/{run_id}", headers=headers)
    assert running.status_code == 200 and running.json()["data"]["status"] == "running", running.text
    wire = NativeInventoryTransport(case["service"])
    await execute_claimed(*claim, transport=wire)
    db.expire_all()
    run = db.get(AIRun, run_id)
    assert run.status == "succeeded", (run.error_code, run.error_message)
    assert len(wire.requests) == 1 and "SYNTH_PRIVATE" not in canonical_json(wire.requests)
    assert set(wire.requests[0]["input"]) == {"context"}
    assert set(wire.requests[0]["input"]["context"]) == {"inventory_source"}
    detail = await async_client.get(f"/api/ai/runs/{run_id}", headers=headers)
    assert detail.status_code == 200, detail.text
    data = detail.json()["data"]
    assert set(data["inventory_findings"]) == {"inventory_source", "inventory_scenario", "inventory_binding"}
    analysis = data["result"]["inventory_analysis"]
    assert analysis["candidate_count"] == 2 and analysis["best_among_declared_candidates"]
    assert analysis["known_feasible_count"] == analysis["known_infeasible_count"] == 1
    assert analysis["best_known_feasible_cost"] == {"numerator": "10", "denominator": "1"}
    assert all(len(row["daily"]) == 2 for row in analysis["candidate_results"])
    blob = db.query(AIInventoryRunResult).filter_by(run_id=run_id).one()
    assert blob.content_hash == hash_content(data["result"]) and blob.result_bytes == len(blob.result_json.encode())
    assert json.loads(run.result_json)["schema_version"] == "inventory_result_ref_v1"
    assert db.query(AIAuditEvent).filter_by(action="run.inventory_result.accept", target=run_id).count() == 1
    audit = await async_client.get(f"/api/ai/admin/runs/{run_id}", headers=auth_headers(case["super"].username))
    assert audit.status_code == 200 and audit.json()["data"]["snapshot_complete"], audit.text
    feedback = await async_client.post(f"/api/ai/runs/{run_id}/feedback", headers=headers, json={"outcome": "accepted", "comment": "合成工程复核，不代表真实采购效果"})
    assert feedback.status_code == 200, feedback.text
    assert before == (case["drug"].stock, case["drug"].price, case["batch"].stock, db.query(PurchaseOrder).count())
    packets = {
        "synthetic_only": True,
        "controlled_business_clock": True,
        "scope": "Actual SQL originals, governed finite scenario, JWT queue and native ASGI; no hospital DB or operational outcome validation",
        "preview": preview.json(),
        "queued": queued,
        "running": running.json(),
        "detail": detail.json(),
        "audit": audit.json(),
        "outbound": wire.requests[0],
        "stored_result_reference": json.loads(run.result_json),
    }
    (tmp_path / "actual-inventory-pipeline-packets.json").write_text(json.dumps(packets, ensure_ascii=False, indent=2))


async def queued_and_claimed(client, headers, db, case, **extra):
    response = await client.post("/api/ai/runs", headers=headers, json=request(case, **extra))
    assert response.status_code == 200, response.text
    claim = claim_next_run(db)
    assert claim and claim[0] == response.json()["data"]["run_id"]
    return claim


def assert_unaccepted(db, run_id):
    run = db.get(AIRun, run_id)
    assert run.result_json == "{}" and db.query(AIInventoryRunResult).filter_by(run_id=run_id).count() == 0
    assert db.query(AIAuditEvent).filter_by(action="run.inventory_result.accept", target=run_id).count() == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["doctor_user", "nurse_user", "cashier_user", "patient_user"])
async def test_disallowed_roles_cannot_queue_inventory_candidates(role, async_client, auth_headers, db_session, pipeline_case):
    response = await async_client.post("/api/ai/runs", headers=auth_headers(pipeline_case["seed"][role].username), json=request(pipeline_case))
    assert response.status_code == 403 and db_session.query(AIRun).count() == 0, response.text


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["patient", "encounter", "quantity", "unit", "parameters", "forecast_reference", "arbitrary_candidate"])
async def test_client_cannot_inject_inventory_facts_or_cross_feature_scope(change, async_client, auth_headers, db_session, pipeline_case):
    case = pipeline_case
    body = request(case)
    if change == "patient":
        body["patient_id"] = case["seed"]["patient"].patient_id
    elif change == "encounter":
        body["encounter_ref"] = "outpatient:1"
    else:
        name, value = {
            "quantity": ("quantity", "999"),
            "unit": ("unit_token", "a" * 64),
            "parameters": ("parameters", {}),
            "forecast_reference": ("supply_series_id", case["scenario"].scenario_id),
            "arbitrary_candidate": ("candidate_id", case["purchase"].source_record_id),
        }[change]
        body["input"][name] = value
    response = await async_client.post("/api/ai/runs", headers=auth_headers(case["admin"].username), json=body)
    assert response.status_code == 422 and db_session.query(AIRun).count() == 0, response.text


@pytest.mark.asyncio
async def test_super_preview_is_separate_from_business_enablement_and_validation(async_client, auth_headers, db_session, pipeline_case):
    case, db = pipeline_case, db_session
    case["feature"].enabled, case["feature"].validation_status = False, "unreviewed"
    db.commit()
    denied = await async_client.post("/api/ai/runs", headers=auth_headers(case["admin"].username), json=request(case))
    assert denied.status_code == 409 and db.query(AIRun).count() == 0, denied.text
    claim = await queued_and_claimed(async_client, auth_headers(case["super"].username), db, case, preview=True)
    wire = NativeInventoryTransport(case["service"])
    await execute_claimed(*claim, transport=wire)
    db.expire_all()
    assert db.get(AIRun, claim[0]).status == "succeeded"
    assert not case["feature"].enabled and case["feature"].validation_status == "unreviewed"


@pytest.mark.asyncio
@pytest.mark.parametrize("when", ["queued", "inflight"])
@pytest.mark.parametrize(
    "change",
    [
        "new_draft_nonwinner",
        "revoke_unit",
        "revoke_observation",
        "sku_stock",
        "batch_stock",
        "actor_role",
        "professional_role",
        "provider_revision",
        "provider_disabled",
        "feature_revision",
        "feature_disabled",
    ],
)
async def test_current_originals_authority_or_configuration_changes_reject_old_results(when, change, async_client, auth_headers, db_session, pipeline_case):
    from app.ai import inventory_native_sources as facts
    from app.ai import supply_sources as units
    from tests.test_ai_inventory_native_source_input import NOTE

    case, db = pipeline_case, db_session
    claim = await queued_and_claimed(async_client, auth_headers(case["admin"].username), db, case)

    def mutate():
        if change == "new_draft_nonwinner":
            facts.create_source(db, case["pharmacist"], source_request(case, candidate(case)))
        elif change == "revoke_unit":
            unit = case["unit"]
            units.review_source(db, case["super"], "unit", unit.unit_definition_id, {"expected_revision": unit.revision, "expected_content_hash": unit.content_hash, "basis_note": NOTE}, revoke=True)
        elif change == "revoke_observation":
            source = case["observation"]
            facts.review_source(db, case["super"], source.source_record_id, {"expected_revision": source.revision, "expected_content_hash": source.content_hash, "basis_note": NOTE}, revoke=True)
        elif change == "sku_stock":
            case["drug"].stock += 1
        elif change == "batch_stock":
            case["batch"].stock += 1
        elif change == "actor_role":
            case["admin"].user_role = "doctor"
        elif change == "professional_role":
            case["pharmacist"].user_role = "nurse"
        elif change == "provider_revision":
            case["provider"].revision += 1
        elif change == "provider_disabled":
            case["provider"].enabled = False
        elif change == "feature_revision":
            case["feature"].revision += 1
        else:
            case["feature"].enabled = False
        db.commit()

    if when == "queued":
        mutate()
    wire = NativeInventoryTransport(case["service"], before=mutate if when == "inflight" else None)
    await execute_claimed(*claim, transport=wire)
    db.expire_all()
    run = db.get(AIRun, claim[0])
    assert run.status == "failed", (run.error_code, run.error_message)
    assert len(wire.requests) == (0 if when == "queued" else 1)
    assert_unaccepted(db, claim[0])


@pytest.mark.asyncio
async def test_inflight_cancel_keeps_usage_without_accepting_native_result(async_client, auth_headers, db_session, pipeline_case):
    case, db = pipeline_case, db_session
    headers = auth_headers(case["admin"].username)
    claim = await queued_and_claimed(async_client, headers, db, case)

    async def cancel():
        response = await async_client.post(f"/api/ai/runs/{claim[0]}/cancel", headers=headers)
        assert response.status_code == 200, response.text

    wire = NativeInventoryTransport(case["service"], before=cancel)
    await execute_claimed(*claim, transport=wire)
    db.expire_all()
    run = db.get(AIRun, claim[0])
    assert run.status == "cancelled" and run.finish_time is not None and len(wire.requests) == 1
    assert_unaccepted(db, run.run_id)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "fault",
    [
        "audit_sql_abort",
        "source_changed_by_blob_insert",
        "prompt_summary_changed_by_audit_insert",
        "task_owner",
        "task_lease",
        "task_status",
        "task_pointer",
        "blob_body",
        "blob_delete",
        "audit_detail",
        "audit_delete",
    ],
)
async def test_sql_acceptance_fault_rolls_back_result_audit_pointer_and_source_changes(fault, async_client, auth_headers, db_session, pipeline_case):
    from app.ai.inventory_native_source_models import AIInventoryNativeSource

    case, db = pipeline_case, db_session
    claim = await queued_and_claimed(async_client, auth_headers(case["admin"].username), db, case)
    source_id = case["observation"].source_record_id
    original_json = case["observation"].payload_json
    trigger = "inventory_owned_pipeline_acceptance_fault"
    if fault == "audit_sql_abort":
        ddl = (
            f"CREATE TRIGGER {trigger} BEFORE INSERT ON hoimsystem_ai_audit_event WHEN NEW.action = 'run.inventory_result.accept' BEGIN SELECT RAISE(ABORT, 'synthetic inventory audit rejection'); END"
        )
    elif fault == "source_changed_by_blob_insert":
        ddl = f"CREATE TRIGGER {trigger} AFTER INSERT ON hoimsystem_ai_inventory_run_result BEGIN UPDATE hoimsystem_ai_inventory_native_source SET payload_json = '{{}}' WHERE source_record_id = '{source_id}'; END"
    elif fault == "prompt_summary_changed_by_audit_insert":
        ddl = f"CREATE TRIGGER {trigger} AFTER INSERT ON hoimsystem_ai_audit_event WHEN NEW.action = 'run.inventory_result.accept' BEGIN UPDATE hoimsystem_ai_run SET context_metadata_json = '{{}}' WHERE run_id = '{claim[0]}'; END"
    else:
        changes = {
            "task_owner": f"UPDATE hoimsystem_ai_run SET requested_by={case['super'].user_id} WHERE run_id='{claim[0]}'",
            "task_lease": f"UPDATE hoimsystem_ai_run SET lease_token='{uuid4()}' WHERE run_id='{claim[0]}'",
            "task_status": f"UPDATE hoimsystem_ai_run SET status='cancelled' WHERE run_id='{claim[0]}'",
            "task_pointer": f"UPDATE hoimsystem_ai_run SET result_json='{{}}' WHERE run_id='{claim[0]}'",
            "blob_body": f"UPDATE hoimsystem_ai_inventory_run_result SET result_json='{{}}' WHERE run_id='{claim[0]}'",
            "blob_delete": f"DELETE FROM hoimsystem_ai_inventory_run_result WHERE run_id='{claim[0]}'",
            "audit_detail": "UPDATE hoimsystem_ai_audit_event SET detail_json='{}' WHERE event_id=NEW.event_id",
            "audit_delete": "DELETE FROM hoimsystem_ai_audit_event WHERE event_id=NEW.event_id",
        }
        if fault in {"task_status", "task_pointer"}:
            timing = f"AFTER UPDATE ON hoimsystem_ai_run WHEN NEW.run_id='{claim[0]}' AND NEW.status='succeeded'"
        elif fault in {"blob_body", "blob_delete"}:
            timing = f"AFTER INSERT ON hoimsystem_ai_inventory_run_result WHEN NEW.run_id='{claim[0]}'"
        else:
            timing = "AFTER INSERT ON hoimsystem_ai_audit_event WHEN NEW.action='run.inventory_result.accept'"
        ddl = f"CREATE TRIGGER {trigger} {timing} BEGIN {changes[fault]}; END"
    db.execute(text(ddl))
    db.commit()
    try:
        wire = NativeInventoryTransport(case["service"])
        await execute_claimed(*claim, transport=wire)
        db.expire_all()
        run = db.get(AIRun, claim[0])
        assert len(wire.requests) == 1 and run.status == "failed" and run.error_code == "RESULT_STORAGE_ERROR", (run.status, run.error_code, run.error_message)
        assert_unaccepted(db, run.run_id)
        assert run.requested_by == case["admin"].user_id and run.lease_token == claim[1]
        assert db.get(AIInventoryNativeSource, source_id).payload_json == original_json
        assert json.loads(run.context_metadata_json)["instructions_digest"]
    finally:
        db.rollback()
        db.execute(text(f"DROP TRIGGER IF EXISTS {trigger}"))
        db.commit()
