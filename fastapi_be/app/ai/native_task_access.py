"""Order all mixed native gates before current authority and private Task TEXT."""


def _guard_charge_identity(db, user, identity):
    """The opaque durable case FK grants no access to its private task body."""
    import json

    from fastapi import HTTPException
    from sqlalchemy import inspect

    from app.ai import charge_reconciliation_sources as sources
    from app.ai.catalog import FEATURE_BY_KEY
    from app.ai.models import AIFeatureConfig, AIRun

    # Save the authenticated epoch before populate_existing refreshes the same
    # ORM object. An expired internal actor has no loaded request epoch.
    loaded = inspect(user).dict
    epoch = {key: loaded[key] for key in ("user_role", "token_invalid_before") if key in loaded}
    actor = sources.current_actor(db, user)
    if any(getattr(actor, key) != value for key, value in epoch.items()):
        raise HTTPException(403, "本次账目任务的原角色或登录授权已改变")
    if actor.user_role != "super_admin" and identity.requested_by != actor.user_id:
        raise HTTPException(403, "不能访问其他用户的 AI 任务")
    if actor.user_role != "super_admin":
        with db.no_autoflush:
            config = db.query(AIFeatureConfig).filter_by(feature_key="charge_reconciliation").populate_existing().with_for_update(read=True).one_or_none()
        spec = FEATURE_BY_KEY["charge_reconciliation"]
        try:
            roles = json.loads(config.allowed_roles_json) if config is not None else list(spec.default_roles)
            if not isinstance(roles, list) or any(type(role) is not str for role in roles):
                raise ValueError("Invalid current charge feature roles")
        except (ValueError, TypeError) as exc:
            raise HTTPException(409, "账目任务当前适用角色配置无法核对") from exc
        if actor.user_role not in roles or actor.user_role not in spec.default_roles:
            raise HTTPException(403, "当前账户已无该账目任务的适用权限")
    # Ordinary reads require the complete current published case. Super reads
    # retain the existing frozen-audit policy and never grant new execution.
    frozen = actor.user_role == "super_admin"
    sources.case_current(db, actor, identity.source_id, audit_only=frozen, execution=not frozen)
    with db.no_autoflush:
        header = db.query(AIRun.run_id, AIRun.feature_key, AIRun.requested_by).filter_by(run_id=identity.run_id).populate_existing().with_for_update(read=True).one_or_none()
    if header is None or header.feature_key != "charge_reconciliation" or header.requested_by != identity.requested_by:
        raise HTTPException(409, "账目任务的持久来源、功能或原申请账户不一致")


def lock_directory_gates(db):
    """Billing -> Satisfaction -> Inventory -> Research -> Operations, before User/Run."""
    from app.ai.charge_reconciliation_write_guard import lock_charge_gate
    from app.ai.inventory_write_guard import lock_inventory_gate
    from app.ai.satisfaction_write_guard import lock_satisfaction_gate

    lock_charge_gate(db)
    lock_satisfaction_gate(db)
    lock_inventory_gate(db)
    from app.ai.research_cohort_write_guard import lock_research_gate

    lock_research_gate(db)
    from app.ai.operations_support_models import AIOperationsWriteGate

    # A mixed legacy directory creates no new gate. Actual operations readers
    # and writers separately require the gate seeded by their migration. If it
    # is present, always take it in the common order before any User/Run lock.
    with db.no_autoflush:
        db.query(AIOperationsWriteGate).filter_by(gate_id=1).populate_existing().with_for_update().one_or_none()


def guard_private_task_read(db, user, run_id):
    from app.ai.document_change_runtime import guard_change_run_id
    from app.ai.drug_label_runtime import guard_drug_label_run_id
    from app.ai.satisfaction_storage import guard_satisfaction_run_id

    # Locators identify a native domain; its complete authority proof follows
    # before loading Task TEXT. Gates remain in the same mixed-directory order.
    lock_directory_gates(db)
    from app.ai.native_task_routing import locate_native_task

    identity = locate_native_task(db, run_id)  # Reject contradictory cross-domain anchors.
    if identity is not None:
        # An actual immutable FK selects exactly one complete domain guard.
        # Only a task with no Artifact needs the orphan JSON-marker probes.
        if identity.domain == "deidentification":
            from app.ai.deidentification_shared import guard_task

            guard_task(db, user, run_id)
            return
        if identity.domain == "operations_support":
            from app.ai.operations_support_shared import guard_operations_task

            guard_operations_task(db, user, run_id)
            return
        if identity.domain == "research_cohort":
            from app.ai.research_cohort_shared import guard_research_task

            guard_research_task(db, user, run_id)
            return
        if identity.domain == "charge":
            _guard_charge_identity(db, user, identity)
            return
        if identity.domain == "document_change":
            accepted = guard_change_run_id(db, user, run_id, current=True)
        elif identity.domain == "satisfaction":
            accepted = guard_satisfaction_run_id(db, user, run_id, audit_only=user.user_role == "super_admin")
        elif identity.domain == "drug_label":
            accepted = guard_drug_label_run_id(db, user, run_id, frozen_audit=user.user_role == "super_admin")
        elif identity.domain == "document":
            from app.ai.document_extraction_runtime import guard_document_run_id

            guard_document_run_id(db, user, run_id)
            return
        else:
            accepted = False
        if not accepted:
            from fastapi import HTTPException

            raise HTTPException(409, "原生任务的实际域锚点已改变，未降级读取")
        return
    from app.ai.deidentification_shared import guard_task as guard_deidentification_task
    from app.ai.deidentification_shared import is_deidentification_task
    from app.ai.operations_support_shared import guard_operations_task, is_operations_task

    if is_operations_task(db, run_id):
        guard_operations_task(db, user, run_id)
        return
    from app.ai.research_cohort_shared import guard_research_task, is_research_task

    if is_deidentification_task(db, run_id):
        guard_deidentification_task(db, user, run_id)
        return
    if is_research_task(db, run_id):
        guard_research_task(db, user, run_id)
        return
    if guard_change_run_id(db, user, run_id, current=True):
        return
    if guard_satisfaction_run_id(db, user, run_id, audit_only=user.user_role == "super_admin"):
        return
    if guard_drug_label_run_id(db, user, run_id, frozen_audit=user.user_role == "super_admin"):
        return
    from app.ai.document_extraction_runtime import guard_document_run_id

    guard_document_run_id(db, user, run_id)
