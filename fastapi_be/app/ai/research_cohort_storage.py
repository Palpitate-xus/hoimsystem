"""Split source artifact foundation, with research authorization before TEXT.

These synchronous helpers never commit, dispatch HTTP or manufacture a usage
receipt. The caller owns rollback/commit. Dedicated queue/worker/receipt/result
acceptance is a later integration; none is implied by a stored source artifact.
"""

import hashlib
import json
import math

from fastapi import HTTPException

from app.ai.research_cohort_artifact_models import ARTIFACT_SCHEMA, BINDING_BYTES, FRAME_BYTES, AIResearchCohortRunArtifact
from app.ai.research_cohort_cases import authorize_case, binding_for, case_current
from app.ai.research_cohort_contract import canonical_json
from app.ai.research_cohort_draft import MAX_BYTES, checked_source, digest
from app.ai.research_cohort_prompt import RESEARCH_SYSTEM_PROMPT, RESEARCH_TASK_VERSION, instructions_for, packaged_task_prompt
from app.ai.research_cohort_protocol import _nonfinite, _object, model_wire
from app.ai.research_cohort_sources import utc_text, utcnow
from app.ai.research_cohort_write_guard import current_actor, current_research_rows, lock_research_write

FEATURE = "research_cohort"
RAW_FIELDS = ("input_json", "evidence_json", "context_metadata_json")


def _sha(raw):
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _json(raw, maximum):
    try:
        if type(raw) is not str or not 0 < len(raw.encode("utf-8")) <= maximum:
            raise ValueError("Whole exact stored UTF8 bytes must fit")
        return json.loads(raw, object_pairs_hook=_object, parse_constant=_nonfinite)
    except (ValueError, TypeError, UnicodeError, RecursionError) as exc:
        raise HTTPException(409, "研究分件原始JSON不完整、重复键或超过既定预算") from exc


def _roles(raw):
    from app.dependencies import VALID_USER_ROLES

    values = _json(raw, 65535)
    if type(values) is not list or any(type(value) is not str or value not in VALID_USER_ROLES for value in values) or len(set(values)) != len(values):
        raise HTTPException(409, "当前科研功能角色配置不是明确闭集")
    return sorted(values)


def _configuration(db, actor, *, preview):
    from app.ai.catalog import CATALOG_VERSION
    from app.ai.models import AIFeatureConfig, AIPromptVersion, AIProvider
    from app.config import settings

    config = current_research_rows(db.query(AIFeatureConfig).filter_by(feature_key=FEATURE), shared=True).one_or_none()
    if config is None:
        raise HTTPException(409, "科研功能尚未配置；来源授权不等于启用模型")
    roles = _roles(config.allowed_roles_json)
    if actor.user_role != "super_admin" and actor.user_role not in roles:
        raise HTTPException(403, "当前身份不在科研功能明确允许角色中")
    if preview and actor.user_role != "super_admin":
        raise HTTPException(403, "仅当前超级管理员可创建配置预览；研究权限仍逐项必需")
    if not preview and (config.enabled != 1 or config.validation_status != "validated"):
        raise HTTPException(409, "科研模型功能未启用或尚未记录当前范围验证")
    provider = current_research_rows(db.query(AIProvider).filter_by(provider_id=config.provider_id), shared=True).one_or_none()
    prompt = current_research_rows(db.query(AIPromptVersion).filter_by(prompt_id=config.active_prompt_id), shared=True).one_or_none() if config.active_prompt_id is not None else None
    if provider is None or provider.enabled != 1 or provider.allows_patient_data != 1 or provider.kind not in {"chat", "responses"} or provider.revision < 1:
        raise HTTPException(409, "模型服务未明确启用或未允许处理受授权资料")
    if (
        provider.model is None
        or not provider.model.strip()
        or type(provider.timeout_seconds) is not int
        or not 1 <= provider.timeout_seconds <= 300
        or type(provider.max_output_tokens) is not int
        or not 1 <= provider.max_output_tokens <= 1000000
        or not math.isfinite(float(provider.temperature))
    ):
        raise HTTPException(409, "实际Provider模型或数值参数不是有效闭集")
    if config.revision < 1 or config.active_prompt_id is not None and (prompt is None or prompt.feature_key != FEATURE or prompt.version < 1):
        raise HTTPException(409, "科研实际不可变Prompt版本或功能修订不一致")
    task = prompt.task_prompt if prompt is not None else packaged_task_prompt()
    instructions = instructions_for(task)
    provider_snapshot = {name: getattr(provider, name) for name in ("provider_id", "revision", "name", "kind", "api_base", "model", "timeout_seconds", "max_output_tokens", "validation_report")}
    provider_snapshot.update(temperature=float(provider.temperature), allows_patient_data=True, effective_output_limit=min(provider.max_output_tokens, settings.AI_MAX_OUTPUT_TOKENS))
    prompt_snapshot = {
        "schema_version": "research_prompt_snapshot_v1",
        "prompt_id": prompt.prompt_id if prompt is not None else None,
        "prompt_version": prompt.version if prompt is not None else 0,
        "origin": "database_version" if prompt is not None else "packaged_catalog",
        "catalog_version": CATALOG_VERSION,
        "native_task_version": RESEARCH_TASK_VERSION,
        "system_prompt": RESEARCH_SYSTEM_PROMPT,
        "task_prompt": task,
        "instructions_digest": _sha(instructions),
    }
    execution = {
        "schema_version": "research_execution_snapshot_v1",
        "feature_key": FEATURE,
        "configuration": {"revision": config.revision, "enabled": config.enabled, "allowed_roles": roles, "daily_limit": config.daily_limit, "active_prompt_id": config.active_prompt_id},
        "provider_snapshot": provider_snapshot,
        "feature_validation": {
            "status": config.validation_status,
            "note": config.validation_note,
            "validated_by": config.validated_by,
            "validated_at": utc_text(config.validated_at),
            "feature_revision": config.revision,
        },
    }
    return prompt_snapshot, execution


def _parts(source, binding, prompt, execution, question):
    short = {
        "schema_version": "research_cohort_task_ref_v1",
        "research_cohort_case_id": binding["case_id"],
        "source_projection_hash": digest(source),
        "source_binding_hash": digest(binding),
        "prompt_snapshot_hash": digest(prompt),
        "execution_snapshot_hash": digest(execution),
        "question": question,
    }
    evidence = [{"kind": "recorded_research_cohort", "source_id": source["source_id"], "source_projection_hash": digest(source), "source_binding_hash": digest(binding)}]
    metadata = {
        "schema_version": "research_cohort_task_metadata_v1",
        "case_id": binding["case_id"],
        "scope_id": binding["scope_id"],
        "source_id": source["source_id"],
        "scope_token": source["scope_token"],
        "public_manifest_hash": source["member_manifest_hash"],
        "instructions_digest": prompt["instructions_digest"],
        "model_version": execution["provider_snapshot"]["model"],
    }
    context = {"source_binding": binding, "question": question, "instructions_digest": prompt["instructions_digest"], "execution_snapshot_hash": digest(execution)}
    return dict(zip(RAW_FIELDS, (canonical_json(short), canonical_json(evidence), canonical_json(metadata)), strict=True)), digest(context)


def opaque_locator(db, run_id):
    """Gate must precede this sole current SHARE locator, never private TEXT."""
    return current_research_rows(
        db.query(AIResearchCohortRunArtifact.run_id, AIResearchCohortRunArtifact.case_id, AIResearchCohortRunArtifact.scope_id, AIResearchCohortRunArtifact.requested_by).filter_by(run_id=run_id),
        shared=True,
    ).one_or_none()


def _frame_proof_impl(artifact):
    source = checked_source(_json(artifact.source_json, MAX_BYTES))
    binding = _json(artifact.source_binding_json, BINDING_BYTES)
    prompt = _json(artifact.prompt_snapshot_json, FRAME_BYTES)
    execution = _json(artifact.execution_snapshot_json, FRAME_BYTES)
    if type(binding) is not dict or type(prompt) is not dict or type(execution) is not dict:
        raise HTTPException(409, "研究分件冻结证明须为完整闭集对象")
    expected_prompt = {"schema_version", "prompt_id", "prompt_version", "origin", "catalog_version", "native_task_version", "system_prompt", "task_prompt", "instructions_digest"}
    expected_execution = {"schema_version", "feature_key", "configuration", "provider_snapshot", "feature_validation"}
    if (
        set(prompt) != expected_prompt
        or set(execution) != expected_execution
        or prompt["schema_version"] != "research_prompt_snapshot_v1"
        or execution["schema_version"] != "research_execution_snapshot_v1"
        or execution["feature_key"] != FEATURE
    ):
        raise HTTPException(409, "研究Prompt或执行快照不是原闭集协议")
    if (
        prompt["system_prompt"] != RESEARCH_SYSTEM_PROMPT
        or prompt["instructions_digest"] != _sha(instructions_for(prompt["task_prompt"]))
        or prompt["prompt_id"] != artifact.prompt_id
        or prompt["prompt_version"] != artifact.prompt_version
    ):
        raise HTTPException(409, "科研固定System、完整Task或原Prompt版本不一致")
    if (
        artifact.schema_version != ARTIFACT_SCHEMA
        or artifact.source_bytes != len(artifact.source_json.encode("utf-8"))
        or artifact.source_projection_hash != digest(source)
        or artifact.source_projection_hash != _sha(artifact.source_json)
    ):
        raise HTTPException(409, "完整研究Source的原UTF8字节或公开投影SHA不一致")
    hashes = {"source_binding_hash": binding, "prompt_snapshot_hash": prompt, "execution_snapshot_hash": execution}
    if any(getattr(artifact, key) != digest(value) for key, value in hashes.items()) or artifact.instructions_digest != prompt["instructions_digest"]:
        raise HTTPException(409, "研究分件冻结锚被替换或不完整")
    return source, binding, prompt, execution


def _frame_proof(artifact):
    try:
        return _frame_proof_impl(artifact)
    except (ValueError, TypeError, KeyError, AttributeError, UnicodeError, RecursionError) as exc:
        raise HTTPException(409, "科研分件的原冻结协议、类型或完整字节损坏") from exc


def load_artifact(db, user, run_id, *, audit_only=False, execution=False):
    """Actual owner/current research scope BEFORE Run or Artifact body SELECT.

    Even explicit Super audit needs current independent patient research access.
    Audit may inspect an own technically revoked Case but never restore a lost
    research permission. New execution always uses the stricter current path.
    """
    from app.ai.models import AIAuditEvent, AIFeatureConfig, AIRun

    actor = lock_research_write(db, user)
    if type(audit_only) is not bool or type(execution) is not bool or audit_only and (actor.user_role != "super_admin" or execution):
        raise HTTPException(403, "冻结审计不能变成执行或绕过真实研究授权")
    locator = opaque_locator(db, run_id)
    if locator is None:
        raise HTTPException(404, "科研任务分件不存在")
    if actor.user_id != locator.requested_by and actor.user_role != "super_admin":
        raise HTTPException(403, "没有读取该科研任务的权限")
    if actor.user_role != "super_admin":
        config = current_research_rows(db.query(AIFeatureConfig.allowed_roles_json).filter_by(feature_key=FEATURE), shared=True).one_or_none()
        if config is None or actor.user_role not in _roles(config.allowed_roles_json):
            raise HTTPException(403, "当前身份不再有该科研任务的功能读取权限")
    if execution:
        case, _, current_source = authorize_case(db, actor, locator.case_id, external_model=True, execution=True)
    else:
        case = case_current(db, actor, locator.case_id, audit_only=audit_only)
        current_source = case["public_source"]
        if case["snapshot"] is None or current_source is None or not audit_only and not case["parent_current"]:
            raise HTTPException(403, "当前项目ACL或逐患者权限/原来源不允许读取科研任务正文")
    # Only after the actual Source authorizer may either private task be loaded.
    run = current_research_rows(db.query(AIRun).filter_by(run_id=run_id), shared=True).one_or_none()
    artifact = current_research_rows(db.query(AIResearchCohortRunArtifact).filter_by(run_id=run_id), shared=True).one()
    if (
        run is None
        or run.feature_key != FEATURE
        or run.requested_by != locator.requested_by
        or run.patient_id is not None
        or run.encounter_ref is not None
        or run.requested_by != artifact.requested_by
    ):
        raise HTTPException(409, "科研Run与独立分件真实FK/owner不一致，不降级为通用任务")
    source, binding, prompt, frozen_execution = _frame_proof(artifact)
    if source != current_source or binding != binding_for(case, current_source) or artifact.case_id != case["case_id"] or artifact.scope_id != case["scope_id"]:
        raise HTTPException(409, "科研任务的全Source、项目、Case或完整集合冻结锚不一致")
    raw = {field: getattr(run, field) for field in RAW_FIELDS}
    parsed = {field: _json(value, 65535) for field, value in raw.items()}
    if type(parsed["input_json"]) is not dict or "question" not in parsed["input_json"]:
        raise HTTPException(409, "科研短任务引用不完整")
    question = parsed["input_json"]["question"]
    if question is not None and (type(question) is not str or len(question) > 2000 or len(question.encode("utf-8")) > 8000):
        raise HTTPException(409, "科研任务原问题不是有界完整字符串")
    expected, context_hash = _parts(source, binding, prompt, frozen_execution, parsed["input_json"]["question"])
    if (
        raw != expected
        or artifact.context_digest != context_hash
        or run.context_digest != context_hash
        or run.prompt_hash != artifact.instructions_digest
        or run.prompt_version != artifact.prompt_version
        or run.provider_id != artifact.provider_id
        or run.provider_revision != artifact.provider_revision
    ):
        raise HTTPException(409, "科研raw3原字节或Run冻结Prompt/Provider上下文不一致")
    if any(getattr(artifact, hash_key) != _sha(raw[field]) for hash_key, field in zip(("input_hash", "evidence_hash", "metadata_hash"), RAW_FIELDS, strict=True)):
        raise HTTPException(409, "科研短任务原始TEXT SHA不一致")
    created = current_research_rows(db.query(AIAuditEvent).filter_by(event_id=artifact.created_audit_event_id), shared=True).one_or_none()
    detail = canonical_json(
        {
            key: getattr(artifact, key)
            for key in ("case_id", "source_projection_hash", "source_binding_hash", "prompt_snapshot_hash", "execution_snapshot_hash", "context_digest", "input_hash", "evidence_hash", "metadata_hash")
        }
    )
    if created is None or created.actor_id != artifact.requested_by or created.target != run_id or created.action != "research.task.artifact.create" or created.detail_json != detail:
        raise HTTPException(409, "科研创建回执不是原具体AuditPK或内容已变")
    if execution:
        if _configuration(db, actor, preview=bool(run.preview)) != (prompt, frozen_execution):
            raise HTTPException(409, "科研当前配置、Provider或Prompt版本已变化，未继续旧冻结执行")
        model_wire(source, parsed["input_json"]["question"], prompt["task_prompt"])
    return run, artifact, case, source


def freeze_artifact(db, user, run_id, case_id, *, question=None):
    """Stage initial source artifact + short raw3 + exact creation audit, no commit.

    Credential availability, transport readiness and daily quota remain mandatory
    responsibilities of the future dedicated create/execute service.
    """
    from app.ai.models import AIAuditEvent, AIRun

    actor = lock_research_write(db, user)
    case, _, source = authorize_case(db, actor, case_id, external_model=True, execution=True)
    header = current_research_rows(db.query(AIRun.preview).filter_by(run_id=run_id), shared=True).one_or_none()
    if header is None:
        raise HTTPException(404, "实际科研Run不存在")
    if type(header.preview) is not int or header.preview not in {0, 1}:
        raise HTTPException(409, "原科研Run预览标志不是实际0/1")
    prompt, execution = _configuration(db, actor, preview=bool(header.preview))
    model_wire(source, question, prompt["task_prompt"])
    run = current_research_rows(db.query(AIRun).filter_by(run_id=run_id)).one()
    if (
        run.feature_key != FEATURE
        or run.requested_by != actor.user_id
        or run.status != "queued"
        or run.lease_token is not None
        or run.patient_id is not None
        or run.encounter_ref is not None
        or opaque_locator(db, run_id) is not None
    ):
        raise HTTPException(409, "只有原owner的新queued未租约科研任务可登记完整来源")
    binding = binding_for(case, source)
    raw, context = _parts(source, binding, prompt, execution, question)
    if any(len(value.encode("utf-8")) > 65535 for value in raw.values()):
        raise HTTPException(413, "科研raw3短引用超过TEXT真实UTF8预算，未截断")
    blobs = {"source_json": (source, MAX_BYTES), "source_binding_json": (binding, BINDING_BYTES), "prompt_snapshot_json": (prompt, FRAME_BYTES), "execution_snapshot_json": (execution, FRAME_BYTES)}
    serialized = {key: canonical_json(value) for key, (value, _) in blobs.items()}
    if any(len(serialized[key].encode("utf-8")) > maximum for key, (_, maximum) in blobs.items()):
        raise HTTPException(413, "科研完整分件超过各自预算，未拼接裁剪")
    run.provider_id = execution["provider_snapshot"]["provider_id"]
    run.provider_revision = execution["provider_snapshot"]["revision"]
    run.prompt_version = prompt["prompt_version"]
    run.prompt_hash = prompt["instructions_digest"]
    run.context_digest = context
    for field, value in raw.items():
        setattr(run, field, value)
    values = {
        **serialized,
        "run_id": run_id,
        "case_id": case_id,
        "scope_id": case["scope_id"],
        "requested_by": actor.user_id,
        "schema_version": ARTIFACT_SCHEMA,
        "recorded_at": utcnow(),
        "source_bytes": len(serialized["source_json"].encode("utf-8")),
        "source_projection_hash": digest(source),
        "source_binding_hash": digest(binding),
        "prompt_id": prompt["prompt_id"],
        "prompt_version": prompt["prompt_version"],
        "prompt_snapshot_hash": digest(prompt),
        "provider_id": run.provider_id,
        "provider_revision": run.provider_revision,
        "config_revision": execution["configuration"]["revision"],
        "execution_snapshot_hash": digest(execution),
        "instructions_digest": prompt["instructions_digest"],
        "context_digest": context,
        **{key: _sha(raw[field]) for key, field in zip(("input_hash", "evidence_hash", "metadata_hash"), RAW_FIELDS, strict=True)},
        "usage_event_id": None,
    }
    detail = canonical_json(
        {
            key: values[key]
            for key in ("case_id", "source_projection_hash", "source_binding_hash", "prompt_snapshot_hash", "execution_snapshot_hash", "context_digest", "input_hash", "evidence_hash", "metadata_hash")
        }
    )
    audit = AIAuditEvent(actor_id=actor.user_id, action="research.task.artifact.create", target=run_id, detail_json=detail)
    db.add(audit)
    db.flush()
    artifact = AIResearchCohortRunArtifact(**values, created_audit_event_id=audit.event_id)
    db.add(artifact)
    db.flush()
    fresh = current_actor(db, actor)
    event = current_research_rows(db.query(AIAuditEvent).filter_by(event_id=audit.event_id), shared=True).one()
    if event.actor_id != fresh.user_id or event.action != "research.task.artifact.create" or event.target != run_id or event.detail_json != detail:
        raise HTTPException(409, "科研具体创建审计PK回执同事务不一致")
    _, actual, _, _ = load_artifact(db, fresh, run_id, execution=True)
    if {column.name: getattr(actual, column.name) for column in actual.__table__.columns} != {**values, "created_audit_event_id": audit.event_id}:
        raise HTTPException(409, "完整科研Source分件与创建值同事务回读不一致")
    return actual
