"""Private split artifacts. Current research rights precede every task TEXT read."""

import datetime as dt

from fastapi import HTTPException
from sqlalchemy.orm import defer

from app.ai import deidentification_sources as sources
from app.ai.deidentification_draft import bounded_json, checked_source
from app.ai.deidentification_frozen import verify_frozen_prompt
from app.ai.deidentification_http import parse_json
from app.ai.deidentification_result import validate_result
from app.ai.deidentification_reviews import publication_view
from app.ai.deidentification_run_models import RESULT_SCHEMA, SOURCE_HASH_FIELDS, SOURCE_SCHEMA, AIDeidentificationRunResult, AIDeidentificationRunSource
from app.ai.deidentification_spans import canonical, digest, text_digest, utf8
from app.ai.deidentification_task_access import authorize_locator, run_identifier
from app.ai.deidentification_task_config import configuration, epoch
from app.ai.deidentification_task_contract import FEATURE_KEY, FrozenTaskRecord, TaskSourceRecord, selection
from app.ai.models import AIAuditEvent, AIPromptVersion, AIRun
from app.ai.research_cohort_sources import utc_text, utcnow
from app.ai.research_cohort_write_guard import current_research_rows

TEXT_FIELDS = ("input_json", "evidence_json", "context_metadata_json")
HASH_FIELDS = ("input_hash", "evidence_hash", "metadata_hash")
PUBLICATION_FIELDS = (
    "schema_version",
    "case_id",
    "source_id",
    "scope_id",
    "recorded_at",
    "content_hash",
    "collection_digest",
    "parent_binding_hash",
    "manifest_hash",
    "status",
    "revision",
    "governance_hash",
    "detail_required",
)


def utc_datetime(value):
    return dt.datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ")


def text_json(value):
    raw = canonical(value)
    if len(utf8(raw)) > 65535:
        raise HTTPException(413, "完整Task JSON超65535UTF8字节，未截断")
    return raw


def original_json(raw, maximum=8 * 1024 * 1024):
    try:
        if type(raw) is not str or len(utf8(raw)) > maximum:
            raise ValueError("Complete bounded raw UTF8 JSON required")
        value = parse_json(utf8(raw))
        if canonical(value) != raw:
            raise ValueError("Original canonical JSON bytes differ")
        return value
    except (ValueError, TypeError, UnicodeError, RecursionError) as exc:
        raise HTTPException(409, "完整原Task JSON或UTF8字节无法核对") from exc


def binding_for(source):
    return {
        "case_id": source["case_id"],
        "source_id": source["source_id"],
        "content_hash": source["content_hash"],
        "governance_hash": source["governance_hash"],
        "collection_digest": source["collection_digest"],
        "projection_hash": digest(source["public_source"]),
    }


def prompt_reference(prompt):
    return {key: prompt[key] for key in ("origin", "prompt_version_id", "version", "native_task_version", "system_hash", "task_hash", "prompt_hash", "instructions_digest")}


def prepare(db, user, values, *, preview=False):
    values = selection(values)
    actor = sources.actor_now(db, user)
    config, provider, public_provider, validation, prompt, roles = configuration(db, actor, preview)
    source = sources.source_current(db, actor, values["deidentification_case_id"], execution=True, external_model=True)
    binding = binding_for(source)
    execution = {"feature_key": FEATURE_KEY, "feature_revision": config.revision, "allowed_roles": roles, "requester_epoch": epoch(actor), "preview": preview, "snapshot_time": utc_text(utcnow())}
    publication = {key: source[key] for key in PUBLICATION_FIELDS}
    body = {
        "schema_version": "deidentification_task_source_v1",
        "source_snapshot": source["snapshot"],
        "publication": publication,
        "public_source": source["public_source"],
        "prompt": prompt,
        "provider": public_provider,
        "validation": validation,
        "execution": execution,
    }
    TaskSourceRecord.model_validate(body, strict=True)
    bounded_json(body)
    task = {
        "schema_version": "deidentification_task_v1",
        "catalog_version": prompt["catalog_version"],
        "input": values,
        "context": binding,
        "provider": public_provider,
        "validation": validation,
        "execution": execution,
        "prompt": prompt_reference(prompt),
    }
    evidence = [{"source_id": binding["source_id"], "kind": "complete_selected_fields_only", "projection_hash": binding["projection_hash"]}]
    metadata = {
        "schema_version": "deidentification_task_metadata_v1",
        "binding": binding,
        "snapshot_time": execution["snapshot_time"],
        "instructions_digest": prompt["instructions_digest"],
        "model_version": provider.model,
        "feature_revision": config.revision,
    }
    raw = dict(zip(TEXT_FIELDS, map(text_json, (task, evidence, metadata)), strict=True))
    return actor, config, provider, body, task, evidence, metadata, raw


def opaque_artifact(db, run_id, *, writing=False):
    columns = [column for column in AIDeidentificationRunSource.__table__.columns if column.name != "source_json"]
    row = current_research_rows(db.query(*columns).filter_by(run_id=run_id), shared=not writing).one_or_none()
    if row is None:
        raise HTTPException(409, "完整75永久Task锚缺失，未降级")
    return dict(row._mapping)


def technical_run(db, run_id, *, writing=False):
    """Trusted lease code reads opaque hashes instead of any Task/Result TEXT."""
    from app.ai.deidentification_collection import _sql_hash

    query = db.query(AIRun).options(*(defer(getattr(AIRun, name)) for name in (*TEXT_FIELDS, "result_json"))).filter_by(run_id=run_id)
    run = current_research_rows(query, shared=not writing).one_or_none()
    if run is not None:
        digest = current_research_rows(db.query(_sql_hash(db, AIRun.result_json)).filter_by(run_id=run_id), shared=True).scalar()
        run.__dict__["_deid_result_pointer_hash"] = digest
    return run


def stage_source(db, run, body, create_event_id):
    raw = bounded_json(body)
    private = body["source_snapshot"]
    prompt = verify_frozen_prompt(body["prompt"])
    binding = original_json(run.input_json, 65535)["context"]
    row = AIDeidentificationRunSource(
        run_id=run.run_id,
        case_id=private["case_id"],
        scope_id=private["scope_id"],
        patient_id=private["patient_id"],
        requested_by=run.requested_by,
        provider_id=run.provider_id,
        prompt_version_id=prompt["prompt_version_id"],
        prompt_origin=prompt["origin"],
        prompt_version=prompt["version"],
        catalog_version=prompt["catalog_version"],
        native_task_version=prompt["native_task_version"],
        schema_version=SOURCE_SCHEMA,
        created_at=utc_datetime(body["execution"]["snapshot_time"]),
        source_json=raw,
        source_hash=text_digest(raw),
        source_bytes=len(utf8(raw)),
        source_projection_hash=digest(body["public_source"]),
        source_content_hash=body["publication"]["content_hash"],
        source_governance_hash=body["publication"]["governance_hash"],
        input_hash=text_digest(run.input_json),
        evidence_hash=text_digest(run.evidence_json),
        metadata_hash=text_digest(run.context_metadata_json),
        prompt_hash=run.prompt_hash,
        context_digest=run.context_digest,
        source_binding_hash=digest(binding),
        instructions_digest=prompt["instructions_digest"],
        create_event_id=create_event_id,
    )
    db.add(row)
    db.flush()
    result = AIDeidentificationRunResult(run_id=run.run_id, schema_version=RESULT_SCHEMA, created_at=row.created_at)
    db.add(result)
    db.flush()
    return row


def create_detail(run, body):
    return {
        "schema_version": "deidentification_create_receipt_v1",
        "source_hash": text_digest(bounded_json(body)),
        "source_binding_hash": digest(original_json(run.input_json, 65535)["context"]),
        **dict(zip(HASH_FIELDS, (text_digest(getattr(run, field)) for field in TEXT_FIELDS), strict=True)),
        "requester_epoch": body["execution"]["requester_epoch"],
        "snapshot_time": body["execution"]["snapshot_time"],
    }


def load_snapshot(db, user, run_id, *, audit_only=False, execution=False):
    actor, locator = authorize_locator(db, user, run_identifier(run_id), audit_only=audit_only, external_model=execution)
    source = sources.source_current(db, actor, locator["case_id"], audit_only=audit_only, execution=execution, external_model=execution)
    if source["snapshot"] is None or not audit_only and not source["eligible"]:
        raise HTTPException(409, "当前来源不能读取旧Task正文")
    # Parent authority and actual complete Source proof passed before these TEXTs.
    run = current_research_rows(db.query(AIRun).filter_by(run_id=locator["run_id"]), shared=True).one_or_none()
    row = current_research_rows(db.query(AIDeidentificationRunSource).filter_by(run_id=locator["run_id"]), shared=True).one_or_none()
    if run is None or row is None:
        raise HTTPException(409, "完整75 Task和Artifact必须同时存在")
    try:
        body = original_json(row.source_json)
        TaskSourceRecord.model_validate(body, strict=True)
        prompt = verify_frozen_prompt(body["prompt"])
        if prompt["prompt_version_id"] is not None:
            saved = current_research_rows(db.query(AIPromptVersion).filter_by(prompt_id=prompt["prompt_version_id"]), shared=True).one_or_none()
            if saved is None:
                raise ValueError("Real saved Prompt FK missing")
            actual_prompt = {key: getattr(saved, key) for key in ("prompt_id", "feature_key", "version", "task_prompt", "change_note", "created_by")}
            actual_prompt["create_time"] = str(saved.create_time)
            if canonical(actual_prompt) != canonical(prompt["database_snapshot"]):
                raise ValueError("Complete actual saved Prompt record differs")
        sources.verify_snapshot(body["source_snapshot"])
        public = checked_source(body["public_source"])
        snapshot, published, _ = publication_view(db, source)
        expected_publication = {**source, "status": "published", "revision": 2, "governance_hash": published["source_governance_hash"]}
        expected_publication = {key: expected_publication[key] for key in PUBLICATION_FIELDS}
        if canonical(body["source_snapshot"]) != canonical(snapshot) or canonical(public) != canonical(published) or body["publication"] != expected_publication:
            raise ValueError("Complete original Source/publication differs")
        task = original_json(run.input_json, 65535)
        FrozenTaskRecord.model_validate(task, strict=True)
        values = selection(task["input"])
        actual_binding = binding_for({**source, "governance_hash": published["source_governance_hash"], "public_source": published})
        expected_task = {
            "schema_version": "deidentification_task_v1",
            "catalog_version": prompt["catalog_version"],
            "input": values,
            "context": actual_binding,
            "provider": body["provider"],
            "validation": body["validation"],
            "execution": body["execution"],
            "prompt": prompt_reference(prompt),
        }
        evidence = [{"source_id": actual_binding["source_id"], "kind": "complete_selected_fields_only", "projection_hash": actual_binding["projection_hash"]}]
        metadata = {
            "schema_version": "deidentification_task_metadata_v1",
            "binding": actual_binding,
            "snapshot_time": body["execution"]["snapshot_time"],
            "instructions_digest": prompt["instructions_digest"],
            "model_version": body["provider"]["model"],
            "feature_revision": body["execution"]["feature_revision"],
        }
        if canonical(task) != canonical(expected_task) or run.evidence_json != text_json(evidence) or run.context_metadata_json != text_json(metadata):
            raise ValueError("Original full raw3/Prompt/provider/validation/execution changed")
        expected_hashes = {
            "source_hash": text_digest(row.source_json),
            "source_projection_hash": digest(public),
            "source_content_hash": digest(snapshot),
            "source_governance_hash": actual_binding["governance_hash"],
            **dict(zip(HASH_FIELDS, (text_digest(getattr(run, field)) for field in TEXT_FIELDS), strict=True)),
            "prompt_hash": prompt["prompt_hash"],
            "context_digest": digest(actual_binding),
            "source_binding_hash": digest(actual_binding),
            "instructions_digest": prompt["instructions_digest"],
        }
        if any(getattr(row, field) != expected_hashes[field] for field in SOURCE_HASH_FIELDS) or row.source_bytes != len(utf8(row.source_json)):
            raise ValueError("Complete SQL hash/UTF8 anchors differ")
        event = current_research_rows(db.query(AIAuditEvent).filter_by(event_id=row.create_event_id), shared=True).one_or_none()
        if (
            event is None
            or (event.actor_id, event.action, event.target, event.detail_json) != (run.requested_by, "deidentification.task.create", run.run_id, canonical(create_detail(run, body)))
            or row.created_at != utc_datetime(body["execution"]["snapshot_time"])
        ):
            raise ValueError("Actual specific create audit/clock differs")
        identity = (
            FEATURE_KEY,
            body["provider"]["provider_id"],
            body["provider"]["revision"],
            prompt["version"],
            prompt["prompt_hash"],
            digest(actual_binding),
            snapshot["patient_id"],
            None,
            body["execution"]["requester_epoch"]["user_id"],
            int(body["execution"]["preview"]),
        )
        if (
            tuple(
                getattr(run, key)
                for key in ("feature_key", "provider_id", "provider_revision", "prompt_version", "prompt_hash", "context_digest", "patient_id", "encounter_ref", "requested_by", "preview")
            )
            != identity
        ):
            raise ValueError("Actual Run immutable binding differs")
        if (
            row.case_id,
            row.scope_id,
            row.patient_id,
            row.requested_by,
            row.provider_id,
            row.schema_version,
            row.prompt_version_id,
            row.prompt_origin,
            row.prompt_version,
            row.catalog_version,
            row.native_task_version,
        ) != (
            snapshot["case_id"],
            snapshot["scope_id"],
            snapshot["patient_id"],
            run.requested_by,
            run.provider_id,
            SOURCE_SCHEMA,
            prompt["prompt_version_id"],
            prompt["origin"],
            prompt["version"],
            prompt["catalog_version"],
            prompt["native_task_version"],
        ):
            raise ValueError("Actual SourceArtifact identity differs")
        if execution:
            config, _, provider, validation, actual_prompt, roles = configuration(db, actor, bool(run.preview))
            if (epoch(actor), provider, validation, actual_prompt, roles, config.revision) != (
                body["execution"]["requester_epoch"],
                body["provider"],
                body["validation"],
                prompt,
                body["execution"]["allowed_roles"],
                body["execution"]["feature_revision"],
            ):
                raise HTTPException(409, "本次请求原角色/登录epoch、模型、配置或Prompt已变化")
        return actor, run, row, body, task, evidence, metadata
    except (ValueError, TypeError, KeyError, UnicodeError, RecursionError) as exc:
        raise HTTPException(409, "完整75 Task/Artifact/source/Prompt proof失效，未降级") from exc


def load_result(db, user, run_id, *, audit_only=False):
    loaded = load_snapshot(db, user, run_id, audit_only=audit_only)
    run, source, body = loaded[1:4]
    result = current_research_rows(db.query(AIDeidentificationRunResult).filter_by(run_id=run.run_id), shared=True).one_or_none()
    if result is None or result.schema_version != RESULT_SCHEMA:
        raise HTTPException(409, "完整75结果Artifact缺失")
    from app.ai.deidentification_receipts import usage_receipt

    usage_receipt(db, run)
    if run.status != "succeeded":
        if run.result_json != "{}" or any(getattr(result, key) is not None for key in ("result_json", "result_hash", "result_bytes", "accepted_at", "accepted_lease", "accept_event_id")):
            raise HTTPException(409, "未成功Task不得携带已接收候选")
        return loaded, None
    value = original_json(result.result_json)
    try:
        checked = validate_result(body["public_source"], value, source.instructions_digest)
        pointer = {"schema_version": "deidentification_result_pointer_v1", "run_id": run.run_id, "result_hash": result.result_hash, "result_bytes": result.result_bytes}
        if (
            result.result_hash != text_digest(result.result_json)
            or result.result_bytes != len(utf8(result.result_json))
            or run.result_json != text_json(pointer)
            or result.accepted_lease != run.lease_token
            or result.accept_event_id is None
            or result.usage_event_id is None
        ):
            raise ValueError("Full accepted result/pointer/lease differs")
        return loaded, checked
    except (ValueError, TypeError) as exc:
        raise HTTPException(409, "完整75结果原文候选无法复算") from exc
