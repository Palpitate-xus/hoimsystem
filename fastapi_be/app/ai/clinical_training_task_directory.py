"""Bounded task candidates, owner Source reads and separate Super technical state."""

from fastapi import HTTPException
from sqlalchemy import select

from app.ai import clinical_training_learner as learner
from app.ai import clinical_training_practice as practice
from app.ai import clinical_training_registry as registry
from app.ai import clinical_training_views as views
from app.ai.clinical_training_run_models import AITrainingRunArtifact
from app.ai.clinical_training_write_guard import lock_training_write
from app.ai.models import AIRun


def list_tasks(db, user, *, submission_id=None, page=1, size=20):
    if type(page) is not int or not 1 <= page <= 100000 or type(size) is not int or not 1 <= size <= 50:
        raise HTTPException(422, "培训任务目录页须为1到100000、每页1到50的明确整数")
    actor = lock_training_write(db, user)
    if actor.user_role != "super_admin":
        actor = learner.current_learner(db, actor)
    statement = select(AITrainingRunArtifact.run_id).join(AIRun, AIRun.run_id == AITrainingRunArtifact.run_id)
    if actor.user_role != "super_admin":
        statement = statement.where(AITrainingRunArtifact.requested_by == actor.user_id)
    if submission_id is not None:
        # Filtering another learner's private submission must not become an
        # alternative Source lookup, even for a technical administrator.
        actor = learner.current_learner(db, actor)
        submission = practice.submission_header(db, actor, registry.identifier(submission_id))
        practice._current_source(db, actor, submission)
        statement = statement.where(AITrainingRunArtifact.submission_id == submission["submission_id"])
    statement = statement.order_by(AIRun.create_time.desc(), AIRun.run_id).offset((page - 1) * size).limit(size + 1)
    with db.no_autoflush:
        bind = db.get_bind()
        if bind.dialect.name in {"mysql", "mariadb"}:
            with getattr(bind, "engine", bind).connect().execution_options(isolation_level="READ COMMITTED") as connection:
                rows = connection.execute(statement).all()
        else:
            rows = db.execute(statement).all()
    items = []
    for (identifier,) in rows[:size]:
        try:
            value = views.technical_metadata(db, actor, identifier) if actor.user_role == "super_admin" and submission_id is None else views.describe_task(db, actor, identifier)
            items.append(value.model_dump(mode="json"))
        except HTTPException as exc:
            if exc.status_code not in {403, 404, 409}:
                raise
    return dict(items=items, page=page, size=size, has_more=len(rows) > size, pagination_basis="committed_opaque_task_candidates_before_independent_current_part_authorization")
