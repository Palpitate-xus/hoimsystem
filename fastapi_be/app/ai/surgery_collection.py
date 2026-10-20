"""Complete controlled surgery collections and narrowly curated resource originals.

The operational capsule's own SHA authenticates its entire readable projection.
Its source-content SHA is an opaque anchor to an independently checked original;
it never claims that hidden foreign raw bytes were disclosed or reconstructed.
"""

import datetime
import json
import re
from typing import Annotated, Literal

from fastapi import HTTPException
from pydantic import Field, TypeAdapter, model_validator
from sqlalchemy import or_

from app.ai import surgery_facts as facts
from app.ai.surgery_contract import SHA256, UUID, Accounting, Amount, CoverageStatus, StrictModel, UtcLimit, UtcText, WorkLimit, WorkWindow, canonical_json, hash_content
from app.ai.surgery_models import AISurgeryPersonAccount, AISurgeryPoolMembership, AISurgeryProtectedWitness, AISurgeryResource, AISurgeryRoomAlias, AISurgerySource
from app.ai.surgery_scenario_input import PeriodSelection, period_for
from app.models import Admission, CssdInstrument, Doctor, SurgeryApplication, SurgerySchedule, User


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


PAGE_SIZE = 128
MAX_SCAN = 200000
MAX_ROOTS = 8192


class CaptureRequest(StrictModel):
    pool_id: UUID
    period: PeriodSelection
    application_ids: list[UUID] = Field(min_length=1, max_length=256)

    @model_validator(mode="after")
    def explicit_case_cohort(self):
        if self.application_ids != sorted(set(self.application_ids)):
            raise ValueError("The declared original case cohort must be complete, distinct and ordered")
        return self


class _Budget:
    """Charge bytes before parsing or copying a complete original into a capture."""

    def __init__(self):
        self.used = 0
        self.scanned = 0

    def bytes(self, size):
        self.used += size
        if self.used > facts.FACT_BYTES:
            raise HTTPException(422, "完整场景原件超过8MiB，不能截断、挑选或丢弃成员")

    def value(self, value):
        self.bytes(facts._json_size(value))

    def raw(self, row):
        self.bytes(len(row.payload_json.encode()) + len(row.parent_binding_json.encode()))

    def row(self):
        self.scanned += 1
        if self.scanned > MAX_SCAN:
            raise HTTPException(422, "完整相关集合扫描超过200000记录，不能截断")


def _rows(query, primary, budget, *, locking=False):
    last = None
    while True:
        page = query.filter(primary > last) if last is not None else query
        page = facts.current_query(page.order_by(primary).limit(PAGE_SIZE), locking=locking).all()
        if not page:
            return
        for row in page:
            budget.row()
            yield row
        last = getattr(page[-1], primary.key)


def _registry_metadata(kind, row, reasons):
    return {
        "registry_kind": kind,
        "registry_record_id": getattr(row, facts.REGISTRY[kind][1]),
        "content_hash": row.content_hash,
        "governance_hash": hash_content(facts.governance_fields(row)) if hasattr(row, "status") else None,
        "status": row.status if hasattr(row, "status") else None,
        "revision": row.revision if hasattr(row, "revision") else None,
        "recorded_at": facts.utc_text(row.recorded_at),
        "reviewed_at": facts.utc_text(row.reviewed_at) if getattr(row, "reviewed_at", None) is not None else None,
        "revoked_at": facts.utc_text(row.revoked_at) if getattr(row, "revoked_at", None) is not None else None,
        "eligible_for_new_use": not reasons,
        "exclusion_reasons": reasons,
    }


def _registry_checked(db, kind, row, budget, *, locking=False):
    budget.raw(row)
    proof = facts.registry_proof(kind, row)
    reasons = []
    if hasattr(row, "status") and row.status != "published":
        reasons.append("registry_not_published")
    try:
        if facts._registry_parent(db, proof["payload"], locking=locking) != proof["parent_binding"]:
            reasons.append("original_parent_changed")
    except HTTPException as exc:
        if exc.status_code not in {404, 409, 422}:
            raise
        reasons.append("original_parent_unavailable")
    return proof, _registry_metadata(kind, row, reasons)


def _case_current(db, actor, pool, application_id, budget, *, locking=False):
    application = facts._row(db, SurgeryApplication, "application_id", application_id, locking=locking)
    doctor = facts._row(db, Doctor, "doctor_id", application.doctor_id, locking=locking)
    admission = facts._row(db, Admission, "admission_id", application.admission_id, locking=locking) if application.admission_id is not None else None
    if admission is not None and admission.patient_id != application.patient_id:
        raise HTTPException(409, "原申请与原住院患者不一致")
    department_id = admission.department_id if admission is not None else doctor.department_id
    if department_id != pool.department_id:
        raise HTTPException(403, "显式病例队列必须属于资源池当前原科室")
    facts._clinical_care(db, actor, application, locking=locking)
    # Preserve semantic commitment, never restore clinical free text unnecessarily.
    fields = ("surgery_name", "surgery_code", "surgery_level", "anesthesia_type", "scheduled_date", "preop_diagnosis", "surgery_indication", "contraindication")
    clinical = {field: getattr(application, field).isoformat() if isinstance(getattr(application, field), datetime.date) else getattr(application, field) for field in fields}
    budget.value(clinical)
    value = {
        "application_id": application.application_id,
        "patient_id": application.patient_id,
        "admission_id": application.admission_id,
        "doctor_id": application.doctor_id,
        "department_id": department_id,
        "status": application.status,
        "admission_status": admission.status if admission is not None else None,
        "admission_doctor_id": admission.doctor_id if admission is not None else None,
        "clinical_content_hash": hash_content(clinical),
    }
    return value


def _source_metadata(row, *, eligible, reasons):
    return {
        "source_record_id": row.source_record_id,
        "source_kind": row.source_kind,
        "source_id": f"surgery_fact:{row.source_record_id}:{row.content_hash[:12]}",
        "content_hash": row.content_hash,
        "governance_hash": hash_content(facts.governance_fields(row)),
        "status": row.status,
        "revision": row.revision,
        "recorded_at": facts.utc_text(row.recorded_at),
        "reviewed_at": facts.utc_text(row.reviewed_at) if row.reviewed_at is not None else None,
        "revoked_at": facts.utc_text(row.revoked_at) if row.revoked_at is not None else None,
        "resource_id": row.resource_id,
        "application_id": row.application_id,
        "eligible_for_new_use": eligible,
        "exclusion_reasons": reasons,
    }


def _source_record(db, actor, row, pool_id, budget, *, locking=False):
    budget.raw(row)
    # Always authenticate before governance/current filtering, including Super.
    facts.source_proof(row)
    if row.source_kind not in facts.CASE_KINDS:
        capsule = safe_resource_original_current(db, actor, row.resource_id, row.source_record_id, pool_id, locking=locking)
        return {
            "representation": "safe_resource_original",
            "metadata": _source_metadata(row, eligible=capsule["eligible_for_new_use"], reasons=capsule["exclusion_reasons"]),
            "original": None,
            "governance": None,
            "capsule": capsule,
        }
    try:
        wrapper = facts.source_current(db, actor, row.source_kind, row.source_record_id, locking=locking)
        reasons = wrapper["exclusion_reasons"]
    except HTTPException as exc:
        if exc.status_code != 403:
            raise
        # The selected current case was independently authorized. An old source
        # may belong to a prior patient/admission and must remain metadata only.
        wrapper = None
        reasons = ["original_case_scope_changed"]
    eligible = wrapper is not None and wrapper["eligible_for_new_use"]
    original = None
    if eligible:
        original = dict(wrapper)
        # Stable canonical capture does not vary with the reader's action flags.
        original.update(audit_only=False, can_review=False, can_revoke=False)
    return {
        "representation": "authorized_case_original",
        "metadata": _source_metadata(row, eligible=eligible, reasons=reasons),
        "original": original,
        "governance": facts.governance_fields(row) if eligible else None,
        "capsule": None,
    }


def _legacy_gaps(db, cases, resources, source_records, aliases, person_users, budget, *, locking=False):
    """Conservative exact legacy metadata witness, without foreign clinical data.

    Old dates and naive execution times are only lexical commitments. No proposed
    future UTC availability is inferred from them. Unmapped OR text is a concrete
    unresolved all-location gap whenever rooms are in the candidate pool.
    """
    patients = {item["patient_id"] for item in cases}
    rooms = {item["resource_id"] for item in resources if item["resource_kind"] == "room"}
    doctor_resources = {}
    if person_users:
        for doctor in _rows(db.query(Doctor).filter(Doctor.user_id.in_(person_users)), Doctor.doctor_id, budget, locking=locking):
            doctor_resources[doctor.doctor_id] = {person_users[doctor.user_id]["resource_id"]}
    covered = set()
    for record in source_records:
        capsule = record["capsule"]
        if capsule is None or not capsule["eligible_for_new_use"] or capsule["payload"].get("protected_witness_hash") is None:
            continue
        witness = facts.current_query(db.query(AISurgeryProtectedWitness).filter_by(source_record_id=capsule["source_record_id"]), locking=locking).one()
        budget.bytes(len(witness.raw_witness_json.encode()))
        raw = json.loads(witness.raw_witness_json)
        covered.add((raw["original_schedule"]["schedule_id"], capsule["resource_id"]))
    predicates = [SurgerySchedule.patient_id.in_(patients)]
    if person_users:
        doctor_ids = db.query(Doctor.doctor_id).filter(Doctor.user_id.in_(person_users))
        predicates += [
            SurgerySchedule.surgeon_id.in_(doctor_ids),
            SurgerySchedule.anesthesiologist_id.in_(doctor_ids),
            SurgerySchedule.scrub_nurse_id.in_(person_users),
            SurgerySchedule.circulating_nurse_id.in_(person_users),
            SurgerySchedule.assistant_ids.isnot(None),
        ]
    if rooms:
        predicates.append(SurgerySchedule.operating_room.isnot(None))
    user_resources = {}
    for item in person_users.values():
        user_resources.setdefault(item["user_id"], set()).add(item["resource_id"])
    gaps = []

    def add_gap(code, commitment):
        gap = {"code": code, "commitment": commitment}
        budget.value(gap)
        gaps.append(gap)

    for schedule in _rows(db.query(SurgerySchedule).filter(or_(*predicates)), SurgerySchedule.schedule_id, budget, locking=locking):
        columns = {
            column.name: getattr(schedule, column.name).isoformat() if isinstance(getattr(schedule, column.name), datetime.date) else getattr(schedule, column.name)
            for column in SurgerySchedule.__table__.columns
        }
        budget.value(columns)
        commitment = hash_content(columns)
        affected = set()
        for key in ("surgeon_id", "anesthesiologist_id"):
            affected.update(doctor_resources.get(getattr(schedule, key), set()))
        for key in ("scrub_nurse_id", "circulating_nurse_id"):
            affected.update(user_resources.get(getattr(schedule, key), set()))
        if schedule.assistant_ids:
            tokens = schedule.assistant_ids.split(",")
            if any(re.fullmatch(r"[1-9][0-9]*", token.strip()) is None for token in tokens) or len({token.strip() for token in tokens}) != len(tokens):
                if person_users:
                    add_gap("legacy_assistant_identity_unresolved", commitment)
            else:
                for token in tokens:
                    affected.update(doctor_resources.get(int(token.strip()), set()))
        if schedule.operating_room and rooms:
            mapped = aliases.get(schedule.schedule_id)
            if mapped is None:
                add_gap("legacy_room_identity_unresolved", commitment)
            else:
                affected.add(mapped)
        if schedule.patient_id in patients:
            add_gap("legacy_patient_busy_not_curated", commitment)
        for resource_id in sorted(affected):
            if (schedule.schedule_id, resource_id) not in covered:
                add_gap("legacy_resource_busy_not_curated", hash_content({"original": commitment, "resource_id": resource_id}))
    return sorted(gaps, key=lambda item: (item["code"], item["commitment"]))


def current_collection(db, user, request, *, locking=False):
    """Read a complete current explicit cohort; does not replay a past collection."""
    request = CaptureRequest.model_validate(request.model_dump() if isinstance(request, CaptureRequest) else request)
    if locking:
        with db.no_autoflush:
            facts.lock_write_gate(db)
    actor, pool = facts.pool_scope(db, user, request.pool_id, locking=locking)
    budget = _Budget()
    pool_proof, pool_metadata = _registry_checked(db, "pool", pool, budget, locking=locking)
    if not pool_metadata["eligible_for_new_use"]:
        raise HTTPException(409, "当前资源池原父件已变化")
    captured_at = facts.utc_text(facts.utcnow())
    cases = [_case_current(db, actor, pool, application_id, budget, locking=locking) for application_id in request.application_ids]
    registry_manifest = [pool_metadata]
    resources = []
    # Keep every membership root, including retired/draft claims; only actual
    # current published membership makes a physical resource a candidate.
    for member in _rows(db.query(AISurgeryPoolMembership).filter_by(pool_id=pool.pool_id), AISurgeryPoolMembership.membership_id, budget, locking=locking):
        proof, metadata = _registry_checked(db, "pool_membership", member, budget, locking=locking)
        registry_manifest.append(metadata)
        if member.status != "published":
            continue
        if not metadata["eligible_for_new_use"]:
            raise HTTPException(409, "已发布实际成员的原父件已变化，不能静默遗漏资源")
        resource = facts._row(db, AISurgeryResource, "resource_id", member.resource_id, locking=locking)
        resource_proof, resource_metadata = _registry_checked(db, "resource", resource, budget, locking=locking)
        registry_manifest.append(resource_metadata)
        if not resource_metadata["eligible_for_new_use"]:
            raise HTTPException(409, "实际物理资源父件已变化")
        condition = None
        if resource.equipment_id is not None:
            condition = facts.physical_resource_current_state(db, resource, locking=locking)
        elif resource.cssd_instrument_id is not None:
            item = facts._row(db, CssdInstrument, "instrument_id", resource.cssd_instrument_id, locking=locking)
            condition = {
                "state_hash": hash_content({"status": item.status, "expire_date": item.expire_date.isoformat() if item.expire_date else None, "bd_test": item.bd_test, "bio_monitor": item.bio_monitor})
            }
        resources.append(
            {
                "resource_id": resource.resource_id,
                "resource_kind": resource.resource_kind,
                "content_hash": resource.content_hash,
                "original": resource_proof,
                "membership": {"membership_id": member.membership_id, "content_hash": member.content_hash, "governance_hash": metadata["governance_hash"], "original": proof},
                "physical_condition": condition,
            }
        )
    resources.sort(key=lambda item: item["resource_id"])
    resource_ids = [item["resource_id"] for item in resources]
    person_users = {}
    aliases = {}
    if resource_ids:
        for account in _rows(db.query(AISurgeryPersonAccount).filter(AISurgeryPersonAccount.resource_id.in_(resource_ids)), AISurgeryPersonAccount.binding_id, budget, locking=locking):
            proof, metadata = _registry_checked(db, "person_account", account, budget, locking=locking)
            registry_manifest.append(metadata)
            if not metadata["eligible_for_new_use"]:
                raise HTTPException(409, "实际人员永久账号绑定已变化")
            user_row = facts._row(db, User, "user_id", account.user_id, locking=locking)
            person_users[account.user_id] = {"user_id": account.user_id, "resource_id": account.resource_id}
            # This is a technical identity commitment, not foreign account data.
            metadata["identity_state_hash"] = hash_content(
                {"original": proof["content_hash"] if "content_hash" in proof else account.content_hash, "user_id": user_row.user_id, "user_role": user_row.user_role}
            )
        for alias in _rows(db.query(AISurgeryRoomAlias).filter(AISurgeryRoomAlias.resource_id.in_(resource_ids)), AISurgeryRoomAlias.alias_id, budget, locking=locking):
            proof, metadata = _registry_checked(db, "room_alias", alias, budget, locking=locking)
            registry_manifest.append(metadata)
            if metadata["eligible_for_new_use"] and alias.legacy_schedule_id is not None:
                aliases[alias.legacy_schedule_id] = alias.resource_id
    source_records = []
    query = db.query(AISurgerySource).filter(or_(AISurgerySource.application_id.in_(request.application_ids), AISurgerySource.resource_id.in_(resource_ids)))
    for row in _rows(query, AISurgerySource.source_record_id, budget, locking=locking):
        if len(source_records) >= MAX_ROOTS:
            raise HTTPException(422, "完整相关来源超过8192原件，不能截断或只取已选成员")
        source_records.append(_source_record(db, actor, row, pool.pool_id, budget, locking=locking))
    manifest = [item["metadata"] for item in source_records]
    gaps = _legacy_gaps(db, cases, resources, source_records, aliases, person_users, budget, locking=locking)
    for item in cases:
        if item["status"] not in {0, 1} or item["admission_status"] not in {None, 1}:
            gaps.append({"code": "case_not_current_pending_or_approved", "commitment": hash_content(item)})
    gaps.sort(key=lambda item: (item["code"], item["commitment"]))
    registry_manifest.sort(key=lambda item: (item["registry_kind"], item["registry_record_id"]))
    clocks = []
    for member in [*registry_manifest, *manifest]:
        clocks.extend(member[name] for name in ("recorded_at", "reviewed_at", "revoked_at") if member[name] is not None)
    digests = {
        "case_collection_digest": hash_content(cases),
        "resource_collection_digest": hash_content({"resources": resources, "registry_manifest": registry_manifest}),
        "busy_collection_digest": hash_content({"gaps": gaps, "sources": [item for item in source_records if item["metadata"]["source_kind"] == "resource_availability_busy"]}),
        "fact_collection_digest": hash_content(source_records),
        "private_manifest_digest": hash_content(manifest),
    }
    result = {
        "schema_version": "surgery_capture_v1",
        "request": request.model_dump(mode="json"),
        "pool": {"pool_id": pool.pool_id, "department_id": pool.department_id, "content_hash": pool.content_hash, "governance_hash": pool_metadata["governance_hash"]},
        "period": period_for(request.period).model_dump(mode="json"),
        "as_of": request.period.as_of,
        "captured_at": captured_at,
        "cases": cases,
        "resources": resources,
        "registry_manifest": registry_manifest,
        "source_records": source_records,
        "member_manifest": manifest,
        "known_gaps": gaps,
        "max_available_at": max(clocks),
        **digests,
    }
    result["collection_digest"] = hash_content({key: value for key, value in result.items() if key not in {"captured_at"}})
    facts._bounded_json(result, facts.FACT_BYTES)
    return result


def preview_input(db, user, request, *, locking=False):
    """Complete current candidates plus late-original availability diagnostics."""
    return current_collection(db, user, request, locking=locking)


def capture_input(db, user, request, *, locking=False):
    """Capture current evidence at the declared cutoff, never silently backdate it."""
    result = current_collection(db, user, request, locking=locking)
    if result["as_of"] > result["captured_at"] or result["max_available_at"] > result["as_of"]:
        raise HTTPException(409, "相关完整原件登记、治理或当前捕获晚于原截止，请刷新截止并重新审阅")
    return result
