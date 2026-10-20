"""Complete SOFA results live in bounded MEDIUMTEXT, bound to the accepted lease."""

import hashlib
import json
from typing import Literal

from fastapi import HTTPException
from pydantic import Field

from app.ai.sofa_contract import StrictModel, canonical_json, hash_content
from app.ai.sofa_models import RESULT_BYTES, AISofaRunResult


class SofaResultReference(StrictModel):
    schema_version: Literal["sofa_result_ref_v1"]
    run_id: str = Field(pattern=r"^[a-f0-9-]{36}$")
    lease_token: str = Field(pattern=r"^[a-f0-9-]{36}$")
    content_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    result_bytes: int = Field(gt=0, le=RESULT_BYTES)
    source_binding_hash: str = Field(pattern=r"^[a-f0-9]{64}$")


def bounded_result(value):
    """Count actual UTF-8 bytes of the complete envelope, never truncate fields."""
    try:
        serialized = canonical_json(value)
        encoded = serialized.encode("utf-8")
    except (ValueError, TypeError, UnicodeError, RecursionError) as exc:
        raise HTTPException(422, "SOFA完整结果不是可保存的有限UTF-8 JSON") from exc
    if not encoded or len(encoded) > RESULT_BYTES:
        raise HTTPException(422, "SOFA完整结果超过8MiB存储上限，未接收或截断")
    return serialized, hashlib.sha256(encoded).hexdigest(), len(encoded)


def run_binding(run):
    from app.ai.sofa_context import SofaBinding

    try:
        binding = SofaBinding.model_validate(json.loads(run.input_json)["payload"]["context"]["sofa_binding"])
        if run.feature_key != "sepsis_risk" or binding.patient_id != run.patient_id or binding.admission_id != run.encounter_ref:
            raise ValueError("SOFA任务原患者或住院不符")
        return binding.model_dump(mode="json")
    except (ValueError, TypeError, KeyError, AttributeError, RecursionError) as exc:
        raise HTTPException(409, "SOFA任务完整原件的冻结引用无效") from exc


def stage_result(db, run, lease, value):
    """Caller holds the running lease row lock and commits result/state/audit atomically."""
    from app.ai.governance import audit
    from app.ai.models import utcnow

    if run.status != "running" or run.lease_token != lease:
        raise HTTPException(409, "SOFA结果仅能由当前执行租约接收")
    binding = run_binding(run)
    serialized, content_hash, result_bytes = bounded_result(value)
    if db.query(AISofaRunResult.run_id).filter_by(run_id=run.run_id).first() is not None:
        raise HTTPException(409, "SOFA完整结果已经接收，不可覆盖")
    row = AISofaRunResult(
        run_id=run.run_id, lease_token=lease, schema_version="sofa_complete_result_v1", content_hash=content_hash, result_json=serialized, result_bytes=result_bytes, created_at=utcnow()
    )
    reference = SofaResultReference(
        schema_version="sofa_result_ref_v1",
        run_id=run.run_id,
        lease_token=lease,
        content_hash=content_hash,
        result_bytes=result_bytes,
        source_binding_hash=hash_content(binding),
    ).model_dump(mode="json")
    db.add(row)
    audit(db, run.requested_by, "run.sofa_result.accept", run.run_id, {"content_hash": content_hash, "result_bytes": result_bytes, "source_binding_hash": reference["source_binding_hash"]})
    return canonical_json(reference)


def expand_result(db, run):
    """Authorization precedes expansion; verify bytes, lease and the frozen source binding."""
    try:
        reference = SofaResultReference.model_validate(json.loads(run.result_json))
        if run.status != "succeeded" or reference.run_id != run.run_id or reference.lease_token != run.lease_token or reference.source_binding_hash != hash_content(run_binding(run)):
            raise ValueError("SOFA原执行租约、结果状态或原件引用不符")
        row = db.query(AISofaRunResult).filter_by(run_id=run.run_id).populate_existing().one_or_none()
        if row is None or row.lease_token != reference.lease_token or row.schema_version != "sofa_complete_result_v1":
            raise ValueError("SOFA完整结果正文或租约丢失")
        if not isinstance(row.result_json, str) or len(row.result_json.encode("utf-8")) > RESULT_BYTES:
            raise ValueError("SOFA完整结果超出边界")
        value = json.loads(row.result_json)
        serialized, content_hash, size = bounded_result(value)
        if serialized != row.result_json or content_hash != row.content_hash or content_hash != reference.content_hash or size != row.result_bytes or size != reference.result_bytes:
            raise ValueError("SOFA完整结果正文或字节摘要不符")
        binding = run_binding(run)
        from app.ai.schemas import SofaChangeGenerationResult, SofaGenerationResult

        schema = SofaGenerationResult if binding["kind"] == "daily" else SofaChangeGenerationResult
        result = schema.model_validate(value).model_dump(mode="json")
        native = result["sofa_analysis" if binding["kind"] == "daily" else "sofa_change_analysis"]
        native_binding = native["source_binding"]
        if any(native_binding[key] != binding[key] for key in ("source_id", "content_hash", "projection_hash", "recipe_digest", "policy_digest")):
            raise ValueError("SOFA结果原件绑定与冻结任务不符")
        from app.ai.gateway import AIExecutionError, validate_generation
        from app.ai.sofa_context import expand_context

        snapshot = json.loads(run.input_json)
        context = expand_context(db, snapshot["payload"]["context"])
        try:
            checked = validate_generation(
                value,
                json.loads(run.evidence_json),
                sofa_source=context.get("sofa_source"),
                sofa_change_source=context.get("sofa_change_source"),
                instructions_digest=hashlib.sha256((snapshot["system_prompt"] + "\n\n" + snapshot["task_prompt"]).encode()).hexdigest(),
                model_version=snapshot["provider_snapshot"]["model"],
            )
        except AIExecutionError as exc:
            raise ValueError("SOFA完整原件重算或固定说明与保存结果不符") from exc
        if checked.model_dump(mode="json") != result:
            raise ValueError("SOFA结果严格重算结构不符")
        return result
    except (HTTPException, ValueError, TypeError, KeyError, AttributeError, UnicodeError, OverflowError, RecursionError) as exc:
        raise HTTPException(409, "SOFA完整结果、租约、字节容量或来源绑定校验失败，未展示损坏或截断结果") from exc
