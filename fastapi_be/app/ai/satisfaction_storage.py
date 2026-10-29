"""Durable original task anchors and lease/audit-bound complete safe results.

No function commits. The shared worker owns the transaction containing the
Artifact, short Run reference, final task state and its other audit events.
"""

import hashlib
import json
from types import SimpleNamespace
from typing import Annotated, Literal

from fastapi import HTTPException
from pydantic import Field, TypeAdapter
from sqlalchemy import inspect
from sqlalchemy.orm import defer

from app.ai.retry_policy import retry_snapshots_equal
from app.ai.satisfaction_artifact_models import AISatisfactionRunArtifact
from app.ai.satisfaction_context import FEATURE_KEY, SatisfactionContextBinding, expand_context, satisfaction_evidence, selection, short_context, source_binding
from app.ai.satisfaction_contract import SHA, UUID, Positive, StrictModel
from app.ai.satisfaction_draft import MAX_BYTES, canonical_json, source_hash
from app.ai.satisfaction_frozen import SatisfactionFrozenProvider, SatisfactionFrozenValidation
from app.ai.satisfaction_prompt import SATISFACTION_SYSTEM_PROMPT

ARTIFACT_SCHEMA = "satisfaction_run_artifact_v1"
REFERENCE_SCHEMA = "satisfaction_result_ref_v1"
TEXT_BYTES = 65535
RECEIPT_ACTION = "run.satisfaction_result.accept"
# Historical bodies must be explicitly retained here when a future fixed System
# version is introduced. Arbitrary self-rehashed System text is never supported.
SUPPORTED_SYSTEMS = frozenset({SATISFACTION_SYSTEM_PROMPT})

TASK_FIELDS = (
    "feature_key",
    "provider_id",
    "provider_revision",
    "prompt_version",
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


class SatisfactionResultReference(StrictModel):
    schema_version: Literal["satisfaction_result_ref_v1"]
    run_id: UUID
    case_id: UUID
    lease_token: UUID
    content_hash: SHA
    result_bytes: Annotated[int, Field(strict=True, gt=0, le=MAX_BYTES)]
    source_binding_hash: SHA
    receipt_event_id: Positive


def text_hash(value, limit=TEXT_BYTES):
    if type(value) is not str or not 0 < len(value.encode("utf-8", errors="strict")) <= limit:
        raise ValueError("The complete retained JSON exceeds its UTF8 storage boundary")
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _canonical_value(raw, limit=TEXT_BYTES):
    text_hash(raw, limit)
    value = json.loads(raw)
    if canonical_json(value) != raw:
        raise ValueError("Original JSON must remain canonical, unique, scalar-exact and finite")
    return value


def bounded_result(value):
    try:
        serialized = canonical_json(value)
        encoded = serialized.encode("utf-8", errors="strict")
    except (ValueError, TypeError, UnicodeError, RecursionError) as exc:
        raise HTTPException(422, "评价完整结果须为有限UTF8 JSON") from exc
    if not 0 < len(encoded) <= MAX_BYTES:
        raise HTTPException(422, "评价完整结果超过8MiB，未接收或截断")
    return serialized, hashlib.sha256(encoded).hexdigest(), len(encoded)


def _task(run, *, execution=False):
    from app.ai.context import ContextBundle, context_metadata

    snapshot, evidence, metadata = _canonical_value(run.input_json), _canonical_value(run.evidence_json), _canonical_value(run.context_metadata_json)
    if not isinstance(snapshot, dict) or set(snapshot) != {"catalog_version", "system_prompt", "task_prompt", "payload", "provider_snapshot", "feature_validation"}:
        raise ValueError("The complete closed original satisfaction task is required")
    TypeAdapter(UUID).validate_python(run.run_id, strict=True)
    if run.feature_key != FEATURE_KEY or run.patient_id is not None or run.encounter_ref is not None or type(run.requested_by) is not int or run.requested_by < 1:
        raise ValueError("Satisfaction tasks cannot acquire patient or encounter scope")
    if run.status not in {"queued", "running", "succeeded", "failed", "cancelled"} or type(run.preview) is not int or run.preview not in (0, 1):
        raise ValueError("The actual task state or preview scalar differs")
    if (
        type(snapshot["system_prompt"]) is not str
        or snapshot["system_prompt"] not in SUPPORTED_SYSTEMS
        or execution
        and snapshot["system_prompt"] != SATISFACTION_SYSTEM_PROMPT
        or type(snapshot["task_prompt"]) is not str
        or not snapshot["task_prompt"].strip()
        or type(snapshot["catalog_version"]) is not str
        or not snapshot["catalog_version"]
    ):
        raise ValueError("Original fixed System and Task bodies must remain complete")
    payload = snapshot["payload"]
    if not isinstance(payload, dict) or set(payload) != {"input", "context", "tools", "evidence"} or payload["tools"] != {}:
        raise ValueError("Only one short reconstructible satisfaction source and no tools are allowed")
    context = payload["context"]
    bound = SatisfactionContextBinding.model_validate(context["satisfaction_binding"])
    binding = bound.model_dump(mode="json")
    if selection(payload["input"]) != bound.case_id or canonical_json(context) != canonical_json(short_context(binding, context["snapshot_time"])):
        raise ValueError("The short original source, scope or scalar types differ")
    if payload["evidence"] != evidence or evidence != [satisfaction_evidence(binding)]:
        raise ValueError("The one original reconstructible evidence must remain exact")
    provider = SatisfactionFrozenProvider.model_validate(snapshot["provider_snapshot"])
    validation = SatisfactionFrozenValidation.model_validate(snapshot["feature_validation"])
    if canonical_json(provider.model_dump(mode="json")) != canonical_json(snapshot["provider_snapshot"]) or canonical_json(validation.model_dump(mode="json")) != canonical_json(
        snapshot["feature_validation"]
    ):
        raise ValueError("Original provider or validation fields and scalar types differ")
    if (
        type(run.provider_id) is not int
        or type(run.provider_revision) is not int
        or run.provider_id != provider.provider_id
        or run.provider_revision != provider.revision
        or type(run.prompt_version) is not int
        or run.prompt_version < 0
        or run.prompt_hash != source_hash([snapshot["system_prompt"], snapshot["task_prompt"]])
        or run.context_digest != source_hash(context)
    ):
        raise ValueError("The actual original provider or Prompt identity differs")
    expected = {
        **context_metadata(ContextBundle(data=context, evidence=evidence, department_ids=set())),
        "feature_revision": validation.feature_revision,
        "validation_status": validation.status,
        "tool_fingerprint": source_hash({}),
        "instructions_digest": hashlib.sha256((snapshot["system_prompt"] + "\n\n" + snapshot["task_prompt"]).encode("utf-8", errors="strict")).hexdigest(),
        "model_version": provider.model,
    }
    if not isinstance(metadata, dict) or canonical_json(metadata) != canonical_json(expected):
        raise ValueError("The full retained task metadata differs from its original Prompt and source")
    return snapshot, binding, metadata, evidence


def _anchors(run, binding):
    return {
        "input_hash": text_hash(run.input_json),
        "evidence_hash": text_hash(run.evidence_json),
        "metadata_hash": text_hash(run.context_metadata_json),
        "prompt_hash": run.prompt_hash,
        "context_digest": run.context_digest,
        "source_binding_hash": source_hash(binding),
    }


def _artifact(db, run_id, *, exclusive=False, include_result=False):
    with db.no_autoflush:
        query = db.query(AISatisfactionRunArtifact)
        if not include_result:
            query = query.options(defer(AISatisfactionRunArtifact.result_json))
        return query.filter_by(run_id=run_id).populate_existing().with_for_update(read=not exclusive).one_or_none()


def _current_task(db, run):
    from app.ai.models import AIRun

    state = inspect(run, raiseerr=False)
    identifier = state.identity[0] if state is not None and state.identity is not None else getattr(run, "run_id", None)
    row = db.query(AIRun.run_id, AIRun.status, *(getattr(AIRun, key) for key in TASK_FIELDS)).filter_by(run_id=identifier).with_for_update(read=True).one_or_none()
    if row is None:
        raise ValueError("The actual durable task is absent")
    # Current original columns do not refresh away pending latency/token fields.
    return SimpleNamespace(**dict(row._mapping))


def load_snapshot(db, run, *, execution=False):
    from app.ai.satisfaction_sources import utc_text
    from app.ai.satisfaction_write_guard import lock_satisfaction_gate

    try:
        if db is None:
            raise ValueError("An actual durable task anchor is required")
        with db.no_autoflush:
            lock_satisfaction_gate(db)
            original = _current_task(db, run)
            snapshot, binding, metadata, evidence = _task(original, execution=execution)
            row = _artifact(db, original.run_id)
        if (
            row is None
            or row.schema_version != ARTIFACT_SCHEMA
            or row.case_id != binding["case_id"]
            or row.requested_by != original.requested_by
            or any(getattr(row, key) != value for key, value in _anchors(original, binding).items())
            or utc_text(row.created_at) < snapshot["payload"]["context"]["snapshot_time"]
        ):
            raise ValueError("The durable original task bytes or actual source/author binding differ")
        return snapshot, binding, metadata, evidence
    except (HTTPException, ValueError, TypeError, KeyError, AttributeError, UnicodeError, RecursionError) as exc:
        raise HTTPException(409, "评价任务的完整原来源、Prompt、身份或SQL锚点无效，未降级读取") from exc


def run_binding(db, run):
    return load_snapshot(db, run)[1]


def lock_run_scope(db, run):
    from app.ai.satisfaction_contract import SOURCE_ROLES
    from app.ai.satisfaction_write_guard import lock_satisfaction_write

    with db.no_autoflush:
        return lock_satisfaction_write(db, SimpleNamespace(user_id=run.requested_by), allowed_roles=SOURCE_ROLES)


def _run_identifier(run):
    if isinstance(run, str):
        return run
    state = inspect(run, raiseerr=False)
    return state.identity[0] if state is not None and state.identity is not None else getattr(run, "run_id", None)


def _routing_locator(db, run_id):
    """Only opaque immutable identity, always a current read after the Gate."""
    with db.no_autoflush:
        return (
            db.query(AISatisfactionRunArtifact.run_id, AISatisfactionRunArtifact.case_id, AISatisfactionRunArtifact.requested_by)
            .filter_by(run_id=run_id)
            .populate_existing()
            .with_for_update(read=True)
            .one_or_none()
        )


def guard_satisfaction_run_id(db, user, run_id, *, audit_only=False):
    """Current Source authority before any private task TEXT or whole Artifact.

    False means there is no durable satisfaction Artifact, not that a legacy
    task is authorized. The caller must retain its original legacy authorizer.
    """
    from app.ai.catalog import FEATURE_BY_KEY
    from app.ai.models import AIFeatureConfig, AIRun
    from app.ai.satisfaction_context import binding_for_value
    from app.ai.satisfaction_contract import SOURCE_ROLES
    from app.ai.satisfaction_sources import authorize_case, frozen_case_proof
    from app.ai.satisfaction_write_guard import lock_satisfaction_write
    from app.dependencies import VALID_USER_ROLES

    actor = lock_satisfaction_write(db, user, allowed_roles=VALID_USER_ROLES)
    with db.no_autoflush:
        # Routing hint only. Locking an unrelated Run here would invert that
        # feature's Source -> Run order; an old RR view may also miss this row.
        header = db.query(AIRun.run_id, AIRun.feature_key, AIRun.requested_by).filter_by(run_id=run_id).one_or_none()

    def authority(owner):
        if actor.user_role not in SOURCE_ROLES:
            raise HTTPException(403, "当前账户已无本项评价任务权限")
        if actor.user_role != "super_admin" and owner != actor.user_id:
            raise HTTPException(403, "没有读取该评价任务的权限")
        if audit_only and actor.user_role != "super_admin":
            raise HTTPException(403, "历史任务审计仅供超级管理员访问。")

    def configured_roles():
        if actor.user_role == "super_admin":
            return
        with db.no_autoflush:
            config = db.query(AIFeatureConfig).filter_by(feature_key=FEATURE_KEY).populate_existing().with_for_update(read=True).one_or_none()
        try:
            roles = json.loads(config.allowed_roles_json) if config is not None else list(FEATURE_BY_KEY[FEATURE_KEY].default_roles)
            if not isinstance(roles, list) or any(type(role) is not str for role in roles):
                raise ValueError("The actual configured feature roles are invalid")
        except (ValueError, TypeError) as exc:
            raise HTTPException(409, "评价任务当前适用角色配置无法核对") from exc
        if actor.user_role not in roles or actor.user_role not in FEATURE_BY_KEY[FEATURE_KEY].default_roles:
            raise HTTPException(403, "当前账户已无该评价任务的适用权限")

    if header is not None and header.feature_key == FEATURE_KEY:
        authority(header.requested_by)
        configured_roles()
    locator = _routing_locator(db, run_id)
    if locator is None:
        return False
    try:
        TypeAdapter(UUID).validate_python(run_id, strict=True)
    except (ValueError, TypeError) as exc:
        raise HTTPException(409, "评价任务的持久技术标识已损坏") from exc
    # Only an actual current Artifact identifies native authority under an old
    # read view or a forged feature/JSON body. It contains no task/source text.
    authority(locator.requested_by)
    if header is None or header.feature_key != FEATURE_KEY:
        configured_roles()
    if audit_only:
        # This internal no-user proof is reachable only after actual current
        # Super authority. It verifies frozen own bytes, never new execution.
        binding_for_value(frozen_case_proof(db, locator.case_id))
    else:
        authorize_case(db, actor, locator.case_id, execution=False)
    # Current Run ownership is checked only after Source authority, never before
    # another feature's Source lock. The immutable locator is re-bound exactly.
    with db.no_autoflush:
        current = db.query(AIRun.run_id, AIRun.feature_key, AIRun.requested_by).filter_by(run_id=run_id).with_for_update(read=True).one_or_none()
    if current is None or current.requested_by != locator.requested_by or current.feature_key != FEATURE_KEY:
        raise HTTPException(409, "评价任务的持久来源、功能或原申请账户不一致")

    return True


def authorize_run_scope(db, user, run, *, execution=False, audit_only=False):
    """Current role/owner/opaque locator/Source scope before private task JSON."""
    from app.ai.satisfaction_contract import SOURCE_ROLES
    from app.ai.satisfaction_write_guard import lock_satisfaction_write

    if audit_only and execution:
        raise HTTPException(403, "当前账号没有本次任务的执行权限。")
    identifier = _run_identifier(run)
    if not guard_satisfaction_run_id(db, user, identifier, audit_only=audit_only):
        raise HTTPException(409, "评价任务缺少持久原件锚点，未降级读取")
    actor = lock_satisfaction_write(db, user, allowed_roles=SOURCE_ROLES)
    snapshot = load_snapshot(db, SimpleNamespace(run_id=identifier), execution=execution)[0]
    expanded = expand_context(db, snapshot["payload"]["context"], user=None if audit_only else actor, current=execution, locking=execution)
    return actor, expanded


def stage_anchor(db, run):
    from app.ai.satisfaction_sources import authorize_case, utc_text, utcnow

    actor = lock_run_scope(db, run)
    try:
        snapshot, binding, _, _ = _task(run, execution=True)
        authorize_case(db, actor, binding["case_id"], binding=source_binding(binding), locking=True, execution=True)
        if _artifact(db, run.run_id) is not None:
            raise ValueError("The original task anchor already exists")
        clock = utcnow()
        if utc_text(clock) < snapshot["payload"]["context"]["snapshot_time"]:
            raise ValueError("The server task clock precedes the source capture")
        artifact = AISatisfactionRunArtifact(run_id=run.run_id, case_id=binding["case_id"], requested_by=run.requested_by, schema_version=ARTIFACT_SCHEMA, created_at=clock, **_anchors(run, binding))
        db.add(artifact)
        db.flush()
        from app.ai.native_task_routing import remember_staged_identity

        remember_staged_identity(db, artifact)
        actor = lock_run_scope(db, run)
        authorize_case(db, actor, binding["case_id"], binding=source_binding(binding), locking=True, execution=True)
        return load_snapshot(db, run, execution=True)[0]
    except (ValueError, TypeError, KeyError, AttributeError, UnicodeError, RecursionError) as exc:
        raise HTTPException(409, "评价完整任务和当前来源未能原子绑定，未入队") from exc


def _lock_lease(db, run, lease):
    from app.ai.models import AIRun

    try:
        TypeAdapter(UUID).validate_python(lease, strict=True)
        TypeAdapter(UUID).validate_python(run.run_id, strict=True)
    except (ValueError, TypeError) as exc:
        raise HTTPException(409, "评价任务租约或实际任务标识无效") from exc
    fields = TASK_FIELDS
    with db.no_autoflush:
        row = db.query(AIRun.status, AIRun.lease_token, *(getattr(AIRun, key) for key in fields)).filter_by(run_id=run.run_id).with_for_update().one_or_none()
    if row is None or row.status != "running" or run.status != "running" or row.lease_token != lease or run.lease_token != lease or any(getattr(row, key) != getattr(run, key) for key in fields):
        raise HTTPException(409, "只有数据库中仍有效的同一执行租约可接收评价结果")


def _current_configuration(db, actor, run, snapshot, metadata):
    from app.ai.catalog import FEATURE_BY_KEY
    from app.ai.models import AIFeatureConfig, AIProvider
    from app.ai.runtime import check_configuration, provider_snapshot

    config = db.query(AIFeatureConfig).filter_by(feature_key=FEATURE_KEY).populate_existing().with_for_update().one_or_none()
    provider = db.query(AIProvider).filter_by(provider_id=run.provider_id).populate_existing().with_for_update().one_or_none()
    spec = FEATURE_BY_KEY[FEATURE_KEY]
    if config is None or provider is None:
        raise HTTPException(409, "评价功能或原模型服务已不存在")
    try:
        roles = json.loads(config.allowed_roles_json)
        if not isinstance(roles, list) or not roles or any(type(role) is not str for role in roles):
            raise ValueError("Current feature roles are invalid")
        if actor.user_role != "super_admin" and (actor.user_role not in roles or actor.user_role not in spec.default_roles):
            raise HTTPException(403, "当前账户已无本项评价任务权限")
        validation = {
            "status": config.validation_status,
            "note": config.validation_note,
            "validated_by": config.validated_by,
            "validated_at": None if config.validated_at is None else str(config.validated_at),
            "feature_revision": config.revision,
        }
        if config.revision != metadata["feature_revision"] or provider.revision != run.provider_revision or validation != snapshot["feature_validation"]:
            raise ValueError("The original feature or provider revision changed")
        if check_configuration(db, actor, spec, config, bool(run.preview)) is not provider or not retry_snapshots_equal(provider_snapshot(provider), snapshot["provider_snapshot"]):
            raise ValueError("The complete current model limits or identity changed")
    except (ValueError, TypeError, KeyError) as exc:
        raise HTTPException(409, "评价最终接收时的功能、适用范围或完整模型配置已变化") from exc


def _receipt_detail(run, binding, lease, content_hash, size):
    return {
        "schema_version": "satisfaction_accept_receipt_v1",
        "run_id": run.run_id,
        "case_id": binding["case_id"],
        "lease_token": lease,
        "source_binding_hash": source_hash(binding),
        "content_hash": content_hash,
        "result_bytes": size,
    }


def _verify_receipt(db, run, row, binding):
    from app.ai.models import AIAuditEvent

    event = db.query(AIAuditEvent).filter_by(event_id=row.receipt_event_id).populate_existing().with_for_update(read=True).one_or_none()
    expected = _receipt_detail(run, binding, row.accepted_lease, row.result_hash, row.result_bytes)
    if event is None or event.actor_id != run.requested_by or event.action != RECEIPT_ACTION or event.target != run.run_id or event.detail_json != canonical_json(expected):
        raise ValueError("The exact acceptance audit identity or original receipt differs")


def _read_result_row(db, run, reference, binding):
    from app.ai.satisfaction_sources import utc_text

    row = _artifact(db, run.run_id, include_result=True)
    if (
        row is None
        or row.case_id != reference.case_id
        or row.accepted_lease != reference.lease_token
        or row.receipt_event_id != reference.receipt_event_id
        or row.source_binding_hash != reference.source_binding_hash
        or row.result_hash != reference.content_hash
        or row.result_bytes != reference.result_bytes
        or row.accepted_at is None
        or utc_text(row.accepted_at) < utc_text(row.created_at)
    ):
        raise ValueError("The complete original result or its specific audit/lease identity differs")
    value = _canonical_value(row.result_json, MAX_BYTES)
    serialized, content_hash, size = bounded_result(value)
    if serialized != row.result_json or content_hash != row.result_hash or size != row.result_bytes:
        raise ValueError("The whole original result SHA or exact bytes differ")
    _verify_receipt(db, run, row, binding)
    return value


def stage_result(db, run, lease, value):
    from app.ai.models import AIAuditEvent
    from app.ai.satisfaction_result import validate_result
    from app.ai.satisfaction_sources import authorize_case, utcnow

    actor = lock_run_scope(db, run)
    _lock_lease(db, run, lease)
    snapshot, binding, metadata, _ = load_snapshot(db, run, execution=True)
    _current_configuration(db, actor, run, snapshot, metadata)
    _, _, source = authorize_case(db, actor, binding["case_id"], binding=source_binding(binding), locking=True, execution=True)
    try:
        bounded_result(value)
        checked = validate_result(value, source).model_dump(mode="json")
        if canonical_json(checked) != canonical_json(value):
            raise ValueError("The complete result cannot silently convert scalar types or fields")
        body, content_hash, size = bounded_result(checked)
        row = _artifact(db, run.run_id, exclusive=True)
        if row is None or row.result_hash is not None:
            raise ValueError("An original accepted result cannot be replaced")
        detail = _receipt_detail(run, binding, lease, content_hash, size)
        receipt = AIAuditEvent(actor_id=run.requested_by, action=RECEIPT_ACTION, target=run.run_id, detail_json=canonical_json(detail))
        db.add(receipt)
        db.flush()
        row.result_json, row.result_hash, row.result_bytes = body, content_hash, size
        row.receipt_event_id, row.accepted_lease, row.accepted_at = receipt.event_id, lease, utcnow()
        db.flush()
        reference = SatisfactionResultReference(
            schema_version=REFERENCE_SCHEMA,
            run_id=run.run_id,
            case_id=binding["case_id"],
            lease_token=lease,
            content_hash=content_hash,
            result_bytes=size,
            source_binding_hash=source_hash(binding),
            receipt_event_id=receipt.event_id,
        )
        # Same-transaction triggers can mutate Actor/Source/configuration after
        # any write. Recheck actual current rows after our acceptance receipt.
        actor = lock_run_scope(db, run)
        _lock_lease(db, run, lease)
        load_snapshot(db, run, execution=True)
        _current_configuration(db, actor, run, snapshot, metadata)
        authorize_case(db, actor, binding["case_id"], binding=source_binding(binding), locking=True, execution=True)
        stored = _read_result_row(db, run, reference, binding)
        if stored != checked:
            raise ValueError("The accepted complete result changed during SQL writes")
        return canonical_json(reference.model_dump(mode="json"))
    except (ValueError, TypeError, KeyError, AttributeError, UnicodeError, RecursionError) as exc:
        raise HTTPException(409, "评价完整结果、原统计、逐字摘录或原子接收回执无法核对") from exc


def expand_result(db, run, *, user=None):
    """Internal no-user reads require prior actual Super/Run authorization."""
    from app.ai.models import AIRun
    from app.ai.satisfaction_result import validate_result

    try:
        authorized_context = authorize_run_scope(db, user, run)[1] if user is not None else None
        snapshot, binding, _, _ = load_snapshot(db, run)
        with db.no_autoflush:
            result_header = db.query(AIRun.status, AIRun.lease_token, AIRun.result_json).filter_by(run_id=run.run_id).with_for_update(read=True).one_or_none()
        if result_header is None:
            raise ValueError("The actual result task is absent")
        reference = SatisfactionResultReference.model_validate(_canonical_value(result_header.result_json))
        if (
            canonical_json(reference.model_dump(mode="json")) != result_header.result_json
            or result_header.status != "succeeded"
            or reference.run_id != run.run_id
            or reference.case_id != binding["case_id"]
            or reference.lease_token != result_header.lease_token
            or reference.source_binding_hash != source_hash(binding)
        ):
            raise ValueError("Original success state, result reference or lease differs")
        context = authorized_context or expand_context(db, snapshot["payload"]["context"], current=False)
        value = _read_result_row(db, run, reference, binding)
        checked = validate_result(value, context["satisfaction_source"]).model_dump(mode="json")
        if canonical_json(checked) != canonical_json(value):
            raise ValueError("The original complete result fields or scalar types differ")
        return checked
    except HTTPException as exc:
        if exc.status_code == 403:
            raise
        raise HTTPException(409, "评价完整结果、原安全来源、租约或特定审核回执已损坏") from exc
    except (ValueError, TypeError, KeyError, AttributeError, UnicodeError, RecursionError) as exc:
        raise HTTPException(409, "评价完整结果、原安全来源、租约或特定审核回执已损坏") from exc


def is_satisfaction_run(db, run):
    """Keep only explicitly identified pre-Case feedback history read-only.

    This classifier grants no authority or execution. Root's shared recheck
    rejects legacy inference. An immutable Artifact or any retained dedicated
    marker always overrides a forged legacy body.
    """
    from app.ai.catalog import COMMON_SYSTEM_PROMPT

    def pairs(items):
        value = {}
        for key, child in items:
            if key in value:
                raise ValueError("Duplicate retained task JSON member")
            value[key] = child
        return value

    def finite(_):
        raise ValueError("Nonfinite retained task JSON")

    def parse(raw):
        text_hash(raw)
        value = json.loads(raw, object_pairs_hook=pairs, parse_constant=finite)
        canonical_json(value).encode("utf-8", errors="strict")
        return value

    def markers(value):
        if isinstance(value, dict):
            return (
                bool(
                    {"satisfaction_binding", "satisfaction_source", "satisfaction_case", "satisfaction_case_id", "satisfaction_analysis", "satisfaction_artifact", "frozen_satisfaction_audit"}
                    & value.keys()
                )
                or value.get("source_domain") == "recorded_satisfaction_review_case"
                or value.get("schema_version") == REFERENCE_SCHEMA
                or any(markers(child) for child in value.values())
            )
        return isinstance(value, list) and any(markers(child) for child in value)

    identifier = _run_identifier(run)
    if db is not None and identifier:
        from app.ai.satisfaction_write_guard import lock_satisfaction_gate

        with db.no_autoflush:
            lock_satisfaction_gate(db)
            if _routing_locator(db, identifier) is not None:
                return True
    try:
        snapshot = parse(run.input_json) if isinstance(run.input_json, str) else None
        result = parse(run.result_json) if isinstance(run.result_json, str) else None
        if markers(snapshot) or markers(result):
            return True
    except (ValueError, TypeError, UnicodeError, RecursionError) as exc:
        if run.feature_key == FEATURE_KEY:
            return True
        raise HTTPException(409, "已存评价任务JSON无效，不能降级读取") from exc
    if run.feature_key != FEATURE_KEY:
        return False
    payload = snapshot.get("payload") if isinstance(snapshot, dict) else None
    context = payload.get("context") if isinstance(payload, dict) else None
    values = payload.get("input") if isinstance(payload, dict) else None
    legacy = (
        db is not None
        and identifier
        and isinstance(snapshot, dict)
        and snapshot.get("system_prompt") == COMMON_SYSTEM_PROMPT
        and isinstance(context, dict)
        and context.get("source_domain") == "feedback"
        and isinstance(values, dict)
        and isinstance(result, dict)
    )
    return not bool(legacy)
