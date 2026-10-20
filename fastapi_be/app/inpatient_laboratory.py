"""Explicitly verified admission lab registration; legacy clocks and stored values stay intact."""

import datetime
import hashlib
import json
import uuid
from decimal import Decimal
from typing import Literal

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.inpatient_observations import authorize_observation_admission, canonical_json, canonical_uuid, explicit_utc, utc_text

LAB_SOURCE_ROLES = frozenset({"doctor", "director", "admin", "super_admin"})
LAB_READ_ROLES = LAB_SOURCE_ROLES | {"nurse"}
SCHEMA_VERSION = "inpatient_lab_source_v1"
AVAILABILITY_BASIS = "server_registered_after_verification"
NAMESPACE_BASIS = "explicit_user_attestation_no_stored_lis_origin"
MAPPING_GOVERNANCE = ("mapping_id", "source_id", "content_hash", "status", "revision", "governance_hash", "published_at", "published_by", "revoked_at", "revoked_by", "revoke_reason")
FROZEN_FIELDS = ("lab_source_id", "patient_id", "admission_id", "observation_id", "mapping_id", "schema_version", "created_by", "raw_original_hash", "mapping_content_hash")
NOTE_FIELDS = ("collection_time_basis_note", "admission_binding_note", "source_namespace_basis_note")
CONFIRM_FIELDS = ("collection_time_confirmed", "admission_binding_confirmed", "source_namespace_confirmed")


def utcnow():
    return datetime.datetime.now(datetime.UTC).replace(tzinfo=None)


def opaque_id(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 36 or not value.strip():
        raise ValueError("原检验标识须为非空且最多36字的原始字符串")
    return value


def hash_content(value):
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


class SourceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    patient_id: int = Field(strict=True, ge=1, le=2147483647)
    admission_id: str
    observation_id: str
    mapping_id: str
    expected_source_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    expected_mapping_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    collected_at_utc: datetime.datetime
    collection_time_confirmed: Literal[True]
    collection_time_basis_note: str = Field(min_length=20, max_length=2000)
    admission_binding_confirmed: Literal[True]
    admission_binding_note: str = Field(min_length=20, max_length=2000)
    source_namespace_confirmed: Literal[True]
    source_namespace_basis_note: str = Field(min_length=20, max_length=2000)

    _uuid = field_validator("admission_id", "mapping_id")(canonical_uuid)
    _opaque = field_validator("observation_id")(opaque_id)
    _utc = field_validator("collected_at_utc", mode="before")(explicit_utc)

    @field_validator(*CONFIRM_FIELDS, mode="before")
    @classmethod
    def explicit_confirmation(cls, value):
        if value is not True:
            raise ValueError("每项人工核实均须显式确认，不接受数字或字符串替代")
        return value

    @field_validator(*NOTE_FIELDS)
    @classmethod
    def meaningful_note(cls, value):
        if len(value.strip()) < 20:
            raise ValueError("核实依据须至少20字有效内容")
        return value


class SourceRevoke(BaseModel):
    model_config = ConfigDict(extra="forbid")

    patient_id: int = Field(strict=True, ge=1, le=2147483647)
    admission_id: str
    expected_revision: int = Field(strict=True, ge=1)
    reason: str = Field(min_length=1, max_length=1000)

    _uuid = field_validator("admission_id")(canonical_uuid)

    @field_validator("reason")
    @classmethod
    def meaningful_reason(cls, value):
        if not value.strip():
            raise ValueError("撤销依据不能为空白")
        return value


def authorize_scope(db, user, patient_id, admission_id, *, creating=False):
    from app.models import User

    admission = authorize_observation_admission(db, user, patient_id, admission_id)
    actor = db.query(User).filter_by(user_id=user.user_id).populate_existing().one_or_none()
    if creating and (actor is None or actor.user_role not in LAB_SOURCE_ROLES):
        raise HTTPException(403, "只有有本次住院照护权限的医生、主任或管理员可登记检验来源")
    return admission


def _legacy_clock(value):
    if value is None:
        return None
    if not isinstance(value, datetime.datetime) or value.tzinfo is not None:
        raise ValueError("原检验钟点格式无效")
    return value.isoformat(timespec="microseconds")


def _stored_decimal(value):
    if value is None:
        return None
    if not isinstance(value, Decimal) or not value.is_finite():
        raise ValueError("原检验数值不是有效的数据库十进制值")
    return format(value, "f")


def original_snapshot(observation, report, order):
    """Hash stable clinical originals, excluding later critical and integration workflow changes."""
    numeric = {key: _stored_decimal(getattr(observation, key)) for key in ("value_num", "reference_low", "reference_high")}
    if (numeric["value_num"] is None) == (observation.value_text is None) or (numeric["value_num"] is not None and not observation.unit):
        raise ValueError("原检验数值/文本及单位不满足来源契约")
    return {
        "observation": {
            **{
                key: getattr(observation, key)
                for key in ("observation_id", "lab_result_id", "code_system", "code", "display", "value_text", "unit", "reference_text", "method", "specimen_type", "flag")
            },
            **numeric,
            "collected_at": _legacy_clock(observation.collected_at),
            "time_basis": "unknown",
            "value_representation": "database_stored_decimal_text",
        },
        "report": {
            **{key: getattr(report, key) for key in ("lab_result_id", "lab_order_id", "sample_id", "result", "abnormal_flag", "technician_id", "audit_status", "auditor_id")},
            "report_time": _legacy_clock(report.report_time),
            "audit_time": _legacy_clock(report.audit_time),
            "time_basis": "unknown",
            "review_scheme": "distinct_local_entry_and_review_users" if report.technician_id is not None else "no_local_entry_actor_plus_local_reviewer",
        },
        "order": {
            **{key: getattr(order, key) for key in ("lab_order_id", "patient_id", "doctor_id", "check_type", "check_items", "urgent", "status", "sample_status")},
            "create_time": _legacy_clock(order.create_time),
            "time_basis": "unknown",
        },
    }


def load_original(db, observation_id, patient_id):
    from app.models import LabObservation, LabOrder, LabResult, User

    try:
        opaque_id(observation_id)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    observation = db.query(LabObservation).filter_by(observation_id=observation_id).populate_existing().one_or_none()
    report = db.query(LabResult).filter_by(lab_result_id=observation.lab_result_id).populate_existing().one_or_none() if observation else None
    order = db.query(LabOrder).filter_by(lab_order_id=report.lab_order_id).populate_existing().one_or_none() if report else None
    if (
        observation is None
        or report is None
        or order is None
        or order.patient_id != patient_id
        or observation.observation_id != observation_id
        or report.lab_result_id != observation.lab_result_id
        or order.lab_order_id != report.lab_order_id
    ):
        raise HTTPException(409, "原检验指标、报告、申请或患者归属不存在或已改变")
    if report.audit_status != 1 or order.status != 2 or report.auditor_id is None or report.auditor_id == report.technician_id:
        raise HTTPException(409, "原报告未满足独立审核要求，不可登记或继续使用")
    if db.query(User.user_id).filter_by(user_id=report.auditor_id).first() is None:
        raise HTTPException(409, "原审核人不存在，请核对原报告")
    try:
        snapshot = original_snapshot(observation, report, order)
    except (ValueError, TypeError, AttributeError) as exc:
        raise HTTPException(409, "原检验临床内容格式校验失败") from exc
    return observation, snapshot, hash_content(snapshot)


def frozen_metadata(row):
    return {
        **{key: getattr(row, key) for key in FROZEN_FIELDS},
        **{key: utc_text(getattr(row, key)) for key in ("collected_at_utc", "registered_at", "available_at")},
    }


def metadata(row):
    return {
        **frozen_metadata(row),
        "source_id": f"inpatient_lab:{row.lab_source_id}:{row.content_hash[:12]}",
        "content_hash": row.content_hash,
        "status": row.status,
        "revision": row.revision,
        "revoked_at": utc_text(row.revoked_at) if row.revoked_at is not None else None,
        "revoked_by": row.revoked_by,
        "revoke_reason": row.revoke_reason,
    }


def create_source(db, user, values):
    from app.ai.lab_mappings import mapping_current, mapping_matches
    from app.models import InpatientLabSource

    req = values if isinstance(values, SourceCreate) else SourceCreate.model_validate(values)
    authorize_scope(db, user, req.patient_id, req.admission_id, creating=True)
    observation, original, raw_hash = load_original(db, req.observation_id, req.patient_id)
    mapping = mapping_current(db, req.mapping_id)
    if raw_hash != req.expected_source_hash or mapping["content_hash"] != req.expected_mapping_hash:
        raise HTTPException(409, "原检验或映射已变化，请重新核对候选与摘要")
    if not mapping_matches(mapping, observation):
        raise HTTPException(409, "所选映射与原检验编码、单位、标本、方法或值类型不一致")
    now = utcnow()
    if req.collected_at_utc > now:
        raise HTTPException(422, "人工核实的采样时刻不能在未来")
    if explicit_utc(mapping["published_at"]) > now:
        raise HTTPException(409, "映射发布时间晚于本次来源登记时刻，请核对明确UTC时钟")
    row = InpatientLabSource(
        lab_source_id=str(uuid.uuid4()),
        patient_id=req.patient_id,
        admission_id=req.admission_id,
        observation_id=req.observation_id,
        active_observation_id=req.observation_id,
        mapping_id=req.mapping_id,
        collected_at_utc=req.collected_at_utc,
        registered_at=now,
        available_at=now,
        created_by=user.user_id,
        schema_version=SCHEMA_VERSION,
        raw_original_hash=raw_hash,
        mapping_content_hash=mapping["content_hash"],
        status="active",
        revision=1,
        revoke_reason="",
    )
    snapshot = {
        **frozen_metadata(row),
        "original": original,
        "mapping": mapping,
        "source_namespace": mapping["source_namespace"],
        "source_namespace_origin_basis": NAMESPACE_BASIS,
        "availability_basis": AVAILABILITY_BASIS,
        "sampling_time_basis": "explicit_user_verified_utc_not_legacy_clock_proof",
        "source_verification": "explicit_user_attestation_not_independently_verified",
        **{key: getattr(req, key) for key in (*NOTE_FIELDS, *CONFIRM_FIELDS)},
    }
    row.snapshot_json = canonical_json(snapshot)
    row.content_hash = hash_content(snapshot)
    db.add(row)
    return row


def source_current(db, row, *, allow_revoked=False):
    """Validate originals and mapping body; expose revoked governance only on explicit request."""
    from app.ai.lab_mappings import mapping_current, mapping_matches
    from app.models import Admission, InpatientLabSource

    if not isinstance(row, InpatientLabSource):
        raise HTTPException(409, "检验来源类型无效")
    current = db.query(InpatientLabSource).filter_by(lab_source_id=row.lab_source_id).populate_existing().one_or_none()
    if current is None:
        raise HTTPException(409, "原检验登记来源已不存在")
    try:
        for key in ("lab_source_id", "admission_id", "mapping_id"):
            canonical_uuid(getattr(current, key))
        opaque_id(current.observation_id)
        snapshot = json.loads(current.snapshot_json)
        if not isinstance(snapshot, dict) or not isinstance(snapshot.get("mapping"), dict):
            raise ValueError("冻结来源或映射正文结构无效")
        if current.schema_version != SCHEMA_VERSION or current.content_hash != hash_content(snapshot) or current.snapshot_json != canonical_json(snapshot):
            raise ValueError("冻结正文或哈希不一致")
        if any(snapshot.get(key) != value for key, value in frozen_metadata(current).items()):
            raise ValueError("冻结元数据不一致")
        if not current.collected_at_utc <= current.registered_at == current.available_at <= utcnow():
            raise ValueError("登记或可用时间链无效")
        if any(snapshot.get(key) is not True for key in CONFIRM_FIELDS) or any(not isinstance(snapshot.get(key), str) or not 20 <= len(snapshot[key].strip()) <= 2000 for key in NOTE_FIELDS):
            raise ValueError("缺少明确人工核实依据")
        if (
            snapshot.get("availability_basis") != AVAILABILITY_BASIS
            or snapshot.get("source_namespace_origin_basis") != NAMESPACE_BASIS
            or snapshot.get("sampling_time_basis") != "explicit_user_verified_utc_not_legacy_clock_proof"
            or snapshot.get("source_verification") != "explicit_user_attestation_not_independently_verified"
        ):
            raise ValueError("来源时钟或字典来源语义改变")
        if current.status == "active":
            if current.revision != 1 or current.active_observation_id != current.observation_id or current.revoked_at is not None or current.revoked_by is not None or current.revoke_reason != "":
                raise ValueError("活动来源治理不一致")
        elif current.status == "revoked":
            if (
                current.revision != 2
                or current.active_observation_id is not None
                or current.revoked_at is None
                or not current.registered_at <= current.revoked_at <= utcnow()
                or not isinstance(current.revoked_by, int)
                or current.revoked_by <= 0
                or not current.revoke_reason.strip()
            ):
                raise ValueError("撤销来源治理不一致")
        else:
            raise ValueError("来源状态无效")
    except (ValueError, TypeError, AttributeError, OverflowError, RecursionError) as exc:
        raise HTTPException(409, "冻结检验来源完整性校验失败，请由超级管理员核查") from exc
    if db.query(Admission.admission_id).filter_by(admission_id=current.admission_id, patient_id=current.patient_id).first() is None:
        raise HTTPException(409, "原住院不存在或患者归属已改变")
    observation, original, raw_hash = load_original(db, current.observation_id, current.patient_id)
    if raw_hash != current.raw_original_hash or original != snapshot.get("original"):
        raise HTTPException(409, "原检验临床内容、父链或审核事实已改变")
    mapping = mapping_current(db, current.mapping_id, allow_revoked=True)
    mutable = {"status", "revision", "revoked_at", "revoked_by", "revoke_reason", "governance_hash"}
    if (
        mapping["content_hash"] != current.mapping_content_hash
        or {key: value for key, value in mapping.items() if key not in mutable} != {key: value for key, value in snapshot.get("mapping", {}).items() if key not in mutable}
        or snapshot.get("source_namespace") != mapping["source_namespace"]
        or not mapping_matches(mapping, observation)
        or explicit_utc(mapping["published_at"]) > current.registered_at
    ):
        raise HTTPException(409, "原项目映射正文或匹配条件已改变")
    excluded = (["source_revoked"] if current.status == "revoked" else []) + (["mapping_revoked"] if mapping["status"] != "published" else [])
    if excluded and not allow_revoked:
        raise HTTPException(409, "检验来源或项目映射已撤销，不能作为有效数值输入")
    return {**metadata(current), "snapshot": snapshot, "mapping_current": {key: mapping.get(key) for key in MAPPING_GOVERNANCE}, "eligible": not excluded, "exclusion_reasons": excluded}
