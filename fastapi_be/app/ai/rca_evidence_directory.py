"""Current short directories. No source body or release eligibility is implied."""

from typing import Annotated, Literal

from fastapi import HTTPException
from pydantic import Field

from app.ai import rca_evidence_contract as c
from app.ai import rca_evidence_current as current_keys
from app.ai import rca_evidence_grants as g
from app.ai import rca_evidence_input as i
from app.ai.rca_evidence_cases import wire
from app.ai.rca_evidence_models import AIRcaEvidenceCase, AIRcaEvidenceOriginal, AIRcaPurposeGrant
from app.ai.rca_evidence_write_guard import lock_event_identity


class OriginalMetadata(c.StrictModel):
    original_id: c.OpaqueId
    event_id: i.PositiveId
    origin_kind: c.ItemKind
    content_hash: c.SHA
    status: Literal["draft", "published", "rejected", "revoked"]
    revision: Annotated[int, Field(strict=True, ge=1, le=3)]
    recorded_at: str
    created_by: i.PositiveId
    patient_association_matches: bool
    complete_current_detail_required: Literal[True]


class CaseMetadata(c.StrictModel):
    case_id: c.OpaqueId
    event_id: i.PositiveId
    content_hash: c.SHA
    collection_hash: c.SHA
    status: Literal["draft", "published", "rejected", "revoked"]
    revision: Annotated[int, Field(strict=True, ge=1, le=3)]
    recorded_at: str
    created_by: i.PositiveId
    patient_association_matches: bool
    complete_current_detail_required: Literal[True]


class GrantMetadata(c.StrictModel):
    grant_id: c.OpaqueId
    event_id: i.PositiveId
    permission_kind: i.PermissionKind
    grantee_id: i.PositiveId
    content_hash: c.SHA
    status: Literal["active", "revoked"]
    revision: Annotated[int, Field(strict=True, ge=1, le=2)]
    issued_at: str
    valid_until: str
    patient_association_matches: bool
    complete_current_detail_required: Literal[True]


class Directory(c.StrictModel):
    schema_version: Literal["rca_evidence_directory_v1"]
    kind: Literal["originals", "cases", "grants"]
    event_id: i.PositiveId
    page: Annotated[int, Field(strict=True, ge=1, le=4096)]
    page_size: Annotated[int, Field(strict=True, ge=1, le=100)]
    total: Annotated[int, Field(strict=True, ge=0, le=c.MAX_MEMBERS)]
    items: list[OriginalMetadata | CaseMetadata | GrantMetadata] = Field(max_length=100)
    completeness: Literal["current_same_event_directory_not_causal_or_hospital_coverage"]


def directory(db, user, event_id, kind, *, page=1, page_size=20):
    if kind not in {"originals", "cases", "grants"} or type(page) is not int or not 1 <= page <= 4096 or type(page_size) is not int or not 1 <= page_size <= 100:
        raise HTTPException(422, "须明确目录类型与严格正整数分页范围")
    if kind == "grants":
        g.current_actor(db, user, g.SOURCE_ROLES)
        parent = lock_event_identity(db, event_id)
        if parent is None:
            raise HTTPException(404, "实际不良事件不存在")
        model, dtype = AIRcaPurposeGrant, GrantMetadata
        fields = ("grant_id", "event_id", "permission_kind", "grantee_id", "content_hash", "status", "revision", "issued_at", "valid_until", "patient_id_at_grant")
    else:
        auth = g.authorize_event(db, user, event_id)
        parent = auth.identity
        model, dtype = (AIRcaEvidenceOriginal, OriginalMetadata) if kind == "originals" else (AIRcaEvidenceCase, CaseMetadata)
        fields = (("original_id", "event_id", "origin_kind") if kind == "originals" else ("case_id", "event_id", "collection_hash")) + (
            "content_hash",
            "status",
            "revision",
            "recorded_at",
            "created_by",
            "patient_id_at_capture",
        )
    # Parent X closes every supported writer; current opaque discovery plus
    # exact PK metadata avoids RR next-key gaps on unrelated events.
    identifiers = current_keys.discover(db, model, fields[0], event_id)
    rows = [current_keys.current_metadata(db, model, fields[0], identifier, event_id, tuple(getattr(model, key) for key in fields)) for identifier in identifiers]
    items = []
    for row in rows[(page - 1) * page_size : page * page_size]:
        values = dict(zip(fields, row, strict=True))
        association = values.pop("patient_id_at_grant" if kind == "grants" else "patient_id_at_capture")
        for key in ("recorded_at", "issued_at", "valid_until"):
            if key in values:
                values[key] = i.utc_text(values[key])
        items.append(dtype(**values, patient_association_matches=association == parent.patient_id, complete_current_detail_required=True))
    result = Directory(
        schema_version="rca_evidence_directory_v1",
        kind=kind,
        event_id=event_id,
        page=page,
        page_size=page_size,
        total=len(rows),
        items=items,
        completeness="current_same_event_directory_not_causal_or_hospital_coverage",
    )
    wire(result)
    return result
