"""Actual governed bed originals, durable queue, native HTTP and complete SQL results."""

import json
import uuid

import httpx
import pytest
from fastapi import HTTPException

from app.ai import bed_facts as facts
from app.ai import bed_series as series
from app.ai import governance
from app.ai.bed_config import BedSettings, runtime_descriptor
from app.ai.bed_contract import hash_content
from app.ai.bed_series_models import AIBedRunResult
from app.ai.bed_server import create_bed_app
from app.ai.bed_storage import RESULT_BYTES, bounded_result
from app.ai.governance import digest, encode_json
from app.ai.models import AIAuditEvent, AIFeedback, AIKnowledgeDocument, AIRun
from app.ai.runtime import claim_next_run, create_run, execute_claimed
from app.ai.schemas import RunRequest
from app.models import Admission, Bed, Doctor, Ward
from tests.test_ai_bed_facts import NOTE
from tests.test_ai_bed_facts import bed_case as bed_case
from tests.test_ai_bed_series import create_series, publish_series
from tests.test_ai_bed_series_input import original, period_request, series_request
from tests.test_ai_bed_series_input import series_case as series_case
from tests.test_ai_runtime import clean_ai_tasks as clean_ai_tasks
from tests.test_ai_runtime import configure

KEY = "synthetic-bed-pipeline-independent-key-1234567890"


class RealBedTransport(httpx.AsyncBaseTransport):
    """Keep the real native ASGI computation and inspect the actual HTTP request."""

    def __init__(self, app, before=None):
        self.inner = httpx.ASGITransport(app=app)
        self.requests, self.before = [], before

    async def handle_async_request(self, request):
        self.requests.append(json.loads(request.content))
        if self.before:
            self.before()
        return await self.inner.handle_async_request(request)


@pytest.fixture
def pipeline_case(db_session, series_case, clean_ai_tasks, monkeypatch):
    case = series_case
    db_session.query(AIBedRunResult).delete()
    case["series"] = publish_series(db_session, case, create_series(db_session, case))
    monkeypatch.setenv("AI_PROVIDER_LOCAL_BED_API_KEY", KEY)
    config = BedSettings(AI_PROVIDER_LOCAL_BED_API_KEY=KEY)
    provider, feature = configure(db_session, case["seed"], "bed_forecast")
    provider.kind, provider.model = "specialist", runtime_descriptor(config)["model_version"]
    provider.api_base, provider.api_key_env = "http://localhost:8820", "AI_PROVIDER_LOCAL_BED_API_KEY"
    provider.supported_features_json = encode_json(["bed_forecast"])
    provider.validation_report = "Synthetic engineering evidence only, not actual physical-bed operational validation."
    provider.timeout_seconds = 110
    provider.allows_patient_data = False
    db_session.commit()
    case.update(provider=provider, feature=feature, service=create_bed_app(config))
    return case


def make_complete_series(db, case):
    """Create and independently publish224 actual daily originals, without fake DTOs."""
    from app.ai.bed_series_input import SeriesPeriodRequest, period_bounds, preview_input

    days = period_bounds(SeriesPeriodRequest.model_validate(period_request(case)))["business_dates"]
    roots = {kind: [original(db, case, kind, day, known=True) for day in days] for kind in ("census", "flow_day")}
    chosen = {row.source_record_id for rows in roots.values() for row in rows} | {case["capacity"].source_record_id, case["future"].source_record_id}
    request = series_request(db, case, chosen=chosen)
    preview = preview_input(db, case["director"], case["period"])
    row = series.create_series(db, case["director"], {"request": request, "expected_collection_digest": preview["collection_digest"]})
    db.commit()
    case["series"] = publish_series(db, case, row)
    return roots


def run_request(case, horizon=7, **changes):
    return RunRequest(
        feature_key="bed_forecast", input={"bed_series_id": case["series"].series_id, "horizon_days": horizon, "question": "SYNTH_PRIVATE_BED_QUESTION_不能覆盖实测原量或容量情景"}, **changes
    )


async def successful(db, case, *, horizon=7):
    run = create_run(db, case["director"], run_request(case, horizon))
    wire = RealBedTransport(case["service"])
    await execute_claimed(*claim_next_run(db), transport=wire)
    db.expire_all()
    stored = db.get(AIRun, run.run_id)
    assert stored.status == "succeeded", (stored.error_code, stored.error_message)
    return stored, wire


def business_rows(db):
    return {
        model.__tablename__: [tuple(getattr(row, col.name) for col in model.__table__.columns) for row in db.query(model).order_by(*model.__table__.primary_key.columns).all()]
        for model in (Ward, Bed, Admission)
    }


@pytest.mark.asyncio
async def test_actual_224_originals_five_complete_targets_queue_blob_history_feedback_super_trace(async_client, db_session, auth_headers, pipeline_case, tmp_path):
    case = pipeline_case
    roots = make_complete_series(db_session, case)
    assert sum(map(len, roots.values())) == 224
    before, headers = business_rows(db_session), auth_headers(case["director"].username)
    response = await async_client.post("/api/ai/operational-context", headers=headers, json={"feature_key": "bed_forecast", "input": run_request(case).input})
    assert response.status_code == 200, response.text
    inspection = response.json()["data"]
    context = inspection["context"]
    assert context["bed_series"]["snapshot"] == json.loads(case["series"].snapshot_json)
    assert context["bed_source"] == context["bed_series"]["public_source"] == json.loads(case["series"].projection_json)
    assert len(context["bed_source"]["census_observations"]) == len(context["bed_source"]["flow_observations"]) == 112
    assert len(case["series"].snapshot_json.encode()) > 65535 and len(case["series"].projection_json.encode()) > 65535
    detail = await async_client.get("/api/ai/bed-series/" + case["series"].series_id, headers=headers)
    options = await async_client.get("/api/ai/bed-sources/options", headers=headers, params={"department_id": case["department"].department_id})
    assert detail.status_code == options.status_code == 200
    assert detail.json()["data"]["eligible"] is True
    by_horizon = {}
    for horizon in (7, 14):
        horizon_inspection = inspection
        if horizon == 14:
            response = await async_client.post("/api/ai/operational-context", headers=headers, json={"feature_key": "bed_forecast", "input": run_request(case, horizon).input})
            assert response.status_code == 200, response.text
            horizon_inspection = response.json()["data"]
        run, wire = await successful(db_session, case, horizon=horizon)
        frozen = json.loads(run.input_json)
        assert "bed_source" not in frozen["payload"]["context"] and "bed_series" not in frozen["payload"]["context"]
        assert all(len(value.encode()) <= 65535 for value in (run.input_json, run.evidence_json, run.context_metadata_json, run.result_json))
        assert len(wire.requests) == 1
        packet = wire.requests[0]
        assert packet["schema_version"] == "11" and packet["store"] is False
        assert packet["input"] == {"context": {"bed_source": context["bed_source"]}, "horizon_days": horizon}
        assert packet["instructions"] == frozen["system_prompt"] + "\n\n" + frozen["task_prompt"]
        assert all(private not in encode_json(packet["input"]) for private in ("department_id", "ward_id", "created_by", NOTE, "SYNTH_PRIVATE_BED_QUESTION", "basis_note", case["person"].name))
        blob, pointer = db_session.get(AIBedRunResult, run.run_id), json.loads(run.result_json)
        assert pointer["schema_version"] == "bed_result_ref_v1" and pointer["content_hash"] == blob.content_hash
        assert blob.result_bytes == len(blob.result_json.encode()) > 65535
        assert db_session.query(AIAuditEvent).filter_by(target=run.run_id, action="run.bed_result.accept").count() == 1
        response = await async_client.get(f"/api/ai/runs/{run.run_id}", headers=headers)
        assert response.status_code == 200, response.text
        data = response.json()["data"]
        assert data["result"] == json.loads(blob.result_json)
        assert data["bed_findings"]["bed_source"] == context["bed_source"]
        assert data["bed_findings"]["bed_binding"] == horizon_inspection["context"]["bed_binding"]
        assert data["bed_findings"]["bed_binding"]["horizon_days"] == horizon
        native = data["result"]["bed_analysis"]
        assert native["horizon_days"] == horizon and [target["status"] for target in native["targets"]] == ["complete"] * 5
        assert all(target["backtest"]["forecast_pair_count"] == 28 * horizon for target in native["targets"])
        assert all(target["backtest"]["unique_target_dates"] == 27 + horizon for target in native["targets"])
        response = await async_client.post(f"/api/ai/runs/{run.run_id}/feedback", headers=headers, json={"outcome": "modified", "comment": "合成病区原件与五项目标人工复核，不构成实际运营验证"})
        assert response.status_code == 200, response.text
        trace = await async_client.get(f"/api/ai/admin/runs/{run.run_id}", headers=auth_headers(case["super"].username))
        assert trace.status_code == 200, trace.text
        assert trace.json()["data"]["frozen_request"]["payload"]["context"]["bed_source"] == context["bed_source"]
        by_horizon[str(horizon)] = {"inspection": horizon_inspection, "run_detail": data, "frozen_request": frozen, "super_trace": trace.json()["data"]}
    history = await async_client.get("/api/ai/runs", headers=headers, params={"feature_key": "bed_forecast", "ward_id": case["ward"].ward_id, "bed_series_id": case["series"].series_id})
    assert history.status_code == 200 and len(history.json()["data"]) == 2, history.text
    assert {item["run_id"] for item in history.json()["data"]} == {branch["run_detail"]["run_id"] for branch in by_horizon.values()}
    fixture = {"inspection": inspection, "series_detail": detail.json()["data"], "source_options": options.json()["data"], "by_horizon": by_horizon, "history": history.json()}
    (tmp_path / "actual-bed-pipeline-ui.json").write_text(json.dumps(fixture, ensure_ascii=False, indent=2), encoding="utf-8")
    assert before == business_rows(db_session)


def mutate(db, case, change):
    if change == "series_revoke":
        series.revoke_series(db, case["super"], case["series"].series_id, {"expected_revision": 2, "reason": "合成床位序列经复核停止后续使用"})
    elif change == "fact_revoke":
        source = case["census"]
        facts.revoke_source(db, case["super"], source.source_kind, source.source_record_id, {"expected_revision": 2, "reason": "合成原观察待重新核对"})
    elif change == "new_bed":
        db.add(Bed(ward_id=case["ward"].ward_id, bed_no="synthetic-later", status=0))
    elif change == "new_fact":
        original(db, case, "census")
    elif change == "role":
        case["director"].user_role = "doctor"
    elif change == "scope":
        db.query(Doctor).filter_by(user_id=case["director"].user_id).update({"department_id": case["foreign"].department_id})
    elif change == "body":
        case["series"].snapshot_json = "{}"
    elif change == "config":
        case["feature"].revision += 1
        case["provider"].revision += 1
        case["provider"].enabled = False
    else:
        raise AssertionError(change)
    db.commit()


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["queued", "inflight", "history"])
@pytest.mark.parametrize("change", ["series_revoke", "fact_revoke", "new_bed", "new_fact", "role", "scope", "body", "config"])
async def test_changed_members_governance_and_authorization_rechecked_at_each_phase(phase, change, async_client, db_session, auth_headers, pipeline_case):
    case = pipeline_case
    run = create_run(db_session, case["director"], run_request(case))
    if phase == "queued":
        mutate(db_session, case, change)
    wire = RealBedTransport(case["service"], (lambda: mutate(db_session, case, change)) if phase == "inflight" else None)
    await execute_claimed(*claim_next_run(db_session), transport=wire)
    db_session.expire_all()
    stored = db_session.get(AIRun, run.run_id)
    if phase != "history":
        assert stored.status == "failed" and stored.result_json == "{}", (stored.status, stored.error_code, stored.error_message)
        assert db_session.get(AIBedRunResult, run.run_id) is None
        assert len(wire.requests) == (0 if phase == "queued" else 1)
        return
    assert stored.status == "succeeded", (stored.error_code, stored.error_message)
    original_value = json.loads(db_session.get(AIBedRunResult, run.run_id).result_json)
    mutate(db_session, case, change)
    response = await async_client.get(f"/api/ai/runs/{run.run_id}", headers=auth_headers(case["director"].username))
    assert response.status_code == (403 if change in {"role", "scope"} else 200 if change == "config" else 409), response.text
    if change == "config":
        assert response.json()["data"]["result"] == original_value
    response = await async_client.get(f"/api/ai/runs/{run.run_id}", headers=auth_headers(case["super"].username))
    assert response.status_code == (409 if change == "body" else 200), response.text
    if change != "body":
        assert response.json()["data"]["result"] == original_value


@pytest.mark.asyncio
async def test_real_sql_audit_failure_rolls_back_complete_blob_pointer_and_success(db_session, pipeline_case, monkeypatch):
    case = pipeline_case
    run = create_run(db_session, case["director"], run_request(case))
    actual = governance.audit

    def broken_audit(db, actor_id, action, target, detail=None):
        if action == "run.bed_result.accept":
            db.add(AIAuditEvent(actor_id=actor_id, action=None, target=target, detail_json="{}"))
        else:
            actual(db, actor_id, action, target, detail)

    monkeypatch.setattr(governance, "audit", broken_audit)
    await execute_claimed(*claim_next_run(db_session), transport=RealBedTransport(case["service"]))
    db_session.expire_all()
    stored = db_session.get(AIRun, run.run_id)
    assert stored.status == "failed" and stored.error_code == "RESULT_STORAGE_ERROR" and stored.result_json == "{}"
    assert db_session.get(AIBedRunResult, run.run_id) is None
    assert db_session.query(AIAuditEvent).filter_by(target=run.run_id, action="run.bed_result.accept").count() == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("transition", ["cancelled", "lease_replaced"])
async def test_inflight_cancel_or_replaced_lease_never_accepts_complete_blob(transition, db_session, pipeline_case):
    case = pipeline_case
    run = create_run(db_session, case["director"], run_request(case))
    claim = claim_next_run(db_session)

    def change():
        db_session.expire_all()
        current = db_session.get(AIRun, run.run_id)
        if transition == "cancelled":
            current.status = "cancelled"
        else:
            current.lease_token = str(uuid.uuid4())
        db_session.commit()

    wire = RealBedTransport(case["service"], before=change)
    await execute_claimed(*claim, transport=wire)
    db_session.expire_all()
    stored = db_session.get(AIRun, run.run_id)
    assert stored.status == ("cancelled" if transition == "cancelled" else "running")
    assert stored.result_json == "{}" and db_session.get(AIBedRunResult, run.run_id) is None
    assert len(wire.requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["body", "missing_blob", "lease", "rehashed_false_proof", "rehashed_false_explanation", "pointer_whitespace", "pointer_duplicate"])
async def test_history_feedback_and_super_trace_reject_damaged_complete_results(change, async_client, db_session, auth_headers, pipeline_case):
    case = pipeline_case
    run, _ = await successful(db_session, case)
    blob = db_session.get(AIBedRunResult, run.run_id)
    if change == "body":
        blob.result_json = "{}"
    elif change == "missing_blob":
        db_session.delete(blob)
    elif change == "lease":
        blob.lease_token = str(uuid.uuid4())
    elif change == "pointer_whitespace":
        run.result_json = json.dumps(json.loads(run.result_json), ensure_ascii=False, indent=2)
    elif change == "pointer_duplicate":
        run.result_json = run.result_json[:-1] + ',"schema_version":"bed_result_ref_v1"}'
    else:
        value = json.loads(blob.result_json)
        if change == "rehashed_false_proof":
            value["bed_analysis"]["targets"][0]["last_day_value"] = 999
        else:
            value["summary"] = "伪造已经自动调床并发现确定未满足收治需求"
        blob.result_json, blob.content_hash, blob.result_bytes = bounded_result(value)
        pointer = json.loads(run.result_json)
        pointer.update(content_hash=blob.content_hash, result_bytes=blob.result_bytes)
        run.result_json = encode_json(pointer)
    db_session.commit()
    for username, path in ((case["director"].username, f"/api/ai/runs/{run.run_id}"), (case["super"].username, f"/api/ai/admin/runs/{run.run_id}")):
        response = await async_client.get(path, headers=auth_headers(username))
        assert response.status_code == 409, (change, path, response.status_code)
    response = await async_client.post(
        f"/api/ai/runs/{run.run_id}/feedback", headers=auth_headers(case["director"].username), json={"outcome": "accepted", "comment": "损坏原结果不能记为已经人工接受"}
    )
    assert response.status_code == 409, (change, response.status_code)
    assert db_session.query(AIFeedback).filter_by(run_id=run.run_id).count() == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["prompt", "context", "metadata", "evidence", "tools", "input_horizon", "bound_horizon", "selected_ref", "provider"])
async def test_queued_original_run_bindings_are_checked_before_any_http(change, db_session, pipeline_case):
    case = pipeline_case
    run = create_run(db_session, case["director"], run_request(case))
    frozen = json.loads(run.input_json)
    metadata = json.loads(run.context_metadata_json)
    if change == "prompt":
        frozen["task_prompt"] = "从未实际执行过的不同Prompt原文"
    elif change == "context":
        frozen["payload"]["context"]["missing_data"] = ["伪造所有原来源均完整"]
    elif change == "metadata":
        metadata["source_count"] = 999
    elif change == "evidence":
        run.evidence_json = encode_json([])
    elif change == "tools":
        frozen["payload"]["tools"] = {"triage_rules": {"emergency": True, "emergency_message": "未经冻结工具不得改固定床位解释"}}
    elif change == "input_horizon":
        frozen["payload"]["input"]["horizon_days"] = 14
    elif change == "provider":
        frozen["provider_snapshot"]["provider_id"] += 1
    else:
        if change == "bound_horizon":
            frozen["payload"]["context"]["bed_binding"]["horizon_days"] = 14
        else:
            frozen["payload"]["context"]["selected_sources"]["bed_series_id"] = str(uuid.uuid4())
        # Updating untrusted outer digests cannot make typed input/reference mismatches valid.
        run.context_digest = digest(frozen["payload"]["context"])
        metadata["context_digest"] = run.context_digest
        metadata["clinical_context_fingerprint"] = digest({key: value for key, value in frozen["payload"]["context"].items() if key != "snapshot_time"})
    run.input_json, run.context_metadata_json = encode_json(frozen), encode_json(metadata)
    db_session.commit()
    wire = RealBedTransport(case["service"])
    await execute_claimed(*claim_next_run(db_session), transport=wire)
    db_session.expire_all()
    stored = db_session.get(AIRun, run.run_id)
    assert stored.status == "failed" and stored.result_json == "{}" and not wire.requests, (change, stored.status, stored.error_code)
    assert db_session.get(AIBedRunResult, run.run_id) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["prompt", "context_digest", "metadata_snapshot", "selected_ref", "horizon"])
async def test_history_and_admin_trace_recheck_original_frozen_binding(change, async_client, db_session, auth_headers, pipeline_case):
    case = pipeline_case
    run, _ = await successful(db_session, case)
    frozen, metadata = json.loads(run.input_json), json.loads(run.context_metadata_json)
    if change == "prompt":
        frozen["task_prompt"] += "原任务未执行的后补Prompt"
    elif change == "context_digest":
        run.context_digest = "0" * 64
    elif change == "metadata_snapshot":
        metadata["snapshot_time"] = "2000-01-01T00:00:00.000000Z"
    elif change == "selected_ref":
        frozen["payload"]["context"]["selected_sources"]["bed_series_id"] = str(uuid.uuid4())
    else:
        frozen["payload"]["input"]["horizon_days"] = 14
    run.input_json, run.context_metadata_json = encode_json(frozen), encode_json(metadata)
    db_session.commit()
    for username, path in ((case["director"].username, f"/api/ai/runs/{run.run_id}"), (case["super"].username, f"/api/ai/admin/runs/{run.run_id}")):
        response = await async_client.get(path, headers=auth_headers(username))
        assert response.status_code == 409, (change, path, response.status_code)


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["queued", "history"])
@pytest.mark.parametrize("attack", ["evidence", "tools"])
async def test_mutually_rewritten_evidence_or_tools_must_match_exact_selected_series_packet(phase, attack, async_client, db_session, auth_headers, pipeline_case):
    case = pipeline_case
    if phase == "history":
        run, _ = await successful(db_session, case)
    else:
        run = create_run(db_session, case["director"], run_request(case))
    frozen = json.loads(run.input_json)
    if attack == "evidence":
        evidence = json.loads(run.evidence_json)
        evidence[0]["content"] = "SYNTH_UNFROZEN_PRIVATE_EVIDENCE_并非原系列绑定内容"
        frozen["payload"]["evidence"] = evidence
        run.evidence_json = encode_json(evidence)
    else:
        frozen["payload"]["tools"] = {"synthetic_unfrozen_capacity": 999}
        metadata = json.loads(run.context_metadata_json)
        metadata["tool_fingerprint"] = digest(frozen["payload"]["tools"])
        run.context_metadata_json = encode_json(metadata)
    run.input_json = encode_json(frozen)
    db_session.commit()
    if phase == "queued":
        wire = RealBedTransport(case["service"])
        await execute_claimed(*claim_next_run(db_session), transport=wire)
        db_session.expire_all()
        assert db_session.get(AIRun, run.run_id).status == "failed" and wire.requests == []
        assert db_session.get(AIBedRunResult, run.run_id) is None
    else:
        response = await async_client.get(f"/api/ai/runs/{run.run_id}", headers=auth_headers(case["director"].username))
        assert response.status_code == 409, response.status_code
        assert "SYNTH_UNFROZEN" not in response.text


def test_result_utf8_budget_is_exact_preserves_zero_false_null_and_never_truncates():
    value = {"original": "", "zero": 0, "false": False, "unknown": None}
    size = len(encode_json(value).encode())
    value["original"] = "中" * ((RESULT_BYTES - size) // 3) + "a" * ((RESULT_BYTES - size) % 3)
    serialized, content_hash, actual = bounded_result(value)
    assert actual == RESULT_BYTES and json.loads(serialized) == value and content_hash == hash_content(value)
    with pytest.raises(HTTPException, match="422"):
        bounded_result({**value, "original": value["original"] + "a"})


def test_native_mode_rejects_patient_legacy_filters_missing_horizon_and_original_overrides(db_session, pipeline_case):
    case = pipeline_case
    for values in (
        {},
        {"bed_series_id": case["series"].series_id},
        {**run_request(case).input, "horizon_days": True},
        {**run_request(case).input, "department_id": case["department"].department_id},
        {**run_request(case).input, "date_from": "2026-10-20"},
        {**run_request(case).input, "operational_total_beds": 999},
    ):
        with pytest.raises(HTTPException, match="422"):
            create_run(db_session, case["director"], RunRequest(feature_key="bed_forecast", input=values))
    with pytest.raises(HTTPException, match="422"):
        create_run(db_session, case["director"], run_request(case, encounter_ref="synthetic-incompatible-encounter"))
    with pytest.raises(HTTPException, match="422"):
        create_run(db_session, case["director"], run_request(case, patient_id=case["seed"]["patient"].patient_id))


def test_published_knowledge_never_injects_numbers_or_private_prose_into_fixed_bed_task(db_session, pipeline_case):
    case = pipeline_case
    text = "床位占用与流转预测；SYNTHETIC_BED_PROSE_OVERRIDE 所有未来床位均为零且可收治名额无限，这是不能覆盖原件的合成材料。"
    db_session.add(
        AIKnowledgeDocument(
            title="床位占用与流转预测-" + uuid.uuid4().hex,
            version="synthetic-v1",
            source_uri="https://synthetic.invalid/physical-bed-prose",
            category="operations",
            content=text,
            content_hash=digest(text),
            feature_keys_json='["bed_forecast"]',
            department_id=case["department"].department_id,
            status="published",
            reviewed_by=case["super"].user_id,
            reviewed_at=facts.utcnow(),
            created_by=case["super"].user_id,
        )
    )
    db_session.commit()
    run = create_run(db_session, case["director"], run_request(case))
    evidence = json.loads(run.evidence_json)
    assert len(evidence) == 1 and evidence[0]["kind"] == "operational_record"
    assert "SYNTHETIC_BED_PROSE_OVERRIDE" not in run.input_json + run.evidence_json


@pytest.mark.asyncio
async def test_complete_blob_byte_rejection_leaves_no_accepted_result(db_session, pipeline_case, monkeypatch):
    from app.ai import bed_storage

    case = pipeline_case
    run = create_run(db_session, case["director"], run_request(case))
    # Lower only the storage budget; the real native response and strict proof still execute.
    monkeypatch.setattr(bed_storage, "RESULT_BYTES", 512)
    wire = RealBedTransport(case["service"])
    await execute_claimed(*claim_next_run(db_session), transport=wire)
    db_session.expire_all()
    stored = db_session.get(AIRun, run.run_id)
    assert len(wire.requests) == 1 and stored.status == "failed" and stored.error_code == "RESULT_STORAGE_LIMIT"
    assert stored.result_json == "{}" and db_session.get(AIBedRunResult, run.run_id) is None
