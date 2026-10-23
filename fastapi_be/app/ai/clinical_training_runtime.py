"""Caller-visible training creation/claim/stop transactions; no generic path."""

import datetime as dt
from types import SimpleNamespace

from fastapi import HTTPException
from sqlalchemy import select

from app.ai import clinical_training_attempts as attempts
from app.ai import clinical_training_cancellation as cancellation
from app.ai import clinical_training_receipts as receipts
from app.ai import clinical_training_registry as registry
from app.ai import clinical_training_storage as storage
from app.ai.clinical_training_run_models import AITrainingRunArtifact
from app.ai.clinical_training_usage_contract import usage
from app.ai.models import AIRun


def locate_owner(db, identifier):
    """Bodyless independent current lookup plus this Session's actual SQL.

    The lookup retains no Artifact/Run lock before acquiring Source/Config.
    A previously opened MySQL RR snapshot must also see a newly committed
    artifact, while a caller's actual uncommitted insertion stays locatable.
    """
    identifier = registry.identifier(identifier)
    statement = select(AITrainingRunArtifact.requested_by).where(AITrainingRunArtifact.run_id == identifier)
    with db.no_autoflush:
        current = None
        bind = db.get_bind()
        if bind.dialect.name in {"mysql", "mariadb"}:
            with getattr(bind, "engine", bind).connect().execution_options(isolation_level="READ COMMITTED") as connection:
                current = connection.execute(statement).scalar_one_or_none()
        own = db.execute(statement).scalar_one_or_none()
    if own is not None and current is not None and own != current:
        raise HTTPException(409, "培训实际SQL分件归属与当前读不同，未猜测任务所有人")
    return own if own is not None else current


def create_training_run(db, user, selection, *, preview=False):
    try:
        identifier = storage.stage_run(db, user, selection, preview=preview)
        db.commit()
        # Return the opaque PK: never refresh an expired full Run merely to
        # obtain its ID after commit and before a new Source authorization.
        return identifier
    except Exception:
        db.rollback()
        raise


def claim_training_run(db, identifier):
    """One exact committed claim; unavailable queued sources fail at known zero."""
    identifier = registry.identifier(identifier)
    try:
        if attempts._phase_seen(db, identifier, ("claim_event_id", "usage_event_id")):
            return None
        owner = locate_owner(db, identifier)
        if owner is None:
            raise HTTPException(409, "原生培训任务缺少实际分件，未降级通用领取")
        actor = SimpleNamespace(user_id=owner)
        try:
            claim = attempts.stage_claim(db, actor, identifier)
        except HTTPException:
            db.rollback()
            receipts.stage_unclaimed_failure(db, identifier, error_code="TASK_NO_LONGER_AUTHORIZED")
            db.commit()
            return None
        if claim is None:
            db.rollback()
            return None
        db.commit()
        return claim.lease_token
    except Exception:
        db.rollback()
        raise


def cancel_training_run(db, user, identifier):
    try:
        ack = cancellation.stage_cancel(db, user, identifier)
        db.commit()
        return ack
    except Exception:
        db.rollback()
        raise


def _interrupted_candidates(db, deadline):
    """Bounded opaque current candidates without a Run lock before Gate X.

    Independent RC candidates have priority over a caller's older RR view;
    this Session's actual SQL also includes uncommitted phase transitions.
    Every candidate still needs its complete current technical receipt proof.
    """
    statement = (
        select(AIRun.run_id)
        .join(AITrainingRunArtifact, AITrainingRunArtifact.run_id == AIRun.run_id)
        .where(AIRun.status.in_(["running", "cancelled"]), AIRun.start_time < deadline, AITrainingRunArtifact.usage_event_id.is_(None))
        .order_by(AIRun.start_time, AIRun.run_id)
        .limit(100)
    )
    with db.no_autoflush:
        current = []
        bind = db.get_bind()
        if bind.dialect.name in {"mysql", "mariadb"}:
            with getattr(bind, "engine", bind).connect().execution_options(isolation_level="READ COMMITTED") as connection:
                current = list(connection.scalars(statement))
        own = list(db.scalars(statement))
    return list(dict.fromkeys([*current, *own]))[:100]


def expire_interrupted_training_runs(db):
    """At most100 technical candidates, no HTTP replay or invented paid zero.

    Ten minutes is an uncertainty timeout policy, not proof of process death
    or a provider's billing. A committed dispatch becomes unknown/null; a
    genuinely undispatched original claim is provably unattempted zero.
    """
    deadline = registry.utcnow() - dt.timedelta(minutes=10)
    identifiers = _interrupted_candidates(db, deadline)
    total = 0
    try:
        for identifier in identifiers:
            actual = attempts.technical_header(db, identifier, exclusive=True)
            if actual.claim is None or actual.artifact["usage_event_id"] is not None or actual.header["status"] not in {"running", "cancelled"} or actual.header["start_time"] >= deadline:
                continue
            dispatched = actual.dispatch is not None
            value = receipts.stage_terminal(
                db,
                actual.claim,
                dispatch_event_id=actual.dispatch.dispatch_event_id if dispatched else None,
                usage=usage(None, None, None) if dispatched else usage(0, 0, False),
                status="failed",
                error_code="WORKER_INTERRUPTED",
                latency_ms=0,
            )
            total += value is not None
        db.commit()
        return total
    except Exception:
        db.rollback()
        raise
