"""Real synthetic Source→Profile→Run→split result and current read boundaries."""

# ruff: noqa: F811 -- actual same-case ORM fixtures are intentionally registered.

import copy
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import event, text

from app.ai import infection_cluster_contract as c
from app.ai import infection_cluster_registry as registry
from app.ai import infection_cluster_scenario as scenario
from app.ai import infection_cluster_statistics as engine
from app.ai import infection_cluster_task_context as context
from app.ai import infection_cluster_task_contract as t
from app.ai import infection_cluster_task_runtime as runtime
from app.ai import infection_cluster_task_storage as storage
from app.ai.infection_cluster_models import AIInfectionPurposeGrant
from app.ai.infection_cluster_run_models import AIInfectionRunArtifact as Artifact
from app.ai.models import AIAuditEvent, AIRun
from tests.test_ai_infection_cluster_profiles import configuration_request, create, profile_case, publish, save  # noqa: F401
from tests.test_ai_infection_cluster_sources import cas


@pytest.fixture
def task_case(profile_case):
    case = profile_case
    db = case["db"]
    full = scenario.create_scenario(db, case["author"], case["create"])
    db.commit()
    full = scenario.review_scenario(
        db, case["reviewer"], full.scenario_id, {**cas(full), "decision": "publish", "privacy_review": "confirmed", "faithfulness_review": "confirmed", "parameters_review": "confirmed"}
    )
    db.commit()
    case["scenario"] = full
    profile = publish(case, create(case, validated=True))
    req = configuration_request(profile.profile_id)
    req.update(enabled=True, validation_status="validated", validation_note="仅合成工程状态机依据，不声称实际本地临床验证。")
    save(case, req)
    case["task_request"] = dict(infection_cluster_scenario_id=full.scenario_id, preview=False)
    yield case
    db.rollback()
    ids = [row[0] for row in db.query(Artifact.run_id).all()]
    db.query(Artifact).delete(synchronize_session=False)
    if ids:
        db.query(AIRun).filter(AIRun.run_id.in_(ids)).delete(synchronize_session=False)
    db.query(AIAuditEvent).filter(AIAuditEvent.action.like("run.infection_cluster.%")).delete(synchronize_session=False)
    db.commit()


def stage(case):
    out = runtime.create_run(case["db"], case["author"], case["task_request"])
    case["db"].commit()
    return out["run_id"]


def finish(case, rid):
    lease, source, frozen = runtime.claim(case["db"], rid)
    case["db"].commit()
    result = engine.evaluate(source)
    runtime.terminal(case["db"], rid, lease, status="succeeded", result=result, attempted=True, completed=True, milliseconds=0)
    case["db"].commit()
    return result


def test_actual_published_source_without_external_transfer_grant_executes_local_and_keeps_three_exact_audits(task_case):
    case, db = task_case, task_case["db"]
    assert db.query(AIInfectionPurposeGrant).filter_by(purpose="external_model_transfer").count() == 0
    rid = stage(case)
    artifact = db.get(Artifact, rid)
    assert artifact.result_json is artifact.usage_event_id is artifact.accept_event_id is None
    assert db.get(AIRun, rid).result_json == "{}"
    source = storage.authorize(db, case["author"], rid)[4]
    expected = finish(case, rid)
    actual = storage.load_result(db, case["author"], rid)
    assert actual == expected and actual.family_size == 2
    artifact, run = db.get(Artifact, rid), db.get(AIRun, rid)
    assert len({artifact.create_event_id, artifact.usage_event_id, artifact.accept_event_id}) == 3
    receipt = storage.usage(db, artifact, run)
    assert receipt.input_tokens == receipt.output_tokens == 0 and receipt.model_call_attempted is False
    assert receipt.calculation_attempted is receipt.calculation_completed is True
    assert run.provider_id is None and run.prompt_version == 0
    assert artifact.accepted_at.microsecond == 123456 and run.create_time.microsecond == run.finish_time.microsecond == 0
    assert c.digest(source) == artifact.source_hash and artifact.source_bytes == len(c.utf8(artifact.source_json))
    assert "mapping_key" not in artifact.source_json and "description" not in artifact.source_json
    assert t.ResultPointer.model_validate_json(run.result_json).result_hash == c.digest(actual)


def task_text_queries(queries):
    # SQL hash/octet expressions are deliberately technical, not a recovered
    # Source or Task TEXT selection. They return only scalar SHA/length values.
    return [
        sql
        for sql in queries
        if sql.lstrip().upper().startswith("SELECT")
        and "hoim_infection_sha256(" not in sql
        and "SHA2(CAST(" not in sql
        and ("hoimsystem_ai_run.input_json" in sql or "hoimsystem_ai_infection_run_artifact.source_json" in sql or "hoimsystem_ai_infection_run_artifact.result_json" in sql)
    ]


@pytest.mark.parametrize("identity", ["author", "reviewer"])
def test_actual_patient_purpose_withdrawal_has_zero_task_body_even_super_and_keeps_only_technical_zero_usage(task_case, identity):
    case, db = task_case, task_case["db"]
    rid = stage(case)
    finish(case, rid)
    grant = case["grants"][0 if identity == "author" else 1]
    registry.revoke_record(db, case["reviewer"], "grant", grant.record_id, cas(grant))
    db.commit()
    queries = []

    def capture(conn, cursor, sql, params, ctx, many):
        queries.append(sql)

    event.listen(db.get_bind(), "before_cursor_execute", capture)
    try:
        with pytest.raises(HTTPException) as exc:
            storage.load_result(db, case[identity], rid)
        assert exc.value.status_code == 403
        artifact, run = storage.verify_technical_run(db, rid)
        receipt = storage.usage(db, artifact, SimpleNamespace(**{key: value for key, value in run.items() if key not in t.RAW_FIELDS}))
    finally:
        event.remove(db.get_bind(), "before_cursor_execute", capture)
    assert task_text_queries(queries) == []
    assert receipt.model_call_attempted is False and receipt.input_tokens == 0


@pytest.mark.parametrize("field", ["input_json", "evidence_json", "context_metadata_json"])
def test_canonical_self_rehash_of_run_json_cannot_bypass_immutable_exact_create_audit(task_case, field):
    case, db = task_case, task_case["db"]
    rid = stage(case)
    changed = "{}" if field != "evidence_json" else "[{}]"
    db.execute(text("UPDATE hoimsystem_ai_run SET " + field + "=:v WHERE run_id=:id"), {"v": changed, "id": rid})
    anchor = {"input_json": "input_hash", "evidence_json": "evidence_hash", "context_metadata_json": "metadata_hash"}[field]
    db.execute(text("UPDATE hoimsystem_ai_infection_run_artifact SET " + anchor + "=:hash WHERE run_id=:id"), {"hash": c.text_digest(changed), "id": rid})
    db.commit()
    with pytest.raises(HTTPException) as exc:
        storage.authorize(db, case["author"], rid)
    assert exc.value.status_code == 409


def test_actual_anchor_classifies_erased_feature_all_json_markers_and_expired_orm_without_task_text(task_case):
    case, db = task_case, task_case["db"]
    rid = stage(case)
    db.execute(text("UPDATE hoimsystem_ai_run SET feature_key='generic',input_json='{}',evidence_json='[]',context_metadata_json='{}',result_json='{}' WHERE run_id=:id"), {"id": rid})
    db.commit()
    run = db.get(AIRun, rid)
    db.expire(run)
    queries = []

    def capture(conn, cursor, sql, params, ctx, many):
        queries.append(sql)

    event.listen(db.get_bind(), "before_cursor_execute", capture)
    try:
        assert storage.is_infection_run(db, run) and storage.is_infection_run(db, rid)
        assert not storage.is_infection_run(db, "old-generic-non-uuid")
    finally:
        event.remove(db.get_bind(), "before_cursor_execute", capture)
    assert task_text_queries(queries) == []
    with pytest.raises(HTTPException):
        storage.verify_technical_run(db, rid)


def test_own_unflushed_native_anchor_never_falls_through_generic_classifier(task_case):
    db = task_case["db"]
    rid = "00000000-0000-0000-0000-000000009999"
    db.add(Artifact(run_id=rid, scenario_id=task_case["scenario"].scenario_id, requested_by=task_case["author"].user_id))
    assert storage.is_infection_run(db, rid)
    db.rollback()


def test_requester_id_only_worker_cannot_accept_changed_epoch_even_when_both_roles_allowed(task_case):
    case, db = task_case, task_case["db"]
    prepared = context.prepare(db, case["author"], case["scenario"].scenario_id)
    frozen = context.freeze("00000000-0000-0000-0000-000000009999", prepared, preview=False)
    # Independent pure comparison proves the worker must compare the original
    # epoch in addition to an otherwise still-valid current local scope.
    changed = list(prepared)
    changed[0] = SimpleNamespace(user_id=case["author"].user_id, user_role="admin", token_invalid_before=None)
    with pytest.raises(HTTPException):
        context.compare_current(frozen, changed, execution=True)
    assert context.compare_current(frozen, changed, execution=False) == prepared[2]


def test_changed_mathematical_result_rehash_cannot_substitute_actual_full_exact_analysis(task_case):
    case, db = task_case, task_case["db"]
    rid = stage(case)
    result = finish(case, rid).model_dump(mode="json")
    # An algebraically valid exact fraction but wrong for the actual fixed table.
    altered = copy.deepcopy(result)
    altered["candidates"][0]["exact_p"] = dict(numerator="1", denominator="2")
    assert not engine.verify_analysis_binding(storage.authorize(db, case["author"], rid)[4], altered)
    artifact = db.get(Artifact, rid)
    raw, sha = c.canonical(altered), c.digest(altered)
    db.query(Artifact).filter_by(run_id=rid).update(dict(result_json=raw, result_hash=sha, result_bytes=len(c.utf8(raw))), synchronize_session=False)
    run = db.get(AIRun, rid)
    pointer = t.ResultPointer.model_validate_json(run.result_json).model_copy(update=dict(result_hash=sha, result_bytes=len(c.utf8(raw))))
    run.result_json = t.task_json(pointer)
    db.commit()
    assert artifact.result_hash != c.digest(result) or db.get(Artifact, rid).result_hash != c.digest(result)
    with pytest.raises((HTTPException, ValueError)):
        storage.load_result(db, case["author"], rid)
