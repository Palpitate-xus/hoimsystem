"""Current Super-only finite-Scope capture; large pieces never enter Run TEXT."""

from fastapi import HTTPException

from app.ai import document_change_contract as c
from app.ai import document_change_sources as sources
from app.ai.context import ContextBundle
from app.ai.document_change_draft import checked_source, source_id
from app.ai.document_change_view_contract import (
    MISSING_DATA,
    DocumentChangeContext,
    DocumentChangeRequest,
    binding_for_source,
    private_scope_packet,
    source_packet,
)

PREFLIGHT_RUN_ID = "00000000-0000-0000-0000-000000000000"


def selection(values):
    try:
        return DocumentChangeRequest.model_validate(values)
    except (ValueError, TypeError, UnicodeError) as exc:
        raise HTTPException(422, "指南版本核对仅接受明确有限范围原件ID和可选问题") from exc


def short_context(binding, snapshot_time):
    return DocumentChangeContext(scope="document_change_review", snapshot_time=snapshot_time, document_change_binding=binding, missing_data=list(MISSING_DATA))


def change_evidence(binding):
    values = [
        {
            "source_id": f"document_change_scope:{binding.scope.scope_id}:{binding.scope.content_hash[:12]}",
            "kind": "document_change_scope",
            **binding.scope.model_dump(mode="json"),
            "source_digest": binding.source_digest,
            "inventory_hash": binding.inventory_hash,
            "member_count": binding.member_count,
        }
    ]
    for side, original in (("baseline", binding.baseline_original), ("candidate", binding.candidate_original)):
        values.append({"source_id": f"document_original:{original.original_id}:{original.content_hash[:12]}", "kind": "document_original", "side": side, **original.model_dump(mode="json")})
    return values


def prepare_context(db, user, values):
    request = selection(values)
    record, source = sources.authorize_scope(db, user, request.document_change_scope_id)
    try:
        binding = binding_for_source(source)
        snapshot_time = c.e.utc_text(sources.utcnow())
        if c.e.clock(snapshot_time) < c.e.clock(record.governance.reviewed_at):
            raise ValueError("A current task capture cannot predate the actual Scope review")
        # Individually valid8MiB bodies do not guarantee their whole wire wrappers
        # fit. Reject before enqueue rather than creating an unreadable task.
        source_packet(PREFLIGHT_RUN_ID, binding, source)
        private_scope_packet(PREFLIGHT_RUN_ID, binding, record.snapshot, record.governance, record.audit_event_ids)
        context = short_context(binding, snapshot_time)
    except (ValueError, TypeError, UnicodeError) as exc:
        raise HTTPException(409, "完整选件、有限范围或分件响应超过容量，未裁剪原文或依赖") from exc
    return ContextBundle(data=context.model_dump(mode="json"), evidence=change_evidence(binding)), record, source


def change_context(db, user, values):
    return prepare_context(db, user, values)[0]


def verify_current_context(db, user, value):
    try:
        context = DocumentChangeContext.model_validate(value)
        bound = context.document_change_binding
        record, source = sources.authorize_scope(db, user, bound.scope.scope_id, expected_content_hash=bound.scope.content_hash, expected_governance_hash=bound.scope.governance_hash)
        if binding_for_source(source) != bound or c.e.clock(context.snapshot_time) < c.e.clock(record.governance.reviewed_at) or c.e.clock(context.snapshot_time) > sources.utcnow():
            raise ValueError("The exact complete current Scope or capture clock differs")
        return context, record, source
    except (ValueError, TypeError, UnicodeError) as exc:
        raise HTTPException(409, "当前完整有限范围或原文治理已变化，请重新核对") from exc


def public_payload(payload, source):
    """Only a server-resolved actual public source and the explicit question leave."""
    if type(payload) is not dict or set(payload) != {"input", "context", "tools", "evidence"}:
        raise ValueError("The whole closed task envelope is required")
    request = DocumentChangeRequest.model_validate(payload["input"])
    context = DocumentChangeContext.model_validate(payload["context"])
    source = checked_source(source)
    binding = context.document_change_binding
    if c.e.canonical_json(context) != c.e.canonical_json(payload["context"]):
        raise ValueError("The short context must retain exact scalar types")
    if request.document_change_scope_id != binding.scope.scope_id or binding_for_source(source) != binding:
        raise ValueError("The selected Scope and complete public source differ")
    if payload["tools"] != {} or payload["evidence"] != change_evidence(binding):
        raise ValueError("Finite version review cannot mix unrelated tools or citations")
    if source_id(source) != change_evidence(binding)[0]["source_id"]:
        raise ValueError("The fixed proof and citation identity differ")
    return {"document_change_source": source.model_dump(mode="json"), "question": request.question}
