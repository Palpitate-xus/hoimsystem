"""Bodyless local Task metadata and separately authorized complete parts."""

from types import SimpleNamespace

from fastapi import HTTPException

from app.ai import infection_cluster_contract as c
from app.ai import infection_cluster_registry as r
from app.ai import infection_cluster_task_contract as t
from app.ai import infection_cluster_task_storage as storage
from app.ai import infection_cluster_task_view_contract as wire
from app.ai.infection_cluster_run_models import AIInfectionRunArtifact as Artifact
from app.ai.infection_cluster_write_guard import current
from app.dependencies import VALID_USER_ROLES
from app.sql_counts import locked_row_count


def _actor(db, user, owner=None):
    # Stopping/inspecting one's own technical Task remains safe after a clinical
    # purpose or executable role is lost. This is not clinical read authority.
    actor = r._start(db, user, roles=VALID_USER_ROLES, related_user_ids={owner} if owner is not None else ())
    if owner is not None and actor.user_id != owner and actor.user_role != "super_admin":
        raise HTTPException(403, "仅本人或当前Super可读取本地任务技术元数据")
    return actor


def metadata(db, user, rid):
    opaque = storage.locator(db, rid)
    if opaque is None:
        raise HTTPException(404, "持久化本地任务不存在")
    _actor(db, user, opaque.requested_by)
    artifact, run = storage.verify_technical_run(db, rid)
    receipt = storage.usage(db, artifact, SimpleNamespace(**{key: value for key, value in run.items() if key not in t.RAW_FIELDS}))
    result = dict(
        schema_version="infection_local_task_metadata_v1",
        run_id=rid,
        feature_key=t.FEATURE_KEY,
        engine="prediction",
        status=run["status"],
        preview=bool(run["preview"]),
        scenario_id=artifact.scenario_id,
        snapshot_id=artifact.snapshot_id,
        profile_id=artifact.profile_id,
        created_at=r.utc(artifact.created_at),
        run_created_at=run["create_time"].isoformat(),
        run_finish_at=run["finish_time"].isoformat() if run["finish_time"] else None,
        source_hash=artifact.source_hash,
        source_bytes=artifact.source_bytes,
        result_hash=artifact.result_hash,
        result_bytes=artifact.result_bytes,
        result_available=run["status"] == "succeeded",
        receipt_event_id=artifact.usage_event_id,
        usage=receipt.model_dump(mode="json") if receipt else None,
        usage_receipt_status="recorded" if receipt else "pending",
        protected_hashes_are_opaque=True,
        clinical_parts_require_current_patient_purpose=True,
        clinical_body_included=False,
        parts_separately_bounded=True,
        automatic_actions=False,
    )
    return wire.TaskMetadata.model_validate(result).model_dump(mode="json")


def part(db, user, rid, name):
    if name not in {"task", "source", "result"}:
        raise HTTPException(422, "仅支持明确的完整task/source/result独立件")
    actor, run, artifact, frozen, source = storage.authorize(db, user, rid)
    value = frozen.model_dump(mode="json") if name == "task" else source.model_dump(mode="json") if name == "source" else storage.load_result(db, actor, rid)
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    result = dict(
        schema_version="infection_local_task_part_v1",
        run_id=rid,
        part=name,
        value=value,
        value_hash=c.digest(value),
        value_bytes=len(c.utf8(c.canonical(value))),
        authority="current_patient_processing_and_local_profile_not_anonymity_or_clinical_validation",
    )
    return wire.TaskPart.model_validate(result).model_dump(mode="json")


def directory(db, user, *, scenario_id=None, page=1, size=20):
    actor = _actor(db, user)
    if type(page) is not int or page < 1 or type(size) is not int or not 1 <= size <= 100:
        raise HTTPException(422, "需要明确分页参数")
    query = db.query(Artifact.run_id)
    if actor.user_role != "super_admin":
        query = query.filter(Artifact.requested_by == actor.user_id)
    if scenario_id is not None:
        from pydantic import TypeAdapter

        TypeAdapter(c.UUID).validate_python(scenario_id)
        query = query.filter(Artifact.scenario_id == scenario_id)
    total = locked_row_count(current(query, shared=True), Artifact.run_id, aggregate=True)
    ids = current(query.order_by(Artifact.created_at.desc(), Artifact.run_id.desc()), shared=True).offset((page - 1) * size).limit(size).all()
    # This is a native Artifact directory, not a claim to include unverifiable
    # legacy78 generic tasks. Every item remains bodyless and hash-opaque.
    items = [metadata(db, actor, row.run_id) for row in ids]
    return wire.TaskDirectory(schema_version="infection_local_task_directory_v1", items=items, total=total, page=page, size=size, native_artifacts_only=True, clinical_body_included=False).model_dump(
        mode="json"
    )
