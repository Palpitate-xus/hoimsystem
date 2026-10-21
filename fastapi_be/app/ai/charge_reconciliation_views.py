"""Current ordinary reads and frozen Super audit of complete ledger tasks."""

from app.ai.charge_reconciliation_context import expand_context
from app.ai.charge_reconciliation_contract import utc_text
from app.ai.charge_reconciliation_receipts import load_terminal
from app.ai.charge_reconciliation_run_models import AIChargeRunArtifact
from app.ai.charge_reconciliation_runtime import authorize_charge_run, current_actor
from app.ai.charge_reconciliation_storage import ANCHOR_FIELDS
from app.ai.charge_reconciliation_view_contract import ChargeArtifactRecord


def describe_charge_run(db, user, run, include_result=True):
    snapshot, binding, metadata, evidence = authorize_charge_run(db, user, run)
    result, receipt = load_terminal(db, run)
    fields = (
        "run_id",
        "feature_key",
        "status",
        "preview",
        "prompt_version",
        "provider_revision",
        "context_digest",
        "patient_id",
        "encounter_ref",
        "error_code",
        "error_message",
        "latency_ms",
        "create_time",
        "start_time",
        "finish_time",
    )
    data = {key: getattr(run, key) for key in fields}
    data.update(
        feature_name="收费与漏记账核对",
        requires_human_review=True,
        context_metadata=metadata,
        charge_case_id=binding["case_snapshot_id"],
        usage_receipt=receipt,
        input_tokens=receipt["input_tokens"],
        output_tokens=receipt["output_tokens"],
        usage_receipt_status="interrupted" if run.error_code == "WORKER_INTERRUPTED" else "recorded" if run.latency_ms is not None else "pending",
    )
    if include_result:
        row = db.query(AIChargeRunArtifact).filter_by(run_id=run.run_id).populate_existing().with_for_update(read=True).one()
        data["charge_artifact"] = ChargeArtifactRecord(
            schema_version=row.schema_version,
            run_id=row.run_id,
            case_snapshot_id=row.case_snapshot_id,
            requested_by=row.requested_by,
            created_at=utc_text(row.created_at),
            **{key: getattr(row, key) for key in ANCHOR_FIELDS},
            result_hash=row.result_hash,
            result_bytes=row.result_bytes,
            receipt_event_id=row.receipt_event_id,
            accepted_lease=row.accepted_lease,
        ).model_dump(mode="json")
        actor = current_actor(db, user)
        expanded = expand_context(db, snapshot["payload"]["context"], user=actor, current=actor.user_role != "super_admin")
        data["charge_findings"] = {key: expanded[key] for key in ("charge_binding", "charge_source", "charge_case")}
        data["charge_findings"].update(input=snapshot["payload"]["input"], context=snapshot["payload"]["context"])
        data["result"], data["evidence"] = result, evidence
    return data
