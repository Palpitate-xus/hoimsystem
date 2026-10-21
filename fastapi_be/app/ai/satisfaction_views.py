"""Current ordinary reads, explicit Super frozen audit, and bounded HTTP views.

Source/result/provider storage budgets remain separate. A convenience HTTP view
repeats safe proof fields, so its complete wire has an explicit larger budget.
No individual Source, result blob, request or original task TEXT limit changes.
"""

from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder

from app.ai.satisfaction_draft import canonical_json

RUN_RESPONSE_BYTES = 40 * 1024 * 1024
CONTEXT_RESPONSE_BYTES = 32 * 1024 * 1024
TRACE_RESPONSE_BYTES = 80 * 1024 * 1024


def checked_response(value, maximum=RUN_RESPONSE_BYTES):
    try:
        wire = jsonable_encoder(value)
        if len(canonical_json(wire).encode("utf-8", errors="strict")) > maximum:
            raise ValueError("Complete composite response exceeds its own wire budget")
        return wire
    except (ValueError, TypeError, KeyError, AttributeError, UnicodeError, RecursionError) as exc:
        raise HTTPException(409, "完整评价响应超过对应组合容量或含无效JSON，未截断返回") from exc


def describe_satisfaction_run(db, user, run, *, include_result=True):
    from app.ai.satisfaction_runtime import current_actor
    from app.ai.satisfaction_runtime import describe_satisfaction_run as describe

    actor = current_actor(db, user)
    value = describe(db, actor, run, include_result=include_result, audit_only=actor.user_role == "super_admin")
    # Bind the actual response wrapper, not only the nested result's size.
    checked_response({"code": 200, "msg": "success", "data": value})
    return value


def trace_proof(db, user, run):
    from app.ai.satisfaction_artifact_models import ANCHOR_FIELDS, AISatisfactionRunArtifact
    from app.ai.satisfaction_runtime import authorize_satisfaction_run, current_actor
    from app.ai.satisfaction_sources import utc_text

    actor = current_actor(db, user)
    if actor.user_role != "super_admin":
        raise HTTPException(403, "完整评价溯源仅限当前超级管理员")
    _, snapshot, _, _, _, expanded = authorize_satisfaction_run(db, actor, run, audit_only=True)
    # Preserve the three original scalar byte strings separately; expansion is
    # a distinct authorized view and never pretends to be the frozen raw JSON.
    view = {**snapshot, "payload": {**snapshot["payload"], "context": expanded}}
    artifact = db.query(AISatisfactionRunArtifact).filter_by(run_id=run.run_id).populate_existing().with_for_update(read=True).one()
    names = ("schema_version", "run_id", "case_id", "requested_by", *ANCHOR_FIELDS, "result_hash", "result_bytes", "receipt_event_id", "usage_event_id", "accepted_lease")
    proof = {key: getattr(artifact, key) for key in names}
    proof["created_at"] = utc_text(artifact.created_at)
    proof["accepted_at"] = utc_text(artifact.accepted_at) if artifact.accepted_at is not None else None
    return view, {
        "raw_frozen_json": {key: getattr(run, key) for key in ("input_json", "evidence_json", "context_metadata_json")},
        "satisfaction_artifact": proof,
        "frozen_satisfaction_audit": True,
    }
