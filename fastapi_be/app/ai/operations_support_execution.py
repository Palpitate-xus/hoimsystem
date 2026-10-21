"""One committed operations dispatch, detached public inputs and no SQL await."""

import time
from types import SimpleNamespace

from fastapi import HTTPException

from app.ai import operations_support_attempts as attempts
from app.ai import operations_support_configuration as configuration
from app.ai import operations_support_gateway as gateway
from app.ai import operations_support_receipts as receipts
from app.ai import operations_support_result_storage as results
from app.ai import operations_support_storage as storage
from app.ai.governance import provider_credential
from app.ai.models import AIProvider
from app.ai.operations_support_usage_contract import usage
from app.ai.operations_support_write_guard import current_actor


def _factory(value):
    if value is not None:
        return value
    from app.database import SessionLocal

    return SessionLocal


def delivery_precheck(db, identifier, lease):
    """Trusted bodyless short transaction, closed before Source/Config locks."""
    actual = attempts.technical_header(db, identifier, exclusive=False)
    if actual.claim is None or actual.claim.lease_token != lease or actual.dispatch is not None or actual.artifact["usage_event_id"] is not None or actual.header["status"] not in {"running", "cancelled"}:
        return None
    return actual.claim, actual.header["status"] == "cancelled"


def _prepare_dispatch(factory, claim):
    actor = SimpleNamespace(user_id=claim.requested_by)
    with factory() as db:
        dispatched = attempts.stage_dispatch(db, actor, claim)
        if dispatched is None:
            db.rollback()
            return None
        run, artifact, source, private, prompt, execution, selection = storage.load_artifact(db, actor, claim.run_id, execution=True)
        current = current_actor(db, actor)
        configured = configuration.configuration(db, current, preview=bool(run.preview))
        provider = SimpleNamespace(**{column.name: getattr(configured[1], column.name) for column in AIProvider.__table__.columns})
        task_prompt = prompt["task_prompt"]
        provider_credential(provider)
        gateway.request(provider, source, selection, task_prompt)
        db.commit()
        # The exact PK becomes owned only after this delivery observes commit.
        dispatch_id = dispatched.dispatch_event_id
    return dispatch_id, provider, source, selection, task_prompt


def _latency(started):
    return min(2147483647, max(0, int((time.monotonic() - started) * 1000)))


def _settle(factory, claim, dispatch_id, actual_usage, error, started):
    with factory() as db:
        value = receipts.stage_terminal(db, claim, dispatch_event_id=dispatch_id, usage=actual_usage, status="failed", error_code=error, latency_ms=_latency(started))
        db.commit()
        return value


async def execute_operations_claimed(identifier, lease, *, session_factory=None, transport=None):
    """No automatic model retry; duplicates never terminate the original owner."""
    factory, started = _factory(session_factory), time.monotonic()
    dispatch_id, draft, error = None, None, None
    actual_usage = usage(0, 0, False)
    with factory() as db:
        checked = delivery_precheck(db, identifier, lease)
    if checked is None:
        return
    claim, cancelled = checked
    if cancelled:
        _settle(factory, claim, None, actual_usage, "TASK_CANCELLED", started)
        return
    try:
        prepared = _prepare_dispatch(factory, claim)
        if prepared is None:
            return
        dispatch_id, provider, source, selection, task_prompt = prepared
        draft, actual_usage, call_latency = await gateway.generate_operations(provider, source, selection, task_prompt, transport=transport)
    except gateway.OperationsCallError as exc:
        actual_usage, error = exc.usage, exc.code
    except HTTPException:
        error = "OPERATIONS_CURRENT_STATE_CHANGED"
    except Exception:
        error = "OPERATIONS_EXECUTION_ERROR"
    if draft is not None and error is None:
        try:
            with factory() as db:
                accepted = results.stage_result(db, SimpleNamespace(user_id=claim.requested_by), claim, draft, dispatch_event_id=dispatch_id, usage=actual_usage, latency_ms=_latency(started))
                if accepted is not None:
                    db.commit()
                    return
                db.rollback()
                # None may mean a legitimate in-flight cancellation. Always
                # attempt settlement under this exact committed dispatch PK;
                # existing or foreign-delivery receipts remain inert there.
                error = "OPERATIONS_RESULT_NOT_ACCEPTED"
        except HTTPException:
            error = "OPERATIONS_RESULT_NOT_ACCEPTED"
        except Exception:
            error = "OPERATIONS_RESULT_STORAGE_ERROR"
    _settle(factory, claim, dispatch_id, actual_usage, error or "OPERATIONS_RESULT_NOT_ACCEPTED", started)
