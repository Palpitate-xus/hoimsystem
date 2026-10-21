"""Complete coding drafts: bounded SQL blobs and lease-bound short references.

This module never commits. The worker accepts the pointer, success state, blob and
audit in one transaction after locking current authority and every original.
"""

import hashlib
import json
from typing import Literal

from fastapi import HTTPException
from pydantic import Field, field_validator

from app.ai.coding_evidence_input import SHA as SHA256
from app.ai.coding_evidence_input import StrictModel
from app.ai.coding_evidence_models import MAX_BYTES as RESULT_BYTES
from app.ai.coding_evidence_models import AICodingRunResult
from app.ai.coding_evidence_sources import canonical_json, hash_content
from app.ai.inventory_contract import identity, utc

TEXT_BYTES = 65535


class CodingResultReference(StrictModel):
    schema_version: Literal["coding_result_ref_v1"]
    run_id: str
    case_snapshot_id: str
    lease_token: str
    content_hash: SHA256
    result_bytes: int = Field(strict=True, gt=0, le=RESULT_BYTES)
    source_binding_hash: SHA256
    _ids = field_validator("run_id", "case_snapshot_id", "lease_token")(identity)


def bounded_result(value):
    try:
        serialized = canonical_json(value)
        encoded = serialized.encode("utf-8")
    except (ValueError, TypeError, UnicodeError, RecursionError) as exc:
        raise HTTPException(422, "编码证据完整结果须为有限UTF-8 JSON") from exc
    if not 0 < len(encoded) <= RESULT_BYTES:
        raise HTTPException(422, "编码证据完整结果超过8MiB，未接收或截断")
    return serialized, hashlib.sha256(encoded).hexdigest(), len(encoded)


def _canonical_value(raw, limit):
    if type(raw) is not str or not 0 < len(raw.encode("utf-8")) <= limit:
        raise ValueError("Complete original JSON exceeds its UTF-8 storage boundary")
    value = json.loads(raw)
    if canonical_json(value) != raw:
        raise ValueError("Complete original JSON is not canonical, finite and unique")
    return value


def is_coding_snapshot(snapshot):
    if not isinstance(snapshot, dict):
        raise HTTPException(409, "编码证据冻结任务须为完整JSON对象")
    payload, provider = snapshot.get("payload", {}), snapshot.get("provider_snapshot", {})
    if not isinstance(payload, dict) or not isinstance(provider, dict):
        raise HTTPException(409, "冻结任务的原服务或输入无效")
    context, values = payload.get("context", {}), payload.get("input", {})
    if not isinstance(context, dict) or not isinstance(values, dict):
        raise HTTPException(409, "编码证据原上下文或引用结构无效")
    return bool({"coding_binding", "coding_source", "coding_case"} & context.keys()) or "coding_case_id" in values


def load_snapshot(run):
    """Reconstruct all short frozen anchors without trusting matching new hashes."""
    from app.ai.coding_evidence_context import CodingContextBinding, coding_evidence, selection, short_context
    from app.ai.coding_evidence_prompt import CODING_SYSTEM_PROMPT
    from app.ai.governance import digest

    try:
        snapshot = _canonical_value(run.input_json, TEXT_BYTES)
        metadata = _canonical_value(run.context_metadata_json, TEXT_BYTES)
        if set(metadata) != {
            "context_digest",
            "clinical_context_fingerprint",
            "tool_fingerprint",
            "source_count",
            "department_ids",
            "missing_data",
            "snapshot_time",
            "feature_revision",
            "validation_status",
            "instructions_digest",
            "model_version",
        }:
            raise ValueError("Frozen coding metadata must preserve its complete closed contract")
        evidence = _canonical_value(run.evidence_json, TEXT_BYTES)
        payload = snapshot["payload"]
        context = payload["context"]
        if set(payload) != {"input", "context", "tools", "evidence"} or set(snapshot) != {"catalog_version", "system_prompt", "task_prompt", "payload", "provider_snapshot", "feature_validation"}:
            raise ValueError("Closed complete frozen task fields are required")
        bound = CodingContextBinding.model_validate(context["coding_binding"])
        binding = bound.model_dump(mode="json")
        if canonical_json(binding) != canonical_json(context["coding_binding"]):
            raise ValueError("Typed original binding must preserve exact JSON scalar types")
        identity(run.run_id)
        if run.feature_key != "drg_evidence_review" or run.patient_id != bound.patient_id or run.encounter_ref != bound.admission_id:
            raise ValueError("The Run must bind the same actual patient and Admission as its case")
        if snapshot["system_prompt"] != CODING_SYSTEM_PROMPT or type(snapshot["task_prompt"]) is not str:
            raise ValueError("Complete original fixed output contract and task Prompt are required")
        instructions_digest = hashlib.sha256((snapshot["system_prompt"] + "\n\n" + snapshot["task_prompt"]).encode("utf-8")).hexdigest()
        if metadata.get("instructions_digest") != instructions_digest:
            raise ValueError("Frozen Prompt summary differs from its original complete text")
        if digest([snapshot["system_prompt"], snapshot["task_prompt"]]) != run.prompt_hash or digest(context) != run.context_digest or metadata["context_digest"] != run.context_digest:
            raise ValueError("Original prompts or context digest differs")
        if digest({key: value for key, value in context.items() if key != "snapshot_time"}) != metadata["clinical_context_fingerprint"] or digest(payload["tools"]) != metadata["tool_fingerprint"]:
            raise ValueError("Original complete scope or tools differ")
        if payload["tools"] != {} or payload["evidence"] != evidence or evidence != [coding_evidence(binding)]:
            raise ValueError("Coding requires exactly its reconstructible original evidence and no tools")
        if type(metadata["source_count"]) is not int or metadata["source_count"] != 1 or type(metadata["feature_revision"]) is not int or metadata["feature_revision"] < 1:
            raise ValueError("Original source count or feature revision differs")
        if selection(payload["input"]) != bound.case_snapshot_id:
            raise ValueError("Original selected scenario differs")
        utc(context["snapshot_time"])
        expected_context = short_context(binding, context["snapshot_time"])
        if canonical_json(context) != canonical_json(expected_context):
            raise ValueError("Original short context contains a different scope, body or missing-data declaration")
        for name, expected in (("snapshot_time", context["snapshot_time"]), ("missing_data", expected_context["missing_data"]), ("department_ids", bound.department_ids)):
            if canonical_json(metadata[name]) != canonical_json(expected):
                raise ValueError("Original metadata differs from frozen context")
        provider = snapshot["provider_snapshot"]
        if (
            type(provider["provider_id"]) is not int
            or provider["provider_id"] != run.provider_id
            or type(provider["revision"]) is not int
            or provider["revision"] != run.provider_revision
            or provider["revision"] < 1
            or provider["kind"] not in {"chat", "responses"}
            or type(provider["model"]) is not str
            or not provider["model"]
            or metadata["model_version"] != provider["model"]
        ):
            raise ValueError("Original provider identity differs")
        validation = snapshot["feature_validation"]
        if type(validation["feature_revision"]) is not int or validation["feature_revision"] != metadata["feature_revision"] or validation["status"] != metadata["validation_status"]:
            raise ValueError("Original feature-validation revision differs")
        return snapshot, metadata, evidence, binding
    except (HTTPException, ValueError, TypeError, KeyError, AttributeError, UnicodeError, OverflowError, RecursionError) as exc:
        raise HTTPException(409, "编码证据任务的完整原病案、Prompt、范围或证据绑定无效") from exc


def run_binding(run):
    return load_snapshot(run)[3]


def lock_run_scope(db, run):
    """Gate -> current actor -> actual Home before the execution lease lock."""
    from types import SimpleNamespace

    from app.ai.catalog import FEATURE_BY_KEY
    from app.ai.coding_evidence_guard import lock_coding_gate, lock_coding_write

    with db.no_autoflush:
        lock_coding_gate(db)
        binding = run_binding(run)
        return lock_coding_write(db, SimpleNamespace(user_id=run.requested_by), allowed_roles=FEATURE_BY_KEY["drg_evidence_review"].default_roles, home_ids=[binding["home_id"]])


def _lock_lease(db, run, lease):
    """Read database state without refreshing pending token/latency fields away."""
    from app.ai.models import AIRun

    try:
        identity(lease)
        identity(run.run_id)
    except (ValueError, TypeError, AttributeError) as exc:
        raise HTTPException(409, "编码证据执行租约或任务标识无效") from exc
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
        raise HTTPException(409, "只有数据库中仍有效的当前执行租约可接收编码证据结果")


def _stage_blob(db, run, lease, binding, value):
    """SQL-only staging primitive; caller must first authorize and recompute."""
    from app.ai.governance import audit
    from app.ai.models import utcnow

    _lock_lease(db, run, lease)
    if canonical_json(run_binding(run)) != canonical_json(binding):
        raise HTTPException(409, "编码证据原短引用不同")
    serialized, content_hash, size = bounded_result(value)
    if db.query(AICodingRunResult.run_id).filter_by(run_id=run.run_id).first() is not None or any(isinstance(row, AICodingRunResult) and row.run_id == run.run_id for row in db.new):
        raise HTTPException(409, "编码证据完整结果已经接收，不可覆盖")
    reference = CodingResultReference(
        schema_version="coding_result_ref_v1",
        run_id=run.run_id,
        case_snapshot_id=binding["case_snapshot_id"],
        lease_token=lease,
        content_hash=content_hash,
        result_bytes=size,
        source_binding_hash=hash_content(binding),
    ).model_dump(mode="json")
    db.add(
        AICodingRunResult(
            run_id=run.run_id,
            case_snapshot_id=binding["case_snapshot_id"],
            lease_token=lease,
            schema_version="coding_complete_result_v1",
            source_binding_hash=reference["source_binding_hash"],
            content_hash=content_hash,
            result_json=serialized,
            result_bytes=size,
            created_at=utcnow(),
        )
    )
    audit(db, run.requested_by, "run.coding_result.accept", run.run_id, {key: reference[key] for key in ("content_hash", "result_bytes", "source_binding_hash")})
    return canonical_json(reference)


def _verify_result(value, source, binding):
    from app.ai.coding_evidence_result import validate_result

    return validate_result(value, source, binding["projection_hash"]).model_dump(mode="json")


def stage_result(db, run, lease, value):
    from app.ai.catalog import FEATURE_BY_KEY
    from app.ai.coding_evidence_context import expand_context
    from app.ai.models import AIFeatureConfig, AIProvider
    from app.ai.runtime import check_configuration, provider_snapshot

    snapshot, metadata, _, binding = load_snapshot(run)
    actor = lock_run_scope(db, run)
    _lock_lease(db, run, lease)
    config = db.query(AIFeatureConfig).filter_by(feature_key=run.feature_key).populate_existing().with_for_update().one_or_none()
    provider = db.query(AIProvider).filter_by(provider_id=run.provider_id).populate_existing().with_for_update().one_or_none()
    if config is None or config.revision != metadata["feature_revision"] or provider is None or provider.revision != run.provider_revision:
        raise HTTPException(409, "编码证据最终接收时原功能或模型版本已经变化")
    if check_configuration(db, actor, FEATURE_BY_KEY[run.feature_key], config, bool(run.preview)) is not provider or provider_snapshot(provider) != snapshot["provider_snapshot"]:
        raise HTTPException(409, "编码证据最终接收时模型或适用权限已经变化")
    context = expand_context(db, snapshot["payload"]["context"], user=actor, current=True)
    bounded_result(value)
    checked = _verify_result(value, context["coding_source"], binding)
    if canonical_json(checked) != canonical_json(value):
        raise HTTPException(409, "编码证据完整草稿不得含类型转换或未核实字段")
    return _stage_blob(db, run, lease, binding, checked)


def _read_blob(db, run):
    reference = CodingResultReference.model_validate(_canonical_value(run.result_json, TEXT_BYTES))
    if canonical_json(reference.model_dump(mode="json")) != run.result_json:
        raise ValueError("Complete-result reference changes JSON scalar types")
    binding = run_binding(run)
    if (
        run.status != "succeeded"
        or reference.run_id != run.run_id
        or reference.case_snapshot_id != binding["case_snapshot_id"]
        or reference.lease_token != run.lease_token
        or reference.source_binding_hash != hash_content(binding)
    ):
        raise ValueError("Original result status, lease, scenario or binding differs")
    row = db.query(AICodingRunResult).filter_by(run_id=run.run_id).populate_existing().with_for_update(read=True).one_or_none()
    if (
        row is None
        or row.schema_version != "coding_complete_result_v1"
        or row.case_snapshot_id != reference.case_snapshot_id
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
    from app.ai.coding_evidence_context import expand_context

    try:
        value = _read_blob(db, run)
        snapshot, _, _, binding = load_snapshot(run)
        context = expand_context(db, snapshot["payload"]["context"])
        checked = _verify_result(value, context["coding_source"], binding)
        if canonical_json(checked) != canonical_json(value):
            raise ValueError("Complete result types differ from its original stored JSON")
        return checked
    except (HTTPException, ValueError, TypeError, KeyError, AttributeError, UnicodeError, OverflowError, RecursionError) as exc:
        raise HTTPException(409, "编码证据完整结果、租约、原病案或完整引文核对失败，未展示损坏结果") from exc
