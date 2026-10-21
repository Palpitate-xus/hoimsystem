"""One authentic76 dispatch, detached wire values and no SQL across HTTP."""

import asyncio
import time
from types import SimpleNamespace

from fastapi import HTTPException

from app.ai import research_variables_attempts as attempts
from app.ai import research_variables_receipts as receipts
from app.ai import research_variables_result_storage as results
from app.ai import research_variables_storage as storage
from app.ai import research_variables_task_reader as reader
from app.ai.governance import provider_credential
from app.ai.research_cohort_write_guard import lock_research_gate
from app.ai.research_variables_configuration import current_configuration
from app.ai.research_variables_gateway import VariableGatewayError, build_request, generate_research_variables
from app.ai.research_variables_storage_contract import VariableUsageReceipt


def usage(inputs=None, outputs=None, attempted=None):
    return VariableUsageReceipt(input_tokens=inputs, output_tokens=outputs, complete=inputs is not None and outputs is not None, model_call_attempted=attempted)


def delivery_precheck(db, identifier, lease):
    """Trusted metadata only; caller closes this Session before waiting Source."""
    lock_research_gate(db)
    identity = reader.locate_artifact(db, identifier)
    if identity is None:
        return None
    header, artifact = reader._headers(db, identity, exclusive=False)
    reader._creation_audit(db, header, artifact)
    if (
        artifact["claim_lease"] != lease
        or artifact["claim_event_id"] is None
        or artifact["dispatch_event_id"] is not None
        or artifact["usage_event_id"] is not None
        or header["status"] not in {"running", "cancelled"}
    ):
        return None
    task = SimpleNamespace(run=SimpleNamespace(**header), artifact=SimpleNamespace(**artifact))
    claim = attempts.verify_claim(db, task)
    return claim, header["status"] == "cancelled"


def _factory(value):
    if value is not None:
        return value
    from app.database import SessionLocal

    return SessionLocal


def _settle(factory, claim, delivery, receipt, code, started):
    with factory() as db:
        recorded = receipts.stage_terminal(
            db,
            claim,
            delivery=delivery,
            receipt=receipt,
            status="failed",
            error_code=code,
            error_message="本次原领取未接受完整结果，仅保留实际已知或未知调用回执；未返回或恢复原件正文。",
            latency_ms=max(0, int((time.monotonic() - started) * 1000)),
        )
        db.commit()
        return recorded


async def execute_research_variables_claimed(identifier, lease, *, session_factory=None, transport=None):
    factory = _factory(session_factory)
    started = time.monotonic()
    with factory() as db:
        checked = delivery_precheck(db, identifier, lease)
    if checked is None:
        return
    claim, cancelled = checked
    receipt, delivery, result, code = usage(0, 0, False), None, None, None
    actor = SimpleNamespace(user_id=claim.requested_by)
    if cancelled:
        _settle(factory, claim, None, receipt, "TASK_CANCELLED", started)
        return
    try:
        with factory() as db:
            task = reader.load_task(db, actor, identifier, exclusive=True, for_execution=True)
            attempts.verify_claim(db, task, claim)
            configured = current_configuration(db, task.authority.actor, preview=bool(task.run.preview), require_credentials=True)
            storage._verify_configuration(task.snapshot, configured)
            # Materialize every wire value and resolve the actual credential
            # before closing SQL. No ORM reference survives into provider I/O.
            snapshot = task.snapshot.model_copy(deep=True)
            binding, source = task.binding.model_copy(deep=True), task.source.model_copy(deep=True)
            credential = provider_credential(configured.provider)
            build_request(snapshot, binding, source)
            staged = attempts.stage_dispatch(db, task.authority.actor, claim)
            if staged is None:
                db.rollback()
                return
            db.commit()
            # A failed/uncertain commit never becomes this call's send owner.
            delivery = staged
        result, inputs, outputs = await generate_research_variables(snapshot, binding, source, credential=credential, transport=transport)
        receipt = usage(inputs, outputs, True)
    except VariableGatewayError as exc:
        receipt = usage(exc.input_tokens, exc.output_tokens, True) if exc.model_call_attempted else usage(0, 0, False)
        code = exc.code
    except HTTPException:
        code = "VARIABLE_CURRENT_STATE_CHANGED"
    except asyncio.CancelledError:
        _settle(factory, claim, delivery, usage(None, None, None) if delivery is not None else usage(0, 0, False), "WORKER_INTERRUPTED", started)
        raise
    except Exception:
        if delivery is not None:
            receipt, code = usage(None, None, None), "WORKER_INTERRUPTED"
        else:
            code = "VARIABLE_EXECUTION_ERROR"
    if result is not None and code is None:
        try:
            with factory() as db:
                accepted = results.stage_result(db, actor, delivery, result, receipt, latency_ms=max(0, int((time.monotonic() - started) * 1000)))
                if accepted is None:
                    # Cancellation/refusal is not evidence that the received
                    # model reply was unbilled. Always try this exact delivery.
                    raise HTTPException(409, "本次完整结果未接受，仍结算原分派实际回执")
                db.commit()
            return
        except HTTPException:
            code = "VARIABLE_RESULT_NOT_ACCEPTED"
        except Exception:
            code = "VARIABLE_RESULT_STORAGE_ERROR"
    _settle(factory, claim, delivery, receipt, code or "VARIABLE_RESULT_NOT_ACCEPTED", started)
