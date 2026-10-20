"""Complete controlled surgery collections and narrowly curated resource originals.

The operational capsule's own SHA authenticates its entire readable projection.
Its source-content SHA is an opaque anchor to an independently checked original;
it never claims that hidden foreign raw bytes were disclosed or reconstructed.
"""

import datetime
from typing import Annotated, Literal

from fastapi import HTTPException
from pydantic import Field, TypeAdapter, model_validator

from app.ai import surgery_facts as facts
from app.ai.surgery_contract import SHA256, UUID, Accounting, Amount, CoverageStatus, StrictModel, UtcLimit, UtcText, WorkLimit, WorkWindow, canonical_json, hash_content
from app.ai.surgery_models import AISurgeryPoolMembership, AISurgeryResource


class SafeBasis(StrictModel):
    basis_hash: SHA256


class SafeRoomCapability(SafeBasis):
    kind: Literal["operating_room_identity_capability"]
    identity_status: Literal["verified", "unknown"]
    capability_hashes: list[SHA256] = Field(max_length=256)
    capability_status: Literal["verified", "not_verified", "unknown"]
    valid_from_at: UtcText
    valid_until: UtcLimit


class SafeEquipmentCapability(SafeRoomCapability):
    kind: Literal["equipment_identity_capability"]


class SafePersonQualification(SafeBasis):
    kind: Literal["person_identity_qualification"]
    identity_status: Literal["verified", "unknown"]
    capability_hashes: list[SHA256] = Field(max_length=256)
    qualification_status: Literal["verified", "not_verified", "unknown"]
    valid_from_at: UtcText
    valid_until: UtcLimit


class SafeAvailability(SafeBasis):
    kind: Literal["resource_availability_busy"]
    record_type: Literal["availability"]
    start_at: UtcText
    end_at: UtcText
    state: Literal["available", "unavailable", "unknown"]


class SafeDuty(SafeBasis):
    kind: Literal["resource_availability_busy"]
    record_type: Literal["duty"]
    start_at: UtcText
    end_at: UtcText
    accounting: Accounting


class SafeBusy(SafeBasis):
    kind: Literal["resource_availability_busy"]
    record_type: Literal["busy_capsule"]
    start_at: UtcText
    end_at: UtcText | None
    end_absent_reason: Literal["ongoing_unknown_end", "not_recorded"] | None
    verified_until_at: UtcText | None
    continuity_status: Literal["confirmed", "unknown"]
    busy_status: Literal["committed", "completed", "cancelled", "unknown"]
    transition_class_hash: SHA256 | None
    transition_class_absent_reason: Literal["unknown", "not_applicable"] | None
    accounting: Accounting
    basis_code: Literal["explicit_local_operational_observation", "protected_legacy_witness"]
    protected_witness_hash: SHA256 | None


SafeAvailabilityPayload = Annotated[SafeAvailability | SafeDuty | SafeBusy, Field(discriminator="record_type")]


class SafeTransitionPair(SafeBasis):
    from_class_hash: SHA256
    to_class_hash: SHA256
    minimum_gap_us: Amount
    penalty: Amount


class SafeTransitionPolicy(SafeBasis):
    kind: Literal["resource_occupation_policy"]
    policy_type: Literal["transition"]
    effective_from_at: UtcText
    effective_until: UtcLimit
    pairs: list[SafeTransitionPair] = Field(max_length=32768)
    pair_coverage: CoverageStatus


class SafeWorkPolicy(SafeBasis):
    kind: Literal["resource_occupation_policy"]
    policy_type: Literal["work"]
    effective_from_at: UtcText
    effective_until: UtcLimit
    max_single_presence: WorkLimit
    max_work_rolling_24h: WorkLimit
    max_work_rolling_7d: WorkLimit
    minimum_rest: WorkLimit
    fixed_windows: list[WorkWindow] = Field(max_length=64)
    policy_reference_hash: SHA256


SafeOccupationPayload = Annotated[SafeTransitionPolicy | SafeWorkPolicy, Field(discriminator="policy_type")]
SafeResourcePayload = Annotated[SafeRoomCapability | SafeEquipmentCapability | SafePersonQualification | SafeAvailabilityPayload | SafeOccupationPayload, Field(discriminator="kind")]
SAFE_PAYLOAD = TypeAdapter(SafeResourcePayload)
PRIVATE_PAYLOAD = TypeAdapter(facts.SourcePayload)


class SafeResourceOriginal(StrictModel):
    schema_version: Literal["surgery_safe_resource_original_v1"]
    resource_id: UUID
    source_record_id: UUID
    source_kind: Literal["operating_room_identity_capability", "person_identity_qualification", "resource_availability_busy", "resource_occupation_policy", "equipment_identity_capability"]
    source_content_hash: SHA256
    source_governance_hash: SHA256
    status: facts.SourceStatus
    revision: int = Field(strict=True, ge=1, le=3)
    recorded_at: UtcText
    reviewed_at: UtcText | None
    published_at: UtcText | None
    payload: SafeResourcePayload | None
    eligible_for_new_use: bool
    exclusion_reasons: list[str]
    redacted: bool

    @model_validator(mode="after")
    def complete_safe_original(self):
        if self.redacted != (self.payload is None) or self.eligible_for_new_use and (self.redacted or self.status != "published" or self.published_at is None):
            raise ValueError("Ineligible originals cannot be restored through a complete capsule claim")
        if self.payload is not None and self.payload.kind != self.source_kind:
            raise ValueError("Safe original kind differs")
        return self


class SafeResourceOriginalWrapper(SafeResourceOriginal):
    capsule_hash: SHA256


def project_safe_resource_payload(payload):
    """Pure exact mechanical projection; no key/quantity/qualification inference."""
    typed = PRIVATE_PAYLOAD.validate_python(payload)
    if typed.kind in facts.CASE_KINDS:
        raise ValueError("Clinical case originals cannot become cross-scope operational capsules")

    def project(value):
        if isinstance(value, list):
            return [project(item) for item in value]
        if not isinstance(value, dict):
            return value
        result = {}
        for key, item in value.items():
            if key in {"user_id", "doctor_id"}:
                continue
            if key.endswith("_note"):
                result[key[:-5] + "_hash"] = hash_content(item)
            elif key == "capability_keys":
                result["capability_hashes"] = [hash_content(raw) for raw in item]
            elif key in {"transition_class_key", "from_class_key", "to_class_key"}:
                result[key[:-4] + "_hash"] = hash_content(item) if item is not None else None
            elif key == "policy_reference":
                result["policy_reference_hash"] = hash_content(item)
            else:
                result[key] = project(item)
        return result

    return SAFE_PAYLOAD.validate_python(project(typed.model_dump(mode="json"))).model_dump(mode="json")


def safe_resource_original_current(db, user, resource_id, source_id, authorized_pool_id, *, locking=False, as_of=None):
    """Authorize one local physical member, then verify a safe all-location source."""
    actor, pool = facts.pool_scope(db, user, authorized_pool_id, locking=locking)
    resource = facts._row(db, AISurgeryResource, "resource_id", facts.canonical_id(resource_id), locking=locking)
    facts.registry_proof("resource", resource)
    members = facts.current_query(db.query(AISurgeryPoolMembership).filter_by(pool_id=pool.pool_id, resource_id=resource.resource_id, status="published"), locking=locking).all()
    if len(members) != 1:
        raise HTTPException(403 if not members else 409, "当前本地资源池没有唯一可核实的实际物理资源成员关系")
    member_proof = facts.registry_proof("pool_membership", members[0])
    if facts._registry_parent(db, member_proof["payload"], locking=locking) != member_proof["parent_binding"]:
        raise HTTPException(409, "当前本地成员原父件已变化")
    row = facts.source_row(db, source_id, locking=locking)
    body, request = facts.source_proof(row)
    if row.resource_id != resource.resource_id or row.source_kind in facts.CASE_KINDS:
        raise HTTPException(422, "所选原件不属于此实际资源，不能扩权读取病例原件")
    reasons = []
    if row.status != "published":
        reasons.append("source_not_published")
    if isinstance(request.payload, facts.BusyPayload) and request.payload.protected_witness_hash is not None:
        if not facts._protected_current(db, row, body["payload"], locking=locking):
            reasons.append("protected_original_changed")
    try:
        current = facts._source_parent(db, actor, request, locking=locking, authorize=False, authorize_original_pool=False)
        if current != body["parent_binding"]:
            reasons.append("original_parent_changed")
    except HTTPException as exc:
        if exc.status_code not in {404, 409, 422}:
            raise
        reasons.append("original_parent_unavailable")
    if as_of is not None:
        cutoff = datetime.datetime.fromisoformat(facts.KnownTime(kind="known", at=as_of).at.replace("Z", "+00:00")).replace(tzinfo=None) if isinstance(as_of, str) else as_of
        if cutoff.tzinfo is not None:
            cutoff = cutoff.astimezone(datetime.UTC).replace(tzinfo=None)
        if row.recorded_at > cutoff or row.reviewed_at is None or row.reviewed_at > cutoff:
            reasons.append("original_not_available_at_as_of")
    original = SafeResourceOriginal(
        schema_version="surgery_safe_resource_original_v1",
        resource_id=resource.resource_id,
        source_record_id=row.source_record_id,
        source_kind=row.source_kind,
        source_content_hash=row.content_hash,
        source_governance_hash=hash_content(facts.governance_fields(row)),
        status=row.status,
        revision=row.revision,
        recorded_at=facts.utc_text(row.recorded_at),
        reviewed_at=facts.utc_text(row.reviewed_at) if row.reviewed_at is not None else None,
        published_at=facts.utc_text(row.reviewed_at) if row.reviewed_at is not None and row.status in {"published", "revoked"} else None,
        payload=project_safe_resource_payload(body["payload"]) if not reasons else None,
        eligible_for_new_use=not reasons,
        exclusion_reasons=reasons,
        redacted=bool(reasons),
    ).model_dump(mode="json")
    if len(canonical_json(original).encode()) > facts.FACT_BYTES:
        raise HTTPException(422, "完整安全原件超过8MiB，不得截断")
    return SafeResourceOriginalWrapper(**original, capsule_hash=hash_content(original)).model_dump(mode="json")
