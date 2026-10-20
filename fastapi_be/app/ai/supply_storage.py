"""Complete supply proofs: bounded SQL blobs and lease-bound short references.

This module never commits. The worker accepts the pointer, success state, blob and
audit in one transaction after locking current authority and every original.
"""

import hashlib
import json
import re
from typing import Literal

from fastapi import HTTPException
from pydantic import Field, field_validator

from app.ai.supply_contract import SHA256, StrictModel, canonical_json, hash_content, identity, utc
from app.ai.supply_series_models import RESULT_BYTES, AISupplyRunResult

TEXT_BYTES = 65535


class SupplyResultReference(StrictModel):
    schema_version: Literal["supply_result_ref_v1"]
    run_id: str
    series_id: str
    lease_token: str
    content_hash: SHA256
    result_bytes: int = Field(strict=True, gt=0, le=RESULT_BYTES)
    source_binding_hash: SHA256
    _ids = field_validator("run_id", "series_id", "lease_token")(identity)


def bounded_result(value):
    try:
        serialized = canonical_json(value)
        encoded = serialized.encode("utf-8")
    except (ValueError, TypeError, UnicodeError, RecursionError) as exc:
        raise HTTPException(422, "物资预测完整结果须为有限UTF-8 JSON") from exc
    if not 0 < len(encoded) <= RESULT_BYTES:
        raise HTTPException(422, "物资预测完整结果超过8MiB，未接收或截断")
    return serialized, hashlib.sha256(encoded).hexdigest(), len(encoded)


def _canonical_value(raw, limit):
    if type(raw) is not str or not 0 < len(raw.encode("utf-8")) <= limit:
        raise ValueError("Complete original JSON exceeds its UTF-8 storage boundary")
    value = json.loads(raw)
    if canonical_json(value) != raw:
        raise ValueError("Complete original JSON is not canonical, finite and unique")
    return value


def is_supply_snapshot(snapshot):
    if not isinstance(snapshot, dict):
        raise HTTPException(409, "物资预测冻结任务须为完整JSON对象")
    payload, provider = snapshot.get("payload", {}), snapshot.get("provider_snapshot", {})
    if not isinstance(payload, dict) or not isinstance(provider, dict):
        raise HTTPException(409, "冻结任务的原服务或输入无效")
    context, values = payload.get("context", {}), payload.get("input", {})
    if not isinstance(context, dict) or not isinstance(values, dict):
        raise HTTPException(409, "物资预测原上下文或引用结构无效")
    return bool({"supply_binding", "supply_source", "supply_series"} & context.keys()) or "supply_series_id" in values or str(provider.get("model", "")).startswith("supply:")


def load_snapshot(run):
    """Reconstruct all short frozen anchors without trusting matching new hashes."""
    from app.ai.governance import digest
    from app.ai.supply_context import SupplyContextBinding, _short_context, selection, supply_evidence

    try:
        snapshot = _canonical_value(run.input_json, TEXT_BYTES)
        metadata = _canonical_value(run.context_metadata_json, TEXT_BYTES)
        evidence = _canonical_value(run.evidence_json, TEXT_BYTES)
        payload = snapshot["payload"]
        context = payload["context"]
        bound = SupplyContextBinding.model_validate(context["supply_binding"])
        binding = bound.model_dump(mode="json")
        if canonical_json(binding) != canonical_json(context["supply_binding"]):
            raise ValueError("Typed original binding must preserve exact JSON scalar types")
        identity(run.run_id)
        if run.feature_key != "supply_forecast" or run.patient_id is not None or run.encounter_ref is not None:
            raise ValueError("Supply quantity series cannot mix individual patient/task scope")
        if type(snapshot["system_prompt"]) is not str or type(snapshot["task_prompt"]) is not str:
            raise ValueError("Complete original prompts must be text")
        if digest([snapshot["system_prompt"], snapshot["task_prompt"]]) != run.prompt_hash or digest(context) != run.context_digest or metadata["context_digest"] != run.context_digest:
            raise ValueError("Original prompts or context digest differs")
        if digest({key: value for key, value in context.items() if key != "snapshot_time"}) != metadata["clinical_context_fingerprint"] or digest(payload["tools"]) != metadata["tool_fingerprint"]:
            raise ValueError("Original complete scope or tools differ")
        if payload["tools"] != {} or payload["evidence"] != evidence or evidence != [supply_evidence(binding)]:
            raise ValueError("Supply needs exactly its reconstructible original evidence and no tools")
        if type(metadata["source_count"]) is not int or metadata["source_count"] != 1 or type(metadata["feature_revision"]) is not int or metadata["feature_revision"] < 1:
            raise ValueError("Original source count or feature revision differs")
        if selection(payload["input"]) != (bound.series_id, bound.horizon_days):
            raise ValueError("Original selected series differs")
        utc(context["snapshot_time"])
        expected_context = _short_context(binding, context["snapshot_time"])
        if canonical_json(context) != canonical_json(expected_context):
            raise ValueError("Original short context contains a different scope, body or missing-data declaration")
        for name, expected in (("snapshot_time", context["snapshot_time"]), ("missing_data", expected_context["missing_data"]), ("department_ids", [])):
            if canonical_json(metadata[name]) != canonical_json(expected):
                raise ValueError("Original metadata differs from frozen context")
        provider = snapshot["provider_snapshot"]
        if (
            type(provider["provider_id"]) is not int
            or provider["provider_id"] != run.provider_id
            or type(provider["revision"]) is not int
            or provider["revision"] != run.provider_revision
            or provider["revision"] < 1
            or provider["kind"] != "specialist"
            or type(provider["model"]) is not str
            or re.fullmatch(r"supply:[a-f0-9]{64}", provider["model"]) is None
        ):
            raise ValueError("Original provider identity differs")
        validation = snapshot["feature_validation"]
        if type(validation["feature_revision"]) is not int or validation["feature_revision"] != metadata["feature_revision"] or validation["status"] != metadata["validation_status"]:
            raise ValueError("Original feature-validation revision differs")
        return snapshot, metadata, evidence, binding
    except (HTTPException, ValueError, TypeError, KeyError, AttributeError, UnicodeError, OverflowError, RecursionError) as exc:
        raise HTTPException(409, "物资预测任务的完整原序列、Prompt、范围或证据绑定无效") from exc


def run_binding(run):
    return load_snapshot(run)[3]


def lock_run_scope(db, run):
    """Serialize against all same-SKU original writes before locking the run."""
    from app.ai.supply_sources import lock_supply_scope
    from app.models import User

    binding = run_binding(run)
    actor = db.query(User).filter_by(user_id=run.requested_by).populate_existing().one_or_none()
    if actor is None:
        raise HTTPException(403, "物资预测任务用户已经失效")
    actor, _ = lock_supply_scope(db, actor, binding["item_kind"], binding["item_id"], require_active=True)
    return actor


def _lock_lease(db, run, lease):
    """Read database state without refreshing pending token/latency fields away."""
    from app.ai.models import AIRun

    try:
        identity(lease)
        identity(run.run_id)
    except (ValueError, TypeError, AttributeError) as exc:
        raise HTTPException(409, "物资预测执行租约或任务标识无效") from exc
    fields = (
        "feature_key",
        "provider_id",
        "provider_revision",
        "requested_by",
        "preview",
        "patient_id",
        "encounter_ref",
        "prompt_hash",
        "context_digest",
        "input_json",
        "evidence_json",
        "context_metadata_json",
    )
    with db.no_autoflush:
        row = db.query(AIRun.status, AIRun.lease_token, *(getattr(AIRun, key) for key in fields)).filter(AIRun.run_id == run.run_id).with_for_update().one_or_none()
    if row is None or row.status != "running" or row.lease_token != lease or run.status != "running" or run.lease_token != lease or any(getattr(row, key) != getattr(run, key) for key in fields):
        raise HTTPException(409, "只有数据库中仍有效的当前执行租约可接收物资预测结果")


def _stage_blob(db, run, lease, binding, value):
    """SQL-only staging primitive; caller must first authorize and recompute."""
    from app.ai.governance import audit
    from app.ai.models import utcnow

    _lock_lease(db, run, lease)
    if canonical_json(run_binding(run)) != canonical_json(binding):
        raise HTTPException(409, "物资预测原短引用不同")
    serialized, content_hash, size = bounded_result(value)
    if db.query(AISupplyRunResult.run_id).filter_by(run_id=run.run_id).first() is not None or any(isinstance(row, AISupplyRunResult) and row.run_id == run.run_id for row in db.new):
        raise HTTPException(409, "物资预测完整结果已经接收，不可覆盖")
    reference = SupplyResultReference(
        schema_version="supply_result_ref_v1",
        run_id=run.run_id,
        series_id=binding["series_id"],
        lease_token=lease,
        content_hash=content_hash,
        result_bytes=size,
        source_binding_hash=hash_content(binding),
    ).model_dump(mode="json")
    db.add(
        AISupplyRunResult(
            run_id=run.run_id,
            series_id=binding["series_id"],
            lease_token=lease,
            schema_version="supply_complete_result_v1",
            source_binding_hash=reference["source_binding_hash"],
            content_hash=content_hash,
            result_json=serialized,
            result_bytes=size,
            created_at=utcnow(),
        )
    )
    audit(db, run.requested_by, "run.supply_result.accept", run.run_id, {key: reference[key] for key in ("content_hash", "result_bytes", "source_binding_hash")})
    return canonical_json(reference)


def _verify_result(value, snapshot, evidence, source):
    from app.ai.gateway import validate_generation

    return validate_generation(
        value,
        evidence,
        supply_source=source,
        supply_horizon=snapshot["payload"]["context"]["supply_binding"]["horizon_days"],
        instructions_digest=hashlib.sha256((snapshot["system_prompt"] + "\n\n" + snapshot["task_prompt"]).encode("utf-8")).hexdigest(),
        model_version=snapshot["provider_snapshot"]["model"],
    ).model_dump(mode="json")


def stage_result(db, run, lease, value):
    from app.ai.catalog import FEATURE_BY_KEY
    from app.ai.models import AIFeatureConfig, AIProvider
    from app.ai.runtime import check_configuration, provider_snapshot
    from app.ai.supply_series import authorize_series

    snapshot, metadata, evidence, binding = load_snapshot(run)
    actor = lock_run_scope(db, run)
    _lock_lease(db, run, lease)
    config = db.query(AIFeatureConfig).filter_by(feature_key=run.feature_key).populate_existing().with_for_update().one_or_none()
    provider = db.query(AIProvider).filter_by(provider_id=run.provider_id).populate_existing().with_for_update().one_or_none()
    if config is None or config.revision != metadata["feature_revision"] or provider is None or provider.revision != run.provider_revision:
        raise HTTPException(409, "物资预测最终接收时原功能或模型版本已经变化")
    if check_configuration(db, actor, FEATURE_BY_KEY[run.feature_key], config, bool(run.preview)) is not provider or provider_snapshot(provider) != snapshot["provider_snapshot"]:
        raise HTTPException(409, "物资预测最终接收时模型或适用权限已经变化")
    _, _, source = authorize_series(db, actor, binding["series_id"], binding["horizon_days"], binding=binding, locking=True)
    bounded_result(value)
    checked = _verify_result(value, snapshot, evidence, source)
    if canonical_json(checked) != canonical_json(value):
        raise HTTPException(409, "物资预测完整结果不得含类型转换或未核实字段")
    return _stage_blob(db, run, lease, binding, checked)


def _read_blob(db, run):
    reference = SupplyResultReference.model_validate(_canonical_value(run.result_json, TEXT_BYTES))
    if canonical_json(reference.model_dump(mode="json")) != run.result_json:
        raise ValueError("Complete-result reference changes JSON scalar types")
    binding = run_binding(run)
    if (
        run.status != "succeeded"
        or reference.run_id != run.run_id
        or reference.series_id != binding["series_id"]
        or reference.lease_token != run.lease_token
        or reference.source_binding_hash != hash_content(binding)
    ):
        raise ValueError("Original result status, lease, series or binding differs")
    row = db.query(AISupplyRunResult).filter_by(run_id=run.run_id).populate_existing().one_or_none()
    if (
        row is None
        or row.schema_version != "supply_complete_result_v1"
        or row.series_id != reference.series_id
        or row.lease_token != reference.lease_token
        or row.source_binding_hash != reference.source_binding_hash
        or type(row.result_bytes) is not int
    ):
        raise ValueError("Complete original result is absent or differently bound")
    value = _canonical_value(row.result_json, RESULT_BYTES)
    serialized, content_hash, size = bounded_result(value)
    if serialized != row.result_json or content_hash != row.content_hash or content_hash != reference.content_hash or size != row.result_bytes or size != reference.result_bytes:
        raise ValueError("Complete original result digest or UTF-8 size differs")
    return value


def expand_result(db, run):
    from app.ai.gateway import AIExecutionError
    from app.ai.supply_context import expand_context

    try:
        value = _read_blob(db, run)
        snapshot, _, evidence, _ = load_snapshot(run)
        context = expand_context(db, snapshot["payload"]["context"])
        checked = _verify_result(value, snapshot, evidence, context["supply_source"])
        if canonical_json(checked) != canonical_json(value):
            raise ValueError("Complete result types differ from its original stored JSON")
        return checked
    except (HTTPException, AIExecutionError, ValueError, TypeError, KeyError, AttributeError, UnicodeError, OverflowError, RecursionError) as exc:
        raise HTTPException(409, "物资预测完整结果、租约、原序列或固定预测配方核对失败，未展示损坏结果") from exc
