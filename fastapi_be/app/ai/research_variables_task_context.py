"""Current project/patient/model authority precedes Batch and later Task TEXT.

Source, private Scope and authorization Binding are complete independent
pieces. Their own wrappers must fit before a Run may be queued. A registered
8MiB Source is not a promise that any provider protocol or Task can contain it.
"""

from dataclasses import dataclass

from fastapi import HTTPException

from app.ai.research_cohort_sources import utc_text, utcnow
from app.ai.research_cohort_write_guard import current_actor, lock_research_write
from app.ai.research_variables_authority import authorize_variable_scope
from app.ai.research_variables_batches import _header, batch_current
from app.ai.research_variables_fields import LIMITATIONS, VARIABLE_SOURCE_ROLES
from app.ai.research_variables_task_binding import VariableTaskBinding, binding_reference, evidence_for_binding
from app.ai.research_variables_task_contract import (
    MAX_BINDING_BYTES,
    MAX_RUN_TEXT_BYTES,
    SOURCE_DOMAIN,
    VariableTaskAccessManifest,
    VariableTaskSelection,
    VariableTaskSource,
    canonical,
    digest,
    validate_frozen_source,
)


@dataclass(frozen=True)
class VariableTaskAuthority:
    actor: object
    scope: dict
    acl: dict
    patient_authorizations: tuple
    manifest: VariableTaskAccessManifest


@dataclass(frozen=True)
class VariablePreparedContext:
    selection: VariableTaskSelection
    data: dict
    evidence: list
    binding: VariableTaskBinding
    source: VariableTaskSource
    private_scope: dict
    authority: VariableTaskAuthority


def selection(values):
    try:
        return VariableTaskSelection.model_validate(values)
    except (ValueError, TypeError, UnicodeError) as exc:
        raise HTTPException(422, "仅接受明确科研变量批次UUID及原样可选问题，未接受患者、就诊或自由来源正文") from exc


def access_manifest(actor, scope, acl, permissions):
    return VariableTaskAccessManifest(
        schema_version="research_variable_task_access_v1",
        requested_by=actor.user_id,
        actor_role=actor.user_role,
        actor_token_invalid_before=utc_text(actor.token_invalid_before) if actor.token_invalid_before is not None else None,
        scope_id=scope["identity"]["scope_id"],
        scope_content_hash=scope["content_hash"],
        scope_governance_hash=scope["governance_hash"],
        acl_id=acl["identity"]["source_record_id"],
        acl_content_hash=acl["content_hash"],
        acl_governance_hash=acl["governance_hash"],
        patient_authorizations=[
            {
                "patient_id": value["identity"]["patient_id"],
                "authorization_id": value["identity"]["source_record_id"],
                "content_hash": value["content_hash"],
                "governance_hash": value["governance_hash"],
            }
            for value in permissions
        ],
    )


def authorize_request(db, user, batch_id, *, expected_authorization_hash=None, expected_acl_id=None):
    """No Batch/private Task TEXT is selected by this function.

    The technical original hash/ACL ID come from immutable Task header columns,
    never caller authority. A new permission/epoch cannot revive the old Task.
    All original Scope patients are checked, even those omitted by the Batch's
    narrower selected subset. The caller keeps the transaction and parent locks.
    """
    actor = lock_research_write(db, user, allowed_roles=VARIABLE_SOURCE_ROLES)
    header = _header(db, batch_id)
    reference = {key: getattr(header, key) for key in ("scope_id", "scope_content_hash", "scope_governance_hash")}
    actor, scope, acl, permissions = authorize_variable_scope(db, actor, reference, external_model=True)
    manifest = access_manifest(actor, scope, acl, permissions)
    if expected_acl_id is not None and manifest.acl_id != expected_acl_id:
        raise HTTPException(403, "任务原项目ACL已改变，另一项目许可不能恢复原任务")
    if expected_authorization_hash is not None and digest(manifest, MAX_BINDING_BYTES) != expected_authorization_hash:
        raise HTTPException(403, "任务原逐患者用途、项目ACL、请求角色或登录授权已改变")
    return VariableTaskAuthority(actor, scope, acl, tuple(permissions), manifest)


def _epoch(actor):
    return actor.user_id, actor.user_role, actor.token_invalid_before


def wire_parts(binding, source, private_scope):
    """Each returned complete HTTP piece has its own all-or-refuse 8MiB cap."""
    binding = VariableTaskBinding.model_validate(binding)
    checked = validate_frozen_source(source.model_dump(mode="json"), binding.source_projection_hash)
    if (
        len(canonical(checked).encode("utf-8")) != binding.source_bytes
        or checked.source_id != binding.source_id
        or checked.documents_hash != binding.documents_hash
        or digest(checked.recipe) != binding.source_recipe_hash
        or digest(private_scope) != binding.private_scope_hash
        or len(canonical(private_scope).encode("utf-8")) != binding.private_scope_bytes
    ):
        raise ValueError("Complete independently anchored Source/Scope pieces cannot be substituted")
    reference = binding_reference(binding)
    parts = {
        "source": {"schema_version": "research_variable_task_source_part_v1", "binding": reference, "source": source.model_dump(mode="json")},
        "scope": {"schema_version": "research_variable_task_scope_part_v1", "binding": reference, "private_scope": private_scope},
        "binding": {"schema_version": "research_variable_task_binding_part_v1", "binding": binding.model_dump(mode="json")},
    }
    for value in parts.values():
        canonical(value)
    return parts


def prepare_context(db, user, values):
    chosen = selection(values)
    authority = authorize_request(db, user, chosen.research_variable_batch_id)
    epoch = _epoch(authority.actor)
    packet = batch_current(db, authority.actor, chosen.research_variable_batch_id)
    if not packet["eligible"] or packet["status"] != "published":
        raise HTTPException(409, "任务需要完整当前已发布变量批次、字典及捕获者权限，未自动采用旧件")
    proof = packet["original"]
    try:
        source = validate_frozen_source(proof["source"], packet["projection_hash"])
        if source.external_model_use != "recorded_permitted":
            raise ValueError("Model use was not explicitly recorded as permitted")
        private_scope = {"snapshot": proof["snapshot"], "proof": {key: value for key, value in proof.items() if key not in {"snapshot", "source"}}}
        snapshot, definition = proof["snapshot"], proof["snapshot"]["capture"]["dictionary_original"]
        binding = VariableTaskBinding(
            schema_version="research_variable_task_binding_v1",
            batch_id=packet["batch_id"],
            batch_content_hash=packet["content_hash"],
            batch_governance_hash=packet["governance_hash"],
            batch_created_event_id=proof["identity"]["created_event_id"],
            batch_last_event_id=proof["last_event_id"],
            dictionary_id=packet["dictionary_id"],
            dictionary_content_hash=snapshot["request"]["dictionary_content_hash"],
            dictionary_governance_hash=snapshot["request"]["dictionary_governance_hash"],
            dictionary_created_event_id=definition["identity"]["created_event_id"],
            dictionary_last_event_id=definition["last_event_id"],
            collection_digest=snapshot["collection_digest"],
            member_manifest_hash=snapshot["member_manifest_hash"],
            source_projection_hash=packet["projection_hash"],
            source_id=source.source_id,
            documents_hash=source.documents_hash,
            source_recipe_hash=digest(source.recipe),
            source_bytes=len(canonical(source).encode("utf-8")),
            private_scope_hash=digest(private_scope),
            private_scope_bytes=len(canonical(private_scope).encode("utf-8")),
            request_authorization=authority.manifest,
            request_authorization_hash=digest(authority.manifest, MAX_BINDING_BYTES),
        )
        data = {
            "scope": {"source_domain": SOURCE_DOMAIN, "selected_sources": {"research_variable_batch_id": binding.batch_id}},
            "snapshot_time": utc_text(utcnow()),
            "research_variable_binding": binding_reference(binding),
            "question": chosen.question,
            "missing_data": list(LIMITATIONS),
        }
        evidence = evidence_for_binding(binding)
        canonical(data, MAX_RUN_TEXT_BYTES)
        canonical(evidence, MAX_RUN_TEXT_BYTES)
        wire_parts(binding, source, private_scope)
    except (ValueError, TypeError, KeyError, UnicodeError) as exc:
        raise HTTPException(409, "完整变量来源、原件、授权锚或分件容量无法核对，未截断") from exc
    fresh = authorize_request(db, authority.actor, binding.batch_id, expected_authorization_hash=binding.request_authorization_hash, expected_acl_id=authority.manifest.acl_id)
    current = current_actor(db, fresh.actor, allowed_roles=VARIABLE_SOURCE_ROLES)
    if _epoch(current) != epoch:
        raise HTTPException(403, "任务上下文构建期间原请求角色或登录授权已变化")
    return VariablePreparedContext(chosen, data, evidence, binding, source, private_scope, fresh)


def public_payload(prepared):
    """Only an authorized complete projection and unchanged question go out."""
    if not isinstance(prepared, VariablePreparedContext):
        raise TypeError("A current prepared research variable context is required")
    checked = validate_frozen_source(prepared.source.model_dump(mode="json"), prepared.binding.source_projection_hash)
    if checked.external_model_use != "recorded_permitted" or prepared.data["question"] != prepared.selection.question:
        raise ValueError("The original explicit model permission and unchanged question must remain bound")
    value = {"research_variable_source": checked.model_dump(mode="json"), "question": prepared.selection.question}
    canonical(value)
    return value
