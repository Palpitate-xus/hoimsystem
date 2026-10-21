"""Dedicated RCA creation/claim stages; inference execution is added separately."""

import uuid
from types import SimpleNamespace

from fastapi import HTTPException

from app.ai import rca_evidence_attempts as attempts
from app.ai import rca_evidence_configuration as configuration
from app.ai import rca_evidence_context as context
from app.ai import rca_evidence_grants as grants
from app.ai import rca_evidence_receipts as receipts
from app.ai import rca_evidence_storage as storage
from app.ai import rca_evidence_task_contract as task_types
from app.ai.models import AIRun
from app.ai.rca_evidence_gateway import RcaEvidenceGatewayError, build_request


@grants._write
def create_rca_run(db, user, req):
    """Explicit creation with current Source/config and whole-wire preflight."""
    if req.feature_key != task_types.FEATURE_KEY or req.patient_id is not None or req.encounter_ref is not None or type(req.preview) is not bool:
        raise HTTPException(422, "仅明确受审RCA Case及显式预览，不接受其它功能、患者或就诊范围")
    prepared = context.prepare_context(db, user, req.input)
    current = configuration.for_context(db, user, prepared, req.preview, writing=True)
    before = configuration.current_daily_count(db, prepared.binding.requested_by, grants.utcnow())
    if before >= current.config.daily_limit:
        raise HTTPException(429, "该功能今日明确调用额度已用完")
    snapshot = configuration.snapshot_for_context(prepared, current)
    payload = {
        "input": prepared.selection.model_dump(mode="json"),
        "context": task_types.expand_public_context(prepared.data, prepared.source),
        "tools": {},
        "evidence": prepared.evidence,
    }
    try:
        build_request(current.provider, current.task_prompt, payload)  # No HTTP; full protocol/System/Task bytes count.
    except RcaEvidenceGatewayError as exc:
        raise HTTPException(409, "完整事件调查Source、System/Task和实际协议请求无法适配；未入队、发送或裁剪") from exc
    run = AIRun(run_id=str(uuid.uuid4()), prompt_version=current.prompt_version, preview=int(req.preview))
    stored = storage.stage_run(db, user, run, prepared, snapshot)
    configuration.for_execution(db, user, run.run_id)
    after = configuration.current_daily_count(db, prepared.binding.requested_by, grants.utcnow())
    if after != before + 1 or after > current.config.daily_limit:
        raise HTTPException(409, "实际日配额或同事务新增任务集合发生变化，整件未入队")
    db.commit()
    return stored.run


@grants._write
def claim_rca_run(db, identifier):
    """One exact claim; adjacent deliveries never reacquire an existing owner."""
    if attempts._already_claimed(db, identifier):
        return None
    identity = storage.locate_artifact(db, identifier)
    if identity is None:
        raise HTTPException(409, "原生RCA任务缺少实际Artifact，不降级通用claim")
    actor = SimpleNamespace(user_id=identity[2])
    try:
        configuration.for_execution(db, actor, identifier)
    except HTTPException:
        # Trusted queue processing can settle a never-claimed task at known
        # zero without regaining Source/Task body rights. A concurrent claim
        # makes this stale delivery inert inside the Run X stage.
        db.rollback()
        receipts.stage_unclaimed_terminal(db, identifier, status="failed", error_code="TASK_NO_LONGER_AUTHORIZED")
        db.commit()
        return None
    claim = attempts.stage_claim(db, actor, identifier)
    if claim is None:
        db.rollback()
        return None
    configuration.for_execution(db, actor, identifier)
    db.commit()
    return claim.lease_token
