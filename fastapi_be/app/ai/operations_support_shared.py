"""Opaque native routing and quarantine; neither grants document authority."""

from types import SimpleNamespace

from fastapi import HTTPException
from sqlalchemy import and_, case, exists, func, or_, select, update
from sqlalchemy.orm import load_only

from app.ai import operations_support_attempts as attempts
from app.ai import operations_support_registry as registry
from app.ai import operations_support_storage as storage
from app.ai.models import AIRun
from app.ai.native_task_routing import _domains, locate_native_task, opaque_run_id
from app.ai.operations_support_configuration import FEATURE
from app.ai.operations_support_run_models import AIOperationsRunArtifact
from app.ai.operations_support_write_guard import current_actor


def create_shared_run(db, user, request):
    from app.ai.operations_support_runtime import create_operations_run
    from app.ai.operations_support_task_contract import OperationsTaskSelection

    if request.feature_key != FEATURE or request.patient_id is not None or request.encounter_ref is not None or type(request.preview) is not bool:
        raise HTTPException(422, "运维任务只接受明确受审资料集和目标，不接受患者、就诊或其它功能范围")
    registry.typed(OperationsTaskSelection, request.input)
    identifier = create_operations_run(db, user, request.input, preview=request.preview)
    return db.query(AIRun).options(load_only(AIRun.run_id, AIRun.feature_key)).filter_by(run_id=identifier).one()


def marker_expression(*, mysql):
    predicates = [AIRun.feature_key == FEATURE]
    for column, schema in ((AIRun.input_json, "operations_support_task_ref_v1"), (AIRun.context_metadata_json, "operations_support_task_metadata_v1")):
        valid = case((func.json_valid(column) == 1, column), else_="{}")
        value = func.json_extract(valid, "$.schema_version")
        predicates.append((func.json_unquote(value) if mysql else value) == schema)
        if column is AIRun.input_json:
            predicates.append(func.json_contains_path(valid, "one", "$.operations_case_id") == 1 if mysql else func.json_type(valid, "$.operations_case_id").is_not(None))
    return func.coalesce(or_(*predicates), False)


def is_operations_task(db, value):
    identity = locate_native_task(db, value)
    if identity is not None:
        return identity.domain == FEATURE
    identifier = opaque_run_id(value)
    if db is None or type(identifier) is not str:
        return False
    mysql = db.get_bind().dialect.name in {"mysql", "mariadb"}
    statement = select(marker_expression(mysql=mysql).label("operations_native_marker")).where(AIRun.run_id == identifier)
    with db.no_autoflush:
        if mysql:
            with getattr(db.get_bind(), "engine", db.get_bind()).connect().execution_options(isolation_level="READ COMMITTED") as connection:
                found = connection.execute(statement).one_or_none()
        else:
            found = db.execute(statement).one_or_none()
    return found is not None and found[0] is True


def is_located_operations_task(db, value):
    """Own opaque three-column precheck only; grants no part/stop authority.

    Negative classification must not query another domain before its original
    Gate. Current short RC and actual same-transaction SQL are both required;
    no process-local hint can stand in for a persisted Artifact.
    """
    identifier = opaque_run_id(value)
    if db is None or type(identifier) is not str:
        return False
    statement = select(AIOperationsRunArtifact.run_id, AIOperationsRunArtifact.case_id, AIOperationsRunArtifact.requested_by).where(AIOperationsRunArtifact.run_id == identifier)
    with db.no_autoflush:
        found = set()
        bind = db.get_bind()
        if bind.dialect.name in {"mysql", "mariadb"}:
            with getattr(bind, "engine", bind).connect().execution_options(isolation_level="READ COMMITTED") as connection:
                found.update(tuple(row) for row in connection.execute(statement))
        found.update(tuple(row) for row in db.execute(statement))
    if len(found) > 1:
        raise HTTPException(409, "运维实际同事务与当前分件身份不一致，未猜测域或读取正文")
    return bool(found)


def guard_operations_task(db, user, identifier):
    identity = locate_native_task(db, identifier)
    if identity is None or identity.domain != FEATURE:
        raise HTTPException(409, "运维任务缺少完整持久分件，未降级读取或执行")
    return storage.load_artifact(db, user, identifier)


def queue_candidate_condition(db):
    """Skip impossible headers at SQL selection, preserving later valid jobs."""
    from app.dependencies import VALID_USER_ROLES
    from app.models import User

    model = AIOperationsRunArtifact
    native = exists().where(model.run_id == AIRun.run_id).correlate(AIRun)
    known_actor = exists().where(User.user_id == AIRun.requested_by, User.user_role.in_(sorted(VALID_USER_ROLES))).correlate(AIRun)
    unclaimed = exists().where(model.run_id == AIRun.run_id, model.requested_by == AIRun.requested_by, model.claim_event_id.is_(None), model.dispatch_event_id.is_(None), model.usage_event_id.is_(None)).correlate(AIRun)
    clean_header = and_(
        AIRun.feature_key == FEATURE,
        AIRun.lease_token.is_(None),
        AIRun.start_time.is_(None),
        AIRun.finish_time.is_(None),
        AIRun.latency_ms.is_(None),
        AIRun.error_code.is_(None),
        AIRun.error_message.is_(None),
        AIRun.input_tokens == 0,
        AIRun.output_tokens == 0,
        AIRun.result_json == "{}",
    )
    others = or_(*(exists().where(other.run_id == AIRun.run_id).correlate(AIRun) for domain, other, _ in _domains() if domain != FEATURE))
    return or_(and_(native, known_actor, unclaimed, clean_header), and_(~native, or_(others, ~marker_expression(mysql=db.get_bind().dialect.name in {"mysql", "mariadb"}), known_actor)))


def quarantine_orphan(db, identifier):
    """Trusted queued maintenance, bodyless and without a billing assertion."""
    from app.dependencies import VALID_USER_ROLES

    try:
        attempts.lock_gate(db)
        with db.no_autoflush:
            owner = db.query(AIRun.requested_by).filter_by(run_id=identifier, status="queued").scalar()
        if owner is None or locate_native_task(db, identifier) is not None:
            db.rollback()
            return False
        actor = current_actor(db, SimpleNamespace(user_id=owner), allowed_roles=VALID_USER_ROLES)
        actor_identity = (actor.user_id, actor.user_role, actor.token_invalid_before)
        before = storage.run_header(db, identifier)
        if before is None or before["status"] != "queued" or before["requested_by"] != actor.user_id:
            db.rollback()
            return False
        when = registry.utcnow()
        values = {"status": "failed", "error_code": "NATIVE_ARTIFACT_REQUIRED", "error_message": "原运维任务缺少完整持久分件；只保留技术状态，未读取正文或调用模型", "finish_time": when.replace(microsecond=0)}
        changed = db.execute(
            update(AIRun)
            .where(
                AIRun.run_id == identifier,
                AIRun.status == "queued",
                AIRun.requested_by == actor.user_id,
                marker_expression(mysql=db.get_bind().dialect.name in {"mysql", "mariadb"}),
                *(~exists().where(model.run_id == AIRun.run_id) for _, model, _ in _domains()),
            )
            .values(**values)
            .execution_options(synchronize_session=False)
        )
        if changed.rowcount != 1:
            db.rollback()
            return False
        detail = {"schema_version": "operations_support_orphan_quarantine_v1", "run_id": identifier, "reason": "missing_durable_operations_artifact", "recorded_at": registry.utc_text(when)}
        event_id = registry.audit_event(db, actor.user_id, "operations.task.quarantine", identifier, detail, when)
        registry.verify_event(db, event_id, actor.user_id, "operations.task.quarantine", identifier, detail, when)
        current = current_actor(db, SimpleNamespace(user_id=owner), allowed_roles=VALID_USER_ROLES)
        if (current.user_id, current.user_role, current.token_invalid_before) != actor_identity or storage.run_header(db, identifier) != {**before, **values} or locate_native_task(db, identifier) is not None:
            raise HTTPException(409, "运维不完整任务隔离后实际账户、技术头或域锚改变")
        db.commit()
        return True
    except Exception:
        db.rollback()
        raise
