"""One committed RCA dispatch, no SQL connection across HTTP, no replay."""

import datetime as dt
import time
from types import SimpleNamespace

from fastapi import HTTPException

from app.ai import rca_evidence_attempts as attempts
from app.ai import rca_evidence_configuration as configuration
from app.ai import rca_evidence_grants as grants
from app.ai import rca_evidence_receipts as receipts
from app.ai import rca_evidence_result_storage as results
from app.ai import rca_evidence_task_contract as task_types
from app.ai.models import AIProvider, AIRun
from app.ai.rca_evidence_gateway import RcaEvidenceGatewayError, build_request, generate_rca_evidence
from app.ai.rca_evidence_run_models import AIRcaEvidenceRunArtifact
from app.ai.rca_evidence_task_views import RcaUsageReceipt


def _factory(value):
    if value is not None:
        return value
    from app.database import SessionLocal

    return SessionLocal


def usage(inputs=None, outputs=None, attempted=None):
    return RcaUsageReceipt(input_tokens=inputs, output_tokens=outputs, complete=inputs is not None and outputs is not None, model_call_attempted=attempted)


def delivery_precheck(db, identifier, lease):
    """Trusted metadata only; caller closes this transaction before Source.

    A previously dispatched/settled delivery is inert even if its original
    Source has since been revoked. It cannot terminate the in-flight owner.
    """
    actual = receipts.technical_header(db, identifier)
    if actual.claim is None or actual.claim.lease_token != lease or actual.dispatch is not None or actual.artifact["usage_event_id"] is not None:
        return None
    if actual.header["status"] not in {"running", "cancelled"}:
        return None
    return actual.claim, actual.header["status"] == "cancelled"


def _settle(factory, proof, dispatch_id, receipt, error, started):
    with factory() as db:
        value = receipts.stage_terminal(
            db,
            proof,
            dispatch_event_id=dispatch_id,
            usage=receipt,
            status="failed",
            error_code=error,
            latency_ms=min(2147483647, max(0, int((time.monotonic() - started) * 1000))),
        )
        db.commit()
        return value


async def execute_rca_claimed(identifier, lease, *, session_factory=None, transport=None):
    factory = _factory(session_factory)
    started = time.monotonic()
    proof = None
    dispatch_id = None
    receipt = usage(0, 0, False)
    result = None
    error = None
    # Independent technical precheck: no retained Run SHARE while waiting for
    # Source/Event/config. The real stage revalidates all actual claim fields.
    with factory() as db:
        checked = delivery_precheck(db, identifier, lease)
    if checked is None:
        return
    proof, cancelled = checked
    if cancelled:
        _settle(factory, proof, None, receipt, "TASK_CANCELLED", started)
        return
    actor = SimpleNamespace(user_id=proof.requested_by)
    try:
        with factory() as db:
            stored, configured = configuration.for_execution(db, actor, identifier)
            if attempts.claim_proof(db, stored) != proof:
                raise HTTPException(409, "原claim实际PK或租约已改变")
            payload = {
                "input": stored.snapshot.payload.input.model_dump(mode="json"),
                "context": task_types.expand_public_context(stored.snapshot.payload.context, stored.source),
                "tools": {},
                "evidence": [item.model_dump(mode="json") for item in stored.snapshot.payload.evidence],
            }
            task_prompt = stored.snapshot.task_prompt
            # Materialize every field, including credential references, while
            # the real current provider is loaded. No detached ORM lazy load.
            provider = SimpleNamespace(**{column.name: getattr(configured.provider, column.name) for column in AIProvider.__table__.columns})
            build_request(provider, task_prompt, payload)
            dispatched = attempts.stage_dispatch(db, actor, proof)
            if dispatched is None:
                db.rollback()
                return
            configuration.for_execution(db, actor, identifier)
            db.commit()
            # A commit exception is uncertain: never claim ownership of a
            # dispatch whose successful commit was not observed by this call.
            dispatch_id = dispatched.dispatch_event_id
        result, inputs, outputs = await generate_rca_evidence(provider, task_prompt, payload, transport=transport)
        receipt = usage(inputs, outputs, True)
    except RcaEvidenceGatewayError as exc:
        receipt = usage(exc.input_tokens, exc.output_tokens, True) if exc.model_call_attempted else usage(0, 0, False)
        error = exc.code
    except HTTPException:
        error = "RCA_CURRENT_STATE_CHANGED"
    except Exception:
        error = "RCA_EXECUTION_ERROR"
    if result is not None and error is None:
        try:
            with factory() as db:
                configuration.for_execution(db, actor, identifier)
                accepted = results.stage_result(
                    db,
                    actor,
                    proof,
                    result,
                    dispatch_event_id=dispatch_id,
                    usage=receipt,
                    latency_ms=min(2147483647, max(0, int((time.monotonic() - started) * 1000))),
                )
                if accepted is None:
                    # A storage refusal is not evidence of an unbilled call.
                    # The terminal stage independently checks this delivery's
                    # exact dispatch PK; another owner still remains inert.
                    raise HTTPException(409, "本次完整正文未接受，仍按原dispatch核对实际用量")
                configuration.for_execution(db, actor, identifier)
                db.commit()
            return
        except HTTPException:
            error = "RCA_RESULT_NOT_ACCEPTED"
        except Exception:
            error = "RESULT_STORAGE_ERROR"
    # The Run X stage rechecks this delivery's actual dispatch ID. A second
    # delivery that failed Source while another committed cannot settle it.
    _settle(factory, proof, dispatch_id, receipt, error or "RCA_RESULT_NOT_ACCEPTED", started)


def expire_interrupted_rca_runs(db):
    """Recover at most100 technical candidates per poll, never repeat HTTP.

    This is an execution timeout/interruption uncertainty policy, not proof
    that a process died or that its provider charged zero tokens.
    """
    deadline = grants.utcnow() - dt.timedelta(minutes=10)
    rows = (
        db.query(AIRun.run_id)
        .join(AIRcaEvidenceRunArtifact, AIRcaEvidenceRunArtifact.run_id == AIRun.run_id)
        .filter(AIRun.status.in_(["running", "cancelled"]), AIRun.start_time < deadline, AIRcaEvidenceRunArtifact.usage_event_id.is_(None))
        .order_by(AIRun.start_time, AIRun.run_id)
        .limit(100)
        .all()
    )
    total = 0
    try:
        for (identifier,) in rows:
            current = receipts.technical_header(db, identifier, exclusive=True)
            if current.claim is None or current.artifact["usage_event_id"] is not None or current.header["status"] not in {"running", "cancelled"} or current.header["start_time"] >= deadline:
                continue
            attempted = current.dispatch is not None
            value = receipts.stage_terminal(
                db,
                current.claim,
                dispatch_event_id=current.dispatch.dispatch_event_id if attempted else None,
                usage=usage(None, None, None) if attempted else usage(0, 0, False),
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
