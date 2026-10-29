"""Dedicated research task creation and split authorized reads, not shared dispatch.

Local Case eligibility never proves external model permission. All clinical
parts, including Super audit, require current project and patient permissions.
Technical metadata/cancel paths confer no Source, inference or export authority.
"""

import datetime as dt
from typing import Annotated

from fastapi import HTTPException
from pydantic import Field

from app.ai.research_cohort_artifact_models import AIResearchCohortRunArtifact
from app.ai.research_cohort_cases import authorize_case
from app.ai.research_cohort_contract import UUID, StrictModel, canonical_json
from app.ai.research_cohort_draft import MAX_BYTES
from app.ai.research_cohort_gateway import request
from app.ai.research_cohort_receipts import _header, read_usage_event, usage
from app.ai.research_cohort_result_storage import load_result
from app.ai.research_cohort_sources import utc_text, utcnow
from app.ai.research_cohort_storage import FEATURE, _configuration, _json, freeze_artifact, load_artifact, opaque_locator
from app.ai.research_cohort_write_guard import current_research_rows, lock_research_write
from app.sql_counts import locked_row_count


class ResearchRunInput(StrictModel):
    research_cohort_case_id: UUID
    question: Annotated[str, Field(strict=True, max_length=2000)] | None = None


def selection(value):
    try:
        selected = ResearchRunInput.model_validate(value, strict=True)
        if selected.question is not None and len(selected.question.encode("utf-8", errors="strict")) > 8000:
            raise ValueError("The whole question must fit 8000 UTF8 bytes")
        return selected
    except (ValueError, TypeError, UnicodeError) as exc:
        raise HTTPException(422, "科研任务仅接受规范Case引用与2000码点/8000UTF8原问题") from exc


def _fixed_role(actor):
    from app.ai.catalog import FEATURE_BY_KEY

    if actor.user_role not in FEATURE_BY_KEY[FEATURE].default_roles:
        raise HTTPException(403, "当前角色无权使用此功能。")


def _technical_access(db, user, run_id, *, audit_only=False):
    """Gate/current actor -> opaque Artifact SHARE, no Run or clinical TEXT."""
    from app.ai.models import AIFeatureConfig
    from app.ai.research_cohort_storage import _roles

    actor = lock_research_write(db, user)
    if type(audit_only) is not bool or audit_only and actor.user_role != "super_admin":
        raise HTTPException(403, "技术审计须为当前超级管理员的显式操作")
    locator = opaque_locator(db, run_id)
    if locator is None:
        raise HTTPException(404, "科研任务分件不存在")
    if actor.user_role != "super_admin":
        _fixed_role(actor)
        if actor.user_id != locator.requested_by:
            raise HTTPException(403, "不能读取其他账户科研任务")
        config = current_research_rows(db.query(AIFeatureConfig.allowed_roles_json).filter_by(feature_key=FEATURE), shared=True).one_or_none()
        if config is None or actor.user_role not in _roles(config.allowed_roles_json):
            raise HTTPException(403, "当前身份不再具备本功能任务读取权限")
    return actor, locator


def create_research_run(db, user, value, *, preview=False):
    """Current full Source, fixed roles/config/quota and exact artifact, then commit."""
    from app.ai.governance import provider_credential
    from app.ai.models import AIFeatureConfig, AIProvider, AIRun

    try:
        selected = selection(value)
        if type(preview) is not bool:
            raise HTTPException(422, "科研预览标志须为实际布尔值")
        actor = lock_research_write(db, user)
        _fixed_role(actor)
        _, _, source = authorize_case(db, actor, selected.research_cohort_case_id, external_model=True, execution=True)
        config = current_research_rows(db.query(AIFeatureConfig).filter_by(feature_key=FEATURE)).one_or_none()
        if config is None or type(config.daily_limit) is not int or config.daily_limit < 1:
            raise HTTPException(409, "当前科研功能或每日额度尚未明确配置")
        prompt, _ = _configuration(db, actor, preview=preview)
        provider = current_research_rows(db.query(AIProvider).filter_by(provider_id=config.provider_id), shared=True).one()
        provider_credential(provider)
        request(provider, source, selected.question, prompt["task_prompt"])
        clock = utcnow().replace(microsecond=0)
        start = dt.datetime.combine(clock.date(), dt.time.min)
        count_query = db.query(AIRun).filter(AIRun.feature_key == FEATURE, AIRun.requested_by == actor.user_id, AIRun.create_time >= start)
        used = locked_row_count(current_research_rows(count_query, shared=True), AIRun.run_id, aggregate=True)
        if used >= config.daily_limit:
            raise HTTPException(429, "科研功能今日提交额度已用完")
        run = AIRun(
            feature_key=FEATURE,
            requested_by=actor.user_id,
            provider_id=provider.provider_id,
            provider_revision=provider.revision,
            prompt_version=prompt["prompt_version"],
            prompt_hash=prompt["instructions_digest"],
            context_digest="0" * 64,
            preview=int(preview),
            status="queued",
            create_time=clock,
            input_json="{}",
            evidence_json="[]",
            context_metadata_json="{}",
            result_json="{}",
            input_tokens=0,
            output_tokens=0,
        )
        db.add(run)
        db.flush()
        identifier = run.run_id
        freeze_artifact(db, actor, identifier, selected.research_cohort_case_id, question=selected.question)
        expected = {column.name: getattr(run, column.name) for column in run.__table__.columns}
        actual = load_artifact(db, actor, identifier, execution=True)[0]
        if {column.name: getattr(actual, column.name) for column in actual.__table__.columns} != expected or locked_row_count(current_research_rows(count_query, shared=True), AIRun.run_id, aggregate=True) != used + 1:
            raise HTTPException(409, "科研Run原始字段、具体Artifact或实际当前COUNT同事务回读不一致")
        db.commit()
        return identifier
    except Exception:
        db.rollback()
        raise


def describe_research_run(db, user, run_id, *, audit_only=False):
    """Short metadata only; clinical Source/Scope/Result are separate actual reads."""
    actor, locator = _technical_access(db, user, run_id, audit_only=audit_only)
    available, binding = False, None
    try:
        _, artifact, _, _ = load_artifact(db, actor, run_id, audit_only=audit_only)
        binding = _json(artifact.source_binding_json, 32768)
        available = True
    except HTTPException as exc:
        if exc.status_code != 403:
            raise
    header = _header(db, run_id, shared=True)
    if header is None or header["feature_key"] != FEATURE or header["requested_by"] != locator.requested_by:
        raise HTTPException(409, "科研技术Run header与实际Artifact不一致")
    technical = current_research_rows(
        db.query(AIResearchCohortRunArtifact.source_projection_hash, AIResearchCohortRunArtifact.source_binding_hash, AIResearchCohortRunArtifact.usage_event_id).filter_by(run_id=run_id), shared=True
    ).one()
    pending = header["status"] in {"running", "cancelled"} and header["lease_token"] is not None and technical.usage_event_id is None
    if header["status"] == "queued":
        if header["lease_token"] is not None or header["start_time"] is not None or header["finish_time"] is not None or technical.usage_event_id is not None:
            raise HTTPException(409, "排队科研任务已有执行痕迹，不能假称未调用")
        receipt = usage(0, 0, False)
    elif pending:
        receipt = usage(None, None, None)
    else:
        receipt = read_usage_event(db, run_id)["usage"]
    fields = ("run_id", "feature_key", "status", "preview", "error_code", "error_message", "latency_ms", "create_time", "start_time", "finish_time")
    value = {key: utc_text(header[key]) if key in {"create_time", "start_time", "finish_time"} else bool(header[key]) if key == "preview" else header[key] for key in fields}
    value.update(
        schema_version="research_cohort_task_metadata_v1",
        split_artifacts=True,
        research_cohort_case_id=locator.case_id,
        scope_id=locator.scope_id,
        source_projection_hash=technical.source_projection_hash,
        source_binding_hash=technical.source_binding_hash,
        binding=binding,
        clinical_parts_available=available,
        protected_hashes_are_opaque=not available,
        cancellation_pending=pending and header["status"] == "cancelled",
        usage=receipt,
    )
    return value


def list_research_runs(db, user, *, case_id=None, status=None, page=1, size=20, audit_only=False):
    """Technical headers only; a directory row grants no clinical part access."""
    from app.ai.models import AIFeatureConfig, AIRun
    from app.ai.research_cohort_storage import _roles

    if (
        type(page) is not int
        or not 1 <= page <= 100000
        or type(size) is not int
        or not 1 <= size <= 100
        or status is not None
        and status not in {"queued", "running", "succeeded", "failed", "cancelled"}
    ):
        raise HTTPException(422, "科研任务目录须使用明确分页和状态")
    actor = lock_research_write(db, user)
    if type(audit_only) is not bool or audit_only and actor.user_role != "super_admin":
        raise HTTPException(403, "技术审计须为当前超级管理员显式操作")
    if actor.user_role != "super_admin":
        _fixed_role(actor)
        config = current_research_rows(db.query(AIFeatureConfig.allowed_roles_json).filter_by(feature_key=FEATURE), shared=True).one_or_none()
        if config is None or actor.user_role not in _roles(config.allowed_roles_json):
            raise HTTPException(403, "当前身份没有科研任务目录权限")
    artifact = AIResearchCohortRunArtifact
    fields = (
        AIRun.run_id,
        AIRun.feature_key,
        AIRun.status,
        AIRun.preview,
        AIRun.create_time,
        AIRun.finish_time,
        artifact.case_id,
        artifact.scope_id,
        artifact.source_projection_hash,
        artifact.source_binding_hash,
    )
    query = db.query(*fields).join(artifact, artifact.run_id == AIRun.run_id).filter(AIRun.feature_key == FEATURE)
    if actor.user_role != "super_admin":
        query = query.filter(artifact.requested_by == actor.user_id, AIRun.requested_by == actor.user_id)
    if case_id is not None:
        query = query.filter(artifact.case_id == case_id)
    if status is not None:
        query = query.filter(AIRun.status == status)
    total = locked_row_count(current_research_rows(query, shared=True), AIRun.run_id, aggregate=True)
    rows = current_research_rows(query.order_by(AIRun.create_time.desc(), AIRun.run_id).offset((page - 1) * size).limit(size), shared=True).all()
    items = []
    for row in rows:
        item = dict(row._mapping)
        item["preview"] = bool(item["preview"])
        item["create_time"], item["finish_time"] = utc_text(item["create_time"]), utc_text(item["finish_time"])
        item.update(schema_version="research_cohort_task_directory_item_v1", detail_required=True, no_clinical_body_in_directory=True)
        items.append(item)
    return {"items": items, "page": page, "size": size, "total": total}


def read_research_part(db, user, run_id, part, *, audit_only=False):
    """Each requested whole object is <=8MiB, never a duplicated full wrapper."""
    if part not in {"source", "scope", "result", "task"} or type(part) is not str:
        raise HTTPException(422, "只提供明确的Source/Scope/Result/原Task分件")
    run, artifact, case, source = load_artifact(db, user, run_id, audit_only=audit_only)
    if part == "source":
        value = source
    elif part == "scope":
        value = case["snapshot"]
    elif part == "result":
        value = load_result(db, user, run_id, audit_only=audit_only)[1]
    else:
        value = {
            "input_json": run.input_json,
            "evidence_json": run.evidence_json,
            "context_metadata_json": run.context_metadata_json,
            "input_hash": artifact.input_hash,
            "evidence_hash": artifact.evidence_hash,
            "metadata_hash": artifact.metadata_hash,
            "schema_version": "research_cohort_task_part_v1",
            "run_id": run_id,
            "artifact": {
                column.name: utc_text(getattr(artifact, column.name)) if column.name == "recorded_at" else getattr(artifact, column.name)
                for column in artifact.__table__.columns
                if column.name not in {"source_json", "source_binding_json", "prompt_snapshot_json", "execution_snapshot_json"}
            },
            "source_binding": _json(artifact.source_binding_json, 32768),
            "prompt_snapshot": _json(artifact.prompt_snapshot_json, 262144),
            "execution_snapshot": _json(artifact.execution_snapshot_json, 262144),
            # These are actual current/audit Case fields, not manufactured
            # eligibility flags. Scope/Source independently supply two large
            # fields to the same closed Case proof in the client.
            "case_metadata": {key: value for key, value in case.items() if key not in {"snapshot", "public_source"}},
        }
    if len(canonical_json(value).encode("utf-8")) > MAX_BYTES:
        raise HTTPException(413, "完整科研独立分件超过8MiB，未拼接或裁剪")
    return value
