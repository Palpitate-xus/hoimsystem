"""Filter native evaluation history through the actual immutable Case FK."""

from fastapi import HTTPException
from pydantic import TypeAdapter

from app.ai.models import AIRun
from app.ai.satisfaction_artifact_models import AISatisfactionRunArtifact
from app.ai.satisfaction_contract import UUID
from app.ai.satisfaction_runtime import current_actor
from app.ai.satisfaction_sources import authorize_case, case_current


def filter_history(db, user, query, *, feature_key, case_id=None, native_only=False, other_scope=()):
    if feature_key != "feedback_analysis" or any(value is not None for value in other_scope):
        raise HTTPException(422, "完整评价历史只筛选本功能原件，不能混入患者、科室或其他来源范围")
    actor = current_actor(db, user)
    members = db.query(AISatisfactionRunArtifact.run_id)
    if case_id is not None:
        try:
            identifier = TypeAdapter(UUID).validate_python(case_id, strict=True)
        except (ValueError, TypeError) as exc:
            raise HTTPException(422, "评价历史来源须为规范UUID") from exc
        if actor.user_role == "super_admin":
            case_current(db, actor, identifier, audit_only=True)
        else:
            authorize_case(db, actor, identifier, execution=False, locking=True)
        members = members.filter_by(case_id=identifier)
    if native_only or case_id is not None:
        query = query.filter(AIRun.run_id.in_(members))
    return query
