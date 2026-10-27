"""Controlled surgery originals and technical identities, never clinical execution.

Registry anchors are permanent; reviewed claims have their own immutable body and
CAS lifecycle. The local write gate is a protocol, not proof that legacy writers
already participate in it. No foreign clinical witness is returned by this module.
"""

import datetime
import hashlib
import json
import re
import uuid
from typing import Annotated, Literal

from fastapi import HTTPException
from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator
from sqlalchemy import inspect
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.ai import governance
from app.ai.catalog import FEATURE_BY_KEY
from app.ai.models import AIFeatureConfig, AIPatientGrant
from app.ai.surgery_contract import Accounting, Amount, FactKind, Offset, StrictModel, TechnicalKey, UtcText, WorkLimit, WorkWindow, canonical_json, hash_content
from app.ai.surgery_models import (
    FACT_BYTES,
    PARENT_BYTES,
    REGISTRY_BYTES,
    AISurgeryPersonAccount,
    AISurgeryPool,
    AISurgeryPoolMembership,
    AISurgeryProtectedWitness,
    AISurgeryResource,
    AISurgeryRoomAlias,
    AISurgerySource,
    AISurgeryWriteGate,
)
from app.ai.surgery_models import (
    SOURCE_KINDS as SOURCE_KINDS,
)
from app.models import Admission, CssdInstrument, Department, Doctor, Equipment, EquipmentInspection, EquipmentMaintenance, Patient, SurgeryApplication, SurgerySchedule, User
from app.sql_locks import postgresql_gate_statement

SOURCE_ROLES = frozenset({"admin", "super_admin", "director", "doctor"})
RegistryKind = Literal["pool", "resource", "person_account", "room_alias", "pool_membership"]
SourceKind = FactKind
SourceStatus = Literal["draft", "published", "rejected", "revoked"]
UUID = Annotated[str, Field(pattern=r"^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$")]
PositiveInteger = Annotated[int, Field(strict=True, ge=1, le=2147483647)]
Hash = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
CASE_KINDS = {"case_requirements", "duration_observation", "case_duration_estimate"}
REGISTRY = {
    "pool": (AISurgeryPool, "pool_id"),
    "resource": (AISurgeryResource, "resource_id"),
    "person_account": (AISurgeryPersonAccount, "binding_id"),
    "room_alias": (AISurgeryRoomAlias, "alias_id"),
    "pool_membership": (AISurgeryPoolMembership, "membership_id"),
}
GOVERNANCE_FIELDS = ("status", "revision", "reviewed_by", "reviewed_at", "review_basis_note", "revoked_by", "revoked_at", "revoke_reason")


def utcnow():
    return datetime.datetime.now(datetime.UTC).replace(tzinfo=None)


def utc_text(value):
    if not isinstance(value, datetime.datetime):
        raise ValueError("Actual UTC datetime required")
    value = value.replace(tzinfo=datetime.UTC) if value.tzinfo is None else value.astimezone(datetime.UTC)
    if value.year < 1000:
        raise ValueError("UTC clock outside MySQL range")
    return value.isoformat(timespec="microseconds").replace("+00:00", "Z")


def canonical_id(value):
    try:
        if not isinstance(value, str) or str(uuid.UUID(value)) != value:
            raise ValueError("Noncanonical UUID")
    except (ValueError, AttributeError, TypeError) as exc:
        raise HTTPException(422, "标识须为规范小写 UUID") from exc
    return value


class WithBasis(StrictModel):
    basis_note: str = Field(min_length=20, max_length=4000)

    @field_validator("basis_note")
    @classmethod
    def meaningful_basis(cls, value):
        if len("".join(value.split())) < 20 or len(value.encode()) > 4000:
            raise ValueError("Explicit basis requires 20 non-whitespace characters and at most 4000 UTF-8 bytes")
        return value


class KnownTime(StrictModel):
    kind: Literal["known"]
    at: UtcText


class UnknownTime(WithBasis):
    kind: Literal["unknown", "not_applicable"]


TimeLimit = Annotated[KnownTime | UnknownTime, Field(discriminator="kind")]


class PoolPayload(WithBasis):
    kind: Literal["pool"]
    department_id: PositiveInteger
    name: str = Field(min_length=1, max_length=80)


class ResourcePayload(WithBasis):
    kind: Literal["resource"]
    resource_kind: Literal["room", "person", "equipment"]
    equipment_id: PositiveInteger | None
    cssd_instrument_id: PositiveInteger | None
    label: str = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def concrete_identity(self):
        count = (self.equipment_id is not None) + (self.cssd_instrument_id is not None)
        if count != (1 if self.resource_kind == "equipment" else 0):
            raise ValueError("Equipment requires exactly one real Equipment/CSSD asset; people and rooms require neither")
        return self


class PersonAccountPayload(WithBasis):
    kind: Literal["person_account"]
    resource_id: UUID
    user_id: PositiveInteger


class RoomAliasPayload(WithBasis):
    kind: Literal["room_alias"]
    resource_id: UUID
    alias_scope: Literal["namespace", "legacy_schedule"]
    alias_namespace: str | None = Field(pattern=r"^[a-zA-Z0-9_.:/-]{1,80}$")
    legacy_schedule_id: UUID | None
    raw_original_text: str = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def explicit_namespace(self):
        if self.alias_scope == "namespace":
            if self.alias_namespace is None or self.legacy_schedule_id is not None:
                raise ValueError("Explicit namespace alias requires a namespace and no legacy schedule")
        elif self.alias_namespace is not None or self.legacy_schedule_id is None:
            raise ValueError("A per-schedule alias requires its exact actual legacy Schedule")
        return self


class PoolMembershipPayload(WithBasis):
    kind: Literal["pool_membership"]
    pool_id: UUID
    resource_id: UUID


RegistryPayload = Annotated[PoolPayload | ResourcePayload | PersonAccountPayload | RoomAliasPayload | PoolMembershipPayload, Field(discriminator="kind")]


class RegistryCreate(StrictModel):
    payload: RegistryPayload


class StageEstimate(WithBasis):
    segment_id: TechnicalKey
    start_offset_us: Offset
    end_offset_us: Offset


class OccupationRequirement(WithBasis):
    segment_ids: list[TechnicalKey] = Field(min_length=1, max_length=8192)
    occupation_mode: Literal["segments", "envelope"]
    transition_class_key: TechnicalKey | None
    transition_class_absent_reason: Literal["unknown", "not_applicable"] | None
    counted_as_work: bool | None
    counted_as_work_absent_reason: Literal["unknown", "not_applicable"] | None

    @model_validator(mode="after")
    def original_absence(self):
        if len(set(self.segment_ids)) != len(self.segment_ids):
            raise ValueError("Repeated stage ID")
        if (self.transition_class_key is None) != (self.transition_class_absent_reason is not None) or (self.counted_as_work is None) != (self.counted_as_work_absent_reason is not None):
            raise ValueError("Class and work accounting absence must be explicit")
        return self


class DemandRequirement(WithBasis):
    slot_id: TechnicalKey
    capability_keys: list[TechnicalKey] = Field(max_length=256)
    occupation: OccupationRequirement


class RoleRequirement(DemandRequirement):
    role_kind: Literal["surgeon", "anesthesia", "assistant", "scrub_nurse", "circulating_nurse", "other"]
    other_role_key: TechnicalKey | None

    @model_validator(mode="after")
    def explicit_role(self):
        if (self.role_kind == "other") != (self.other_role_key is not None):
            raise ValueError("Other role requires its explicit original key")
        return self


class CaseRequirementsPayload(WithBasis):
    kind: Literal["case_requirements"]
    procedure_group_key: TechnicalKey | None
    procedure_group_absent_reason: Literal["unknown", "not_recorded"] | None
    required: bool | None
    required_absent_reason: Literal["unknown", "not_recorded"] | None
    release: TimeLimit
    deadline: TimeLimit
    patient_segment_ids: list[TechnicalKey] = Field(min_length=1, max_length=8192)
    patient_occupation_mode: Literal["segments", "envelope"]
    room: DemandRequirement
    roles: list[RoleRequirement] = Field(max_length=16)
    equipment: list[DemandRequirement] = Field(max_length=16)
    other_requirements_status: Literal["attested_not_required", "all_required_modeled", "incomplete", "unknown"]

    @model_validator(mode="after")
    def exact_missing_and_slots(self):
        if (self.procedure_group_key is None) != (self.procedure_group_absent_reason is not None) or (self.required is None) != (self.required_absent_reason is not None):
            raise ValueError("Case group/required absence must be explicit")
        slots = [self.room.slot_id, *(item.slot_id for item in self.roles), *(item.slot_id for item in self.equipment)]
        if len(set(slots)) != len(slots) or len(set(self.patient_segment_ids)) != len(self.patient_segment_ids):
            raise ValueError("Repeated demand/patient stage")
        return self


class DurationObservationPayload(WithBasis):
    kind: Literal["duration_observation"]
    observed_start_at: UtcText
    observed_end_at: UtcText
    observed_at: UtcText
    legacy_schedule_id: UUID | None
    clock_interpretation: Literal["explicit_original_utc", "reviewed_legacy_clock_mapping"]

    @model_validator(mode="after")
    def actual_clocks(self):
        if not self.observed_start_at < self.observed_end_at <= self.observed_at:
            raise ValueError("Actual closed observation requires positive actual interval and later actual observation")
        if (self.clock_interpretation == "reviewed_legacy_clock_mapping") != (self.legacy_schedule_id is not None):
            raise ValueError("Legacy clock interpretation needs its exact actual schedule")
        return self


class CaseDurationEstimatePayload(WithBasis):
    kind: Literal["case_duration_estimate"]
    method: Literal["reviewed_case_estimate", "unknown"]
    semantics: Literal["declared_upper_bounds", "declared_point_durations", "unknown"]
    segments: list[StageEstimate] = Field(min_length=1, max_length=8192)

    @model_validator(mode="after")
    def unique_stages(self):
        if len({item.segment_id for item in self.segments}) != len(self.segments):
            raise ValueError("Repeated original stage")
        return self


class RoomCapabilityPayload(WithBasis):
    kind: Literal["operating_room_identity_capability"]
    identity_status: Literal["verified", "unknown"]
    capability_keys: list[TechnicalKey] = Field(max_length=256)
    capability_status: Literal["verified", "not_verified", "unknown"]
    valid_from_at: UtcText
    valid_until: TimeLimit


class PersonQualificationPayload(WithBasis):
    kind: Literal["person_identity_qualification"]
    user_id: PositiveInteger
    doctor_id: PositiveInteger | None
    identity_status: Literal["verified", "unknown"]
    capability_keys: list[TechnicalKey] = Field(max_length=256)
    qualification_status: Literal["verified", "not_verified", "unknown"]
    valid_from_at: UtcText
    valid_until: TimeLimit


class EquipmentCapabilityPayload(RoomCapabilityPayload):
    """Explicit reviewed equipment/CSSD capability; no inference from asset names."""

    kind: Literal["equipment_identity_capability"]


class OperationalInterval(WithBasis):
    start_at: UtcText
    end_at: UtcText

    @model_validator(mode="after")
    def increasing(self):
        if self.start_at >= self.end_at:
            raise ValueError("Explicit positive UTC interval required")
        return self


class AvailabilityPayload(OperationalInterval):
    kind: Literal["resource_availability_busy"]
    record_type: Literal["availability"]
    state: Literal["available", "unavailable", "unknown"]


class DutyPayload(OperationalInterval):
    kind: Literal["resource_availability_busy"]
    record_type: Literal["duty"]
    accounting: Accounting

    @model_validator(mode="after")
    def contained_breaks(self):
        if any(item.start_at < self.start_at or item.end_at > self.end_at for item in self.accounting.breaks):
            raise ValueError("Duty breaks must remain within actual duty")
        return self


class BusyPayload(StrictModel):
    """Safe capsule: no patient/admission/procedure/department ID or free narrative."""

    kind: Literal["resource_availability_busy"]
    record_type: Literal["busy_capsule"]
    start_at: UtcText
    end_at: UtcText | None
    end_absent_reason: Literal["ongoing_unknown_end", "not_recorded"] | None
    verified_until_at: UtcText | None
    continuity_status: Literal["confirmed", "unknown"]
    busy_status: Literal["committed", "completed", "cancelled", "unknown"]
    transition_class_key: TechnicalKey | None
    transition_class_absent_reason: Literal["unknown", "not_applicable"] | None
    accounting: Accounting
    basis_code: Literal["explicit_local_operational_observation", "protected_legacy_witness"]
    basis_hash: Hash
    protected_witness_hash: Hash | None

    @model_validator(mode="after")
    def safe_original(self):
        if (self.end_at is None) != (self.end_absent_reason is not None) or (self.transition_class_key is None) != (self.transition_class_absent_reason is not None):
            raise ValueError("Busy end/class absence must be explicit")
        if self.end_at is not None and self.start_at >= self.end_at:
            raise ValueError("Known busy end must follow actual start")
        if self.verified_until_at is not None and (self.verified_until_at < self.start_at or self.end_at is not None and self.verified_until_at > self.end_at):
            raise ValueError("Verified busy prefix exceeds original interval")
        if (self.basis_code == "protected_legacy_witness") != (self.protected_witness_hash is not None):
            raise ValueError("Protected proof must have its exact server-built commitment")
        return self


ResourceAvailabilityPayload = Annotated[AvailabilityPayload | DutyPayload | BusyPayload, Field(discriminator="record_type")]


class TransitionPair(WithBasis):
    from_class_key: TechnicalKey
    to_class_key: TechnicalKey
    minimum_gap_us: Amount
    penalty: Amount


class TransitionPolicyPayload(WithBasis):
    kind: Literal["resource_occupation_policy"]
    policy_type: Literal["transition"]
    effective_from_at: UtcText
    effective_until: TimeLimit
    pairs: list[TransitionPair] = Field(max_length=32768)
    pair_coverage: Literal["attested_complete", "incomplete", "unknown"]

    @model_validator(mode="after")
    def exact_pairs(self):
        if len({(item.from_class_key, item.to_class_key) for item in self.pairs}) != len(self.pairs):
            raise ValueError("Repeated directed transition pair")
        return self


class WorkPolicyPayload(WithBasis):
    kind: Literal["resource_occupation_policy"]
    policy_type: Literal["work"]
    effective_from_at: UtcText
    effective_until: TimeLimit
    max_single_presence: WorkLimit
    max_work_rolling_24h: WorkLimit
    max_work_rolling_7d: WorkLimit
    minimum_rest: WorkLimit
    fixed_windows: list[WorkWindow] = Field(max_length=64)
    policy_reference: str = Field(min_length=1, max_length=4000)


OccupationPolicyPayload = Annotated[TransitionPolicyPayload | WorkPolicyPayload, Field(discriminator="policy_type")]
SourcePayload = Annotated[
    CaseRequirementsPayload
    | DurationObservationPayload
    | CaseDurationEstimatePayload
    | RoomCapabilityPayload
    | PersonQualificationPayload
    | ResourceAvailabilityPayload
    | OccupationPolicyPayload
    | EquipmentCapabilityPayload,
    Field(discriminator="kind"),
]


class ProfessionalAttestation(StrictModel):
    status: Literal["confirmed", "unknown"]
    signer_doctor_id: PositiveInteger | None
    basis_note: str | None = Field(min_length=20, max_length=4000)

    @model_validator(mode="after")
    def separate_signer(self):
        if self.status == "confirmed":
            if self.signer_doctor_id is None or self.basis_note is None or len("".join(self.basis_note.split())) < 20 or len(self.basis_note.encode()) > 4000:
                raise ValueError("Professional confirmation needs the actual signer and explicit original basis")
        elif self.signer_doctor_id is not None or self.basis_note is not None:
            raise ValueError("Unknown is not a professional signature")
        return self


class SourceCreate(StrictModel):
    pool_id: UUID
    resource_id: UUID | None
    application_id: UUID | None
    payload: SourcePayload
    professional_attestation: ProfessionalAttestation

    @model_validator(mode="after")
    def real_subject(self):
        if self.payload.kind in CASE_KINDS:
            if self.application_id is None or self.resource_id is not None:
                raise ValueError("Case original requires its actual application and no generic resource")
        elif self.resource_id is None or self.application_id is not None or self.professional_attestation.status != "unknown":
            raise ValueError("Resource original requires its resource and no fabricated clinical signer")
        return self


class SourceReview(WithBasis):
    expected_revision: int = Field(strict=True, ge=1, le=1)
    expected_content_hash: Hash
    decision: Literal["publish", "reject"]


class SourceRevoke(WithBasis):
    basis_note: str = Field(min_length=20, max_length=1000)
    expected_revision: int = Field(strict=True, ge=1, le=2)
    expected_content_hash: Hash


def current_query(query, *, locking=False):
    query = query.populate_existing()
    return query.with_for_update() if locking else query


def current_actor(db, user, *, locking=False, clinical=False):
    state = inspect(user, raiseerr=False)
    user_id = state.identity[0] if state is not None and state.identity is not None else user.user_id
    actor = current_query(db.query(User).filter_by(user_id=user_id), locking=locking).one_or_none()
    if actor is None or actor.user_role not in SOURCE_ROLES:
        raise HTTPException(403, "当前身份无手术受控来源权限")
    if actor.user_role == "doctor" and not clinical:
        raise HTTPException(403, "病例专业签署不授予资源运营或排台执行权限")
    # Professional source signing has independent actual-care authority. Execution
    # feature.allowed_roles cannot turn a physician into an operational manager.
    if actor.user_role != "super_admin" and not clinical:
        config = current_query(db.query(AIFeatureConfig).filter_by(feature_key="surgery_scheduling"), locking=locking).one_or_none()
        try:
            roles = json.loads(config.allowed_roles_json) if config is not None else list(FEATURE_BY_KEY["surgery_scheduling"].default_roles)
            if not isinstance(roles, list) or any(type(item) is not str for item in roles) or actor.user_role not in roles:
                raise ValueError("Current role excluded")
        except (ValueError, TypeError) as exc:
            raise HTTPException(403, "当前手术来源角色授权已变化") from exc
    return actor


def lock_write_gate(db):
    """First lock for 65-owned mutations, including metadata-bootstrap databases."""
    dialect = db.get_bind().dialect.name
    if dialect == "mysql":
        statement = mysql_insert(AISurgeryWriteGate).values(gate_id=1, revision=1).prefix_with("IGNORE")
    elif dialect == "postgresql":
        statement = postgresql_gate_statement(AISurgeryWriteGate)
    elif dialect == "sqlite":
        statement = sqlite_insert(AISurgeryWriteGate).values(gate_id=1, revision=1).on_conflict_do_nothing(index_elements=["gate_id"])
    else:
        raise HTTPException(409, "本受控手术写入协议尚未验证当前数据库方言")
    db.execute(statement)
    return current_query(db.query(AISurgeryWriteGate).filter_by(gate_id=1), locking=True).one()


def _row(db, cls, field, identity, *, locking=False):
    row = current_query(db.query(cls).filter(getattr(cls, field) == identity), locking=locking).one_or_none()
    if row is None:
        raise HTTPException(404, "受控原件或真实父件不存在")
    return row


def _bounded_json(value, cap):
    try:
        body = canonical_json(value)
        if not body or len(body.encode()) > cap:
            raise ValueError("Complete original exceeds UTF-8 cap")
        return body
    except (ValueError, TypeError, RecursionError) as exc:
        raise HTTPException(422, "完整原件超过明确字节容量，不能截断保存") from exc


def governance_fields(row):
    return {name: utc_text(getattr(row, name)) if name in {"reviewed_at", "revoked_at"} and getattr(row, name) is not None else getattr(row, name) for name in GOVERNANCE_FIELDS}


def _registry_identity(kind, row):
    cls, primary = REGISTRY[kind]
    excluded = {"payload_json", "parent_binding_json", "content_hash", *GOVERNANCE_FIELDS}
    result = {
        column.name: utc_text(getattr(row, column.name)) if column.name == "recorded_at" else getattr(row, column.name)
        for column in cls.__table__.columns
        if column.name not in excluded and not column.name.startswith("active_")
    }
    return {"registry_kind": kind, "registry_record_id": getattr(row, primary), **result}


def _registry_body(kind, row, payload, parent):
    return {**_registry_identity(kind, row), "payload": payload, "parent_binding": parent}


def _governance_valid(row):
    if row.status not in {"draft", "published", "rejected", "revoked"} or type(row.revision) is not int:
        raise ValueError("Unknown governance")
    reviewed = row.reviewed_at is not None and row.reviewed_by is not None
    if reviewed:
        SourceReview(expected_revision=1, expected_content_hash=row.content_hash, decision="publish", basis_note=row.review_basis_note)
        if row.reviewed_at < row.recorded_at:
            raise ValueError("Backdated review")
    elif row.reviewed_at is not None or row.reviewed_by is not None or row.review_basis_note != "":
        raise ValueError("Partial review")
    if row.status == "draft" and (row.revision != 1 or reviewed) or row.status in {"published", "rejected"} and (row.revision != 2 or not reviewed):
        raise ValueError("False review revision")
    if row.status == "revoked":
        SourceRevoke(expected_revision=2 if reviewed else 1, expected_content_hash=row.content_hash, basis_note=row.revoke_reason)
        if row.revision != (3 if reviewed else 2) or row.revoked_at is None or row.revoked_by is None or row.revoked_at < (row.reviewed_at or row.recorded_at):
            raise ValueError("False revocation")
    elif row.revoked_at is not None or row.revoked_by is not None or row.revoke_reason != "":
        raise ValueError("Revocation on active original")


def registry_proof(kind, row):
    try:
        if row.schema_version != "surgery_registry_private_v1":
            raise ValueError("Unsupported frozen registry schema")
        _bounded_json(json.loads(row.payload_json), REGISTRY_BYTES)
        payload = RegistryCreate(payload=json.loads(row.payload_json)).payload.model_dump(mode="json")
        parent = RegistryParentBinding.model_validate(json.loads(row.parent_binding_json)).model_dump(mode="json")
        if (
            type(parent) is not dict
            or len(row.parent_binding_json.encode()) > PARENT_BYTES
            or canonical_json(payload) != row.payload_json
            or canonical_json(parent) != row.parent_binding_json
            or payload["kind"] != kind
        ):
            raise ValueError("Noncanonical original")
        body = _registry_body(kind, row, payload, parent)
        if len(canonical_json(body).encode()) > REGISTRY_BYTES:
            raise ValueError("Complete registry original exceeds cap")
        if hash_content(body) != row.content_hash:
            raise ValueError("Full original SHA changed")
        if hasattr(row, "status"):
            _governance_valid(row)
        _assert_registry_binding(kind, row, payload)
        return body
    except (ValueError, TypeError, KeyError, ValidationError, RecursionError, HTTPException) as exc:
        raise HTTPException(409, "受控登记原件自身完整性不成立，不能作为冻结原件返回") from exc


def _pool_scope(db, actor, pool, *, locking=False):
    _row(db, Department, "department_id", pool.department_id, locking=locking)
    if actor.user_role == "super_admin":
        return
    doctors = current_query(db.query(Doctor).filter_by(user_id=actor.user_id).order_by(Doctor.doctor_id), locking=locking).all()
    if any(doctor.department_id == pool.department_id for doctor in doctors):
        return
    account = current_query(db.query(AISurgeryPersonAccount).filter_by(user_id=actor.user_id), locking=locking).one_or_none()
    if account is not None:
        registry_proof("person_account", account)
        member = current_query(db.query(AISurgeryPoolMembership).filter_by(pool_id=pool.pool_id, resource_id=account.resource_id, status="published"), locking=locking).one_or_none()
        if member is not None:
            proof = registry_proof("pool_membership", member)
            if _registry_parent(db, proof["payload"], locking=locking) == proof["parent_binding"]:
                return
    raise HTTPException(403, "未建立此手术资源池的当前实际科室或显式人员成员范围")


def pool_scope(db, user, pool_id, *, locking=False, require_published=True, clinical=False):
    actor = current_actor(db, user, locking=locking, clinical=clinical)
    pool = _row(db, AISurgeryPool, "pool_id", canonical_id(pool_id), locking=locking)
    registry_proof("pool", pool)
    _pool_scope(db, actor, pool, locking=locking)
    if require_published and pool.status != "published":
        raise HTTPException(409, "资源池尚未发布或已失效")
    return actor, pool


def _registry_columns(payload):
    kind = payload["kind"]
    fields = {
        "pool": ("department_id",),
        "resource": ("resource_kind", "equipment_id", "cssd_instrument_id"),
        "person_account": ("resource_id", "user_id"),
        "room_alias": ("resource_id", "alias_scope", "alias_namespace", "legacy_schedule_id"),
        "pool_membership": ("pool_id", "resource_id"),
    }[kind]
    values = {key: payload[key] for key in fields}
    if kind == "person_account":
        values["resource_kind"] = "person"
    if kind == "room_alias":
        values.update(resource_kind="room", raw_text_hash=hash_content(payload["raw_original_text"]))
        values["alias_key"] = hash_content(
            {"scope": payload["alias_scope"], "namespace": payload["alias_namespace"], "legacy_schedule_id": payload["legacy_schedule_id"], "raw_text_hash": values["raw_text_hash"]}
        )
    if kind == "pool_membership":
        values["pair_key"] = hash_content({"pool_id": payload["pool_id"], "resource_id": payload["resource_id"]})
    return values


def _registry_parent(db, payload, *, locking=False):
    kind = payload["kind"]
    parent = {"department": None, "resource": None, "pool": None, "user": None, "equipment": None, "cssd_instrument": None, "legacy_schedule": None}
    if kind == "pool":
        department = _row(db, Department, "department_id", payload["department_id"], locking=locking)
        parent["department"] = {"department_id": department.department_id}
    if "resource_id" in payload:
        resource = _row(db, AISurgeryResource, "resource_id", payload["resource_id"], locking=locking)
        registry_proof("resource", resource)
        expected_kind = {"person_account": "person", "room_alias": "room"}.get(kind)
        if expected_kind is not None and resource.resource_kind != expected_kind:
            raise HTTPException(422, "所选真实资源种类不匹配")
        parent["resource"] = {"resource_id": resource.resource_id, "resource_kind": resource.resource_kind, "content_hash": resource.content_hash}
    if kind == "resource":
        if payload["equipment_id"] is not None:
            item = _row(db, Equipment, "equipment_id", payload["equipment_id"], locking=locking)
            parent["equipment"] = {"equipment_id": item.equipment_id}
        if payload["cssd_instrument_id"] is not None:
            item = _row(db, CssdInstrument, "instrument_id", payload["cssd_instrument_id"], locking=locking)
            parent["cssd_instrument"] = {"instrument_id": item.instrument_id}
    if kind == "person_account":
        item = _row(db, User, "user_id", payload["user_id"], locking=locking)
        parent["user"] = {"user_id": item.user_id}
    if kind == "room_alias" and payload["legacy_schedule_id"] is not None:
        schedule = _row(db, SurgerySchedule, "schedule_id", payload["legacy_schedule_id"], locking=locking)
        if schedule.operating_room != payload["raw_original_text"]:
            raise HTTPException(409, "原手术室字符串已变化，不能修剪、猜测或映射其他房间")
        parent["legacy_schedule"] = {"schedule_id": schedule.schedule_id, "raw_text_hash": hash_content(schedule.operating_room)}
    if kind == "pool_membership":
        pool = _row(db, AISurgeryPool, "pool_id", payload["pool_id"], locking=locking)
        registry_proof("pool", pool)
        if pool.status != "published":
            raise HTTPException(409, "成员关系只能基于已发布资源池")
        parent["pool"] = {"pool_id": pool.pool_id, "department_id": pool.department_id, "content_hash": pool.content_hash, "governance_hash": hash_content(governance_fields(pool))}
    return RegistryParentBinding.model_validate(parent).model_dump(mode="json")


def _assert_registry_binding(kind, row, payload):
    for name, value in _registry_columns(payload).items():
        if getattr(row, name) != value:
            raise HTTPException(409, "登记真实 SQL 身份与不可变原件不一致")
    if kind in {"room_alias", "pool_membership"}:
        field, original = ("active_alias_key", "alias_key") if kind == "room_alias" else ("active_pair_key", "pair_key")
        if getattr(row, field) != (getattr(row, original) if row.status == "published" else None):
            raise HTTPException(409, "当前唯一身份声明与治理状态不一致")


def registry_row(db, kind, record_id, *, locking=False):
    if kind not in REGISTRY:
        raise HTTPException(422, "未知资源登记类型")
    cls, primary = REGISTRY[kind]
    return _row(db, cls, primary, canonical_id(record_id), locking=locking)


def registry_current(db, user, kind, record_id, *, pool_id=None, audit_only=False, locking=False):
    actor = current_actor(db, user, locking=locking)
    row = registry_row(db, kind, record_id, locking=locking)
    body = registry_proof(kind, row)
    _assert_registry_binding(kind, row, body["payload"])
    if audit_only and actor.user_role != "super_admin":
        raise HTTPException(403, "冻结审计仅限超级管理员")
    if actor.user_role != "super_admin":
        if kind == "pool":
            _pool_scope(db, actor, row, locking=locking)
        else:
            if pool_id is None:
                raise HTTPException(422, "普通身份读取全局资源必须绑定一个实际授权资源池")
            _, pool = pool_scope(db, actor, pool_id, locking=locking)
            if kind == "pool_membership" and row.pool_id != pool.pool_id:
                raise HTTPException(403, "成员原件不属于所选资源池")
            resource_id = row.resource_id if kind != "resource" else row.resource_id
            members = current_query(db.query(AISurgeryPoolMembership).filter_by(pool_id=pool.pool_id, resource_id=resource_id, status="published"), locking=locking).all()
            if not members:
                raise HTTPException(403, "此资源尚无当前资源池成员资格")
            for member in members:
                registry_proof("pool_membership", member)
    reasons = []
    if hasattr(row, "status") and row.status != "published":
        reasons.append("registry_not_published")
    try:
        if _registry_parent(db, body["payload"], locking=locking) != body["parent_binding"]:
            reasons.append("original_parent_changed")
    except HTTPException as exc:
        if exc.status_code not in {404, 409, 422}:
            raise
        reasons.append("original_parent_unavailable")
    redacted = bool(reasons) and actor.user_role != "super_admin" and not (hasattr(row, "status") and row.status == "draft" and not any(reason.startswith("original_parent") for reason in reasons))
    state = governance_fields(row) if hasattr(row, "status") else None
    return {
        **_registry_identity(kind, row),
        "content_hash": row.content_hash,
        "governance": {key: None if redacted and key in {"review_basis_note", "revoke_reason"} else value for key, value in state.items()} if state is not None else None,
        "governance_hash": hash_content(state) if state is not None else None,
        "payload": None if redacted else body["payload"],
        "parent_binding": None if redacted else body["parent_binding"],
        "eligible_for_new_use": not reasons,
        "exclusion_reasons": reasons,
        "audit_only": audit_only,
        "can_review": actor.user_role == "super_admin" and hasattr(row, "status") and row.status == "draft" and not any(reason.startswith("original_parent") for reason in reasons),
        "can_revoke": actor.user_role == "super_admin" and hasattr(row, "status") and row.status in {"draft", "published"},
    }


def create_registry(db, user, kind, request):
    lock_write_gate(db)
    actor = current_actor(db, user, locking=True)
    if actor.user_role != "super_admin":
        raise HTTPException(403, "技术资源身份登记与跨账号合并仅限超级管理员")
    request = RegistryCreate.model_validate(request.model_dump(mode="json") if isinstance(request, BaseModel) else request)
    payload = request.payload.model_dump(mode="json")
    if payload["kind"] != kind:
        raise HTTPException(422, "资源登记路径与类型不一致")
    parent = _registry_parent(db, payload, locking=True)
    cls, primary = REGISTRY[kind]
    values = _registry_columns(payload)
    row = cls(
        **values,
        **{primary: str(uuid.uuid4())},
        schema_version="surgery_registry_private_v1",
        payload_json=_bounded_json(payload, REGISTRY_BYTES),
        parent_binding_json=_bounded_json(parent, PARENT_BYTES),
        recorded_at=utcnow(),
        created_by=actor.user_id,
    )
    if hasattr(cls, "status"):
        row.status, row.revision = "draft", 1
        row.reviewed_by = row.reviewed_at = row.revoked_by = row.revoked_at = None
        row.review_basis_note = row.revoke_reason = ""
    body = _registry_body(kind, row, payload, parent)
    _bounded_json(body, REGISTRY_BYTES)
    row.content_hash = hash_content(body)
    db.add(row)
    db.flush()
    registry_current(db, actor, kind, getattr(row, primary), audit_only=True, locking=True)
    if current_actor(db, actor, locking=True).user_role != "super_admin":
        raise HTTPException(403, "登记后超级管理员权限已变化，原件与审计均不能保存")
    governance.audit(db, actor.user_id, "surgery.registry.create", getattr(row, primary), {"kind": kind, "content_hash": row.content_hash})
    db.flush()
    if current_actor(db, actor, locking=True).user_role != "super_admin":
        raise HTTPException(403, "审计落库后超级管理员权限已变化")
    registry_current(db, actor, kind, getattr(row, primary), audit_only=True, locking=True)
    return row


def _cas_governance(db, row, request, actor, *, revoke=False, active_fields=None):
    _governance_valid(row)
    if row.content_hash != request.expected_content_hash or row.revision != request.expected_revision:
        raise HTTPException(409, "原件内容或治理版本已变化")
    now = utcnow()
    if now < (row.reviewed_at or row.recorded_at):
        raise HTTPException(409, "服务器治理时刻早于原件")
    if revoke:
        if row.status not in {"draft", "published"}:
            raise HTTPException(409, "该原件已处于终态")
        changes = {"status": "revoked", "revision": row.revision + 1, "revoked_at": now, "revoked_by": actor.user_id, "revoke_reason": request.basis_note}
    else:
        if row.status != "draft":
            raise HTTPException(409, "原件已经审核，不能覆盖原审核")
        changes = {"status": "published" if request.decision == "publish" else "rejected", "revision": 2, "reviewed_at": now, "reviewed_by": actor.user_id, "review_basis_note": request.basis_note}
    for name, value in (active_fields or {}).items():
        changes[name] = value if changes["status"] == "published" else None
    cls = type(row)
    primary = inspect(cls).primary_key[0].name
    count = (
        db.query(cls)
        .filter(getattr(cls, primary) == getattr(row, primary), cls.status == row.status, cls.revision == row.revision, cls.content_hash == row.content_hash)
        .update(changes, synchronize_session=False)
    )
    if count != 1:
        raise HTTPException(409, "原件治理发生并发变化")
    db.flush()
    db.refresh(row)


def review_registry(db, user, kind, record_id, request, *, revoke=False):
    lock_write_gate(db)
    actor = current_actor(db, user, locking=True)
    if actor.user_role != "super_admin":
        raise HTTPException(403, "资源登记治理仅限当前超级管理员")
    cls = SourceRevoke if revoke else SourceReview
    request = cls.model_validate(request.model_dump(mode="json") if isinstance(request, BaseModel) else request)
    row = registry_row(db, kind, record_id, locking=True)
    if not hasattr(row, "status"):
        raise HTTPException(409, "物理身份锚不可撤销或重建；请审核其独立身份、资格或可用性声明")
    current = registry_current(db, actor, kind, record_id, audit_only=True, locking=True)
    if not revoke and any(reason.startswith("original_parent") for reason in current["exclusion_reasons"]):
        raise HTTPException(409, "登记原父件已变化，不能发布过期声明")
    active = {"active_alias_key": row.alias_key} if kind == "room_alias" else {"active_pair_key": row.pair_key} if kind == "pool_membership" else {}
    _cas_governance(db, row, request, actor, revoke=revoke, active_fields=active)
    if current_actor(db, actor, locking=True).user_role != "super_admin":
        raise HTTPException(403, "审核后超级管理员权限已变化，治理与审计均回滚")
    registry_current(db, actor, kind, record_id, audit_only=True, locking=True)
    governance.audit(
        db,
        actor.user_id,
        "surgery.registry.revoke" if revoke else "surgery.registry.review",
        record_id,
        {"kind": kind, "status": row.status, "revision": row.revision, "content_hash": row.content_hash},
    )
    db.flush()
    if current_actor(db, actor, locking=True).user_role != "super_admin":
        raise HTTPException(403, "审计落库后超级管理员权限已变化")
    registry_current(db, actor, kind, record_id, audit_only=True, locking=True)
    return row


class PoolBinding(StrictModel):
    pool_id: UUID
    department_id: PositiveInteger
    content_hash: Hash
    governance_hash: Hash


class ResourceBinding(StrictModel):
    resource_id: UUID
    resource_kind: Literal["room", "person", "equipment"]
    content_hash: Hash
    membership_id: UUID
    membership_content_hash: Hash
    membership_governance_hash: Hash


class CaseBinding(StrictModel):
    application_id: UUID
    patient_id: PositiveInteger
    admission_id: UUID | None
    doctor_id: PositiveInteger
    department_id: PositiveInteger
    admission_doctor_id: PositiveInteger | None
    clinical_content_hash: Hash


class DoctorBinding(StrictModel):
    doctor_id: PositiveInteger
    user_id: PositiveInteger
    department_id: PositiveInteger | None
    identity_content_hash: Hash


class EquipmentCondition(StrictModel):
    equipment_id: PositiveInteger | None
    cssd_instrument_id: PositiveInteger | None
    state_hash: Hash


class LegacyClockBinding(StrictModel):
    schedule_id: UUID
    original_clock_hash: Hash


class SignatureBinding(WithBasis):
    doctor_id: PositiveInteger
    user_id: PositiveInteger
    original_role: str = Field(min_length=1, max_length=20)
    signed_at: UtcText


class SourceParentBinding(StrictModel):
    pool: PoolBinding
    resource: ResourceBinding | None
    case: CaseBinding | None
    professional_signature: SignatureBinding | None
    qualification_doctor: DoctorBinding | None
    person_account_hash: Hash | None
    physical_condition: EquipmentCondition | None
    legacy_clock: LegacyClockBinding | None


class SourceFrozenIdentity(StrictModel):
    source_record_id: UUID
    source_kind: FactKind
    pool_id: UUID
    resource_id: UUID | None
    application_id: UUID | None
    patient_id: PositiveInteger | None
    admission_id: UUID | None
    professional_status: Literal["confirmed", "unknown"]
    signed_by_doctor_id: PositiveInteger | None
    signed_by_user_id: PositiveInteger | None
    signed_at: UtcText | None
    schema_version: Literal["surgery_fact_private_v1"]
    recorded_at: UtcText
    created_by: PositiveInteger


class SourceWrapper(SourceFrozenIdentity):
    source_id: str = Field(pattern=r"^surgery_fact:[a-f0-9-]{36}:[a-f0-9]{12}$")
    content_hash: Hash
    status: SourceStatus
    revision: int = Field(strict=True, ge=1, le=3)
    reviewed_by: PositiveInteger | None
    reviewed_at: UtcText | None
    review_basis_note: str | None
    revoked_by: PositiveInteger | None
    revoked_at: UtcText | None
    revoke_reason: str | None
    governance_hash: Hash
    payload: SourcePayload | None
    parent_binding: SourceParentBinding | None
    eligible_for_new_use: bool
    exclusion_reasons: list[str]
    audit_only: bool
    can_review: bool
    can_revoke: bool


class SafeBusyCapsule(StrictModel):
    schema_version: Literal["surgery_safe_busy_capsule_v1"]
    resource_id: UUID
    source_record_id: UUID
    source_kind: Literal["resource_availability_busy"]
    source_content_hash: Hash
    source_governance_hash: Hash
    status: SourceStatus
    revision: int = Field(strict=True, ge=1, le=3)
    recorded_at: UtcText
    published_at: UtcText | None
    payload: BusyPayload
    eligible_for_new_use: bool
    exclusion_reasons: list[str]


class SafeBusyCapsuleWrapper(SafeBusyCapsule):
    capsule_hash: Hash


class DepartmentLink(StrictModel):
    department_id: PositiveInteger


class ResourceLink(StrictModel):
    resource_id: UUID
    resource_kind: Literal["room", "person", "equipment"]
    content_hash: Hash


class UserLink(StrictModel):
    user_id: PositiveInteger


class EquipmentLink(StrictModel):
    equipment_id: PositiveInteger


class CssdLink(StrictModel):
    instrument_id: PositiveInteger


class LegacyRoomLink(StrictModel):
    schedule_id: UUID
    raw_text_hash: Hash


class RegistryParentBinding(StrictModel):
    department: DepartmentLink | None
    resource: ResourceLink | None
    pool: PoolBinding | None
    user: UserLink | None
    equipment: EquipmentLink | None
    cssd_instrument: CssdLink | None
    legacy_schedule: LegacyRoomLink | None


def _clinical_care(db, actor, application, *, signer_doctor_id=None, locking=False):
    """Independently refresh care dependencies; Super read is not a signature."""
    from app.ai.context import authorize_patient

    _row(db, Patient, "patient_id", application.patient_id, locking=locking)
    if application.admission_id is not None:
        admission = _row(db, Admission, "admission_id", application.admission_id, locking=locking)
        if admission.patient_id != application.patient_id:
            raise HTTPException(409, "原手术申请与住院患者不一致")
    doctors = current_query(db.query(Doctor).filter_by(user_id=actor.user_id).order_by(Doctor.doctor_id), locking=locking).all()
    if signer_doctor_id is not None and actor.user_role not in {"doctor", "director", "super_admin"}:
        raise HTTPException(403, "当前账户不是可专业签署的临床身份")
    if signer_doctor_id is not None and not any(doctor.doctor_id == signer_doctor_id for doctor in doctors):
        raise HTTPException(403, "专业签署医师必须属于当前真实用户账号")
    if actor.user_role == "super_admin" and signer_doctor_id is None:
        return
    if not doctors:
        raise HTTPException(403, "运营或超级管理员身份不能替代真实医师及患者照护关系")
    # Lock exact care-grant and schedule rows used by the existing care policy.
    current_query(db.query(AIPatientGrant).filter_by(user_id=actor.user_id, patient_id=application.patient_id).order_by(AIPatientGrant.grant_id), locking=locking).all()
    current_query(db.query(SurgerySchedule).filter_by(application_id=application.application_id).order_by(SurgerySchedule.schedule_id), locking=locking).all()
    effective = User(user_id=actor.user_id, username=actor.username, user_role="director" if actor.user_role == "director" else "doctor")
    authorize_patient(db, effective, application.patient_id, "inpatient" if application.admission_id is not None else "patient", application.admission_id)


def _source_parent(db, actor, request, *, signature=None, locking=False, authorize=True, authorize_original_pool=True):
    clinical = request.payload.kind in CASE_KINDS
    if authorize_original_pool:
        _, pool = pool_scope(db, actor, request.pool_id, locking=locking, clinical=clinical)
    else:
        if clinical or authorize:
            raise HTTPException(403, "跨池校验仅限已独立授权共享资源的安全忙时胶囊")
        pool = _row(db, AISurgeryPool, "pool_id", request.pool_id, locking=locking)
        registry_proof("pool", pool)
        if pool.status != "published":
            raise HTTPException(409, "原忙时资源池已失效")
    result = {
        "pool": {"pool_id": pool.pool_id, "department_id": pool.department_id, "content_hash": pool.content_hash, "governance_hash": hash_content(governance_fields(pool))},
        "resource": None,
        "case": None,
        "professional_signature": signature,
        "qualification_doctor": None,
        "person_account_hash": None,
        "physical_condition": None,
        "legacy_clock": None,
    }
    if clinical:
        application = _row(db, SurgeryApplication, "application_id", request.application_id, locking=locking)
        doctor = _row(db, Doctor, "doctor_id", application.doctor_id, locking=locking)
        admission = _row(db, Admission, "admission_id", application.admission_id, locking=locking) if application.admission_id is not None else None
        if admission is not None and admission.patient_id != application.patient_id:
            raise HTTPException(409, "原申请与住院患者不一致")
        department_id = admission.department_id if admission is not None else doctor.department_id
        if department_id != pool.department_id:
            raise HTTPException(403, "病例原科室与资源池原科室不一致")
        if authorize:
            _clinical_care(db, actor, application, signer_doctor_id=request.professional_attestation.signer_doctor_id, locking=locking)
        fields = ("surgery_name", "surgery_code", "surgery_level", "anesthesia_type", "scheduled_date", "preop_diagnosis", "surgery_indication", "contraindication")
        clinical_original = {field: getattr(application, field).isoformat() if isinstance(getattr(application, field), datetime.date) else getattr(application, field) for field in fields}
        result["case"] = {
            "application_id": application.application_id,
            "patient_id": application.patient_id,
            "admission_id": application.admission_id,
            "doctor_id": application.doctor_id,
            "department_id": department_id,
            "admission_doctor_id": admission.doctor_id if admission else None,
            "clinical_content_hash": hash_content(clinical_original),
        }
        if request.payload.kind == "duration_observation" and request.payload.legacy_schedule_id is not None:
            schedule = _row(db, SurgerySchedule, "schedule_id", request.payload.legacy_schedule_id, locking=locking)
            if schedule.application_id != application.application_id or schedule.patient_id != application.patient_id:
                raise HTTPException(409, "时长原观测引用了其他病例的旧执行记录")
            # A hash of lexical naive originals does not assert that they were UTC.
            result["legacy_clock"] = {
                "schedule_id": schedule.schedule_id,
                "original_clock_hash": hash_content(
                    {key: getattr(schedule, key).isoformat(timespec="microseconds") if getattr(schedule, key) is not None else None for key in ("start_time", "end_time")}
                ),
            }
    else:
        resource = _row(db, AISurgeryResource, "resource_id", request.resource_id, locking=locking)
        registry_proof("resource", resource)
        member = current_query(db.query(AISurgeryPoolMembership).filter_by(pool_id=pool.pool_id, resource_id=resource.resource_id, status="published"), locking=locking).one_or_none()
        if member is None:
            raise HTTPException(409, "资源缺少当前已发布的资源池成员原件")
        proof = registry_proof("pool_membership", member)
        if _registry_parent(db, proof["payload"], locking=locking) != proof["parent_binding"]:
            raise HTTPException(409, "资源池成员原父件已变化")
        kind = request.payload.kind
        required = (
            "room"
            if kind == "operating_room_identity_capability"
            else "equipment"
            if kind == "equipment_identity_capability"
            else "person"
            if kind == "person_identity_qualification" or isinstance(request.payload, (DutyPayload, WorkPolicyPayload))
            else None
        )
        if required is not None and resource.resource_kind != required:
            raise HTTPException(422, "人员班次、资格、工时或手术室能力与真实资源种类不符")
        result["resource"] = {
            "resource_id": resource.resource_id,
            "resource_kind": resource.resource_kind,
            "content_hash": resource.content_hash,
            "membership_id": member.membership_id,
            "membership_content_hash": member.content_hash,
            "membership_governance_hash": hash_content(governance_fields(member)),
        }
        if kind == "person_identity_qualification":
            account = current_query(db.query(AISurgeryPersonAccount).filter_by(user_id=request.payload.user_id), locking=locking).one_or_none()
            if account is None or account.resource_id != resource.resource_id:
                raise HTTPException(409, "人员资格必须绑定该真实用户唯一的自然人资源")
            registry_proof("person_account", account)
            result["person_account_hash"] = account.content_hash
            if request.payload.doctor_id is not None:
                doctor = _row(db, Doctor, "doctor_id", request.payload.doctor_id, locking=locking)
                if doctor.user_id != account.user_id:
                    raise HTTPException(409, "所选医师别名与实际用户不一致")
                result["qualification_doctor"] = {
                    "doctor_id": doctor.doctor_id,
                    "user_id": doctor.user_id,
                    "department_id": doctor.department_id,
                    "identity_content_hash": hash_content({key: getattr(doctor, key) for key in ("name", "title", "education", "permission")}),
                }
        if resource.equipment_id is not None:
            result["physical_condition"] = {
                "equipment_id": resource.equipment_id,
                "cssd_instrument_id": None,
                "state_hash": physical_resource_current_state(db, resource, locking=locking)["state_hash"],
            }
        if resource.cssd_instrument_id is not None:
            item = _row(db, CssdInstrument, "instrument_id", resource.cssd_instrument_id, locking=locking)
            result["physical_condition"] = {
                "equipment_id": None,
                "cssd_instrument_id": item.instrument_id,
                "state_hash": hash_content(
                    {"status": item.status, "expire_date": item.expire_date.isoformat() if item.expire_date else None, "bd_test": item.bd_test, "bio_monitor": item.bio_monitor}
                ),
            }
    return SourceParentBinding.model_validate(result).model_dump(mode="json")


def _json_size(value):
    """Count canonical UTF-8/escaping before materializing a large raw TEXT body."""
    if isinstance(value, str):
        size = 2
        if len(value) > FACT_BYTES:
            raise HTTPException(422, "完整设备原证据超过字节容量，不能截断")
        for char in value:
            if char in {'"', "\\", "\b", "\f", "\n", "\r", "\t"}:
                size += 2
            elif ord(char) < 32:
                size += 6
            else:
                size += 1 if ord(char) < 128 else len(char.encode("utf-8"))
            if size > FACT_BYTES:
                raise HTTPException(422, "完整设备原证据超过字节容量，不能截断")
        return size
    if isinstance(value, dict):
        return 2 + max(len(value) - 1, 0) + sum(_json_size(key) + 1 + _json_size(item) for key, item in value.items())
    if isinstance(value, list):
        return 2 + max(len(value) - 1, 0) + sum(_json_size(item) for item in value)
    return len(canonical_json(value).encode())


def physical_resource_current_state(db, resource, *, locking=False):
    """Complete bounded maintenance/inspection commitment, never a UTC conversion.

    Inventory counts/notes do not determine future availability. Real equipment
    and complete child-row locking are separate from empirical MySQL lock proof.
    """
    if resource.equipment_id is None:
        raise HTTPException(422, "此依赖集合仅适用于真实 Equipment 资产")
    item = _row(db, Equipment, "equipment_id", resource.equipment_id, locking=locking)
    asset = {key: getattr(item, key) for key in ("equipment_id", "asset_no", "name", "category", "model", "department_id", "location", "status")}
    asset["expiry_date"] = item.expiry_date.isoformat() if item.expiry_date else None
    if _json_size(asset) + 32 > FACT_BYTES:
        raise HTTPException(422, "完整设备依赖超过字节容量")
    header = ('{"asset":' + canonical_json(asset) + ',"child_rows":[').encode()
    digest = hashlib.sha256(header)
    used = len(header) + 2
    count = 0
    counts = {}
    for cls in (EquipmentMaintenance, EquipmentInspection):
        primary = inspect(cls).primary_key[0]
        cursor = None
        counts[cls.__tablename__] = 0
        while True:
            query = db.query(cls).filter(cls.equipment_id == resource.equipment_id)
            if cursor is not None:
                query = query.filter(primary > cursor)
            rows = current_query(query.order_by(primary).limit(128), locking=locking).all()
            if not rows:
                break
            for row in rows:
                count += 1
                if count > 200000:
                    raise HTTPException(422, "完整设备依赖超过扫描容量，不能截断")
                values = {}
                for column in cls.__table__.columns:
                    value = getattr(row, column.name)
                    if isinstance(value, datetime.datetime):
                        value = value.isoformat(timespec="microseconds")  # lexical naive original; no Z suffix guessed
                    elif isinstance(value, datetime.date):
                        value = value.isoformat()
                    elif value is not None and not isinstance(value, (str, int, float, bool)):
                        value = str(value)  # original SQL fixed-precision Decimal
                    values[column.name] = value
                original = {"kind": cls.__tablename__, "row": values}
                size = _json_size(original) + (1 if count > 1 else 0)
                if size > FACT_BYTES - used:
                    raise HTTPException(422, "完整设备依赖累计超过8MiB，不能截断或先构建超大对象")
                used += size
                if count > 1:
                    digest.update(b",")
                digest.update(canonical_json(original).encode())
                counts[cls.__tablename__] += 1
            cursor = getattr(rows[-1], primary.name)
    digest.update(b"]}")
    return {"state_hash": digest.hexdigest(), "child_counts": counts, "canonical_bytes": used}


def _source_identity(row):
    excluded = {"payload_json", "parent_binding_json", "content_hash", *GOVERNANCE_FIELDS}
    values = {
        column.name: utc_text(getattr(row, column.name)) if column.name in {"recorded_at", "signed_at"} and getattr(row, column.name) is not None else getattr(row, column.name)
        for column in AISurgerySource.__table__.columns
        if column.name not in excluded
    }
    return SourceFrozenIdentity.model_validate(values).model_dump(mode="json")


def source_row(db, record_id, kind=None, *, locking=False):
    row = _row(db, AISurgerySource, "source_record_id", canonical_id(record_id), locking=locking)
    if kind is not None and row.source_kind != kind:
        raise HTTPException(404, "原件类型不匹配")
    return row


def source_proof(row):
    try:
        if row.schema_version != "surgery_fact_private_v1" or str(uuid.UUID(row.source_record_id)) != row.source_record_id:
            raise ValueError("Wrong original source identity/schema")
        payload = json.loads(row.payload_json)
        parent = SourceParentBinding.model_validate(json.loads(row.parent_binding_json)).model_dump(mode="json")
        signature = parent["professional_signature"]
        attestation = {"status": row.professional_status, "signer_doctor_id": row.signed_by_doctor_id, "basis_note": signature["basis_note"] if signature else None}
        request = SourceCreate(pool_id=row.pool_id, resource_id=row.resource_id, application_id=row.application_id, payload=payload, professional_attestation=attestation)
        if request.payload.kind != row.source_kind or parent["pool"]["pool_id"] != row.pool_id:
            raise ValueError("Wrong original kind or pool")
        if request.payload.kind in CASE_KINDS:
            if parent["case"] is None or any(parent["case"][key] != getattr(row, key) for key in ("application_id", "patient_id", "admission_id")) or parent["resource"] is not None:
                raise ValueError("Case parent mismatch")
        elif parent["resource"] is None or parent["resource"]["resource_id"] != row.resource_id or parent["case"] is not None:
            raise ValueError("Resource parent mismatch")
        if row.professional_status == "confirmed":
            if (
                signature is None
                or (signature["doctor_id"], signature["user_id"], signature["signed_at"]) != (row.signed_by_doctor_id, row.signed_by_user_id, utc_text(row.signed_at))
                or row.signed_at != row.recorded_at
                or row.signed_by_user_id != row.created_by
            ):
                raise ValueError("Administrative review is not a professional signature")
        elif signature is not None or row.signed_by_user_id is not None or row.signed_at is not None:
            raise ValueError("Unconfirmed fact has a false signer")
        typed = request.payload.model_dump(mode="json")
        if (
            canonical_json(typed) != row.payload_json
            or canonical_json(parent) != row.parent_binding_json
            or len(row.payload_json.encode()) > FACT_BYTES
            or len(row.parent_binding_json.encode()) > PARENT_BYTES
        ):
            raise ValueError("Incomplete/noncanonical original")
        body = {**_source_identity(row), "payload": typed, "parent_binding": parent}
        if len(canonical_json(body).encode()) > FACT_BYTES:
            raise ValueError("Complete source exceeds cap")
        if hash_content(body) != row.content_hash:
            raise ValueError("Full source SHA changed")
        _governance_valid(row)
        return body, request
    except (ValueError, TypeError, KeyError, ValidationError, RecursionError) as exc:
        raise HTTPException(409, "手术原件自身完整性不成立，不得伪称完整冻结原件") from exc


def source_current(db, user, kind, record_id, *, audit_only=False, as_of=None, locking=False):
    row = source_row(db, record_id, kind, locking=locking)
    body, request = source_proof(row)
    actor = current_actor(db, user, locking=locking, clinical=kind in CASE_KINDS)
    if audit_only and actor.user_role != "super_admin":
        raise HTTPException(403, "完整冻结审计仅限超级管理员")
    # Always authorize the original pool; audit does not grant ordinary cross-scope access.
    if actor.user_role != "super_admin":
        pool = _row(db, AISurgeryPool, "pool_id", row.pool_id, locking=locking)
        registry_proof("pool", pool)
        _pool_scope(db, actor, pool, locking=locking)
        if kind in CASE_KINDS:
            application = _row(db, SurgeryApplication, "application_id", row.application_id, locking=locking)
            if application.patient_id != row.patient_id or application.admission_id != row.admission_id:
                raise HTTPException(403, "原病例患者或住院范围已变，当前新病例照护不能授权旧患者原件")
            _clinical_care(db, actor, application, locking=locking)
    reasons = []
    if row.status != "published":
        reasons.append("source_not_published")
    if isinstance(request.payload, BusyPayload) and request.payload.protected_witness_hash is not None:
        if not _protected_current(db, row, body["payload"], locking=locking):
            reasons.append("protected_original_changed")
    try:
        # An old signer's later role is not reinterpreted as its historical role.
        fresh = _source_parent(db, actor, request, signature=body["parent_binding"]["professional_signature"], locking=locking, authorize=False)
        if fresh != body["parent_binding"]:
            reasons.append("original_parent_changed")
        if kind in CASE_KINDS:
            application = _row(db, SurgeryApplication, "application_id", row.application_id, locking=locking)
            if application.status in {3, 4}:
                reasons.append("case_not_currently_applicable")
            if row.admission_id is not None:
                admission = _row(db, Admission, "admission_id", row.admission_id, locking=locking)
                if admission.status != 1:
                    reasons.append("admission_not_currently_inpatient")
    except HTTPException as exc:
        if exc.status_code not in {403, 404, 409, 422}:
            raise
        reasons.append("original_parent_unavailable")
    if as_of is not None:
        if isinstance(as_of, str):
            as_of = datetime.datetime.fromisoformat(KnownTime(kind="known", at=as_of).at.replace("Z", "+00:00")).replace(tzinfo=None)
        elif isinstance(as_of, datetime.datetime) and as_of.tzinfo is not None:
            as_of = as_of.astimezone(datetime.UTC).replace(tzinfo=None)
        if row.recorded_at > as_of or row.reviewed_at is None or row.reviewed_at > as_of:
            reasons.append("original_not_available_at_as_of")
    draft_readable = row.status == "draft" and not any(reason != "source_not_published" for reason in reasons)
    redacted = bool(reasons) and actor.user_role != "super_admin" and not draft_readable
    state = governance_fields(row)
    return SourceWrapper.model_validate(
        {
            **_source_identity(row),
            "source_id": f"surgery_fact:{row.source_record_id}:{row.content_hash[:12]}",
            "content_hash": row.content_hash,
            **{key: None if redacted and key in {"review_basis_note", "revoke_reason"} else value for key, value in state.items()},
            "governance_hash": hash_content(state),
            "payload": None if redacted else body["payload"],
            "parent_binding": None if redacted else body["parent_binding"],
            "eligible_for_new_use": not reasons,
            "exclusion_reasons": reasons,
            "audit_only": audit_only,
            "can_review": actor.user_role == "super_admin" and row.status == "draft" and draft_readable,
            "can_revoke": row.status in {"draft", "published"}
            and (actor.user_role == "super_admin" or row.created_by == actor.user_id and not any(reason.startswith("original_parent") for reason in reasons)),
        }
    ).model_dump(mode="json")


def create_source(db, user, kind, request):
    lock_write_gate(db)
    actor = current_actor(db, user, locking=True, clinical=kind in CASE_KINDS)
    request = SourceCreate.model_validate(request.model_dump(mode="json") if isinstance(request, BaseModel) else request)
    if request.payload.kind != kind:
        raise HTTPException(422, "来源路径与原件类型不同")
    if isinstance(request.payload, BusyPayload) and request.payload.protected_witness_hash is not None:
        raise HTTPException(422, "受保护外科原件凭据必须由服务端构建，不能接受调用者自报证明")
    now = utcnow()
    if isinstance(request.payload, DurationObservationPayload) and request.payload.observed_at > utc_text(now):
        raise HTTPException(422, "实际时长观测不能晚于服务器登记时刻")
    signature = None
    if request.professional_attestation.status == "confirmed":
        signature = {
            "doctor_id": request.professional_attestation.signer_doctor_id,
            "user_id": actor.user_id,
            "original_role": actor.user_role,
            "signed_at": utc_text(now),
            "basis_note": request.professional_attestation.basis_note,
        }
    parent = _source_parent(db, actor, request, signature=signature, locking=True)
    if kind in CASE_KINDS:
        application = _row(db, SurgeryApplication, "application_id", request.application_id, locking=True)
        if application.status in {3, 4}:
            raise HTTPException(409, "已结束或已取消病例不能创建新的排台声明")
    case = parent["case"]
    row = AISurgerySource(
        source_record_id=str(uuid.uuid4()),
        source_kind=kind,
        pool_id=request.pool_id,
        resource_id=request.resource_id,
        application_id=request.application_id,
        patient_id=case["patient_id"] if case else None,
        admission_id=case["admission_id"] if case else None,
        professional_status=request.professional_attestation.status,
        signed_by_doctor_id=signature["doctor_id"] if signature else None,
        signed_by_user_id=actor.user_id if signature else None,
        signed_at=now if signature else None,
        schema_version="surgery_fact_private_v1",
        payload_json=_bounded_json(request.payload.model_dump(mode="json"), FACT_BYTES),
        parent_binding_json=_bounded_json(parent, PARENT_BYTES),
        recorded_at=now,
        created_by=actor.user_id,
        status="draft",
        revision=1,
        reviewed_by=None,
        reviewed_at=None,
        review_basis_note="",
        revoked_by=None,
        revoked_at=None,
        revoke_reason="",
    )
    body = {**_source_identity(row), "payload": request.payload.model_dump(mode="json"), "parent_binding": parent}
    _bounded_json(body, FACT_BYTES)
    row.content_hash = hash_content(body)
    db.add(row)
    db.flush()
    data = source_current(db, actor, kind, row.source_record_id, audit_only=actor.user_role == "super_admin", locking=True)
    if not data["can_review"] and actor.user_role == "super_admin" or any(reason != "source_not_published" for reason in data["exclusion_reasons"]):
        raise HTTPException(409, "写入后原范围或父件已变化，本次原件不能保存")
    final_actor = current_actor(db, actor, locking=True, clinical=kind in CASE_KINDS)
    if signature is not None:
        _clinical_care(db, final_actor, application, signer_doctor_id=signature["doctor_id"], locking=True)
    governance.audit(db, actor.user_id, "surgery.source.create", row.source_record_id, {"kind": kind, "content_hash": row.content_hash, "professional_status": row.professional_status})
    db.flush()
    final_actor = current_actor(db, actor, locking=True, clinical=kind in CASE_KINDS)
    if signature is not None:
        _clinical_care(db, final_actor, application, signer_doctor_id=signature["doctor_id"], locking=True)
    final = source_current(db, final_actor, kind, row.source_record_id, audit_only=final_actor.user_role == "super_admin", locking=True)
    if any(reason != "source_not_published" for reason in final["exclusion_reasons"]):
        raise HTTPException(409, "审计落库后病例或资源父件已变化")
    return row


class ProtectedCapsuleCreate(StrictModel):
    """Explicit server-verified raw mapping; never a caller's hash-only certificate."""

    pool_id: UUID
    resource_id: UUID
    legacy_schedule_id: UUID
    participant_kind: Literal["room", "surgeon", "anesthesia", "assistant", "scrub_nurse", "circulating_nurse"]
    assistant_doctor_id: PositiveInteger | None
    room_alias_id: UUID | None
    start_at: UtcText
    end_at: UtcText | None
    end_absent_reason: Literal["ongoing_unknown_end", "not_recorded"] | None
    verified_until_at: UtcText | None
    continuity_status: Literal["confirmed", "unknown"]
    transition_class_key: TechnicalKey | None
    transition_class_absent_reason: Literal["unknown", "not_applicable"] | None
    accounting: Accounting
    clock_basis_note: str = Field(min_length=20, max_length=4000)

    @model_validator(mode="after")
    def explicit_mapping(self):
        if (self.participant_kind == "room") != (self.room_alias_id is not None) or (self.participant_kind == "assistant") != (self.assistant_doctor_id is not None):
            raise ValueError("Room/assistant mapping requires only its actual explicit identity")
        if len("".join(self.clock_basis_note.split())) < 20 or len(self.clock_basis_note.encode()) > 4000:
            raise ValueError("Original explicit UTC interpretation requires a complete basis")
        return self


def _raw_busy_mapping(db, request, *, locking=False):
    """Server-only exact originals; no part of this body enters a readable capsule."""
    schedule = _row(db, SurgerySchedule, "schedule_id", request.legacy_schedule_id, locking=locking)
    application = _row(db, SurgeryApplication, "application_id", schedule.application_id, locking=locking)
    if application.patient_id != schedule.patient_id:
        raise HTTPException(409, "受保护执行记录与申请患者不一致")
    if application.admission_id is not None:
        admission = _row(db, Admission, "admission_id", application.admission_id, locking=locking)
        if admission.patient_id != application.patient_id:
            raise HTTPException(409, "受保护原病例与住院患者不一致")
    resource = _row(db, AISurgeryResource, "resource_id", request.resource_id, locking=locking)
    registry_proof("resource", resource)
    mapping = None
    if request.participant_kind == "room":
        alias = registry_row(db, "room_alias", request.room_alias_id, locking=locking)
        proof = registry_proof("room_alias", alias)
        # Legacy rows have no trusted namespace column. A namespace name alone
        # cannot prove which physical OR a legacy unqualified string denoted.
        if (
            alias.status != "published"
            or alias.alias_scope != "legacy_schedule"
            or alias.legacy_schedule_id != schedule.schedule_id
            or alias.resource_id != resource.resource_id
            or proof["payload"]["raw_original_text"] != schedule.operating_room
        ):
            raise HTTPException(409, "旧自由房间文本须有此原记录专属的已发布物理房间映射")
        mapping = {"alias_id": alias.alias_id, "content_hash": alias.content_hash, "governance_hash": hash_content(governance_fields(alias))}
    else:
        if resource.resource_kind != "person":
            raise HTTPException(422, "人员忙时映射须使用真实自然人资源")
        if request.participant_kind in {"scrub_nurse", "circulating_nurse"}:
            user_id = getattr(schedule, request.participant_kind + "_id")
        else:
            if request.participant_kind == "assistant":
                tokens = (schedule.assistant_ids or "").split(",")
                if not tokens or any(re.fullmatch(r"[1-9][0-9]*", token.strip()) is None for token in tokens):
                    raise HTTPException(409, "旧助手身份集合无法完整规范解析，不能猜测人员")
                ids = [int(token.strip()) for token in tokens]
                if len(set(ids)) != len(ids) or request.assistant_doctor_id not in ids:
                    raise HTTPException(409, "显式助手不在完整原助手集合中")
                doctor_id = request.assistant_doctor_id
            else:
                doctor_id = schedule.surgeon_id if request.participant_kind == "surgeon" else schedule.anesthesiologist_id
            doctor = _row(db, Doctor, "doctor_id", doctor_id, locking=locking)
            user_id = doctor.user_id
        if user_id is None:
            raise HTTPException(409, "旧人员缺少实际用户身份，不能合成为已核实自然人")
        account = current_query(db.query(AISurgeryPersonAccount).filter_by(user_id=user_id), locking=locking).one_or_none()
        if account is None or account.resource_id != resource.resource_id:
            raise HTTPException(409, "旧人员必须匹配该实际用户永久唯一的自然人绑定")
        registry_proof("person_account", account)
        mapping = {"binding_id": account.binding_id, "user_id": account.user_id, "content_hash": account.content_hash}
    fields = (
        "schedule_id",
        "application_id",
        "patient_id",
        "operating_room",
        "surgery_date",
        "start_time",
        "end_time",
        "surgeon_id",
        "anesthesiologist_id",
        "assistant_ids",
        "scrub_nurse_id",
        "circulating_nurse_id",
        "status",
    )
    raw_schedule = {name: getattr(schedule, name).isoformat() if isinstance(getattr(schedule, name), datetime.date) else getattr(schedule, name) for name in fields}
    return {
        "schema_version": "surgery_protected_busy_v1",
        "request": request.model_dump(mode="json"),
        "original_schedule": raw_schedule,
        "original_application": {
            "application_id": application.application_id,
            "patient_id": application.patient_id,
            "admission_id": application.admission_id,
            "doctor_id": application.doctor_id,
            "status": application.status,
        },
        "mapping": mapping,
    }


def _protected_current(db, row, payload, *, locking=False):
    try:
        witness = _row(db, AISurgeryProtectedWitness, "source_record_id", row.source_record_id, locking=locking)
        original = json.loads(witness.witness_json)
        if (
            canonical_json(original) != witness.witness_json
            or len(witness.witness_json.encode()) > FACT_BYTES
            or hash_content(original) != witness.content_hash
            or witness.content_hash != payload["protected_witness_hash"]
            or witness.source_kind != "resource_availability_busy"
            or witness.recorded_at != row.recorded_at
            or witness.created_by != row.created_by
        ):
            raise ValueError("Protected full source commitment mismatch")
        request = ProtectedCapsuleCreate.model_validate(original["request"])
        if (request.pool_id, request.resource_id) != (row.pool_id, row.resource_id):
            raise ValueError("Protected scope differs")
        names = ("start_at", "end_at", "end_absent_reason", "verified_until_at", "continuity_status", "transition_class_key", "transition_class_absent_reason", "accounting")
        request_values = request.model_dump(mode="json")
        if any(payload[name] != request_values[name] for name in names) or payload["basis_hash"] != hash_content(
            {"basis_code": "explicit_legacy_utc_interpretation", "basis_note": request.clock_basis_note}
        ):
            raise ValueError("Readable capsule differs from protected original interpretation")
    except (ValueError, TypeError, KeyError, ValidationError, RecursionError, HTTPException) as exc:
        raise HTTPException(409, "受保护原凭据自身完整性不成立") from exc
    try:
        return _raw_busy_mapping(db, request, locking=locking) == original
    except HTTPException as exc:
        if exc.status_code in {404, 409, 422}:
            return False
        raise


def create_protected_capsule(db, user, request):
    lock_write_gate(db)
    actor = current_actor(db, user, locking=True)
    if actor.user_role != "super_admin":
        raise HTTPException(403, "跨范围原证据只能由有全局原件读取权的超级管理员受控封装")
    request = ProtectedCapsuleCreate.model_validate(request.model_dump(mode="json") if isinstance(request, BaseModel) else request)
    raw = _raw_busy_mapping(db, request, locking=True)
    status = raw["original_schedule"]["status"]
    # Cancelled running legacy rows lack a reliable stop event: never release them.
    if status == 3 and raw["original_schedule"]["end_time"] is None and request.end_at is not None:
        raise HTTPException(409, "旧取消记录无真实结束证明，不能封装为已释放时段")
    if status == 2 and (raw["original_schedule"]["end_time"] is None or request.end_at is None):
        raise HTTPException(409, "已完成忙时须有实际结束原件及明确 UTC 解释")
    if raw["original_schedule"]["start_time"] is None:
        raise HTTPException(409, "旧排台缺实际起始时刻，不能把日期或估计当作实际忙时")
    payload = BusyPayload(
        kind="resource_availability_busy",
        record_type="busy_capsule",
        start_at=request.start_at,
        end_at=request.end_at,
        end_absent_reason=request.end_absent_reason,
        verified_until_at=request.verified_until_at,
        continuity_status=request.continuity_status,
        busy_status="completed" if status == 2 else "unknown" if status == 3 else "committed",
        transition_class_key=request.transition_class_key,
        transition_class_absent_reason=request.transition_class_absent_reason,
        accounting=request.accounting,
        basis_code="protected_legacy_witness",
        basis_hash=hash_content({"basis_code": "explicit_legacy_utc_interpretation", "basis_note": request.clock_basis_note}),
        protected_witness_hash=hash_content(raw),
    )
    source_request = SourceCreate(
        pool_id=request.pool_id, resource_id=request.resource_id, application_id=None, payload=payload, professional_attestation={"status": "unknown", "signer_doctor_id": None, "basis_note": None}
    )
    now = utcnow()
    if payload.start_at > utc_text(now) or payload.end_at is not None and payload.end_at > utc_text(now) or payload.verified_until_at is not None and payload.verified_until_at > utc_text(now):
        raise HTTPException(422, "实际执行忙时及核实前缀不能晚于封装登记时刻")
    parent = _source_parent(db, actor, source_request, locking=True)
    row = AISurgerySource(
        source_record_id=str(uuid.uuid4()),
        source_kind=payload.kind,
        pool_id=request.pool_id,
        resource_id=request.resource_id,
        application_id=None,
        patient_id=None,
        admission_id=None,
        professional_status="unknown",
        signed_by_doctor_id=None,
        signed_by_user_id=None,
        signed_at=None,
        schema_version="surgery_fact_private_v1",
        payload_json=_bounded_json(payload.model_dump(mode="json"), FACT_BYTES),
        parent_binding_json=_bounded_json(parent, PARENT_BYTES),
        recorded_at=now,
        created_by=actor.user_id,
        status="draft",
        revision=1,
        reviewed_by=None,
        reviewed_at=None,
        review_basis_note="",
        revoked_by=None,
        revoked_at=None,
        revoke_reason="",
    )
    row.content_hash = hash_content({**_source_identity(row), "payload": payload.model_dump(mode="json"), "parent_binding": parent})
    db.add(row)
    db.flush()
    db.add(
        AISurgeryProtectedWitness(
            source_record_id=row.source_record_id,
            source_kind=payload.kind,
            witness_json=_bounded_json(raw, FACT_BYTES),
            content_hash=payload.protected_witness_hash,
            recorded_at=now,
            created_by=actor.user_id,
        )
    )
    db.flush()
    if not _protected_current(db, row, payload.model_dump(mode="json"), locking=True):
        raise HTTPException(409, "封装后原凭据发生当前变化，原件与审计均不能保存")
    source_current(db, actor, payload.kind, row.source_record_id, audit_only=True, locking=True)
    governance.audit(db, actor.user_id, "surgery.source.protected_capsule.create", row.source_record_id, {"content_hash": row.content_hash, "witness_hash": payload.protected_witness_hash})
    db.flush()
    if current_actor(db, actor, locking=True).user_role != "super_admin":
        raise HTTPException(403, "封装审计落库后超级管理员权限已变化")
    final = source_current(db, actor, payload.kind, row.source_record_id, audit_only=True, locking=True)
    if any(reason != "source_not_published" for reason in final["exclusion_reasons"]):
        raise HTTPException(409, "封装审计落库后受保护原件或资源范围已变化")
    return row


def review_source(db, user, kind, record_id, request, *, revoke=False):
    lock_write_gate(db)
    actor = current_actor(db, user, locking=True, clinical=kind in CASE_KINDS)
    started_as_super = actor.user_role == "super_admin"
    cls = SourceRevoke if revoke else SourceReview
    request = cls.model_validate(request.model_dump(mode="json") if isinstance(request, BaseModel) else request)
    row = source_row(db, record_id, kind, locking=True)
    current = source_current(db, actor, kind, record_id, audit_only=actor.user_role == "super_admin", locking=True)
    if revoke:
        if not current["can_revoke"]:
            raise HTTPException(403, "仅原作者仍有当前双重范围或超级管理员可撤销")
    elif actor.user_role != "super_admin":
        raise HTTPException(403, "来源发布仅限当前超级管理员，发布不代替专业签署")
    elif not current["can_review"]:
        raise HTTPException(409, "原件父件或适用范围已变化，不能发布")
    _cas_governance(db, row, request, actor, revoke=revoke)
    current_actor(db, actor, locking=True, clinical=kind in CASE_KINDS)
    after = source_current(db, actor, kind, record_id, audit_only=actor.user_role == "super_admin", locking=True)
    if not revoke and request.decision == "publish" and not after["eligible_for_new_use"]:
        raise HTTPException(409, "发布后当前原件范围已变化，审核与审计均回滚")
    governance.audit(db, actor.user_id, "surgery.source.revoke" if revoke else "surgery.source.review", record_id, {"kind": kind, "revision": row.revision, "content_hash": row.content_hash})
    db.flush()
    final_actor = current_actor(db, actor, locking=True, clinical=kind in CASE_KINDS)
    if (not revoke or started_as_super) and final_actor.user_role != "super_admin":
        raise HTTPException(403, "来源审计落库后超级管理员权限已变化")
    final = source_current(db, final_actor, kind, record_id, audit_only=final_actor.user_role == "super_admin", locking=True)
    if not revoke and request.decision == "publish" and not final["eligible_for_new_use"]:
        raise HTTPException(409, "来源审计落库后原范围已变化，审核均回滚")
    return row


def safe_resource_busy_current(db, user, resource_id, source_id, authorized_pool_id, *, locking=False, as_of=None):
    """Read safe all-location occupation via current membership, without foreign PHI.

    The capsule has its own complete SHA. source_content_hash is an opaque anchor
    to the server-authenticated original, not a claim that a client can reconstruct
    the undisclosed foreign pool/clinical/protected-witness body from this view.
    """
    actor, pool = pool_scope(db, user, authorized_pool_id, locking=locking)
    resource = _row(db, AISurgeryResource, "resource_id", canonical_id(resource_id), locking=locking)
    registry_proof("resource", resource)
    member = current_query(db.query(AISurgeryPoolMembership).filter_by(pool_id=pool.pool_id, resource_id=resource.resource_id, status="published"), locking=locking).one_or_none()
    if member is None:
        raise HTTPException(403, "当前授权资源池不包含此实际共享资源")
    membership = registry_proof("pool_membership", member)
    if _registry_parent(db, membership["payload"], locking=locking) != membership["parent_binding"]:
        raise HTTPException(409, "当前本地资源成员原件已失效")
    row = source_row(db, source_id, "resource_availability_busy", locking=locking)
    body, request = source_proof(row)
    if row.resource_id != resource.resource_id or not isinstance(request.payload, BusyPayload):
        raise HTTPException(422, "所选原件不是此物理资源的严格安全忙时胶囊")
    reasons = []
    if row.status != "published":
        reasons.append("source_not_published")
    if request.payload.protected_witness_hash is not None and not _protected_current(db, row, body["payload"], locking=locking):
        reasons.append("protected_original_changed")
    try:
        if _source_parent(db, actor, request, locking=locking, authorize=False, authorize_original_pool=False) != body["parent_binding"]:
            reasons.append("original_parent_changed")
    except HTTPException as exc:
        if exc.status_code not in {404, 409, 422}:
            raise
        reasons.append("original_parent_unavailable")
    if as_of is not None:
        cutoff = datetime.datetime.fromisoformat(KnownTime(kind="known", at=as_of).at.replace("Z", "+00:00")).replace(tzinfo=None) if isinstance(as_of, str) else as_of
        if isinstance(cutoff, datetime.datetime) and cutoff.tzinfo is not None:
            cutoff = cutoff.astimezone(datetime.UTC).replace(tzinfo=None)
        if row.recorded_at > cutoff or row.reviewed_at is None or row.reviewed_at > cutoff:
            reasons.append("original_not_available_at_as_of")
    capsule = {
        "schema_version": "surgery_safe_busy_capsule_v1",
        "resource_id": resource.resource_id,
        "source_record_id": row.source_record_id,
        "source_kind": row.source_kind,
        "source_content_hash": row.content_hash,
        "source_governance_hash": hash_content(governance_fields(row)),
        "status": row.status,
        "revision": row.revision,
        "recorded_at": utc_text(row.recorded_at),
        "published_at": utc_text(row.reviewed_at) if row.reviewed_at is not None and row.status in {"published", "revoked"} else None,
        "payload": body["payload"],
        "eligible_for_new_use": not reasons,
        "exclusion_reasons": reasons,
    }
    capsule = SafeBusyCapsule.model_validate(capsule).model_dump(mode="json")
    _bounded_json(capsule, FACT_BYTES)
    return {**capsule, "capsule_hash": hash_content(capsule)}
