"""Shared75 actual Main/JWT and queue, with synthetic SQL and MockTransport only."""

import datetime as dt
import hashlib
import json
import uuid
from types import SimpleNamespace

import httpx
import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import event, text

from app import database
from app.ai import runtime, worker
from app.ai.deidentification_dispatch import DeidentificationClaim
from app.ai.deidentification_models import AIDeidentificationExportRelease, AIDeidentificationReview
from app.ai.deidentification_run_models import AIDeidentificationRunResult, AIDeidentificationRunSource
from app.ai.deidentification_shared import is_deidentification_task
from app.ai.deidentification_spans import canonical, digest, text_digest
from app.ai.models import AIAuditEvent, AIRun
from app.ai.native_task_routing import locate_native_task
from app.ai.research_cohort_registry import review_registry_original
from app.ai.schemas import RunRequest
from tests.test_ai_deidentification_runtime import model, queue
from tests.test_ai_deidentification_storage import task_case as task_case  # noqa: F401
from tests.test_ai_research_cohort_contract import BASIS
from tests.test_ai_research_cohort_sources import research_case as research_case  # noqa: F401


def request(case):
    return {"feature_key": "deidentification", "input": {**case["input"], "question": "\ufeff共享75原问题\r\n🧪不能自动替换或导出。"}}


def watched_sessions(monkeypatch, case):
    factory, sessions = database.SessionLocal, []

    def tracked():
        session = factory()
        sessions.append(session)
        return session

    monkeypatch.setattr(database, "SessionLocal", tracked)
    return sessions


def physical_before(db):
    from app.models import MedicalRecord

    # Exact recorded row tuples, including the actual SQL PK; no guessed alias.
    return [tuple(row) for row in db.execute(MedicalRecord.__table__.select().order_by(*MedicalRecord.__table__.primary_key.columns)).all()]


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["chat", "responses"])
async def test_actual_main_create_shared_claim_execute_canonical_parts_trace_feedback_never_apply_or_export(task_case, async_client, auth_headers, monkeypatch, tmp_path, kind):
    case, db = task_case, task_case["db"]
    case["provider"].kind = kind
    db.commit()
    before = physical_before(db)
    header = auth_headers(case["actor"].username)
    super_header = auth_headers(case["users"]["super_admin_user"].username)
    packets = []
    response = await async_client.post("/api/ai/runs", headers=header, json=request(case))
    assert response.status_code == 200, response.text
    queued = response.json()["data"]
    assert queued["status"] == "queued" and queued["split_artifacts"] is True
    assert queued["source"] is queued["result"] is queued["raw_frozen_json"] is None
    assert "原问题" not in response.text and queued["usage_receipt"]["model_call_attempted"] is None
    claimed = runtime.claim_next_run(db)
    assert isinstance(claimed, DeidentificationClaim) and claimed.run_id == queued["run_id"]
    db.rollback()
    sessions = watched_sessions(monkeypatch, case)
    mock_case = {**case, "provider": SimpleNamespace(kind=kind)}
    await runtime.execute_claimed(
        claimed.run_id, claimed.lease_token, deidentification_claim_event_id=claimed.claim_event_id, transport=model(mock_case, packets=packets, sessions=sessions, partial=kind == "responses")
    )
    assert len(packets) == 1 and all(not session.in_transaction() for session in sessions)
    final = await async_client.get("/api/ai/runs/" + claimed.run_id, headers=header)
    assert final.status_code == 200, final.text
    metadata = final.json()["data"]
    assert metadata["status"] == "succeeded" and metadata["parts_wire"] == "canonical_json_body_no_envelope"
    assert metadata["usage_receipt"]["output_tokens"] == (None if kind == "responses" else 13)
    parts, wire = {}, {}
    for part in ("task", "source", "scope", "result"):
        read = await async_client.get(f"/api/ai/deidentification/tasks/{claimed.run_id}/parts/{part}", headers=header)
        assert read.status_code == 200, read.text
        assert len(read.content) <= 8 * 1024 * 1024
        parts[part], wire[part] = read.json(), read.content.decode("utf-8")
        assert read.content == canonical(parts[part]).encode("utf-8")
        assert hashlib.sha256(read.content).hexdigest() == metadata["part_hashes"][part]
    frame = parts["task"]
    assert json.loads(frame["raw_frozen_json"]["input_json"])["input"] == request(case)["input"]
    for field, expected in zip(("input_json", "evidence_json", "context_metadata_json"), ("input_hash", "evidence_hash", "metadata_hash"), strict=True):
        assert text_digest(frame["raw_frozen_json"][field]) == frame["raw_hashes"][expected]
    rebuilt = {
        "schema_version": "deidentification_task_source_v1",
        "source_snapshot": parts["scope"],
        "public_source": parts["source"],
        "publication": frame["publication"],
        "prompt": frame["frozen_prompt"],
        "provider": frame["provider"],
        "validation": frame["validation"],
        "execution": frame["execution"],
    }
    assert digest(rebuilt) == metadata["opaque_hashes"]["source_hash"]
    assert parts["result"]["draft"]["candidates"][0]["quote"] == "张三" and parts["result"]["anonymity_guaranteed"] is False
    trace = await async_client.get("/api/ai/admin/runs/" + claimed.run_id, headers=super_header)
    assert trace.status_code == 200, trace.text
    assert trace.json()["data"]["schema_version"] == "deidentification_split_trace_v1"
    assert set(trace.json()["data"]["parts"]) == {"task", "source", "scope", "result"}
    feedback = await async_client.post("/api/ai/runs/" + claimed.run_id + "/feedback", headers=header, json={"outcome": "accepted", "comment": "仅复核模型候选，未创建人工Review或导出Release"})
    assert feedback.status_code == 200, feedback.text
    assert physical_before(db) == before and db.query(AIDeidentificationReview).count() == db.query(AIDeidentificationExportRelease).count() == 0
    source, result = db.get(AIDeidentificationRunSource, claimed.run_id), db.get(AIDeidentificationRunResult, claimed.run_id)
    assert len({source.create_event_id, result.claim_event_id, result.dispatch_event_id, result.usage_event_id, result.accept_event_id}) == 5
    (tmp_path / ("actual-deidentification-shared-" + kind + ".json")).write_text(
        canonical({"queued": queued, "metadata": metadata, "parts": parts, "parts_original_utf8": wire, "trace": trace.json(), "claim": claimed._asdict(), "outbound": packets}), encoding="utf-8"
    )


@pytest.mark.asyncio
async def test_actual_process_one_forwards_specific75_claim_and_closes_all_sessions_before_http(task_case, monkeypatch):
    case, db = task_case, task_case["db"]
    identifier = queue(case)
    sessions = watched_sessions(monkeypatch, case)
    actual, packets = worker.execute_claimed, []
    mock_case = {**case, "provider": SimpleNamespace(kind="chat")}

    async def with_mock(run_id, lease, **kwargs):
        assert type(kwargs.get("deidentification_claim_event_id")) is int and "research_claim_event_id" not in kwargs
        await actual(run_id, lease, transport=model(mock_case, packets=packets, sessions=sessions), **kwargs)

    monkeypatch.setattr(worker, "execute_claimed", with_mock)
    assert await worker.process_one() is True
    assert db.query(AIRun.status).filter_by(run_id=identifier).scalar() == "succeeded" and len(packets) == 1


@pytest.mark.parametrize(
    "body",
    [
        {"feature_key": "deidentification", "input": {}},
        {"feature_key": "deidentification", "patient_id": 1, "input": {"deidentification_case_id": str(uuid.uuid4())}},
        {"feature_key": "deidentification", "preview": 1, "input": {"deidentification_case_id": str(uuid.uuid4())}},
        {"feature_key": "patient_summary", "input": {"deidentification_case_id": None}},
        {"feature_key": "research_cohort", "input": {"deidentification_case_id": str(uuid.uuid4())}},
    ],
)
def test_pydantic_boundary_rejects_incomplete_foreign_or_coerced75_input_as_validation_error(body):
    with pytest.raises(ValidationError):
        RunRequest.model_validate(body)


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", [None, True, 0, -1, "1", 987654321])
async def test_shared_missing_wrong_claim_pk_never_changes_run_or_calls_model(task_case, bad):
    case, db = task_case, task_case["db"]
    identifier = queue(case)
    claimed = runtime.claim_next_run(db)
    assert isinstance(claimed, DeidentificationClaim)
    before = tuple(db.query(AIRun.status, AIRun.lease_token, AIRun.finish_time, AIRun.error_code).filter_by(run_id=identifier).one())
    count = db.query(AIAuditEvent).count()
    db.commit()
    calls = []
    with pytest.raises(HTTPException) as rejected:
        await runtime.execute_claimed(identifier, claimed.lease_token, deidentification_claim_event_id=bad, transport=httpx.MockTransport(lambda r: calls.append(r)))
    assert rejected.value.status_code == 409 and calls == []
    assert tuple(db.query(AIRun.status, AIRun.lease_token, AIRun.finish_time, AIRun.error_code).filter_by(run_id=identifier).one()) == before
    assert db.query(AIAuditEvent).count() == count


@pytest.mark.asyncio
async def test_current_purpose_withdrawal_denies_all_shared_clinical_routes_even_super_before_text_but_keeps_paid_metadata(task_case, async_client, auth_headers):
    case, db = task_case, task_case["db"]
    identifier = queue(case)
    claimed = runtime.claim_next_run(db)
    db.rollback()
    await runtime.execute_claimed(identifier, claimed.lease_token, deidentification_claim_event_id=claimed.claim_event_id, transport=model(case))
    review_registry_original(db, case["users"]["super_admin_user"], "authorization", case["values"][3]["source_record_id"], {"expected_revision": 2, "basis_note": BASIS}, revoke=True)
    selected = []

    def columns(conn, cursor, sql, args, context, many):
        if sql.lstrip().upper().startswith("SELECT") and cursor.description:
            selected.extend(column[0] for column in cursor.description)

    event.listen(db.bind, "after_cursor_execute", columns)
    try:
        for user in (case["actor"], case["users"]["super_admin_user"]):
            header = auth_headers(user.username)
            for path in (
                f"/api/ai/runs/{identifier}",
                *(f"/api/ai/deidentification/tasks/{identifier}/parts/{part}?audit_only=" + ("true" if user.user_role == "super_admin" else "false") for part in ("task", "source", "scope", "result")),
            ):
                response = await async_client.get(path, headers=header)
                assert response.status_code == 403, response.text
        trace = await async_client.get(f"/api/ai/admin/runs/{identifier}", headers=auth_headers(case["users"]["super_admin_user"].username))
        assert trace.status_code == 403, trace.text
    finally:
        event.remove(db.bind, "after_cursor_execute", columns)
    forbidden = ("input_json", "evidence_json", "context_metadata_json", "source_json", "result_json")
    assert not any(column == name or column.endswith("_" + name) for column in selected for name in forbidden)
    directory = await async_client.get("/api/ai/admin/runs?feature_key=deidentification", headers=auth_headers(case["users"]["super_admin_user"].username))
    assert directory.status_code == 200, directory.text
    record = next(row for row in directory.json()["data"] if row["run_id"] == identifier)
    assert record["clinical_parts_available"] is False and record["binding"] is record["part_hashes"] is None
    assert record["usage_receipt"]["input_tokens"] == 11 and record["source"] is record["result"] is record["raw_frozen_json"] is None


@pytest.mark.asyncio
async def test_orphan_feature75_and_erased_real_artifact_never_fall_back_or_starve_next_real_job(task_case):
    case, db = task_case, task_case["db"]
    valid = queue(case)
    original = db.get(AIRun, valid)
    orphan = AIRun(
        run_id=str(uuid.uuid4()),
        feature_key="deidentification",
        requested_by=original.requested_by,
        provider_id=original.provider_id,
        prompt_hash="1" * 64,
        context_digest="2" * 64,
        input_json="{}",
        evidence_json="[]",
        result_json="{}",
        context_metadata_json="{}",
        create_time=original.create_time - dt.timedelta(seconds=1),
    )
    db.add(orphan)
    db.commit()
    assert is_deidentification_task(db, orphan) is True
    claim = runtime.claim_next_run(db)
    assert isinstance(claim, DeidentificationClaim) and claim.run_id == valid
    db.expire_all()
    assert db.get(AIRun, orphan.run_id).status == "failed" and db.get(AIRun, orphan.run_id).error_code == "NATIVE_ARTIFACT_REQUIRED"
    db.rollback()
    db.execute(text("UPDATE hoimsystem_ai_run SET feature_key='erased',input_json='{}',evidence_json='[]',context_metadata_json='{}',result_json='{}' WHERE run_id=:id"), {"id": valid})
    db.commit()
    assert locate_native_task(db, valid).domain == "deidentification" and is_deidentification_task(db, valid)
    calls = []
    with pytest.raises(HTTPException):
        await runtime.execute_claimed(valid, claim.lease_token, deidentification_claim_event_id=claim.claim_event_id, transport=httpx.MockTransport(lambda r: calls.append(r)))
    assert calls == [] and db.query(AIRun.status).filter_by(run_id=valid).scalar() == "running"
