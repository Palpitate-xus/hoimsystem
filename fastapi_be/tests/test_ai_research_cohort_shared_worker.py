"""Actual shared queue dispatch, concrete research claims and no inference bypass."""

import asyncio
import datetime as dt
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
from app.ai.models import AIAuditEvent, AIProvider, AIRun
from app.ai.research_cohort_artifact_models import AIResearchCohortRunArtifact, AIResearchCohortRunResult
from app.ai.research_cohort_contract import canonical_json
from app.ai.research_cohort_execution import ResearchClaim, recover_interrupted_research_runs
from app.ai.research_cohort_runtime import create_research_run, read_research_part
from app.ai.schemas import RunRequest
from tests.test_ai_research_cohort_execution import reply
from tests.test_ai_research_cohort_execution import runtime_case as runtime_case  # noqa: F401
from tests.test_ai_research_cohort_storage import artifact_foreign_keys as artifact_foreign_keys  # noqa: F401
from tests.test_ai_research_cohort_storage import configured as configured  # noqa: F401
from tests.test_ai_research_cohort_storage import research_case as research_case  # noqa: F401
from tests.test_ai_research_cohort_storage import storage_rows as storage_rows  # noqa: F401
from tests.test_ai_research_cohort_tasks_http import actual_task_routes as actual_task_routes  # noqa: F401


def select_case(case):
    return {"research_cohort_case_id": case["case_id"], "question": "共享worker明确原问题\ufeff\r\n🧪不调整条件。"}


def prepare(case, monkeypatch):
    monkeypatch.setattr(database, "SessionLocal", case["factory"])
    identifier = create_research_run(case["db"], case["actor"], select_case(case))
    claim = runtime.claim_next_run(case["db"])
    assert isinstance(claim, ResearchClaim) and claim.run_id == identifier
    return identifier, claim


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["chat", "responses"])
async def test_actual_main_create_shared_claim_execute_and_separate_full_result_preserve_specific_audit_pk(runtime_case, async_client, auth_headers, actual_task_routes, monkeypatch, tmp_path, kind):
    case, db = runtime_case, runtime_case["db"]
    monkeypatch.setattr(database, "SessionLocal", case["factory"])
    db.get(AIProvider, case["values"]["provider_id"]).kind = kind
    db.commit()
    body = {"feature_key": "research_cohort", "input": select_case(case)}
    response = await async_client.post("/api/ai/runs", json=body, headers=auth_headers(case["actor"].username))
    assert response.status_code == 200, response.text
    queued = response.json()["data"]
    assert queued["schema_version"] == "research_cohort_task_metadata_v1" and queued["status"] == "queued" and queued["split_artifacts"] is True
    claim = runtime.claim_next_run(db)
    assert isinstance(claim, ResearchClaim) and claim.run_id == queued["run_id"]
    calls = []

    def model(incoming):
        assert all(not session.in_transaction() for session in case["sessions"])
        assert not db.in_transaction()
        calls.append({"path": incoming.url.path, "raw_utf8": incoming.content.decode("utf-8")})
        return httpx.Response(200, json=reply(case["source"], kind))

    await runtime.execute_claimed(claim.run_id, claim.lease_token, research_claim_event_id=claim.claim_event_id, transport=httpx.MockTransport(model))
    result = read_research_part(db, case["actor"], claim.run_id, "result")
    assert result["deterministic_evaluation"]["counts"] == case["source"]["counts"] and len(calls) == 1
    artifact = db.get(AIResearchCohortRunArtifact, claim.run_id)
    dispatch = json.loads(db.get(AIAuditEvent, artifact.dispatch_event_id).detail_json)
    assert dispatch["claim_event_id"] == claim.claim_event_id
    accepted = db.get(AIResearchCohortRunResult, claim.run_id)
    assert len({artifact.created_audit_event_id, claim.claim_event_id, artifact.dispatch_event_id, artifact.usage_event_id, accepted.accept_audit_event_id}) == 5
    assert len(read_research_part(db, case["actor"], claim.run_id, "task")["input_json"].encode("utf-8")) <= 65535
    (tmp_path / ("actual-shared-research-worker-" + kind + ".json")).write_text(canonical_json({"queued": queued, "claim": claim.__dict__, "outgoing": calls, "result": result}), encoding="utf-8")


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", [None, True, 0, -1, "1", 987654321])
async def test_missing_or_wrong_claim_pk_never_mutates_first_run_or_calls_model(runtime_case, monkeypatch, bad):
    case, db = runtime_case, runtime_case["db"]
    identifier, claim = prepare(case, monkeypatch)
    before = tuple(db.query(AIRun.status, AIRun.lease_token, AIRun.finish_time, AIRun.error_code).filter_by(run_id=identifier).one())
    audits = db.query(AIAuditEvent).count()
    db.commit()
    calls = []
    with pytest.raises(HTTPException) as rejected:
        await runtime.execute_claimed(identifier, claim.lease_token, research_claim_event_id=bad, transport=httpx.MockTransport(lambda r: calls.append(r)))
    assert rejected.value.status_code == 409 and calls == []
    assert tuple(db.query(AIRun.status, AIRun.lease_token, AIRun.finish_time, AIRun.error_code).filter_by(run_id=identifier).one()) == before
    assert db.query(AIAuditEvent).count() == audits and db.get(AIResearchCohortRunArtifact, identifier).dispatch_event_id is None


@pytest.mark.asyncio
async def test_shared_duplicate_dispatch_cannot_replay_or_terminate_first_worker(runtime_case, monkeypatch):
    case = runtime_case
    identifier, claim = prepare(case, monkeypatch)
    entered, release = asyncio.Event(), asyncio.Event()
    calls = []

    async def model(incoming):
        calls.append(incoming)
        entered.set()
        await release.wait()
        return httpx.Response(200, json=reply(case["source"]))

    async def invoke():
        await runtime.execute_claimed(identifier, claim.lease_token, research_claim_event_id=claim.claim_event_id, transport=httpx.MockTransport(model))

    first = asyncio.create_task(invoke())
    await asyncio.wait_for(entered.wait(), 15)
    try:
        await invoke()
        with pytest.raises(HTTPException):
            await runtime.execute_claimed(identifier, claim.lease_token, research_claim_event_id=claim.claim_event_id + 999999)
    finally:
        release.set()
        await first
    assert len(calls) == 1 and case["db"].query(AIRun.status).filter_by(run_id=identifier).scalar() == "succeeded"


@pytest.mark.asyncio
async def test_actual_process_one_preserves_research_dataclass_and_recovers_in_fresh_session(runtime_case, monkeypatch):
    case, db = runtime_case, runtime_case["db"]
    monkeypatch.setattr(database, "SessionLocal", case["factory"])
    identifier = create_research_run(db, case["actor"], select_case(case))
    calls = []
    actual = worker.execute_claimed

    def model(incoming):
        assert all(not session.in_transaction() for session in case["sessions"])
        calls.append(incoming)
        return httpx.Response(200, json=reply(case["source"]))

    async def with_mock(run_id, lease, **kwargs):
        assert type(kwargs.get("research_claim_event_id")) is int
        await actual(run_id, lease, transport=httpx.MockTransport(model), **kwargs)

    monkeypatch.setattr(worker, "execute_claimed", with_mock)
    assert await worker.process_one()
    assert db.query(AIRun.status).filter_by(run_id=identifier).scalar() == "succeeded" and len(calls) == 1


def test_orphan_native_first_candidate_is_quarantined_without_text_and_next_valid_job_is_claimed(runtime_case, monkeypatch):
    case, db = runtime_case, runtime_case["db"]
    monkeypatch.setattr(database, "SessionLocal", case["factory"])
    orphan_id = case["values"]["run_id"]
    # The existing fixture is an actual committed Run with no Artifact. Erase
    # all JSON markers too: the feature's durable identity may not downgrade.
    db.execute(text("UPDATE hoimsystem_ai_run SET input_json='{}',evidence_json='[]',context_metadata_json='{}',create_time='2000-01-01 00:00:00' WHERE run_id=:id"), {"id": orphan_id})
    db.commit()
    identifier = create_research_run(db, case["actor"], select_case(case))
    outputs = []

    def capture(conn, cursor, sql, params, context, many):
        if sql.lstrip().lower().startswith("select"):
            outputs.extend(c[0] for c in cursor.description or ())

    event.listen(db.bind, "after_cursor_execute", capture)
    try:
        claim = runtime.claim_next_run(db)
    finally:
        event.remove(db.bind, "after_cursor_execute", capture)
    assert isinstance(claim, ResearchClaim) and claim.run_id == identifier
    assert not {"input_json", "evidence_json", "context_metadata_json", "source_json", "result_json"}.intersection(outputs)
    assert db.query(AIRun.status, AIRun.error_code).filter_by(run_id=orphan_id).one() == ("failed", "NATIVE_ARTIFACT_REQUIRED")


def test_other_generic_feature_keeps_original_two_tuple_claim_contract(runtime_case):
    db, case = runtime_case["db"], runtime_case
    identifier = str(uuid.uuid4())
    db.add(
        AIRun(
            run_id=identifier,
            feature_key="operations_qa",
            requested_by=case["actor_id"],
            status="queued",
            prompt_hash="1" * 64,
            context_digest="2" * 64,
            input_json="{}",
            result_json="{}",
            create_time=dt.datetime(2000, 1, 1),
        )
    )
    db.commit()
    claim = runtime.claim_next_run(db)
    assert type(claim) is tuple and len(claim) == 2 and claim[0] == identifier


def test_generic_expiry_excludes_real_research_artifact_even_erased_feature(runtime_case, monkeypatch):
    case, db = runtime_case, runtime_case["db"]
    identifier, claim = prepare(case, monkeypatch)
    db.execute(text("UPDATE hoimsystem_ai_run SET feature_key='operations_qa',start_time='2000-01-01 00:00:00' WHERE run_id=:id"), {"id": identifier})
    db.commit()
    runtime.expire_interrupted_runs(db)
    assert db.query(AIRun.status, AIRun.lease_token).filter_by(run_id=identifier).one() == ("running", claim.lease_token)


def test_research_recovery_refuses_reused_read_transaction(runtime_case):
    case = runtime_case
    case["db"].query(AIRun.run_id).first()
    with pytest.raises(HTTPException) as rejected:
        recover_interrupted_research_runs(case["db"])
    assert rejected.value.status_code == 409


@pytest.mark.parametrize("change", ["patient", "encounter", "preview", "foreign", "missing", "other_feature"])
def test_shared_request_cannot_infer_or_extend_case_from_patient_care_or_other_reference(change):
    value = {"feature_key": "research_cohort", "input": {"research_cohort_case_id": str(uuid.uuid4())}}
    if change == "patient":
        value["patient_id"] = 1
    elif change == "encounter":
        value["encounter_ref"] = "actual-care-still-not-research-authority"
    elif change == "preview":
        value["preview"] = "false"
    elif change == "foreign":
        value["input"]["satisfaction_case_id"] = str(uuid.uuid4())
    elif change == "missing":
        value["input"] = {"question": "不得猜项目或队列"}
    else:
        value["feature_key"] = "operations_qa"
    with pytest.raises((ValidationError, HTTPException)):
        RunRequest.model_validate(value)


@pytest.mark.asyncio
async def test_feature_only_orphan_main_get_trace_refuse_and_admin_directory_is_bodyless(runtime_case, async_client, auth_headers, actual_task_routes):
    case, db = runtime_case, runtime_case["db"]
    identifier = case["values"]["run_id"]
    db.execute(text("UPDATE hoimsystem_ai_run SET input_json='{}',evidence_json='[]',context_metadata_json='{}',result_json='{}' WHERE run_id=:id"), {"id": identifier})
    db.commit()
    columns = []

    def selected(conn, cursor, sql, params, context, many):
        if sql.lstrip().lower().startswith("select"):
            columns.extend(c[0] for c in cursor.description or ())

    event.listen(db.bind, "after_cursor_execute", selected)
    try:
        for path in ("/api/ai/runs/" + identifier, "/api/ai/admin/runs/" + identifier):
            response = await async_client.get(path, headers=auth_headers(case["identities"]["super_admin_user"].username))
            assert response.status_code == 409, response.text
        response = await async_client.get("/api/ai/admin/runs?feature_key=research_cohort", headers=auth_headers(case["identities"]["super_admin_user"].username))
        assert response.status_code == 200, response.text
    finally:
        event.remove(db.bind, "after_cursor_execute", selected)
    item = next(row for row in response.json()["data"] if row["run_id"] == identifier)
    assert item["schema_version"] == "research_cohort_incomplete_task_metadata_v1" and item["clinical_parts_available"] is False
    assert not {"input_json", "evidence_json", "context_metadata_json", "result_json", "source_json"}.intersection(columns)


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["authorization", "provider", "prompt", "role", "token_epoch"])
async def test_actual_shared_inflight_change_retains_paid_receipt_without_accepting_clinical_result(runtime_case, monkeypatch, change):
    from sqlalchemy import func

    from app.ai.models import AIFeatureConfig, AIPromptVersion
    from app.ai.research_cohort_cases import case_current
    from app.ai.research_cohort_receipts import read_usage_event, usage
    from app.ai.research_cohort_registry import review_registry_original
    from app.ai.research_cohort_runtime import describe_research_run
    from tests.test_ai_research_cohort_contract import BASIS

    case, db = runtime_case, runtime_case["db"]
    full = case_current(db, case["actor"], case["case_id"])
    authorization = full["snapshot"]["capture"]["patient_authorizations"][0]["identity"]["source_record_id"]
    db.commit()
    identifier, claim = prepare(case, monkeypatch)
    calls = []

    def model(incoming):
        assert all(not session.in_transaction() for session in case["sessions"])
        calls.append(incoming)
        if change == "authorization":
            review_registry_original(db, case["identities"]["super_admin_user"], "authorization", authorization, {"expected_revision": 2, "basis_note": BASIS}, revoke=True)
        elif change == "provider":
            row = db.get(AIProvider, case["values"]["provider_id"])
            row.enabled, row.revision = 0, row.revision + 1
            db.commit()
        elif change == "prompt":
            version = db.query(func.max(AIPromptVersion.version)).filter_by(feature_key="research_cohort").scalar() + 1
            prompt = AIPromptVersion(
                feature_key="research_cohort",
                version=version,
                task_prompt="共享worker运行时实际新增完整自定义研究Task版本。",
                change_note="Synthetic explicit current version",
                created_by=case["actor_id"],
            )
            db.add(prompt)
            db.flush()
            config = db.get(AIFeatureConfig, "research_cohort")
            config.active_prompt_id, config.revision = prompt.prompt_id, config.revision + 1
            db.commit()
        else:
            db.execute(
                text("UPDATE hoimsystem_users SET " + ("user_role='patient'" if change == "role" else "token_invalid_before='2030-01-01 00:00:00'") + " WHERE user_id=:id"), {"id": case["actor_id"]}
            )
            db.commit()
        return httpx.Response(200, json=reply(case["source"]))

    await runtime.execute_claimed(identifier, claim.lease_token, research_claim_event_id=claim.claim_event_id, transport=httpx.MockTransport(model))
    assert len(calls) == 1 and db.query(AIRun.status).filter_by(run_id=identifier).scalar() == "failed"
    assert db.query(AIResearchCohortRunResult).filter_by(run_id=identifier).count() == 0
    assert read_usage_event(db, identifier)["usage"] == usage(32, 6, True)
    super_id = case["identities"]["super_admin_user"].user_id
    metadata = describe_research_run(db, SimpleNamespace(user_id=super_id), identifier, audit_only=True)
    assert not metadata["clinical_parts_available"] and metadata["binding"] is None and metadata["usage"] == usage(32, 6, True)
    with pytest.raises(HTTPException):
        read_research_part(db, SimpleNamespace(user_id=super_id), identifier, "result", audit_only=True)
