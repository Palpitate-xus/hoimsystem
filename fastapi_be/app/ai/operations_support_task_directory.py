"""Bounded committed task metadata; no Run lock precedes Source authorization."""

from fastapi import HTTPException
from sqlalchemy import select

from app.ai import operations_support_registry as registry
from app.ai import operations_support_views as views
from app.ai.models import AIFeatureConfig, AIRun
from app.ai.operations_support_configuration import FEATURE, roles_for
from app.ai.operations_support_run_models import AIOperationsRunArtifact
from app.ai.operations_support_write_guard import current_rows, lock_operations_write


def list_tasks(db, user, *, case_id=None, page=1, size=20):
    if type(page) is not int or not 1 <= page <= 1000000 or type(size) is not int or not 1 <= size <= 50:
        raise HTTPException(422, "运维任务目录页须为1到1000000、每页1到50的明确整数")
    actor = lock_operations_write(db, user)
    if actor.user_role != "super_admin":
        config = current_rows(db.query(AIFeatureConfig.allowed_roles_json).filter_by(feature_key=FEATURE), shared=True).one_or_none()
        if config is None or actor.user_role not in roles_for(config.allowed_roles_json):
            raise HTTPException(403, "当前配置不再允许本账户读取运维任务")
    statement = select(AIOperationsRunArtifact.run_id).join(AIRun, AIRun.run_id == AIOperationsRunArtifact.run_id)
    if actor.user_role != "super_admin":
        statement = statement.where(AIOperationsRunArtifact.requested_by == actor.user_id)
    if case_id is not None:
        statement = statement.where(AIOperationsRunArtifact.case_id == registry.identifier(case_id))
    statement = statement.order_by(AIRun.create_time.desc(), AIRun.run_id).offset((page - 1) * size).limit(size + 1)
    with db.no_autoflush:
        bind = db.get_bind()
        if bind.dialect.name in {"mysql", "mariadb"}:
            # A fresh short RC lookup avoids a JWT-created old RR view and
            # retains no Run/Artifact locks while Source permissions follow.
            with getattr(bind, "engine", bind).connect().execution_options(isolation_level="READ COMMITTED") as connection:
                rows = connection.execute(statement).all()
        else:
            rows = db.execute(statement).all()
    items = []
    for (identifier,) in rows[:size]:
        try:
            value = views.technical_metadata(db, actor, identifier) if actor.user_role == "super_admin" else views.describe_task(db, actor, identifier)
            items.append(value.model_dump(mode="json"))
        except HTTPException as exc:
            if exc.status_code not in {403, 404, 409}:
                raise
    return {
        "items": items,
        "page": page,
        "size": size,
        "has_more": len(rows) > size,
        "pagination_basis": "committed_opaque_task_candidates_before_independent_current_part_authorization",
    }
