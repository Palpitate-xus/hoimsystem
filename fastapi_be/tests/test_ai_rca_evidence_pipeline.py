"""Main/JWT -> shared claim/dispatch -> local synthetic provider -> SQL parts.

The provider is a controlled ASGI double. No hospital or remote model is used,
and successful literal hypotheses remain unreviewed causal proposals.
"""

import asyncio
import datetime as dt
import hashlib
import json

import pytest
from sqlalchemy import Select, event, inspect, text
from sqlalchemy.orm import Session

from app import database
from app.ai import rca_evidence_grants as grants
from app.ai import rca_evidence_receipts as receipts
from app.ai import rca_evidence_storage as storage
from app.ai import runtime
from app.ai.models import AIAuditEvent, AIFeedback, AIRun
from app.ai.rca_evidence_run_models import AIRcaEvidenceRunResult
from app.models import AdverseEventRca
from tests.test_ai_rca_evidence_configuration import configured
from tests.test_ai_rca_evidence_execution import provider_service
from tests.test_ai_rca_evidence_execution import synthetic_host as synthetic_host
from tests.test_ai_rca_evidence_grants import cas
from tests.test_ai_rca_evidence_grants import grant_case as grant_case


@pytest.fixture
def pipeline(grant_case, auth_headers):
    case, db = grant_case, grant_case["db"]
    stored, prepared, current = configured(case)
    # The configuration helper tests SQL staging separately. Remove only that
    # fixture's never-claimed seed task so this test claims the actual HTTP Run.
    identifier = inspect(stored.run).identity[0]
    db.execute(text("DELETE FROM hoimsystem_ai_rca_evidence_run_artifact WHERE run_id=:id"), {"id": identifier})
    db.execute(text("DELETE FROM hoimsystem_ai_run WHERE run_id=:id"), {"id": identifier})
    db.commit()
    return {"case": case, "db": db, "prepared": prepared, "current": current, "headers": auth_headers(case["actor"].username), "owner": inspect(case["actor"]).identity[0], "engine": db.get_bind()}


async def queue(client, setup):
    selection = {"rca_evidence_case_id": setup["prepared"].binding.case_id, "question": "\ufeff明确人工问题\r\n🧪"}
    preview = await client.post("/api/ai/rca-evidence/context", headers=setup["headers"], json={**selection, "preview": True})
    assert preview.status_code == 200, preview.text
    queued = await client.post("/api/ai/runs", headers=setup["headers"], json={"feature_key": "incident_rca", "input": selection, "preview": True})
    assert queued.status_code == 200, queued.text
    short = queued.json()["data"]
    assert short["feature_key"] == "incident_rca" and short["status"] == "queued" and short["usage_receipt"] is None
    assert "rca_evidence_findings" not in short and "result" not in short
    return short["run_id"], preview.json(), queued.json()


def claim_http_task(db, identifier):
    # Earlier cases deliberately leave revoked/obsolete queue rows. Poll the
    # real queue until each is settled known-zero; never abandon another lease.
    bound = db.query(AIRun).filter_by(status="queued").count() + 1
    for _ in range(bound):
        claim = runtime.claim_next_run(db)
        if claim is not None:
            assert claim[0] == identifier
            return claim
    raise AssertionError("The actual HTTP task never reached a shared claim")


def tracked_factory(engine, active):
    class TrackedSession(Session):
        def __init__(self):
            super().__init__(bind=engine, autoflush=False)
            active.append(self)

        def close(self):
            super().close()
            if self in active:
                active.remove(self)

    return TrackedSession


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["chat", "responses"])
@pytest.mark.parametrize("usage_shape", ["full", "missing", "partial"])
async def test_actual_main_jwt_shared_worker_split_results_trace_history_and_manual_feedback(async_client, pipeline, monkeypatch, kind, usage_shape, tmp_path):
    setup, db = pipeline, pipeline["db"]
    setup["current"].provider.kind = kind
    db.commit()
    identifier, preview, queued = await queue(async_client, setup)
    headers = setup["headers"]
    claim = claim_http_task(db, identifier)
    running = await async_client.get(f"/api/ai/runs/{identifier}", headers=headers)
    assert running.status_code == 200 and running.json()["data"]["status"] == "running", running.text
    db.close()
    active = []
    monkeypatch.setattr(database, "SessionLocal", tracked_factory(setup["engine"], active))

    def lawful_usage(body):
        if usage_shape == "missing":
            del body["usage"]
        elif usage_shape == "partial":
            body["usage"] = {"prompt_tokens" if kind == "chat" else "input_tokens": 11}
        return body

    transport, calls = provider_service(kind, lawful_usage, active)
    before = db.query(AdverseEventRca).count()
    db.close()
    await runtime.execute_claimed(*claim, transport=transport)
    assert len(calls) == 1 and active == []
    detail = await async_client.get(f"/api/ai/runs/{identifier}", headers=headers)
    assert detail.status_code == 200, detail.text
    short = detail.json()["data"]
    assert short["status"] == "succeeded" and short["result"] is None and short["result_reference"]["run_id"] == identifier
    assert short["usage_receipt"] == {
        "input_tokens": None if usage_shape == "missing" else 11,
        "output_tokens": 13 if usage_shape == "full" else None,
        "complete": usage_shape == "full",
        "model_call_attempted": True,
    }
    pieces = {}
    for name, path in short["parts"].items():
        response = await async_client.get(path, headers=headers)
        assert response.status_code == 200, (name, response.text)
        pieces[name] = response.json()
    assert pieces["result"]["data"]["rca_evidence_draft"]["coverage"] == "partial_unverified_hypotheses_no_causal_or_liability_claim"
    assert pieces["result"]["data"]["rca_evidence_draft"]["hypotheses"][0]["supporting_quotes"][0]["quote"] == pieces["source"]["data"]["items"][0]["text"]
    assert pieces["case"]["data"]["execution_current"] is False
    trace = await async_client.get(f"/api/ai/admin/runs/{identifier}", headers=headers)
    assert trace.status_code == 200, trace.text
    original = trace.json()["data"]
    for field, anchor in (("input_json", "input_hash"), ("evidence_json", "evidence_hash"), ("context_metadata_json", "metadata_hash")):
        assert hashlib.sha256(original["raw_frozen_json"][field].encode()).hexdigest() == short["rca_evidence_artifact"][anchor]
    assert len({row["event_id"] for row in original["phase_audits"].values()}) == 5
    histories = {}
    for route in ("/api/ai/runs", "/api/ai/admin/runs"):
        response = await async_client.get(route, headers=headers, params={"feature_key": "incident_rca", "rca_evidence_case_id": short["rca_evidence_case_id"]})
        assert response.status_code == 200, response.text
        assert [row["run_id"] for row in response.json()["data"]] == [identifier]
        histories[route] = response.json()
    feedback = await async_client.post(f"/api/ai/runs/{identifier}/feedback", headers=headers, json={"outcome": "accepted", "comment": "仅工程逐字复核，不确认因果归责"})
    assert feedback.status_code == 200 and feedback.json()["data"]["automatic_legacy_write"] is False, feedback.text
    assert db.query(AdverseEventRca).count() == before and db.query(AIFeedback).filter_by(run_id=identifier).count() == 1
    assert db.query(AIAuditEvent).filter_by(target=identifier, action="rca_run.feedback").count() == 1
    packet = {
        "scope": "actual Main JWT/SQLite/shared worker/local controlled ASGI; not remote inference or clinical RCA validation",
        "preview": preview,
        "queued": queued,
        "running": running.json(),
        "detail": detail.json(),
        "trace": trace.json(),
        "parts": pieces,
        "history": histories,
        "feedback": feedback.json(),
        "outbound": calls[0][1],
    }
    (tmp_path / f"actual-rca-evidence-pipeline-{kind}-{usage_shape}.json").write_text(json.dumps(packet, ensure_ascii=False, indent=2), encoding="utf-8")


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["", "/rca-evidence/source", "/rca-evidence/case", "/rca-evidence/result", "/rca-evidence/receipt"])
async def test_actual_main_original_purpose_loss_is_zero_task_text_before_each_ordinary_read(async_client, pipeline, path):
    setup, db = pipeline, pipeline["db"]
    identifier, _, _ = await queue(async_client, setup)
    grant = grants.grant_detail(db, setup["case"]["actor"], setup["prepared"].binding.event_grant.grant_id)
    grants.revoke_grant(db, setup["case"]["actor"], grant.identity.grant_id, cas(grant))
    db.commit()
    columns = []

    def observe(state):
        if state.is_select and isinstance(state.statement, Select):
            columns.extend(column.key for column in state.statement.selected_columns)

    event.listen(Session, "do_orm_execute", observe)
    try:
        response = await async_client.get(f"/api/ai/runs/{identifier}" + path, headers=setup["headers"])
        assert response.status_code == 403, response.text
    finally:
        event.remove(Session, "do_orm_execute", observe)
    assert not {*storage.RUN_TEXT, *storage.ART_TEXT}.intersection(columns)


@pytest.mark.asyncio
async def test_actual_main_cancel_after_purpose_loss_is_short_known_zero_not_body_authority(async_client, pipeline):
    setup, db = pipeline, pipeline["db"]
    identifier, _, _ = await queue(async_client, setup)
    grant = grants.grant_detail(db, setup["case"]["actor"], setup["prepared"].binding.event_grant.grant_id)
    grants.revoke_grant(db, setup["case"]["actor"], grant.identity.grant_id, cas(grant))
    db.commit()
    response = await async_client.post(f"/api/ai/runs/{identifier}/cancel", headers=setup["headers"])
    assert response.status_code == 200, response.text
    ack = response.json()["data"]
    assert ack["status"] == "cancelled" and ack["usage_event_id"] is not None and ack["receipt_pending"] is False
    assert "rca_evidence_findings" not in ack and "parts" not in ack
    receipt = receipts.read_receipt(db, receipts.technical_header(db, identifier))
    assert receipt.usage.input_tokens == receipt.usage.output_tokens == 0 and receipt.usage.model_call_attempted is False
    assert (await async_client.get(f"/api/ai/runs/{identifier}", headers=setup["headers"])).status_code == 403


@pytest.mark.asyncio
async def test_actual_main_inflight_cancel_settles_original_paid_partial_and_never_accepts_body(async_client, pipeline, monkeypatch):
    setup, db = pipeline, pipeline["db"]
    identifier, _, _ = await queue(async_client, setup)
    claim = claim_http_task(db, identifier)
    db.close()
    active, entered, release = [], asyncio.Event(), asyncio.Event()
    monkeypatch.setattr(database, "SessionLocal", tracked_factory(setup["engine"], active))

    async def held_reply(body):
        entered.set()
        await release.wait()
        body["usage"] = {"prompt_tokens": 11}
        return body

    transport, calls = provider_service("chat", held_reply, active)
    worker = asyncio.create_task(runtime.execute_claimed(*claim, transport=transport))
    try:
        await asyncio.wait_for(entered.wait(), 3)
        response = await async_client.post(f"/api/ai/runs/{identifier}/cancel", headers=setup["headers"])
        assert response.status_code == 200 and response.json()["data"]["receipt_pending"] is True, response.text
    finally:
        release.set()
        await worker
    detail = await async_client.get(f"/api/ai/runs/{identifier}", headers=setup["headers"])
    assert detail.status_code == 200, detail.text
    value = detail.json()["data"]
    assert len(calls) == 1 and value["status"] == "cancelled" and value["result_reference"] is None
    assert value["usage_receipt"] == {"input_tokens": 11, "output_tokens": None, "complete": False, "model_call_attempted": True}
    assert db.query(AIRcaEvidenceRunResult).filter_by(run_id=identifier).count() == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mutation",
    [
        {"patient_id": 1},
        {"encounter_ref": "actual-extra"},
        {"input": {"rca_evidence_case_id": None}},
        {"input": {"rca_evidence_case_id": "x"}},
        {"input": {"text": "private caller supplied raw text"}},
    ],
)
async def test_actual_main_queue_rejects_foreign_scope_or_caller_source_before_any_task_insert(async_client, pipeline, mutation):
    setup, db = pipeline, pipeline["db"]
    body = {"feature_key": "incident_rca", "input": {"rca_evidence_case_id": setup["prepared"].binding.case_id}, "preview": True, **mutation}
    before = db.query(AIRun).count()
    response = await async_client.post("/api/ai/runs", headers=setup["headers"], json=body)
    assert response.status_code == 422, response.text
    assert db.query(AIRun).count() == before


@pytest.mark.asyncio
async def test_actual_admin_empty_later_page_keeps_the_current_metadata_total(async_client, pipeline):
    setup = pipeline
    identifier, _, _ = await queue(async_client, setup)
    response = await async_client.get("/api/ai/admin/runs", headers=setup["headers"], params={"feature_key": "incident_rca", "rca_evidence_case_id": setup["prepared"].binding.case_id, "page": 100})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["data"] == [] and body["total"] == 1 and body["page"] == 100
    assert identifier


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/api/ai/context", "/api/ai/patients", "/api/ai/encounters", "/api/ai/service-options"])
async def test_actual_main_native_rca_cannot_use_generic_patient_or_service_reads(async_client, pipeline, path):
    response = await async_client.get(
        path, headers=pipeline["headers"], params={"feature_key": "incident_rca", **({"patient_id": pipeline["case"]["patient_id"]} if path in {"/api/ai/context", "/api/ai/encounters"} else {})}
    )
    assert response.status_code == 422, response.text


@pytest.mark.asyncio
async def test_actual_feedback_audit_rejection_rolls_back_manual_row_and_keeps_existing_result(async_client, pipeline, monkeypatch):
    setup, db = pipeline, pipeline["db"]
    identifier, _, _ = await queue(async_client, setup)
    claim = claim_http_task(db, identifier)
    db.close()
    active = []
    monkeypatch.setattr(database, "SessionLocal", tracked_factory(setup["engine"], active))
    transport, _ = provider_service("chat", None, active)
    await runtime.execute_claimed(*claim, transport=transport)
    db.execute(
        text("CREATE TRIGGER reject_rca_feedback_audit BEFORE INSERT ON hoimsystem_ai_audit_event WHEN NEW.action='rca_run.feedback' BEGIN SELECT RAISE(ABORT,'synthetic actual audit rejection'); END")
    )
    db.commit()
    try:
        response = await async_client.post(f"/api/ai/runs/{identifier}/feedback", headers=setup["headers"], json={"outcome": "accepted", "comment": "must fully roll back"})
        assert response.status_code == 409, response.text
        assert db.query(AIFeedback).filter_by(run_id=identifier).count() == 0
        assert db.query(AIAuditEvent).filter_by(target=identifier, action="rca_run.feedback").count() == 0
        assert db.query(AIRun.status).filter_by(run_id=identifier).scalar() == "succeeded"
        assert db.query(AIRcaEvidenceRunResult).filter_by(run_id=identifier).count() == 1
    finally:
        db.execute(text("DROP TRIGGER reject_rca_feedback_audit"))
        db.commit()


@pytest.mark.asyncio
async def test_actual_case_revocation_blocks_ordinary_reads_but_explicit_frozen_trace_keeps_distinct_current_governance(async_client, pipeline):
    setup = pipeline
    identifier, _, _ = await queue(async_client, setup)
    case_id = setup["prepared"].binding.case_id
    base = f"/api/ai/admin/rca-evidence/cases/{case_id}"
    current = await async_client.get(base, headers=setup["headers"])
    assert current.status_code == 200, current.text
    row = current.json()["data"]
    body = {
        "expected_revision": row["governance"]["revision"],
        "expected_content_hash": row["content_hash"],
        "expected_governance_hash": row["governance_hash"],
        "basis_note": "明确撤回，不伪造Task执行资格",
    }
    revoked = await async_client.post(base + "/revoke", headers=setup["headers"], json=body)
    assert revoked.status_code == 200, revoked.text
    assert (await async_client.get(f"/api/ai/runs/{identifier}", headers=setup["headers"])).status_code == 409
    trace = await async_client.get(f"/api/ai/admin/runs/{identifier}", headers=setup["headers"])
    assert trace.status_code == 200, trace.text
    proof = trace.json()["data"]
    assert proof["current_case_governance"]["status"] == "revoked" and proof["current_case_governance"]["revision"] == 3
    assert proof["frozen_request"]["source_case_governance"]["status"] == "published" and proof["frozen_request"]["source_case_governance"]["revision"] == 2
    assert proof["current_case_governance_hash"] != proof["rca_evidence_findings"]["rca_evidence_binding"]["case_governance_hash"]
    assert proof["current_source_execution_qualification"] == "not_evaluated_or_regranted_by_frozen_audit"
    for path in proof["parts"].values():
        response = await async_client.get(path, headers=setup["headers"])
        assert response.status_code == 200, response.text
    queued = await async_client.post("/api/ai/runs", headers=setup["headers"], json={"feature_key": "incident_rca", "input": {"rca_evidence_case_id": case_id}, "preview": True})
    assert queued.status_code == 409


@pytest.mark.asyncio
async def test_actual_native_history_keeps_latest_first_and_rejects_other_scope_filters(async_client, pipeline, monkeypatch):
    setup, identifiers = pipeline, []
    start = grants.utcnow()
    for index in range(3):
        monkeypatch.setattr(grants, "utcnow", lambda index=index: start + dt.timedelta(seconds=index))
        identifier, _, _ = await queue(async_client, setup)
        identifiers.append(identifier)
    params = {"feature_key": "incident_rca", "rca_evidence_case_id": setup["prepared"].binding.case_id}
    for route in ("/api/ai/runs", "/api/ai/admin/runs"):
        current = await async_client.get(route, headers=setup["headers"], params=params)
        assert current.status_code == 200, current.text
        assert [row["run_id"] for row in current.json()["data"]] == list(reversed(identifiers))
        assert current.json()["total"] == 3
        invalid = await async_client.get(route, headers=setup["headers"], params={**params, "patient_id": setup["case"]["patient_id"]})
        assert invalid.status_code == 422, invalid.text
