"""Governed staffing originals, distinct from a feasible or published roster."""

import datetime
import hashlib
import json
import re
import uuid
from typing import Annotated, Literal

from fastapi import HTTPException
from pydantic import AfterValidator, BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from app.ai import governance
from app.ai.catalog import FEATURE_BY_KEY
from app.ai.models import AIFeatureConfig
from app.ai.roster_models import AIRosterSource
from app.models import Department, Doctor, User

SOURCE_ROLES = frozenset({"admin", "director", "super_admin"})
SourceKind = Literal["qualification", "duty_interval", "availability", "work_rule_policy"]
SourceStatus = Literal["draft", "published", "rejected", "revoked"]
KINDS = ("qualification", "duty_interval", "availability", "work_rule_policy")
PREFIXES = {"qualification": "roster_qualification", "duty_interval": "roster_duty", "availability": "roster_availability", "work_rule_policy": "roster_work_policy"}
SCHEMA_VERSION = "roster_fact_v1"
MAX_PAYLOAD_BYTES = 262144
MAX_PARENT_BYTES = 32768
# Public proof arithmetic uses exact integer microseconds in JavaScript too.
MAX_CONSTRAINT_MINUTES = 9007199254740991 // 60000000
IDENTITY_FIELDS = ("source_record_id", "source_kind", "department_id", "doctor_id", "schema_version", "recorded_at", "created_by")
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
        raise ValueError("UTC clock is outside MySQL DATETIME range")
    return value.isoformat(timespec="microseconds").replace("+00:00", "Z")


def canonical_utc(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})", value):
        raise ValueError("Explicit UTC/offset clock required; naive clocks cannot be imputed")
    try:
        return utc_text(datetime.datetime.fromisoformat(value.replace("Z", "+00:00")))
    except (ValueError, OverflowError) as exc:
        raise ValueError("Explicit clock is outside the supported UTC range") from exc


def instant(value):
    return datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))


def canonical_id(value):
    if not isinstance(value, str) or str(uuid.UUID(value)) != value:
        raise ValueError("Canonical UUID required")
    return value


PositiveInteger = Annotated[int, Field(ge=1, le=2147483647)]
UtcText = Annotated[str, AfterValidator(canonical_utc)]
CanonicalId = Annotated[str, AfterValidator(canonical_id)]
HashText = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
JobKey = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,47}$")]


class StrictInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class WithEvidence(StrictInput):
    evidence_basis_note: str = Field(min_length=20, max_length=4000)

    @field_validator("evidence_basis_note")
    @classmethod
    def meaningful_basis(cls, value):
        if len("".join(value.split())) < 20:
            raise ValueError("Evidence basis requires at least 20 non-whitespace characters")
        return value


class QualificationPayload(WithEvidence):
    employment_status: Literal["active", "inactive", "unknown"]
    qualification_status: Literal["verified", "not_verified", "unknown"]
    authorized_job_keys: list[JobKey] = Field(max_length=128)
    valid_from_at: UtcText
    valid_until_at: UtcText | None
    expiry_status: Literal["known", "unknown", "not_applicable"]

    @model_validator(mode="after")
    def validity(self):
        if len(self.authorized_job_keys) != len(set(self.authorized_job_keys)):
            raise ValueError("Job keys must be distinct original declarations")
        if (self.expiry_status == "known") != (self.valid_until_at is not None):
            raise ValueError("Known expiry requires the actual end; absent expiry requires an explicit state")
        if self.valid_until_at is not None and instant(self.valid_from_at) >= instant(self.valid_until_at):
            raise ValueError("Qualification validity must be a positive interval")
        return self


class DutyBreak(StrictInput):
    start_at: UtcText
    end_at: UtcText
    counted_as_work: bool | None
    counted_as_work_absent_reason: Literal["unknown", "not_applicable"] | None

    @model_validator(mode="after")
    def consistency(self):
        if instant(self.start_at) >= instant(self.end_at):
            raise ValueError("Break interval must be positive")
        if (self.counted_as_work is None) != (self.counted_as_work_absent_reason is not None):
            raise ValueError("Unknown break accounting requires an explicit absence reason")
        return self


class DutyIntervalPayload(WithEvidence):
    start_at: UtcText
    end_at: UtcText
    commitment_status: Literal["committed", "completed", "cancelled", "unknown"]
    work_location: Literal["home_department", "other_department", "external", "unknown"]
    job_key: JobKey | None
    job_key_absent_reason: Literal["unknown", "not_applicable"] | None
    breaks: list[DutyBreak] = Field(max_length=256)
    breaks_complete: bool
    time_accounting_status: Literal["verified", "unknown"]

    @model_validator(mode="after")
    def interval(self):
        start, end = instant(self.start_at), instant(self.end_at)
        if start >= end:
            raise ValueError("Duty interval must be positive")
        if (self.job_key is None) != (self.job_key_absent_reason is not None):
            raise ValueError("Missing job key requires an explicit absence reason")
        previous = start
        for item in self.breaks:
            left, right = instant(item.start_at), instant(item.end_at)
            if left < previous or left < start or right > end:
                raise ValueError("Breaks must be sorted, non-overlapping and contained in the real duty")
            previous = right
        if self.time_accounting_status == "verified" and (not self.breaks_complete or any(item.counted_as_work is None for item in self.breaks)):
            raise ValueError("Verified accounting requires explicitly complete breaks and known accounting")
        return self


class AvailabilityPayload(WithEvidence):
    start_at: UtcText
    end_at: UtcText
    availability: Literal["available", "unavailable", "unknown"]
    basis_kind: Literal["staff_declaration", "approved_leave", "administrative_confirmation", "other"]

    @model_validator(mode="after")
    def interval(self):
        if instant(self.start_at) >= instant(self.end_at):
            raise ValueError("Availability interval must be positive")
        return self


class ConstraintValue(StrictInput):
    value: int | None = Field(ge=0, le=MAX_CONSTRAINT_MINUTES)
    absent_reason: Literal["unknown", "not_applicable"] | None

    @model_validator(mode="after")
    def known_or_absent(self):
        if (self.value is None) != (self.absent_reason is not None):
            raise ValueError("A missing constraint requires its explicit reason; zero remains a known value")
        return self


class FixedWorkWindow(StrictInput):
    start_at: UtcText
    end_at: UtcText
    minimum_work_minutes: ConstraintValue
    maximum_work_minutes: ConstraintValue

    @model_validator(mode="after")
    def interval_and_bounds(self):
        duration = instant(self.end_at) - instant(self.start_at)
        if not datetime.timedelta(0) < duration <= datetime.timedelta(days=366):
            raise ValueError("Fixed work window must be positive and at most 366 days")
        lower, upper = self.minimum_work_minutes.value, self.maximum_work_minutes.value
        if lower is not None and upper is not None and lower > upper:
            raise ValueError("Known minimum work must not exceed the known maximum")
        return self


class WorkRulePolicyPayload(WithEvidence):
    effective_from_at: UtcText
    effective_until_at: UtcText | None
    effective_until_absent_reason: Literal["unknown", "not_applicable"] | None
    max_single_duty_presence_minutes: ConstraintValue
    max_work_minutes_rolling_24h: ConstraintValue
    max_work_minutes_rolling_7d: ConstraintValue
    minimum_rest_minutes: ConstraintValue
    fixed_work_windows: list[FixedWorkWindow] = Field(max_length=64)
    policy_reference: str = Field(min_length=5, max_length=2000)

    @field_validator("policy_reference")
    @classmethod
    def meaningful_reference(cls, value):
        if len(value.strip()) < 5:
            raise ValueError("Actual policy reference required")
        return value

    @model_validator(mode="after")
    def validity(self):
        if (self.effective_until_at is None) != (self.effective_until_absent_reason is not None):
            raise ValueError("Absent policy validity end requires an explicit reason")
        if self.effective_until_at is not None and instant(self.effective_from_at) >= instant(self.effective_until_at):
            raise ValueError("Policy validity must be positive")
        return self


PAYLOAD_MODELS = {"qualification": QualificationPayload, "duty_interval": DutyIntervalPayload, "availability": AvailabilityPayload, "work_rule_policy": WorkRulePolicyPayload}
Payload = QualificationPayload | DutyIntervalPayload | AvailabilityPayload | WorkRulePolicyPayload


class SourceCreate(StrictInput):
    department_id: PositiveInteger
    doctor_id: PositiveInteger | None
    payload: Payload


class SourceReview(StrictInput):
    expected_revision: int = Field(ge=1, le=3)
    expected_content_hash: HashText
    decision: Literal["publish", "reject"]
    review_basis_note: str = Field(min_length=20, max_length=4000)

    @field_validator("review_basis_note")
    @classmethod
    def meaningful(cls, value):
        value = WithEvidence(evidence_basis_note=value).evidence_basis_note
        if len(value.encode("utf-8")) > 4000:
            raise ValueError("Review basis exceeds the complete 4000-byte SQL bound")
        return value


class SourceRevoke(StrictInput):
    expected_revision: int = Field(ge=1, le=3)
    reason: str = Field(min_length=1, max_length=1000)

    @field_validator("reason")
    @classmethod
    def meaningful(cls, value):
        if not value.strip():
            raise ValueError("Revocation reason cannot be blank")
        return value


class DepartmentBinding(StrictInput):
    department_id: PositiveInteger


class DoctorBinding(DepartmentBinding):
    doctor_id: PositiveInteger


class ParentBinding(StrictInput):
    department: DepartmentBinding
    doctor: DoctorBinding | None


class FrozenIdentity(StrictInput):
    source_record_id: CanonicalId
    source_kind: SourceKind
    department_id: PositiveInteger
    doctor_id: PositiveInteger | None
    schema_version: Literal["roster_fact_v1"]
    recorded_at: UtcText
    created_by: PositiveInteger


def model():
    return AIRosterSource


def current_actor(db, user):
    actor = db.query(User).filter_by(user_id=user.user_id).populate_existing().one_or_none()
    if actor is None or actor.user_role not in SOURCE_ROLES:
        raise HTTPException(403, "当前身份没有排班人员原来源管理权限")
    if actor.user_role != "super_admin":
        config = db.query(AIFeatureConfig).filter_by(feature_key="roster_optimization").populate_existing().one_or_none()
        try:
            roles = json.loads(config.allowed_roles_json) if config is not None else list(FEATURE_BY_KEY["roster_optimization"].default_roles)
            if not isinstance(roles, list) or any(not isinstance(item, str) for item in roles) or actor.user_role not in roles:
                raise ValueError("role excluded")
        except (ValueError, TypeError) as exc:
            raise HTTPException(403, "当前排班来源角色授权已变化") from exc
    return actor


def authorized_departments(db, actor):
    if actor.user_role in {"admin", "super_admin"}:
        return None
    departments = {item[0] for item in db.query(Doctor.department_id).filter(Doctor.user_id == actor.user_id, Doctor.department_id.is_not(None)).all()}
    if not departments:
        raise HTTPException(403, "未建立可核实的当前科室运营范围")
    return departments


def roster_scope(db, user, department_id, *, allow_missing=False):
    actor = current_actor(db, user)
    if type(department_id) is not int or department_id < 1:
        raise HTTPException(422, "科室标识须为正整数")
    permitted = authorized_departments(db, actor)
    if permitted is not None and department_id not in permitted:
        raise HTTPException(403, "不能访问其他科室的排班人员原来源")
    if not allow_missing and db.query(Department).filter_by(department_id=department_id).populate_existing().one_or_none() is None:
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
        raise HTTPException(409 if stored else 422, "人员来源类型、原时刻、数量、缺项或约束不符合明确契约") from exc


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
    """Authenticate the complete original before any current-parent/audit decision."""
    try:
        FrozenIdentity.model_validate(identity(row))
        if not isinstance(row.content_hash, str) or not re.fullmatch(r"[a-f0-9]{64}", row.content_hash):
            raise ValueError("Invalid full hash")
        if len(row.payload_json.encode("utf-8")) > MAX_PAYLOAD_BYTES or len(row.parent_binding_json.encode("utf-8")) > MAX_PARENT_BYTES:
            raise ValueError("Stored full source exceeds cap")
        payload = _typed_payload(row.source_kind, json.loads(row.payload_json), stored=True)
        parent = ParentBinding.model_validate(json.loads(row.parent_binding_json)).model_dump(mode="json")
        if canonical_json(payload) != row.payload_json or canonical_json(parent) != row.parent_binding_json:
            raise ValueError("Stored source is not its complete canonical body")
        if parent["department"]["department_id"] != row.department_id:
            raise ValueError("Original department binding differs")
        if row.source_kind == "work_rule_policy":
            if row.doctor_id is not None or parent["doctor"] is not None:
                raise ValueError("Department policy cannot carry a staff identity")
        elif row.doctor_id is None or parent["doctor"] != {"doctor_id": row.doctor_id, "department_id": row.department_id}:
            raise ValueError("Original staff scope differs")
        if row.source_kind == "duty_interval" and payload["commitment_status"] == "completed" and instant(payload["end_at"]) > instant(utc_text(row.recorded_at)):
            raise ValueError("Completed work was not yet complete at recording")
        if hash_content(immutable_body(row, payload, parent)) != row.content_hash:
            raise ValueError("Full original hash differs")
        _validate_governance(row)
        return payload, parent
    except (ValueError, TypeError, AttributeError, KeyError, RecursionError, ValidationError, HTTPException) as exc:
        raise HTTPException(409, "排班人员原来源的完整正文、身份、时刻、哈希或治理状态不一致") from exc


def parent_exclusion_reasons(db, row, parent):
    reasons = []
    if db.query(Department).filter_by(department_id=row.department_id).populate_existing().one_or_none() is None:
        reasons.append("original_department_missing")
    if row.doctor_id is not None:
        doctor = db.query(Doctor).filter_by(doctor_id=row.doctor_id).populate_existing().one_or_none()
        if doctor is None:
            reasons.append("original_doctor_missing")
        elif {"doctor_id": doctor.doctor_id, "department_id": doctor.department_id} != parent["doctor"]:
            reasons.append("doctor_department_binding_changed")
    return reasons


def source_row(db, source_record_id, kind=None):
    try:
        source_record_id = canonical_id(source_record_id)
    except (ValueError, TypeError, AttributeError) as exc:
        raise HTTPException(422, "来源标识须为规范UUID") from exc
    row = db.query(model()).filter_by(source_record_id=source_record_id).populate_existing().one_or_none()
    if row is None or kind is not None and row.source_kind != kind:
        raise HTTPException(404, "所选类型的排班人员原来源不存在")
    return row


def source_current(db, user, kind, source_record_id, *, audit_only=False, require_published=False):
    row = source_row(db, source_record_id, kind)
    actor = current_actor(db, user)
    if audit_only and actor.user_role != "super_admin":
        raise HTTPException(403, "只有超级管理员可读取完整冻结审计")
    roster_scope(db, actor, row.department_id, allow_missing=actor.user_role in {"admin", "super_admin"})
    payload, parent = source_proof(row)
    parent_reasons = parent_exclusion_reasons(db, row, parent)
    reasons = [*parent_reasons, *([] if row.status == "published" else ["source_" + row.status])]
    if require_published and reasons:
        raise HTTPException(409, "原来源、原人员科室或发布状态已变化，不能用于新计划")
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
        "eligibility_basis": "published_governance_and_current_parent_not_staff_qualification_or_roster_feasibility",
    }
    if not visible:
        data["review_basis_note"] = None
        data["revoke_reason"] = None
    return data


def create_source(db, user, kind, values):
    try:
        request = values if isinstance(values, SourceCreate) else SourceCreate.model_validate(values)
    except ValidationError as exc:
        raise HTTPException(422, "来源请求须使用明确科室、人员及该类型的完整原量") from exc
    actor = roster_scope(db, user, request.department_id)
    payload = _typed_payload(kind, request.payload)
    if (kind == "work_rule_policy") != (request.doctor_id is None):
        raise HTTPException(422, "科室工时规则不填写医生；其他来源必须指定真实本科医生")
    parent = {"department": {"department_id": request.department_id}, "doctor": None}
    if request.doctor_id is not None:
        doctor = db.query(Doctor).filter_by(doctor_id=request.doctor_id).populate_existing().one_or_none()
        if doctor is None or doctor.department_id != request.department_id:
            raise HTTPException(409, "原医生不存在或当前不属于所选原科室")
        parent["doctor"] = {"doctor_id": doctor.doctor_id, "department_id": doctor.department_id}
    now = utcnow()
    if kind == "duty_interval" and payload["commitment_status"] == "completed" and instant(payload["end_at"]) > instant(utc_text(now)):
        raise HTTPException(422, "已完成班次的真实结束时刻不能晚于当前登记时刻")
    payload_json, parent_json = canonical_json(payload), canonical_json(parent)
    if len(payload_json.encode("utf-8")) > MAX_PAYLOAD_BYTES or len(parent_json.encode("utf-8")) > MAX_PARENT_BYTES:
        raise HTTPException(422, "完整排班人员原件超过字节上限，不能截断保存")
    row = model()(
        source_record_id=str(uuid.uuid4()),
        source_kind=kind,
        department_id=request.department_id,
        doctor_id=request.doctor_id,
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
    governance.audit(db, actor.user_id, "roster_source.create", row.source_record_id, {"source_kind": kind, "content_hash": row.content_hash, "department_id": row.department_id})
    return row


def review_source(db, user, kind, source_record_id, values):
    actor = current_actor(db, user)
    if actor.user_role != "super_admin":
        raise HTTPException(403, "只有当前超级管理员可审核发布人员原来源")
    try:
        request = values if isinstance(values, SourceReview) else SourceReview.model_validate(values)
    except ValidationError as exc:
        raise HTTPException(422, "审核须明确原版本、完整哈希及依据") from exc
    row = source_row(db, source_record_id, kind)
    _, parent = source_proof(row)
    if row.status != "draft" or row.revision != request.expected_revision or row.content_hash != request.expected_content_hash or parent_exclusion_reasons(db, row, parent):
        raise HTTPException(409, "只有完整且原人员科室仍有效的原草稿可以审核，请重新读取")
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
    governance.audit(
        db, actor.user_id, "roster_source." + request.decision, row.source_record_id, {"content_hash": row.content_hash, "expected_revision": request.expected_revision, "revision": row.revision}
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
        roster_scope(db, actor, row.department_id)
        if row.created_by != actor.user_id or parent_exclusion_reasons(db, row, parent):
            raise HTTPException(403, "只能在当前原科室范围撤销本人创建且原人员绑定有效的来源")
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
    governance.audit(db, actor.user_id, "roster_source.revoke", row.source_record_id, {"content_hash": row.content_hash, "expected_revision": request.expected_revision, "revision": row.revision})
    return row


def authorize_source(db, user, kind, source_record_id, *, as_of=None):
    data = source_current(db, user, kind, source_record_id, require_published=True)
    if as_of is not None and instant(data["recorded_at"]) > instant(canonical_utc(as_of)):
        raise HTTPException(409, "原来源在所选可用截止时刻尚未登记")
    return data


def options(db, user, department_id):
    actor = roster_scope(db, user, department_id)
    rows = db.query(Doctor).filter_by(department_id=department_id).order_by(Doctor.doctor_id).limit(2001).all()
    if len(rows) > 2000:
        raise HTTPException(422, "完整人员清单超过界面安全容量，不能以截断清单代替完整人员范围")
    return {
        "department_id": department_id,
        "source_kinds": list(KINDS),
        "schema_version": SCHEMA_VERSION,
        "doctors": [{"doctor_id": row.doctor_id, "department_id": row.department_id, "name": row.name} for row in rows],
        "personnel_collection_complete_in_database": True,
        "personnel_qualification_verified": False,
        "can_record": True,
        "can_review": actor.user_role == "super_admin",
        "provider_required": False,
        "scope_note": "仅当前科室全部Doctor档案；账号、职称或存在排班不证明资质和可用性。本来源不提供逐日号源、完整劳动规则或已发布排班。",
    }
