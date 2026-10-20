"""Immutable organ-support originals; domain facts are validated by fixed definitions."""

import datetime
import json
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from typing import Annotated, Any, Literal

from fastapi import HTTPException
from pydantic import AfterValidator, BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator
from sqlalchemy.exc import IntegrityError

from app.inpatient_laboratory import hash_content
from app.inpatient_observations import canonical_json, canonical_uuid, decimal_text, explicit_utc, utc_text

SUPPORT_ROLES = frozenset({"nurse", "doctor", "director", "admin", "super_admin"})
SourceKind = Literal["map", "respiratory_support", "arterial_pair", "vasoactive", "infection_episode"]
MAX_PAYLOAD_BYTES = 32768
MAX_SOURCE_BYTES = 262144
GOVERNANCE_FIELDS = ("status", "revision", "revoked_at", "revoked_by", "revoke_reason")


def utcnow():
    return datetime.datetime.now(datetime.UTC).replace(tzinfo=None)


def canonical_time(value):
    instant = explicit_utc(value)
    if instant.year < 1000:
        raise ValueError("原UTC时刻须在MySQL DATETIME可保存的1000至9999年范围")
    return utc_text(instant)


UtcText = Annotated[str, AfterValidator(canonical_time)]
CanonicalId = Annotated[str, AfterValidator(canonical_uuid)]
HashText = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]


class StrictInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Quantity(StrictInput):
    value: str | None
    unit: str = Field(min_length=1, max_length=24)
    absent_reason: Literal["unknown", "not_performed", "measurement_error"] | None

    @field_validator("value", mode="before")
    @classmethod
    def nonnegative_original(cls, value):
        if value is not None:
            value = decimal_text(value)
            if Decimal(value) < 0:
                raise ValueError("原数量须为非负十进制字符串，0不作为缺项")
        return value

    @model_validator(mode="after")
    def measured_or_absent(self):
        if (self.value is None) == (self.absent_reason is None):
            raise ValueError("原数量和未测原因须且只能提供一项")
        return self


class SourceCreate(StrictInput):
    patient_id: int = Field(ge=1, le=2147483647)
    admission_id: CanonicalId
    payload: dict[str, Any]


class SourceRevoke(StrictInput):
    patient_id: int = Field(ge=1, le=2147483647)
    admission_id: CanonicalId
    expected_revision: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=1000)

    @field_validator("reason")
    @classmethod
    def meaningful_reason(cls, value):
        if not value.strip():
            raise ValueError("撤销说明不能全为空白")
        return value


@dataclass(frozen=True)
class SourceDefinition:
    kind: str
    schema_version: str
    prefix: str
    model: type
    payload_model: type[BaseModel]
    doctor_required: bool
    prepare: Callable


def definitions():
    # Fixed code-owned definitions only; URL kinds cannot name tables or import code.
    from app.inpatient_infection_episodes import DEFINITIONS as INFECTION
    from app.inpatient_respiratory_sources import DEFINITIONS as RESPIRATORY
    from app.inpatient_vasoactive import DEFINITIONS as VASOACTIVE

    result = {item.kind: item for item in (*RESPIRATORY, *VASOACTIVE, *INFECTION)}
    if set(result) != {"map", "respiratory_support", "arterial_pair", "vasoactive", "infection_episode"}:
        raise RuntimeError("Organ-support domain definitions are incomplete")
    return result


def definition(kind):
    try:
        return definitions()[kind]
    except (KeyError, TypeError) as exc:
        raise HTTPException(422, "请选择已实现的原始支持资料类型") from exc


def current_actor(db, user):
    from app.models import User

    actor = db.query(User).filter_by(user_id=user.user_id).populate_existing().one_or_none()
    if actor is None or actor.user_role not in SUPPORT_ROLES:
        raise HTTPException(403, "当前身份没有原住院器官支持资料权限")
    return actor


def authorize_scope(db, user, patient_id, admission_id, *, creating=False, doctor_required=False):
    from app.ai.news2_sources import clinical_qualification
    from app.inpatient_gcs import authorize_scope as authorize_clinical_original
    from app.inpatient_observations import authorize_observation_admission

    actor = current_actor(db, user)
    authorize_observation_admission(db, actor, patient_id, admission_id)
    if creating:
        authorize_clinical_original(db, actor, patient_id, admission_id, creating=True)
        if doctor_required and clinical_qualification(db, actor, patient_id, admission_id) is None:
            raise HTTPException(403, "这类临床核实须有实际Doctor身份、允许角色和原住院照护关系或有效限期授权")
    return actor


def can_record(db, user, patient_id, admission_id, spec):
    try:
        authorize_scope(db, user, patient_id, admission_id, creating=True, doctor_required=spec.doctor_required)
        return True
    except HTTPException:
        return False


def author_qualification(db, actor, patient_id, admission_id, spec, recorded_at):
    value = {"actor_id": actor.user_id, "role_at_creation": actor.user_role, "care_authorization": "authorized_original_admission_at_creation", "authorized_at": utc_text(recorded_at)}
    if spec.doctor_required or actor.user_role == "super_admin":
        from app.ai.news2_sources import clinical_qualification

        doctor = clinical_qualification(db, actor, patient_id, admission_id)
        if doctor is None:
            raise HTTPException(403, "管理权限和额外资料授权本身不赋予实际医生签署身份")
        value.update(doctor_id=doctor.doctor_id, doctor_user_id=doctor.user_id, clinical_review_signed=True)
    return value


def metadata(row, spec):
    return {
        "support_source_id": row.support_source_id,
        "kind": spec.kind,
        "patient_id": row.patient_id,
        "admission_id": row.admission_id,
        "event_at": utc_text(row.event_at) if row.event_at is not None else None,
        "recorded_at": utc_text(row.recorded_at),
        "created_by": row.created_by,
        "schema_version": row.schema_version,
    }


def frozen_content(row, spec, payload, references, qualification):
    return {**metadata(row, spec), "payload": payload, "reference_snapshots": references, "author_qualification": qualification}


def governance(row):
    value = {key: utc_text(row.revoked_at) if key == "revoked_at" and row.revoked_at is not None else getattr(row, key) for key in GOVERNANCE_FIELDS}
    return {**value, "governance_hash": hash_content(value)}


def _validated_payload(spec, values, *, stored=False):
    try:
        return spec.payload_model.model_validate(values).model_dump(mode="json")
    except ValidationError as exc:
        raise HTTPException(409 if stored else 422, "原器官支持资料的数量、时刻、缺项或明确关联不符合该类型契约") from exc


def create_source(db, user, kind, values):
    spec = definition(kind)
    try:
        req = values if isinstance(values, SourceCreate) else SourceCreate.model_validate(values)
    except ValidationError as exc:
        raise HTTPException(422, "新增原资料只接受明确患者、原住院和该类型原始字段") from exc
    actor = authorize_scope(db, user, req.patient_id, req.admission_id, creating=True, doctor_required=spec.doctor_required)
    now = utcnow()
    payload = _validated_payload(spec, req.payload)
    if len(canonical_json(payload).encode("utf-8")) > MAX_PAYLOAD_BYTES:
        raise HTTPException(422, "完整原始字段超过32768个UTF-8字节，不保存或截断")
    event_at, references = spec.prepare(db, req.patient_id, req.admission_id, payload, now)
    if event_at is not None and (not isinstance(event_at, datetime.datetime) or event_at.tzinfo is not None or event_at > now or event_at.year < 1000):
        raise HTTPException(422, "原事件UTC时刻不能晚于本次服务器登记时刻")
    if not isinstance(references, dict):
        raise ValueError("Fixed domain preparer must return a reference object")
    qualification = author_qualification(db, actor, req.patient_id, req.admission_id, spec, now)
    row = spec.model(
        support_source_id=str(uuid.uuid4()),
        patient_id=req.patient_id,
        admission_id=req.admission_id,
        event_at=event_at,
        recorded_at=now,
        created_by=actor.user_id,
        schema_version=spec.schema_version,
        payload_json=canonical_json(payload),
        reference_snapshot_json=canonical_json(references),
        author_qualification_json=canonical_json(qualification),
        status="active",
        revision=1,
        revoke_reason="",
    )
    content = frozen_content(row, spec, payload, references, qualification)
    if len(canonical_json(content).encode("utf-8")) > MAX_SOURCE_BYTES:
        raise HTTPException(422, "完整原件及引用超过262144个UTF-8字节，不保存或截断")
    row.content_hash = hash_content(content)
    authorize_scope(db, actor, req.patient_id, req.admission_id, creating=True, doctor_required=spec.doctor_required)
    db.add(row)
    db.flush()
    return row


def row_by_id(db, spec, identifier):
    try:
        canonical_uuid(identifier)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    row = db.query(spec.model).filter_by(support_source_id=identifier).populate_existing().one_or_none()
    if row is None:
        raise HTTPException(404, "该类型原器官支持资料不存在")
    return row


def _validate_qualification(row, spec, qualification):
    base = {"actor_id", "role_at_creation", "care_authorization", "authorized_at"}
    clinical = {"doctor_id", "doctor_user_id", "clinical_review_signed"}
    if (
        not isinstance(qualification, dict)
        or set(qualification) not in (base, base | clinical)
        or type(qualification.get("actor_id")) is not int
        or qualification["actor_id"] != row.created_by
        or qualification.get("role_at_creation") not in {"nurse", "doctor", "director", "super_admin"}
        or qualification.get("care_authorization") != "authorized_original_admission_at_creation"
        or qualification.get("authorized_at") != utc_text(row.recorded_at)
    ):
        raise ValueError("原作者资格快照无效")
    required = spec.doctor_required or qualification["role_at_creation"] == "super_admin"
    if required != (set(qualification) == base | clinical):
        raise ValueError("原临床签署身份字段不完整")
    if required and (
        qualification["role_at_creation"] not in {"doctor", "director", "super_admin"}
        or qualification["clinical_review_signed"] is not True
        or type(qualification["doctor_id"]) is not int
        or qualification["doctor_id"] < 1
        or type(qualification["doctor_user_id"]) is not int
        or qualification["doctor_user_id"] != row.created_by
    ):
        raise ValueError("原医生签署资格无效")


def source_current(db, row, kind, *, allow_revoked=False, audit_only=False):
    spec = definition(kind)
    if not isinstance(row, spec.model):
        raise HTTPException(409, "原资料类型与固定源定义不一致")
    current = row_by_id(db, spec, row.support_source_id)
    now = utcnow()
    try:
        canonical_uuid(current.support_source_id)
        canonical_uuid(current.admission_id)
        if type(current.patient_id) is not int or current.patient_id < 1 or type(current.created_by) is not int or current.created_by < 1 or current.schema_version != spec.schema_version:
            raise ValueError("原归属、作者或类型版本无效")
        if current.recorded_at.tzinfo is not None or current.recorded_at > now or current.recorded_at.year < 1000:
            raise ValueError("原系统登记UTC时刻无效")
        if current.event_at is not None and (current.event_at.tzinfo is not None or current.event_at > current.recorded_at or current.event_at.year < 1000):
            raise ValueError("原事件UTC时刻无效")
        if not isinstance(current.payload_json, str) or len(current.payload_json.encode("utf-8")) > MAX_PAYLOAD_BYTES:
            raise ValueError("原始字段超出完整存储限制")
        if not isinstance(current.reference_snapshot_json, str) or len(current.reference_snapshot_json.encode("utf-8")) > MAX_SOURCE_BYTES:
            raise ValueError("完整原始引用超过存储限制")
        if not isinstance(current.author_qualification_json, str) or len(current.author_qualification_json.encode("utf-8")) > MAX_PAYLOAD_BYTES:
            raise ValueError("原签署资格超过存储限制")
        payload = _validated_payload(spec, json.loads(current.payload_json), stored=True)
        references, qualification = json.loads(current.reference_snapshot_json), json.loads(current.author_qualification_json)
        if (
            not isinstance(references, dict)
            or current.payload_json != canonical_json(payload)
            or current.reference_snapshot_json != canonical_json(references)
            or current.author_qualification_json != canonical_json(qualification)
        ):
            raise ValueError("原完整件不是固定类型的规范JSON")
        _validate_qualification(current, spec, qualification)
        content = frozen_content(current, spec, payload, references, qualification)
        if len(canonical_json(content).encode("utf-8")) > MAX_SOURCE_BYTES or current.content_hash != hash_content(content):
            raise ValueError("原完整件摘要或长度不一致")
        if current.status == "active":
            if current.revision != 1 or current.revoked_at is not None or current.revoked_by is not None or current.revoke_reason != "":
                raise ValueError("活动原件治理状态无效")
        elif current.status == "revoked":
            if (
                current.revision != 2
                or current.revoked_at is None
                or current.revoked_at.tzinfo is not None
                or not current.recorded_at <= current.revoked_at <= now
                or type(current.revoked_by) is not int
                or current.revoked_by < 1
                or not current.revoke_reason.strip()
            ):
                raise ValueError("撤销原件治理状态无效")
        else:
            raise ValueError("原件状态无效")
    except (ValueError, TypeError, AttributeError, OverflowError, KeyError, RecursionError) as exc:
        raise HTTPException(409, "原器官支持资料的完整正文、归属、时刻、签署资格或治理摘要不一致") from exc
    from app.models import Admission, Doctor

    admission = db.query(Admission).filter_by(admission_id=current.admission_id, patient_id=current.patient_id).populate_existing().one_or_none()
    original_admission_current = admission is not None
    reasons = []
    if not original_admission_current:
        reasons.append("original_admission_changed_or_missing")
    if qualification.get("doctor_id") is not None and db.query(Doctor.doctor_id).filter_by(doctor_id=qualification["doctor_id"], user_id=qualification["doctor_user_id"]).first() is None:
        reasons.append("signed_doctor_identity_changed")
    try:
        event_at, live_references = spec.prepare(db, current.patient_id, current.admission_id, payload, current.recorded_at)
        if event_at != current.event_at or canonical_json(live_references) != canonical_json(references):
            reasons.append("original_dependency_or_binding_changed")
    except (HTTPException, ValueError, TypeError, KeyError, ValidationError) as exc:
        reasons.append("original_dependency_or_binding_changed")
        if not audit_only:
            raise HTTPException(409, "原器官支持资料的依赖、明确关联、规则映射或原量已变化") from exc
    if reasons and not audit_only:
        raise HTTPException(409, "原住院、签署医生关联或明确原始依赖已变化")
    if current.status != "active":
        reasons.append("source_revoked")
        if not allow_revoked:
            raise HTTPException(409, "原器官支持资料已撤销")
    return {
        **content,
        "source_id": f"{spec.prefix}:{current.support_source_id}:{current.content_hash[:12]}",
        "content_hash": current.content_hash,
        **governance(current),
        "eligible": not reasons,
        "exclusion_reasons": reasons,
        "original_admission_current": original_admission_current,
        "source_verification": "explicit_human_record_not_independently_verified",
    }


def authorize_source(db, user, patient_id, admission_id, kind, identifier, *, as_of=None):
    actor = authorize_scope(db, user, patient_id, admission_id)
    spec = definition(kind)
    row = row_by_id(db, spec, identifier)
    if row.patient_id != patient_id or row.admission_id != admission_id:
        raise HTTPException(409, "原支持资料不属于明确患者及原住院")
    source = source_current(db, row, kind)
    if as_of is not None:
        cutoff = explicit_utc(as_of) if isinstance(as_of, str) else as_of
        if row.recorded_at > cutoff:
            raise HTTPException(409, "原资料在所选可用截止之后登记，不能追认为旧截止时已知")
    authorize_scope(db, actor, patient_id, admission_id)
    return source


def revoke_source(db, user, kind, identifier, values):
    spec = definition(kind)
    try:
        req = values if isinstance(values, SourceRevoke) else SourceRevoke.model_validate(values)
    except ValidationError as exc:
        raise HTTPException(422, "撤销须提供明确原归属、当前版本及有效说明") from exc
    actor = current_actor(db, user)
    row = row_by_id(db, spec, identifier)
    if row.patient_id != req.patient_id or row.admission_id != req.admission_id:
        raise HTTPException(409, "撤销归属与原支持资料不一致")
    if actor.user_role != "super_admin":
        authorize_scope(db, actor, req.patient_id, req.admission_id)
        if row.created_by != actor.user_id:
            raise HTTPException(403, "仅原记录人或超级管理员可撤销原支持资料")
    source_current(db, row, kind, allow_revoked=True, audit_only=actor.user_role == "super_admin")
    now = utcnow()
    changed = (
        db.query(spec.model)
        .filter_by(support_source_id=identifier, status="active", revision=req.expected_revision)
        .update({"status": "revoked", "revision": req.expected_revision + 1, "revoked_at": now, "revoked_by": actor.user_id, "revoke_reason": req.reason}, synchronize_session=False)
    )
    if changed != 1:
        raise HTTPException(409, "原支持资料版本已变化或已撤销，不覆盖旧治理状态")
    return actor, row


def commit_audit(db, actor, action, target, detail):
    from app.ai.governance import audit

    try:
        audit(db, actor.user_id, action, target, detail)
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "原资料与审计发生版本或数据竞争，本次变更均未保存") from exc
    except Exception:
        db.rollback()
        raise
