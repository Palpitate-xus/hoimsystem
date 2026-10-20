"""Governed physical bed originals, without inferring past states or capacities."""

import datetime
import hashlib
import json
import re
import uuid
from typing import Annotated, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import HTTPException
from pydantic import AfterValidator, BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator
from sqlalchemy import inspect

from app.ai import governance
from app.ai.catalog import FEATURE_BY_KEY
from app.ai.models import AIFeatureConfig
from app.models import Department, Doctor, User, Ward

SOURCE_ROLES = frozenset({"admin", "director", "super_admin"})
SourceKind = Literal["census", "flow_day", "capacity_interval"]
SourceStatus = Literal["draft", "published", "rejected", "revoked"]
Review = Literal["confirmed", "not_confirmed", "unknown"]
Coverage = Literal["attested_complete", "incomplete", "unknown"]
Method = Literal["direct_tally", "external_register"]
KINDS = ("census", "flow_day", "capacity_interval")
PREFIXES = {"census": "bed_census", "flow_day": "bed_flow_day", "capacity_interval": "bed_capacity_interval"}
SCHEMA_VERSION = "bed_source_private_v1"
MAX_PAYLOAD_BYTES = 262144
MAX_PARENT_BYTES = 32768
IDENTITY_FIELDS = ("source_record_id", "source_kind", "department_id", "ward_id", "schema_version", "recorded_at", "created_by")
GOVERNANCE_FIELDS = ("status", "revision", "reviewed_by", "reviewed_at", "review_basis_note", "revoked_by", "revoked_at", "revoke_reason")


def utcnow():
    return datetime.datetime.now(datetime.UTC).replace(tzinfo=None)


def canonical_json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def hash_content(value):
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def utc_text(value):
    if not isinstance(value, datetime.datetime):
        raise ValueError("UTC datetime required")
    value = value.replace(tzinfo=datetime.UTC) if value.tzinfo is None else value.astimezone(datetime.UTC)
    if value.year < 1000:
        raise ValueError("Clock is outside MySQL DATETIME range")
    return value.isoformat(timespec="microseconds").replace("+00:00", "Z")


def canonical_utc(value):
    if not isinstance(value, str) or not re.fullmatch(r"[1-9]\d{3}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{6}Z", value):
        raise ValueError("Canonical explicit UTC with six fractional digits required")
    if utc_text(datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))) != value:
        raise ValueError("Invalid original UTC clock")
    return value


def instant(value):
    return datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))


def canonical_id(value):
    if not isinstance(value, str) or str(uuid.UUID(value)) != value:
        raise ValueError("Canonical UUID required")
    return value


def canonical_date(value):
    if not isinstance(value, str) or len(value) != 10 or str(datetime.date.fromisoformat(value)) != value or int(value[:4]) < 1000:
        raise ValueError("Canonical business date required")
    return value


def timezone_name(value):
    try:
        ZoneInfo(value)
    except (ValueError, TypeError, ZoneInfoNotFoundError) as exc:
        raise ValueError("Real IANA timezone required") from exc
    return value


def day_bounds(day, timezone):
    zone = ZoneInfo(timezone)
    first = datetime.date.fromisoformat(day)

    def midnight(date):
        naive = datetime.datetime.combine(date, datetime.time.min)
        candidates = []
        for fold in (0, 1):
            utc = naive.replace(tzinfo=zone, fold=fold).astimezone(datetime.UTC)
            if utc.astimezone(zone).replace(tzinfo=None) == naive:
                candidates.append(utc)
        if not candidates or len(set(candidates)) != 1:
            raise ValueError("Missing or ambiguous local midnight cannot be guessed")
        return utc_text(candidates[0])

    try:
        return midnight(first), midnight(first + datetime.timedelta(days=1))
    except OverflowError as exc:
        raise ValueError("Business midnight is outside supported UTC range") from exc


PositiveInteger = Annotated[int, Field(ge=1, le=2147483647)]
UtcText = Annotated[str, AfterValidator(canonical_utc)]
LocalDate = Annotated[str, AfterValidator(canonical_date)]
Timezone = Annotated[str, Field(min_length=1, max_length=80), AfterValidator(timezone_name)]
CanonicalId = Annotated[str, AfterValidator(canonical_id)]
HashText = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]


class StrictInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class CountValue(StrictInput):
    value: int | None = Field(ge=0, le=2147483647)
    absent_reason: Literal["unknown", "not_recorded"] | None

    @model_validator(mode="after")
    def explicit_absence(self):
        if (self.value is None) != (self.absent_reason is not None):
            raise ValueError("Absent count requires its explicit reason; zero is a real quantity")
        return self


class WithBasis(StrictInput):
    @field_validator("*", check_fields=False)
    @classmethod
    def meaningful_notes(cls, value, info):
        if info.field_name.endswith("_note") and isinstance(value, str) and len("".join(value.split())) < 20:
            raise ValueError("Original basis requires at least 20 non-whitespace characters")
        return value


class ExternalOriginal(WithBasis):
    method: Method
    external_record_key: str | None = Field(max_length=2000)
    external_record_key_absent_reason: Literal["unknown", "not_applicable"] | None

    @model_validator(mode="after")
    def external_absence(self):
        if (self.external_record_key is None) != (self.external_record_key_absent_reason is not None):
            raise ValueError("Absent external key requires an explicit original state")
        if self.external_record_key is not None and not self.external_record_key.strip():
            raise ValueError("External key cannot be blank")
        return self


class CensusPayload(ExternalOriginal):
    schema_version: Literal["bed_census_observation_v1"]
    business_date: LocalDate
    business_timezone: Timezone
    census_at: UtcText
    observed_at: UtcText
    definition: Literal["occupied_physical_beds_at_boundary_v1"]
    boundary_state_confirmed: Review
    occupied_beds: CountValue
    coverage: Coverage
    coverage_basis_note: str = Field(min_length=20, max_length=4000)

    @model_validator(mode="after")
    def original_boundary(self):
        _, end = day_bounds(self.business_date, self.business_timezone)
        if self.census_at != end or self.observed_at < self.census_at:
            raise ValueError("Census must describe the real next-day boundary, observed no earlier than that state")
        return self


class FlowDayPayload(ExternalOriginal):
    schema_version: Literal["bed_flow_day_v1"]
    business_date: LocalDate
    business_timezone: Timezone
    day_start_at: UtcText
    day_end_at: UtcText
    observed_at: UtcText
    definition: Literal["ward_physical_day_events_v1"]
    admission_events: CountValue
    discharge_events: CountValue
    transfer_in_events: CountValue
    transfer_out_events: CountValue
    coverage: Coverage
    coverage_basis_note: str = Field(min_length=20, max_length=4000)
    event_definition_basis_note: str = Field(min_length=20, max_length=4000)

    @model_validator(mode="after")
    def closed_day(self):
        if (self.day_start_at, self.day_end_at) != day_bounds(self.business_date, self.business_timezone) or self.observed_at < self.day_end_at:
            raise ValueError("Physical day events require the exact closed local day and actual later observation")
        return self


class CapacityIntervalPayload(WithBasis):
    schema_version: Literal["bed_capacity_interval_v1"]
    start_at: UtcText
    end_at: UtcText
    basis_kind: Literal["observed_operational_capacity", "reviewed_future_scenario"]
    operational_total_beds: CountValue
    coverage: Coverage
    capacity_definition: Literal["total_operational_physical_beds_v1"]
    capacity_basis_note: str = Field(min_length=20, max_length=4000)
    observed_at: UtcText | None
    staff_readiness: Review
    equipment_readiness: Review
    isolation_applicability: Review
    immediate_admittable_slots: CountValue
    immediate_slots_observed_at: UtcText | None

    @model_validator(mode="after")
    def independent_capacity_clocks(self):
        if self.start_at >= self.end_at:
            raise ValueError("Capacity interval must be positive")
        if self.basis_kind == "observed_operational_capacity":
            if self.observed_at is None or self.observed_at < self.end_at:
                raise ValueError("Historical actual capacity requires actual observation after its entire closed interval")
        elif self.observed_at is not None:
            raise ValueError("A future scenario cannot pretend an actual future observation")
        if (self.immediate_admittable_slots.value is not None) != (self.immediate_slots_observed_at is not None):
            raise ValueError("Known immediate slots require their independent original observation clock")
        if self.basis_kind == "reviewed_future_scenario" and (self.immediate_admittable_slots.value is not None or self.immediate_slots_observed_at is not None):
            raise ValueError("Future total-capacity scenarios cannot supply current immediate slots")
        return self


Payload = Annotated[CensusPayload | FlowDayPayload | CapacityIntervalPayload, Field(discriminator="schema_version")]
PAYLOAD_MODELS = {"census": CensusPayload, "flow_day": FlowDayPayload, "capacity_interval": CapacityIntervalPayload}


class SourceCreate(StrictInput):
    ward_id: PositiveInteger
    payload: Payload


class SourceReview(WithBasis):
    expected_revision: int = Field(ge=1, le=3)
    expected_content_hash: HashText
    decision: Literal["publish", "reject"]
    review_basis_note: str = Field(min_length=20, max_length=4000)

    @field_validator("review_basis_note")
    @classmethod
    def review_bytes(cls, value):
        if len(value.encode("utf-8")) > 4000:
            raise ValueError("Review note exceeds 4000 UTF8 bytes")
        return value


class SourceRevoke(StrictInput):
    expected_revision: int = Field(ge=1, le=3)
    reason: str = Field(min_length=1, max_length=1000)

    @field_validator("reason")
    @classmethod
    def meaningful_reason(cls, value):
        if not value.strip():
            raise ValueError("Revocation note cannot be blank")
        return value


class DepartmentBinding(StrictInput):
    department_id: PositiveInteger


class WardBinding(StrictInput):
    ward_id: PositiveInteger
    department_id: PositiveInteger


class ParentBinding(StrictInput):
    department: DepartmentBinding
    ward: WardBinding


class FrozenIdentity(StrictInput):
    source_record_id: CanonicalId
    source_kind: SourceKind
    department_id: PositiveInteger
    ward_id: PositiveInteger
    schema_version: Literal["bed_source_private_v1"]
    recorded_at: UtcText
    created_by: PositiveInteger


def model():
    from app.ai.bed_models import AIBedSource

    return AIBedSource


def current_query(query, *, locking=False):
    """Refresh ORM identities and optionally use an actual current locking read."""
    query = query.populate_existing()
    return query.with_for_update() if locking else query


def current_actor(db, user, *, locking=False):
    state = inspect(user, raiseerr=False)
    actor_id = state.identity[0] if state is not None and state.identity is not None else user.user_id
    actor = current_query(db.query(User).filter_by(user_id=actor_id), locking=locking).one_or_none()
    if actor is None or actor.user_role not in SOURCE_ROLES:
        raise HTTPException(403, "当前身份没有床位原来源管理权限")
    if actor.user_role != "super_admin":
        config = current_query(db.query(AIFeatureConfig).filter_by(feature_key="bed_forecast"), locking=locking).one_or_none()
        try:
            roles = json.loads(config.allowed_roles_json) if config is not None else list(FEATURE_BY_KEY["bed_forecast"].default_roles)
            if not isinstance(roles, list) or any(not isinstance(item, str) for item in roles) or actor.user_role not in roles:
                raise ValueError("role excluded")
        except (ValueError, TypeError) as exc:
            raise HTTPException(403, "当前床位来源角色授权已变化") from exc
    return actor


def authorized_departments(db, actor, *, locking=False):
    if actor.user_role in {"admin", "super_admin"}:
        return None
    query = db.query(Doctor.department_id).filter(Doctor.user_id == actor.user_id, Doctor.department_id.is_not(None))
    departments = {item[0] for item in current_query(query, locking=locking).all()}
    if not departments:
        raise HTTPException(403, "未建立可核实的当前科室运营范围")
    return departments


def bed_scope(db, user, department_id, *, allow_missing=False, locking=False):
    actor = current_actor(db, user, locking=locking)
    if type(department_id) is not int or department_id < 1:
        raise HTTPException(422, "科室标识须为正整数")
    permitted = authorized_departments(db, actor, locking=locking)
    if permitted is not None and department_id not in permitted:
        raise HTTPException(403, "不能访问其他科室的床位原来源")
    department = current_query(db.query(Department).filter_by(department_id=department_id), locking=locking).one_or_none() if locking or not allow_missing else None
    if not allow_missing and department is None:
        raise HTTPException(422, "来源科室不存在")
    return actor


def identity(row):
    return {key: utc_text(row.recorded_at) if key == "recorded_at" else getattr(row, key) for key in IDENTITY_FIELDS}


def governance_fields(row):
    return {key: utc_text(getattr(row, key)) if key in {"reviewed_at", "revoked_at"} and getattr(row, key) is not None else getattr(row, key) for key in GOVERNANCE_FIELDS}


def metadata(row):
    state = governance_fields(row)
    return {
        **identity(row),
        "source_id": PREFIXES.get(row.source_kind, "invalid") + ":" + row.source_record_id + ":" + row.content_hash[:12],
        "content_hash": row.content_hash,
        **state,
        "governance_hash": hash_content(state),
    }


def immutable_body(row, payload, parent_binding):
    return {**identity(row), "payload": payload, "parent_binding": parent_binding}


def _typed_payload(kind, values, *, stored=False):
    try:
        cls = PAYLOAD_MODELS[kind]
        if isinstance(values, BaseModel):
            values = values.model_dump(mode="json")
        return cls.model_validate(values).model_dump(mode="json")
    except (KeyError, TypeError, ValidationError) as exc:
        raise HTTPException(409 if stored else 422, "床位来源类型、原时刻、数量、缺项或约束不符合明确契约") from exc


def _validate_governance(row):
    if type(row.revision) is not int or row.status not in {"draft", "published", "rejected", "revoked"}:
        raise ValueError("Invalid source governance")
    reviewed = row.reviewed_by is not None and row.reviewed_at is not None
    if reviewed:
        if type(row.reviewed_by) is not int or row.reviewed_by < 1 or row.reviewed_at < row.recorded_at:
            raise ValueError("Invalid reviewer or review clock")
        SourceReview(expected_revision=1, expected_content_hash=row.content_hash, decision="publish", review_basis_note=row.review_basis_note)
    elif row.reviewed_by is not None or row.reviewed_at is not None or row.review_basis_note != "":
        raise ValueError("Partial review provenance")
    if row.status == "draft" and (row.revision != 1 or reviewed):
        raise ValueError("Invalid draft revision")
    if row.status in {"published", "rejected"} and (row.revision != 2 or not reviewed):
        raise ValueError("Invalid reviewed revision")
    if row.status == "revoked":
        if row.revision != (3 if reviewed else 2) or type(row.revoked_by) is not int or row.revoked_by < 1 or row.revoked_at is None:
            raise ValueError("Invalid revoked revision/provenance")
        SourceRevoke(expected_revision=row.revision - 1, reason=row.revoke_reason)
        if row.revoked_at < (row.reviewed_at if reviewed else row.recorded_at):
            raise ValueError("Revocation clock precedes original/review")
    elif row.revoked_by is not None or row.revoked_at is not None or row.revoke_reason != "":
        raise ValueError("Revocation metadata on a non-revoked source")


def source_proof(row):
    """Authenticate original bytes and clocks; never compare today's bed statuses."""
    try:
        FrozenIdentity.model_validate(identity(row))
        if not isinstance(row.content_hash, str) or not re.fullmatch(r"[a-f0-9]{64}", row.content_hash):
            raise ValueError("Invalid full original hash")
        if len(row.payload_json.encode("utf-8")) > MAX_PAYLOAD_BYTES or len(row.parent_binding_json.encode("utf-8")) > MAX_PARENT_BYTES:
            raise ValueError("Stored complete source exceeds its byte capacity")
        payload = _typed_payload(row.source_kind, json.loads(row.payload_json), stored=True)
        parent = ParentBinding.model_validate(json.loads(row.parent_binding_json)).model_dump(mode="json")
        if canonical_json(payload) != row.payload_json or canonical_json(parent) != row.parent_binding_json:
            raise ValueError("Stored original JSON differs from its canonical complete body")
        if parent != {"department": {"department_id": row.department_id}, "ward": {"ward_id": row.ward_id, "department_id": row.department_id}}:
            raise ValueError("Original ward/department identity differs")
        _validate_original_clocks(payload, utc_text(row.recorded_at))
        if hash_content(immutable_body(row, payload, parent)) != row.content_hash:
            raise ValueError("Complete immutable original hash differs")
        _validate_governance(row)
        return payload, parent
    except (ValueError, TypeError, AttributeError, KeyError, RecursionError, UnicodeError, ValidationError, HTTPException) as exc:
        raise HTTPException(409, "床位原来源的完整正文、原病区、时刻、哈希或治理状态不一致") from exc


def _validate_original_clocks(payload, recorded_at):
    for key in ("observed_at", "immediate_slots_observed_at"):
        value = payload.get(key)
        if value is not None and value > recorded_at:
            raise ValueError("Actual observation cannot follow server original recording")


def parent_exclusion_reasons(db, row, parent, *, locking=False):
    reasons = []
    if current_query(db.query(Department).filter_by(department_id=row.department_id), locking=locking).one_or_none() is None:
        reasons.append("original_department_missing")
    ward = current_query(db.query(Ward).filter_by(ward_id=row.ward_id), locking=locking).one_or_none()
    if ward is None:
        reasons.append("original_ward_missing")
    elif {"ward_id": ward.ward_id, "department_id": ward.department_id} != parent["ward"]:
        reasons.append("ward_department_binding_changed")
    return reasons


def source_row(db, source_record_id, kind=None, *, locking=False):
    try:
        source_record_id = canonical_id(source_record_id)
    except (ValueError, TypeError, AttributeError) as exc:
        raise HTTPException(422, "来源标识须为规范UUID") from exc
    row = current_query(db.query(model()).filter_by(source_record_id=source_record_id), locking=locking).one_or_none()
    if row is None or kind is not None and row.source_kind != kind:
        raise HTTPException(404, "所选类型的床位原来源不存在")
    return row


def source_current(db, user, kind, source_record_id, *, audit_only=False, require_published=False, locking=False):
    row = source_row(db, source_record_id, kind, locking=locking)
    actor = current_actor(db, user, locking=locking)
    if audit_only and actor.user_role != "super_admin":
        raise HTTPException(403, "只有超级管理员可读取完整冻结审计")
    bed_scope(db, actor, row.department_id, allow_missing=actor.user_role in {"admin", "super_admin"}, locking=locking)
    payload, parent = source_proof(row)
    parent_reasons = parent_exclusion_reasons(db, row, parent, locking=locking)
    reasons = [*parent_reasons, *([] if row.status == "published" else ["source_" + row.status])]
    if require_published and reasons:
        raise HTTPException(409, "原来源、原病区科室或发布状态已变化，不能用于新计划")
    visible = audit_only or not parent_reasons and row.status in {"draft", "published"}
    data = {
        **metadata(row),
        "payload": payload if visible else None,
        "parent_binding": parent if visible else None,
        "parent_current": not parent_reasons,
        "eligible": not reasons,
        "exclusion_reasons": reasons,
        "can_record": not parent_reasons,
        "can_review": actor.user_role == "super_admin" and row.status == "draft" and not parent_reasons,
        "can_revoke": row.status in {"draft", "published"} and (actor.user_role == "super_admin" or row.created_by == actor.user_id and not parent_reasons),
        "audit_only": audit_only,
        "eligibility_basis": "published_governance_and_current_ward_department_not_census_coverage_capacity_readiness_or_forecast_validation",
    }
    if not visible:
        data["review_basis_note"] = None
        data["revoke_reason"] = None
    return data


def create_source(db, user, kind, values):
    try:
        request = values if isinstance(values, SourceCreate) else SourceCreate.model_validate(values)
    except ValidationError as exc:
        raise HTTPException(422, "来源请求须使用明确病区及该类型完整原量") from exc
    ward = current_query(db.query(Ward).filter_by(ward_id=request.ward_id)).one_or_none()
    if ward is None or ward.department_id is None:
        raise HTTPException(422, "原病区不存在或尚无可核实的科室归属")
    actor = bed_scope(db, user, ward.department_id)
    payload = _typed_payload(kind, request.payload)
    parent = {"department": {"department_id": ward.department_id}, "ward": {"ward_id": ward.ward_id, "department_id": ward.department_id}}
    now = utcnow()
    try:
        _validate_original_clocks(payload, utc_text(now))
    except ValueError as exc:
        raise HTTPException(422, "实际观察时刻不能晚于服务器登记时刻，未来容量场景须明确无实际观察") from exc
    if kind == "capacity_interval" and payload["basis_kind"] == "reviewed_future_scenario" and payload["end_at"] <= utc_text(now):
        raise HTTPException(422, "新建未来容量场景须仍有未来适用部分；历史原件不会随时间流逝改写")
    payload_json, parent_json = canonical_json(payload), canonical_json(parent)
    if len(payload_json.encode("utf-8")) > MAX_PAYLOAD_BYTES or len(parent_json.encode("utf-8")) > MAX_PARENT_BYTES:
        raise HTTPException(422, "完整床位来源超过字节容量，不得截断保存")
    row = model()(
        source_record_id=str(uuid.uuid4()),
        source_kind=kind,
        department_id=ward.department_id,
        ward_id=ward.ward_id,
        schema_version=SCHEMA_VERSION,
        payload_json=payload_json,
        parent_binding_json=parent_json,
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
    row.content_hash = hash_content(immutable_body(row, payload, parent))
    db.add(row)
    db.flush()
    source_proof(row)
    actor = bed_scope(db, actor, row.department_id, locking=True)
    if parent_exclusion_reasons(db, row, parent, locking=True):
        raise HTTPException(409, "保存前原病区归属已经变化，本次来源未登记")
    governance.audit(db, actor.user_id, "bed_source.create", row.source_record_id, {"source_kind": kind, "content_hash": row.content_hash, "department_id": row.department_id, "ward_id": row.ward_id})
    return row


def review_source(db, user, kind, source_record_id, values):
    actor = current_actor(db, user)
    if actor.user_role != "super_admin":
        raise HTTPException(403, "只有当前超级管理员可审核发布床位原来源")
    try:
        request = values if isinstance(values, SourceReview) else SourceReview.model_validate(values)
    except ValidationError as exc:
        raise HTTPException(422, "审核须明确原版本、完整哈希及依据") from exc
    row = source_row(db, source_record_id, kind)
    _, parent = source_proof(row)
    if row.status != "draft" or row.revision != request.expected_revision or row.content_hash != request.expected_content_hash or parent_exclusion_reasons(db, row, parent):
        raise HTTPException(409, "只有完整且原病区科室仍有效的原草稿可以审核，请重新读取")
    now = utcnow()
    if now < row.recorded_at:
        raise HTTPException(409, "审核服务器时刻早于原登记时刻")
    changed = (
        db.query(model())
        .filter_by(source_record_id=row.source_record_id, source_kind=kind, status="draft", revision=request.expected_revision, content_hash=request.expected_content_hash)
        .update(
            {"status": "published" if request.decision == "publish" else "rejected", "revision": 2, "reviewed_by": actor.user_id, "reviewed_at": now, "review_basis_note": request.review_basis_note},
            synchronize_session=False,
        )
    )
    if changed != 1:
        raise HTTPException(409, "原来源在审核时已发生竞争，请刷新")
    db.expire(row)
    row = source_row(db, row.source_record_id, kind)
    source_proof(row)
    actor = current_actor(db, actor, locking=True)
    if actor.user_role != "super_admin":
        raise HTTPException(403, "当前身份已不再具备原来源审核权限，本次未发布")
    if parent_exclusion_reasons(db, row, parent, locking=True):
        raise HTTPException(409, "审核保存前原病区科室已经变化，本次未发布")
    governance.audit(
        db, actor.user_id, "bed_source." + request.decision, row.source_record_id, {"content_hash": row.content_hash, "expected_revision": request.expected_revision, "revision": row.revision}
    )
    return row


def revoke_source(db, user, kind, source_record_id, values):
    actor = current_actor(db, user)
    try:
        request = values if isinstance(values, SourceRevoke) else SourceRevoke.model_validate(values)
    except ValidationError as exc:
        raise HTTPException(422, "撤销须明确原版本及原因") from exc
    row = source_row(db, source_record_id, kind)
    _, parent = source_proof(row)
    if actor.user_role != "super_admin":
        bed_scope(db, actor, row.department_id)
        if row.created_by != actor.user_id or parent_exclusion_reasons(db, row, parent):
            raise HTTPException(403, "只能在当前原病区科室范围撤销本人创建且原病区绑定有效的来源")
    if row.status not in {"draft", "published"} or row.revision != request.expected_revision:
        raise HTTPException(409, "原来源已终结或版本改变，不能重复撤销")
    now = utcnow()
    if now < (row.reviewed_at if row.reviewed_at is not None else row.recorded_at):
        raise HTTPException(409, "撤销服务器时刻早于原登记或审核时刻")
    changed = (
        db.query(model())
        .filter_by(source_record_id=row.source_record_id, source_kind=kind, status=row.status, revision=request.expected_revision, content_hash=row.content_hash)
        .update({"status": "revoked", "revision": request.expected_revision + 1, "revoked_by": actor.user_id, "revoked_at": now, "revoke_reason": request.reason}, synchronize_session=False)
    )
    if changed != 1:
        raise HTTPException(409, "原来源在撤销时已发生竞争，请刷新")
    db.expire(row)
    row = source_row(db, row.source_record_id, kind)
    source_proof(row)
    actor = current_actor(db, actor, locking=True)
    if actor.user_role != "super_admin":
        bed_scope(db, actor, row.department_id, locking=True)
        if row.created_by != actor.user_id or parent_exclusion_reasons(db, row, parent, locking=True):
            raise HTTPException(403, "撤销保存前原病区、科室或当前作者权限已经变化")
    governance.audit(db, actor.user_id, "bed_source.revoke", row.source_record_id, {"content_hash": row.content_hash, "expected_revision": request.expected_revision, "revision": row.revision})
    return row


def authorize_source(db, user, kind, source_record_id, *, as_of=None, locking=False):
    data = source_current(db, user, kind, source_record_id, require_published=True, locking=locking)
    if as_of is not None:
        cutoff = instant(canonical_utc(as_of))
        if any(instant(data[key]) > cutoff for key in ("recorded_at", "reviewed_at")):
            raise HTTPException(409, "原来源在所选可用截止时刻尚未登记或发布")
    return data


def options(db, user, department_id):
    actor = bed_scope(db, user, department_id)
    rows = db.query(Ward).filter_by(department_id=department_id).order_by(Ward.ward_id).limit(2001).all()
    if len(rows) > 2000:
        raise HTTPException(422, "完整病区目录超过容量，不能截断为部分候选")
    return {
        "department_id": department_id,
        "source_kinds": list(KINDS),
        "schema_version": SCHEMA_VERSION,
        "wards": [{"ward_id": row.ward_id, "department_id": row.department_id, "name": row.name, "status": row.status} for row in rows],
        "can_record": True,
        "can_review": actor.user_role == "super_admin",
        "provider_required": False,
        "scope_note": "仅当前科室病区身份目录，包含停用病区以登记历史原量；不证明占床覆盖、当前可收治名额或未来容量，不回填历史床位状态。",
    }
