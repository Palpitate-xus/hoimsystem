"""Durable75 shared routing and split reads, never a technical clinical bypass."""

from fastapi import HTTPException
from sqlalchemy import case, func, or_, select

from app.ai.models import AIRun
from app.ai.native_task_routing import locate_native_task, opaque_run_id


def marker_expression(*, mysql):
    predicates = []
    for column, schema in (
        (AIRun.input_json, "deidentification_task_v1"),
        (AIRun.context_metadata_json, "deidentification_task_metadata_v1"),
        (AIRun.result_json, "deidentification_result_pointer_v1"),
    ):
        valid = case((func.json_valid(column) == 1, column), else_="{}")
        value = func.json_extract(valid, "$.schema_version")
        predicates.append((func.json_unquote(value) if mysql else value) == schema)
        if column is AIRun.input_json:
            for path in ("$.deidentification_case_id", "$.input.deidentification_case_id", "$.deidentification_source", "$.deidentification_binding"):
                predicates.append(func.json_contains_path(valid, "one", path) == 1 if mysql else func.json_type(valid, path).is_not(None))
        elif column is AIRun.result_json:
            predicates.append(func.json_contains_path(valid, "one", "$.deidentification_result") == 1 if mysql else func.json_type(valid, "$.deidentification_result").is_not(None))
    return func.coalesce(or_(AIRun.feature_key == "deidentification", *predicates), False)


def is_deidentification_task(db, run):
    identity = locate_native_task(db, run)
    if identity is not None:
        return identity.domain == "deidentification"
    identifier = opaque_run_id(run)
    if db is None or type(identifier) is not str:
        return False
    mysql = db.get_bind().dialect.name in {"mysql", "mariadb"}
    statement = select(marker_expression(mysql=mysql).label("deidentification_native_marker")).where(AIRun.run_id == identifier)
    with db.no_autoflush:
        bind = db.get_bind()
        if mysql:
            with getattr(bind, "engine", bind).connect().execution_options(isolation_level="READ COMMITTED") as connection:
                row = connection.execute(statement).one_or_none()
        else:
            row = db.execute(statement).one_or_none()
    return row is not None and row[0] is True


def guard_task(db, user, run_id):
    from app.ai.deidentification_storage import load_snapshot

    identity = locate_native_task(db, run_id)
    if identity is None or identity.domain != "deidentification":
        raise HTTPException(409, "75任务缺少完整持久Source，未沿用通用正文或执行")
    return load_snapshot(db, user, run_id, audit_only=False)


def _technical_closure(db, user, run_id):
    from app.ai import deidentification_storage as storage
    from app.ai.deidentification_receipts import run_state, usage_receipt, verify_run_state
    from app.ai.deidentification_spans import canonical, text_digest
    from app.ai.deidentification_task_access import safe_task_metadata

    safe = safe_task_metadata(db, user, run_id)
    run, source = storage.technical_run(db, run_id), storage.opaque_artifact(db, run_id)
    if run is None or (run.feature_key, run.requested_by, run.patient_id, run.provider_id, run.prompt_hash, run.context_digest) != (
        "deidentification",
        source["requested_by"],
        source["patient_id"],
        source["provider_id"],
        source["prompt_hash"],
        source["context_digest"],
    ):
        raise HTTPException(409, "75永久技术FK、实际Run功能或原请求锚不一致")
    verify_run_state(db, run_id, run_state(run, source), source)
    receipt = usage_receipt(db, run, source=source)
    from app.ai.deidentification_receipts import result_header

    result = result_header(db, run_id)
    expected_pointer = (
        canonical({"schema_version": "deidentification_result_pointer_v1", "run_id": run_id, "result_hash": result["result_hash"], "result_bytes": result["result_bytes"]})
        if run.status == "succeeded"
        else "{}"
    )
    if run.__dict__["_deid_result_pointer_hash"] != text_digest(expected_pointer):
        raise HTTPException(409, "75原结果短引用SHA与具体完整结果回执不一致")
    return safe, run, source, receipt


def directory_metadata(db, user, run):
    from app.ai import deidentification_sources as sources
    from app.ai import deidentification_storage as storage
    from app.ai.deidentification_sources import actor_now
    from app.ai.deidentification_task_access import authorize_locator
    from app.ai.research_cohort_sources import utc_text
    from app.ai.research_cohort_write_guard import current_research_rows, lock_research_gate

    identifier = opaque_run_id(run)
    identity = locate_native_task(db, identifier)
    if identity is None:
        lock_research_gate(db)
        actor = actor_now(db, user)
        if actor.user_role != "super_admin":
            raise HTTPException(403, "不完整75任务仅提供当前Super技术目录")
        row = current_research_rows(db.query(AIRun.run_id, AIRun.feature_key, AIRun.status, AIRun.create_time).filter_by(run_id=identifier), shared=True).one_or_none()
        if row is None:
            raise HTTPException(404, "任务不存在")
        return {
            "schema_version": "deidentification_incomplete_task_metadata_v1",
            "run_id": identifier,
            "feature_key": row.feature_key,
            "status": row.status,
            "create_time": utc_text(row.create_time),
            "split_artifacts": True,
            "incomplete_native_artifact": True,
            "clinical_parts_available": False,
            "binding": None,
            "error_code": "NATIVE_ARTIFACT_REQUIRED",
            "error_message": "任务缺少永久受控来源，仅保留技术状态；未读取临床原文、问题或沿用通用模型",
        }
    if identity.domain != "deidentification":
        raise HTTPException(409, "75目录的永久原生域不一致")
    safe, technical, source, receipt = _technical_closure(db, user, identifier)
    actor = actor_now(db, user)
    clinical, binding, part_hashes = False, None, None
    # A failed current Source never permits an Artifact TEXT read. Its hashes
    # remain explicitly opaque technical anchors, not a full client proof.
    try:
        _, locator = authorize_locator(db, actor, identifier, audit_only=actor.user_role == "super_admin")
        current = sources.source_current(db, actor, locator["case_id"], audit_only=actor.user_role == "super_admin")
    except HTTPException as exc:
        if exc.status_code not in {403, 404, 409}:
            raise
    else:
        if current["snapshot"] is not None and (actor.user_role == "super_admin" or current["eligible"]):
            # Artifact/receipt corruption is outside the Source availability
            # catch: do not disguise a corrupt Task as merely unavailable.
            loaded = storage.load_snapshot(db, actor, identifier, audit_only=actor.user_role == "super_admin")
            binding, clinical = loaded[4]["context"], True
            from app.ai.deidentification_receipts import result_header
            from app.ai.deidentification_spans import digest, text_digest

            result = result_header(db, identifier)
            task_part = task_packet(identifier, source, loaded[3], loaded[4], {field: getattr(loaded[1], field) for field in storage.TEXT_FIELDS}, audit_only=actor.user_role == "super_admin")
            part_hashes = {"source": source["source_projection_hash"], "scope": source["source_content_hash"], "task": digest(task_part), "result": result["result_hash"] or text_digest("null")}
    return {
        "schema_version": "deidentification_shared_task_metadata_v1",
        "run_id": identifier,
        "feature_key": "deidentification",
        "status": technical.status,
        "preview": bool(technical.preview),
        "create_time": utc_text(technical.create_time),
        "finish_time": utc_text(technical.finish_time) if technical.finish_time is not None else None,
        "error_code": technical.error_code,
        "error_message": technical.error_message,
        "input_tokens": receipt["input_tokens"],
        "output_tokens": receipt["output_tokens"],
        "usage_receipt": receipt,
        "split_artifacts": True,
        "clinical_parts_available": clinical,
        "binding": binding,
        "opaque_hashes": {
            key: source[key]
            for key in ("source_hash", "source_projection_hash", "source_content_hash", "source_governance_hash", "source_binding_hash", "prompt_hash", "input_hash", "evidence_hash", "metadata_hash")
        },
        "parts_wire": "canonical_json_body_no_envelope",
        "part_hashes": part_hashes,
        "proof_scope": "technical_metadata_and_opaque_hashes_only" if not clinical else "currently_authorized_split_artifact_references",
        "source": None,
        "result": None,
        "raw_frozen_json": None,
        "can_execute": False,
        "can_review": False,
        "can_export": False,
    }


def split_trace(db, user, run_id):
    from app.ai.deidentification_storage import load_snapshot

    load_snapshot(db, user, run_id, audit_only=True)
    return {
        "schema_version": "deidentification_split_trace_v1",
        "run": directory_metadata(db, user, run_id),
        "parts_require_independent_current_reads": True,
        "parts_wire": "canonical_json_body_no_envelope",
        "parts": {part: f"/api/ai/deidentification/tasks/{run_id}/parts/{part}?audit_only=true" for part in ("task", "source", "scope", "result")},
    }


def task_packet(run_id, source, body, task, raw, *, audit_only=False):
    return {
        "schema_version": "deidentification_split_task_v1",
        "run_id": run_id,
        "source_hash": source["source_hash"],
        "source_binding_hash": source["source_binding_hash"],
        "source_projection_hash": source["source_projection_hash"],
        "binding": task["context"],
        "raw_frozen_json": raw,
        "raw_hashes": {key: source[key] for key in ("input_hash", "evidence_hash", "metadata_hash")},
        "frozen_prompt": body["prompt"],
        "provider": body["provider"],
        "validation": body["validation"],
        "execution": body["execution"],
        "publication": body["publication"],
        "can_execute": False,
        "can_review": False,
        "can_export": False,
    }


def part_view(db, user, run_id, part, *, audit_only=False):
    from app.ai import deidentification_storage as storage

    if part == "result":
        return storage.load_result(db, user, run_id, audit_only=audit_only)[1]
    loaded = storage.load_snapshot(db, user, run_id, audit_only=audit_only)
    _, run, artifact, body, task = loaded[:5]
    if part == "task":
        source = storage.opaque_artifact(db, run_id)
        return task_packet(run_id, source, body, task, {field: getattr(run, field) for field in storage.TEXT_FIELDS}, audit_only=audit_only)
    if part == "source":
        return body["public_source"]
    if part == "scope":
        return body["source_snapshot"]
    raise HTTPException(404, "明确分件不存在")


def filter_history(db, user, query, *, feature_key, case_id=None, other_scope=()):
    from app.ai.deidentification_run_models import AIDeidentificationRunSource
    from app.ai.deidentification_sources import actor_now, source_current
    from app.ai.deidentification_task_access import role_configuration
    from app.ai.deidentification_task_contract import TaskInput

    if feature_key != "deidentification" or any(value is not None for value in other_scope):
        raise HTTPException(422, "75历史仅使用明确受控Case，不混用临床、运营或其他原生来源范围")
    actor = actor_now(db, user)
    if actor.user_role != "super_admin":
        role_configuration(db, actor)
    if case_id is not None:
        try:
            checked = TaskInput.model_validate({"deidentification_case_id": case_id}, strict=True)
        except ValueError as exc:
            raise HTTPException(422, "75历史Case标识须规范UUID") from exc
        source_current(db, actor, checked.deidentification_case_id, audit_only=actor.user_role == "super_admin")
        query = query.filter(AIRun.run_id.in_(db.query(AIDeidentificationRunSource.run_id).filter_by(case_id=checked.deidentification_case_id)))
    return actor, query
