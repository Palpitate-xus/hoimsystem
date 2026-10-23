"""Artifact-scoped metadata directory; every returned task reauthorizes Source."""

from fastapi import HTTPException
from sqlalchemy import func, select, true

from app.ai import rca_evidence_contract as c
from app.ai import rca_evidence_grants as grants
from app.ai import rca_evidence_task_contract as t
from app.ai import rca_evidence_task_wire_contract as v
from app.ai import rca_evidence_views as views
from app.ai.models import AIFeedback, AIRun
from app.ai.rca_evidence_run_models import AIRcaEvidenceRunArtifact as Artifact


def history(db, user, *, case_id=None, status=None, requested_by=None, outcome=None, page=1, page_size=30, audit_only=False, other_scope=()):
    actor = grants.current_actor(db, user, grants.SOURCE_ROLES)
    if any(value is not None and value is not False for value in other_scope):
        raise HTTPException(422, "RCA原生历史仅按原Case筛选，不混患者、诊次或其它业务来源")
    if type(page) is not int or not 1 <= page <= 100000 or type(page_size) is not int or not 1 <= page_size <= 100:
        raise HTTPException(422, "须为明确有界的历史页码和页长")
    if case_id is not None:
        try:
            case_id = t.RcaTaskSelection(rca_evidence_case_id=case_id).rca_evidence_case_id
        except ValueError as exc:
            raise HTTPException(422, "须为真实RCA Case技术标识") from exc
    statement = select(Artifact.run_id, Artifact.case_id, Artifact.event_id, Artifact.requested_by, AIRun.create_time.label("ordering_clock")).join(AIRun, AIRun.run_id == Artifact.run_id)
    if case_id is not None:
        statement = statement.where(Artifact.case_id == case_id)
    if not audit_only:
        statement = statement.where(Artifact.requested_by == actor.user_id)
    if requested_by is not None:
        statement = statement.where(Artifact.requested_by == requested_by)
    if status is not None:
        statement = statement.where(AIRun.status == status)
    if outcome is not None:
        statement = statement.where(AIRun.run_id.in_(select(AIFeedback.run_id).where(AIFeedback.outcome == outcome)))
    total = select(func.count().label("candidate_total")).select_from(statement.subquery()).subquery()
    selected = statement.order_by(AIRun.create_time.desc(), AIRun.run_id).offset((page - 1) * page_size).limit(page_size).subquery()
    # A left join preserves the real total even when this later page is empty.
    # Both subqueries use the same single current SQL statement/read view.
    statement = select(selected, total.c.candidate_total).select_from(total.outerjoin(selected, true())).order_by(selected.c.ordering_clock.desc(), selected.c.run_id)
    # One current metadata statement supplies both IDs and its matching total.
    # No range Run SHARE, Task JSON or authority is obtained in this locator.
    with db.no_autoflush:
        bind = db.get_bind()
        if bind.dialect.name in {"mysql", "mariadb"}:
            with getattr(bind, "engine", bind).connect().execution_options(isolation_level="READ COMMITTED") as connection:
                rows = connection.execute(statement).all()
        else:
            rows = db.execute(statement).all()
    candidate_total = rows[0].candidate_total if rows else 0
    rows = [row for row in rows if row.run_id is not None]
    checked = {}
    # A multi-event directory takes its actual Event parents in canonical
    # order. Case/source/Run validation still occurs independently per row.
    for row in sorted(rows, key=lambda row: (row.event_id, row.case_id, row.run_id)):
        try:
            checked[row.run_id] = views.run_view(db, actor, row.run_id, False, frozen_audit=audit_only).model_dump(mode="json")
        except HTTPException as exc:
            if exc.status_code not in {403, 404, 409}:
                raise
    value = {
        "code": 200,
        "msg": "success",
        "data": [checked[row.run_id] for row in rows if row.run_id in checked],
        "total": candidate_total,
        "total_basis": "current_artifact_metadata_candidates_not_authorized_body_count",
        "page": page,
        "page_size": page_size,
    }

    try:
        value = v.RcaHistoryResponse.model_validate(value).model_dump(mode="json")
        c.canonical(value)  # The whole page, not just each independent row.
    except (ValueError, TypeError, UnicodeError) as exc:
        raise HTTPException(409, "完整RCA历史页超过明确容量或不能核对，未截断") from exc
    return value
