"""Current SQL creation, source ownership and complete task/Prompt governance."""

import datetime
import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import delete, event, func, update

from app.ai import charge_reconciliation_runtime as runtime
from app.ai import charge_reconciliation_sources as sources
from app.ai.charge_reconciliation_receipts import load_terminal
from app.ai.charge_reconciliation_run_models import AIChargeRunArtifact
from app.ai.charge_reconciliation_storage import load_snapshot
from app.ai.models import AIAuditEvent, AIFeatureConfig, AIPromptVersion, AIProvider, AIRun
from app.ai.schemas import RunRequest
from app.models import InpatientCharge, User
from tests.test_ai_charge_reconciliation_sources import charge_case as _charge_case
from tests.test_ai_charge_reconciliation_sources import published

charge_case = _charge_case


def configured(case, *, actor=None, preview=True, kind="chat", custom_prompt=False):
    db, actor = case["db"], actor or case["super_admin_user"]
    value = published(case)
    provider = AIProvider(
        name="synthetic-charge-runtime-" + uuid.uuid4().hex,
        kind=kind,
        api_base="http://127.0.0.1:11434/v1",
        model="synthetic-text",
        enabled=1,
        allows_patient_data=1,
        timeout_seconds=5,
        max_output_tokens=4096,
        temperature=0,
        created_by=case["super_admin_user"].user_id,
    )
    db.add(provider)
    db.flush()
    config = db.get(AIFeatureConfig, "charge_reconciliation")
    if config is None:
        config = AIFeatureConfig(feature_key="charge_reconciliation", updated_by=case["super_admin_user"].user_id)
        db.add(config)
    config.provider_id = provider.provider_id
    config.enabled, config.validation_status = 1, "validated"
    config.allowed_roles_json = '["admin","super_admin","cashier","director"]'
    config.daily_limit, config.active_prompt_id, config.revision = 10000, None, 1
    if custom_prompt:
        prompt = AIPromptVersion(
            feature_key="charge_reconciliation",
            version=case["db"].query(AIPromptVersion).count() + 1,
            task_prompt="合成收费人工核实Prompt🙂\r\n请逐字引用原记录，保留不完整覆盖声明。",
            change_note="合成工程验证版本",
            created_by=actor.user_id,
        )
        db.add(prompt)
        db.flush()
        config.active_prompt_id = prompt.prompt_id
    db.commit()
    req = RunRequest(
        feature_key="charge_reconciliation",
        patient_id=value["patient_id"],
        encounter_ref=value["admission_id"],
        input={"charge_case_id": value["case_snapshot_id"], "question": "请核对原记录🙂。"},
        preview=preview,
    )
    return actor, req, value, provider, config


@pytest.mark.parametrize("kind", ["chat", "responses"])
@pytest.mark.parametrize("custom_prompt", [False, True])
def test_create_keeps_actual_original_task_prompt_scope_and_nullable_pending_usage(charge_case, kind, custom_prompt):
    case, db = charge_case, charge_case["db"]
    actor, req, value, provider, config = configured(case, kind=kind, custom_prompt=custom_prompt)
    run = runtime.create_charge_run(db, actor, req)
    snapshot, binding, _, _ = load_snapshot(db, run)
    assert run.status == "queued" and run.patient_id == value["patient_id"] and run.encounter_ref == value["admission_id"]
    assert binding["case_snapshot_id"] == value["case_snapshot_id"]
    assert snapshot["payload"]["context"].keys() == {
        "scope",
        "source_domain",
        "department_ids",
        "selected_sources",
        "charge_binding",
        "scope_note",
        "missing_data",
        "truncated_sources",
        "snapshot_time",
    }
    assert len(run.input_json.encode("utf-8")) < 65535 and '"charge_source"' not in run.input_json
    if custom_prompt:
        prompt = db.get(AIPromptVersion, config.active_prompt_id)
        assert run.prompt_version == prompt.version and snapshot["task_prompt"] == prompt.task_prompt
    result, receipt = load_terminal(db, run)
    assert result is None and receipt["input_tokens"] is receipt["output_tokens"] is receipt["model_call_attempted"] is None
    spec, actual_provider, expanded, epoch = runtime.recheck(db, run)
    assert actual_provider.provider_id == provider.provider_id and spec.key == run.feature_key
    assert expanded["payload"]["context"]["charge_source"] == value["public_source"]
    assert epoch == runtime.actor_epoch(actor)
    event_row = db.query(AIAuditEvent).filter_by(action="run.create", target=run.run_id).one()
    assert event_row.actor_id == actor.user_id


@pytest.mark.parametrize("mutation", ["missing_case", "foreign_source", "extra_input", "wrong_patient", "wrong_admission", "wrong_feature"])
def test_create_rejects_wrong_scope_and_mixed_inputs_without_run_or_artifact(charge_case, mutation):
    case, db = charge_case, charge_case["db"]
    actor, req, _, _, _ = configured(case)
    if mutation == "missing_case":
        req.input = {}
    elif mutation == "foreign_source":
        req.input = {"charge_case_id": str(uuid.uuid4())}
    elif mutation == "extra_input":
        req.input["coding_case_id"] = str(uuid.uuid4())
    elif mutation == "wrong_patient":
        req.patient_id += 10000
    elif mutation == "wrong_admission":
        req.encounter_ref = str(uuid.uuid4())
    else:
        req.feature_key = "record_draft"
    before = db.query(AIRun).count(), db.query(AIChargeRunArtifact).count()
    with pytest.raises(HTTPException) as caught:
        runtime.create_charge_run(db, actor, req)
    assert caught.value.status_code in {403, 404, 409, 422}
    assert (db.query(AIRun).count(), db.query(AIChargeRunArtifact).count()) == before


def test_ordinary_admin_can_create_real_current_source_but_preview_is_super_only(charge_case):
    case, db = charge_case, charge_case["db"]
    actor, req, _, _, _ = configured(case, actor=case["admin_user"], preview=False)
    run = runtime.create_charge_run(db, actor, req)
    runtime.authorize_charge_run(db, actor, run)
    req.preview = True
    with pytest.raises(HTTPException) as caught:
        runtime.create_charge_run(db, actor, req)
    assert caught.value.status_code == 403


@pytest.mark.parametrize("mutation", ["provider_revision", "provider_permission", "feature_revision", "prompt_body", "prompt_pointer", "source", "role", "token_epoch", "queue_age"])
def test_recheck_rejects_actual_changed_current_configuration_source_or_actor(charge_case, mutation):
    case, db = charge_case, charge_case["db"]
    actor, req, _, provider, config = configured(case, custom_prompt=True)
    run = runtime.create_charge_run(db, actor, req)
    if mutation == "provider_revision":
        db.execute(update(AIProvider).where(AIProvider.provider_id == provider.provider_id).values(revision=2))
    elif mutation == "provider_permission":
        db.execute(update(AIProvider).where(AIProvider.provider_id == provider.provider_id).values(allows_patient_data=0))
    elif mutation == "feature_revision":
        db.execute(update(AIFeatureConfig).where(AIFeatureConfig.feature_key == req.feature_key).values(revision=2))
    elif mutation == "prompt_body":
        db.execute(update(AIPromptVersion).where(AIPromptVersion.prompt_id == config.active_prompt_id).values(task_prompt="合成改变后的独立Prompt，不得使用原任务。"))
    elif mutation == "prompt_pointer":
        db.execute(update(AIFeatureConfig).where(AIFeatureConfig.feature_key == req.feature_key).values(active_prompt_id=None))
    elif mutation == "source":
        db.execute(update(InpatientCharge).where(InpatientCharge.charge_id == case["charges"][-1].charge_id).values(status=99))
    elif mutation == "role":
        db.execute(update(User).where(User.user_id == actor.user_id).values(user_role="doctor"))
    elif mutation == "token_epoch":
        db.execute(update(User).where(User.user_id == actor.user_id).values(token_invalid_before=sources.utcnow()))
    else:
        db.execute(update(AIRun).where(AIRun.run_id == run.run_id).values(create_time=sources.utcnow() - datetime.timedelta(days=1)))
    db.commit()
    with pytest.raises((HTTPException, runtime.AIExecutionError)):
        runtime.recheck(db, run)
    db.rollback()


def test_daily_limit_uses_current_locking_count_and_refuses_the_next_whole_task(charge_case):
    case, db = charge_case, charge_case["db"]
    actor, req, _, _, config = configured(case)
    start = datetime.datetime.combine(sources.utcnow().date(), datetime.time.min)
    used = db.query(func.count(AIRun.run_id)).filter(AIRun.feature_key == req.feature_key, AIRun.requested_by == actor.user_id, AIRun.create_time >= start).scalar()
    config.daily_limit = used + 1
    db.commit()
    runtime.create_charge_run(db, actor, req)
    before = db.query(AIRun).count()
    with pytest.raises(HTTPException) as caught:
        runtime.create_charge_run(db, actor, req)
    assert caught.value.status_code == 429 and db.query(AIRun).count() == before


@pytest.mark.parametrize("field,value", [("preview", 0), ("input_tokens", 99), ("error_code", "ALTERED")])
def test_actual_creation_audit_post_insert_fault_rolls_back_task_and_artifact(charge_case, field, value):
    case, db = charge_case, charge_case["db"]
    actor, req, _, _, _ = configured(case)
    before = db.query(AIRun).count(), db.query(AIChargeRunArtifact).count()
    connection, fired = db.connection(), []

    def fault(conn, cursor, statement, parameters, execution_context, many):
        if not fired and statement.lstrip().upper().startswith("INSERT INTO HOIMSYSTEM_AI_AUDIT_EVENT"):
            fired.append(True)
            target = conn.execute(AIRun.__table__.select().order_by(AIRun.create_time.desc(), AIRun.run_id.desc())).first()
            # The exact run target is retained in this INSERT's staged event.
            staged = [row for row in db.new if isinstance(row, AIAuditEvent) and row.action == "run.create"]
            assert len(staged) == 1 and target is not None
            conn.execute(update(AIRun).where(AIRun.run_id == staged[0].target).values({field: value}))

    event.listen(connection, "after_cursor_execute", fault)
    try:
        with pytest.raises(HTTPException) as caught:
            runtime.create_charge_run(db, actor, req)
        assert caught.value.status_code == 409 and fired == [True]
    finally:
        event.remove(connection, "after_cursor_execute", fault)
        db.rollback()
    assert (db.query(AIRun).count(), db.query(AIChargeRunArtifact).count()) == before


@pytest.mark.parametrize("model_name", ["config", "provider", "prompt"])
def test_deleted_current_configuration_cannot_reuse_a_retained_identity_cache(charge_case, model_name):
    case, db = charge_case, charge_case["db"]
    actor, req, _, provider, config = configured(case, custom_prompt=True)
    run = runtime.create_charge_run(db, actor, req)
    prompt = db.get(AIPromptVersion, config.active_prompt_id)
    model, identifier = {"config": (AIFeatureConfig, config.feature_key), "provider": (AIProvider, provider.provider_id), "prompt": (AIPromptVersion, prompt.prompt_id)}[model_name]
    row = db.get(model, identifier)
    primary = tuple(model.__table__.primary_key.columns)[0]
    # Actual SQL removes the row without expiring the already-retained ORM object.
    # Missing foreign parents are fault injection here, not a MySQL FK claim.
    db.connection().execute(delete(model).where(primary == identifier))
    assert db.get(model, identifier) is row
    with pytest.raises(HTTPException) as caught:
        runtime.recheck(db, run)
    assert caught.value.status_code == 409
    db.rollback()
