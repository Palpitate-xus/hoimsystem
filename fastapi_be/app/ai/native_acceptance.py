"""Verify actual native acceptance writes before their transaction commits."""

from fastapi import HTTPException

from app.ai.governance import encode_json
from app.ai.models import AIAuditEvent, AIRun

RUN_FIELDS = (
    "run_id",
    "feature_key",
    "provider_id",
    "provider_revision",
    "prompt_version",
    "prompt_hash",
    "context_digest",
    "patient_id",
    "encounter_ref",
    "requested_by",
    "preview",
    "input_json",
    "evidence_json",
    "context_metadata_json",
    "lease_token",
    "result_json",
    "status",
)
AUDIT_FIELDS = ("actor_id", "action", "target", "detail_json")


def acceptance_state(db, run, action):
    """Capture anchors and the exact staged audit before database triggers run."""
    audits = [row for row in db.new if isinstance(row, AIAuditEvent) and row.action == action and row.target == run.run_id]
    if len(audits) != 1:
        raise HTTPException(409, "完整原生结果须有唯一的本次接收审计")
    event = audits[0]
    return {"run": {key: getattr(run, key) for key in RUN_FIELDS}, "audit": {key: getattr(event, key) for key in AUDIT_FIELDS}, "event": event}


def verify_accepted_result(db, run, lease, expected, result, *, result_reader):
    """Read current SQL rows, lease, whole proof and exact audit after flush.

    The primary-key audit lookup avoids locking unrelated users' audit rows.
    Domain authorization must still be rechecked by the caller before commit.
    """
    row = db.query(*(getattr(AIRun, key) for key in RUN_FIELDS)).filter_by(run_id=run.run_id).with_for_update().one_or_none()
    if row is None or dict(row._mapping) != expected["run"] or row.status != "succeeded" or row.lease_token != lease:
        raise HTTPException(409, "原生结果实际写入后的任务、租约或冻结原件已经改变")
    current = db.query(AIRun).filter_by(run_id=run.run_id).populate_existing().with_for_update().one()
    if encode_json(result_reader(db, current)) != encode_json(result):
        raise HTTPException(409, "实际保存的完整原生证明与本次核算不同")
    event_id = expected["event"].event_id
    event = db.query(*(getattr(AIAuditEvent, key) for key in AUDIT_FIELDS)).filter_by(event_id=event_id).with_for_update(read=True).one_or_none()
    if event_id is None or event is None or dict(event._mapping) != expected["audit"]:
        raise HTTPException(409, "实际保存的原生结果接收审计不同或缺失")
