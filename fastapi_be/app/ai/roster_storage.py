"""Complete roster proofs are bounded blobs, atomically accepted by the current lease."""

import hashlib
import json
from typing import Literal

from fastapi import HTTPException
from pydantic import Field, field_validator

from app.ai.retry_policy import retry_snapshots_equal
from app.ai.roster_contract import SHA256, StrictModel, canonical_json, hash_content, identity
from app.ai.roster_plan_models import RESULT_BYTES, AIRosterRunResult


class RosterResultReference(StrictModel):
    schema_version: Literal["roster_result_ref_v1"]
    run_id: str
    plan_id: str
    lease_token: str
    content_hash: SHA256
    result_bytes: int = Field(gt=0, le=RESULT_BYTES)
    source_binding_hash: SHA256
    _ids = field_validator("run_id", "plan_id", "lease_token")(identity)


def bounded_result(value):
    try:
        serialized = canonical_json(value)
        encoded = serialized.encode("utf-8")
    except (ValueError, TypeError, UnicodeError, RecursionError) as exc:
        raise HTTPException(422, "排班完整结果须为有限UTF-8 JSON") from exc
    if not 0 < len(encoded) <= RESULT_BYTES:
        raise HTTPException(422, "排班完整结果超过8MiB，未接收或截断")
    return serialized, hashlib.sha256(encoded).hexdigest(), len(encoded)


def is_roster_snapshot(snapshot):
    if not isinstance(snapshot, dict):
        raise HTTPException(409, "排班冻结任务须为完整JSON对象")
    payload, provider = snapshot.get("payload", {}), snapshot.get("provider_snapshot", {})
    if not isinstance(payload, dict) or not isinstance(provider, dict):
        raise HTTPException(409, "冻结任务的原服务或输入无效")
    context, values = payload.get("context", {}), payload.get("input", {})
    if not isinstance(context, dict) or not isinstance(values, dict):
        raise HTTPException(409, "排班原上下文或引用结构无效")
    return "roster_binding" in context or "roster_plan_id" in values or str(provider.get("model", "")).startswith("roster:")


def run_binding(run):
    from app.ai.governance import digest
    from app.ai.roster_context import RosterContextBinding, selection

    try:
        snapshot, metadata, evidence = json.loads(run.input_json), json.loads(run.context_metadata_json), json.loads(run.evidence_json)
        payload = snapshot["payload"]
        context = payload["context"]
        bound = RosterContextBinding.model_validate(context["roster_binding"])
        if run.feature_key != "roster_optimization" or run.patient_id is not None or run.encounter_ref is not None:
            raise ValueError("排班任务不能混入个体患者或就诊")
        if any(canonical_json(value) != raw for value, raw in ((snapshot, run.input_json), (metadata, run.context_metadata_json), (evidence, run.evidence_json))):
            raise ValueError("排班原任务不是规范完整JSON")
        if digest([snapshot["system_prompt"], snapshot["task_prompt"]]) != run.prompt_hash or digest(context) != run.context_digest or metadata["context_digest"] != run.context_digest:
            raise ValueError("排班冻结Prompt或上下文锚不同")
        if digest({key: value for key, value in context.items() if key != "snapshot_time"}) != metadata["clinical_context_fingerprint"] or digest(payload["tools"]) != metadata["tool_fingerprint"]:
            raise ValueError("排班完整原范围或工具不同")
        if payload["evidence"] != evidence or type(metadata["source_count"]) is not int or metadata["source_count"] != len(evidence):
            raise ValueError("排班原证据与完整计数不同")
        if metadata["snapshot_time"] != context["snapshot_time"] or metadata["missing_data"] != context["missing_data"] or metadata["department_ids"] != [bound.department_id]:
            raise ValueError("排班原时刻、范围或缺项不同")
        if selection(payload["input"]) != bound.plan_id or context["selected_sources"] != {"roster_plan_id": bound.plan_id}:
            raise ValueError("排班原引用不同")
        if context["scope"] != "department" or context["source_domain"] != "roster_declared_scenario" or context["department_ids"] != [bound.department_id]:
            raise ValueError("排班冻结运营范围不同")
        provider = snapshot["provider_snapshot"]
        if provider["provider_id"] != run.provider_id or provider["revision"] != run.provider_revision or provider["kind"] != "specialist" or not provider["model"].startswith("roster:"):
            raise ValueError("排班原服务身份不同")
        return bound.model_dump(mode="json")
    except (HTTPException, ValueError, TypeError, KeyError, AttributeError, RecursionError) as exc:
        raise HTTPException(409, "排班任务的完整原计划、Prompt、范围或证据绑定无效") from exc


def stage_result(db, run, lease, value):
    from app.ai.governance import audit
    from app.ai.models import AIFeatureConfig, AIProvider, utcnow
    from app.ai.roster_facts import current_actor
    from app.ai.roster_plans import authorize_plan
    from app.ai.runtime import check_configuration, provider_snapshot
    from app.models import User

    if run.status != "running" or run.lease_token != lease:
        raise HTTPException(409, "只有当前执行租约可接收排班结果")
    binding = run_binding(run)
    actor = db.query(User).filter_by(user_id=run.requested_by).populate_existing().with_for_update().one_or_none()
    if actor is None:
        raise HTTPException(403, "排班任务用户已经失效")
    actor = current_actor(db, actor, locking=True)
    config = db.query(AIFeatureConfig).filter_by(feature_key=run.feature_key).populate_existing().with_for_update().one_or_none()
    provider = db.query(AIProvider).filter_by(provider_id=run.provider_id).populate_existing().with_for_update().one_or_none()
    snapshot, metadata = json.loads(run.input_json), json.loads(run.context_metadata_json)
    if config is None or config.revision != metadata["feature_revision"] or provider is None or provider.revision != run.provider_revision:
        raise HTTPException(409, "排班最终接收时原功能或模型版本已经变化")
    from app.ai.catalog import FEATURE_BY_KEY

    if check_configuration(db, actor, FEATURE_BY_KEY[run.feature_key], config, bool(run.preview)) is not provider or not retry_snapshots_equal(provider_snapshot(provider), snapshot["provider_snapshot"]):
        raise HTTPException(409, "排班最终接收时模型或适用权限已经变化")
    authorize_plan(db, actor, binding["plan_id"], binding=binding, locking=True)
    serialized, content_hash, size = bounded_result(value)
    if db.query(AIRosterRunResult.run_id).filter_by(run_id=run.run_id).first() is not None:
        raise HTTPException(409, "排班完整结果已经接收，不可覆盖")
    db.add(
        AIRosterRunResult(
            run_id=run.run_id,
            plan_id=binding["plan_id"],
            lease_token=lease,
            schema_version="roster_complete_result_v1",
            source_binding_hash=hash_content(binding),
            content_hash=content_hash,
            result_json=serialized,
            result_bytes=size,
            created_at=utcnow(),
        )
    )
    reference = RosterResultReference(
        schema_version="roster_result_ref_v1", run_id=run.run_id, plan_id=binding["plan_id"], lease_token=lease, content_hash=content_hash, result_bytes=size, source_binding_hash=hash_content(binding)
    ).model_dump(mode="json")
    audit(db, run.requested_by, "run.roster_result.accept", run.run_id, {"content_hash": content_hash, "result_bytes": size, "source_binding_hash": reference["source_binding_hash"]})
    return canonical_json(reference)


def expand_result(db, run):
    from app.ai.gateway import AIExecutionError, validate_generation
    from app.ai.roster_context import expand_context

    try:
        reference = RosterResultReference.model_validate(json.loads(run.result_json))
        binding = run_binding(run)
        if (
            run.status != "succeeded"
            or reference.run_id != run.run_id
            or reference.plan_id != binding["plan_id"]
            or reference.lease_token != run.lease_token
            or reference.source_binding_hash != hash_content(binding)
        ):
            raise ValueError("排班原状态、租约或来源不同")
        row = db.query(AIRosterRunResult).filter_by(run_id=run.run_id).populate_existing().one_or_none()
        if (
            row is None
            or row.schema_version != "roster_complete_result_v1"
            or row.lease_token != reference.lease_token
            or row.plan_id != reference.plan_id
            or row.source_binding_hash != reference.source_binding_hash
        ):
            raise ValueError("排班完整原结果不存在或原绑定不同")
        if not isinstance(row.result_json, str) or len(row.result_json.encode("utf-8")) > RESULT_BYTES:
            raise ValueError("排班完整结果字节边界不同")
        value = json.loads(row.result_json)
        serialized, content_hash, size = bounded_result(value)
        if serialized != row.result_json or content_hash != row.content_hash or content_hash != reference.content_hash or size != row.result_bytes or size != reference.result_bytes:
            raise ValueError("排班完整结果哈希或容量不同")
        snapshot = json.loads(run.input_json)
        context = expand_context(db, snapshot["payload"]["context"])
        checked = validate_generation(
            value,
            json.loads(run.evidence_json),
            roster_source=context["roster_source"],
            instructions_digest=hashlib.sha256((snapshot["system_prompt"] + "\n\n" + snapshot["task_prompt"]).encode()).hexdigest(),
            model_version=snapshot["provider_snapshot"]["model"],
        )
        return checked.model_dump(mode="json")
    except (HTTPException, AIExecutionError, ValueError, TypeError, KeyError, AttributeError, UnicodeError, OverflowError, RecursionError) as exc:
        raise HTTPException(409, "排班完整结果、租约、原计划或固定优化证明核对失败，未展示损坏结果") from exc
