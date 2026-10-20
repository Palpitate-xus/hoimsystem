"""Explicit admission-bound observations, immutable content and current care authorization."""

import datetime
import hashlib
import json
import re
import uuid
from decimal import Decimal, InvalidOperation
from typing import Literal

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

POINT_VERSION = "inpatient_observation_v1"
URINE_VERSION = "urine_interval_v1"
ABSENT_REASONS = Literal["unknown", "not_performed", "measurement_error"]
MEASUREMENT_UNITS = {
    "heart_rate": "/min",
    "pulse_rate": "/min",
    "respiratory_rate": "/min",
    "systolic_bp": "mm[Hg]",
    "diastolic_bp": "mm[Hg]",
    "temperature": "Cel",
    "spo2": "%",
    "body_weight": "kg",
    "oxygen_flow": "L/min",
    "fio2": "%",
}
OBSERVATION_ROLES = frozenset({"nurse", "doctor", "director", "admin", "super_admin"})
ISO_TIME = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})")
DECIMAL_TEXT = re.compile(r"-?(?:0|[1-9]\d{0,15})(?:\.\d{1,8})?")


def utcnow():
    return datetime.datetime.now(datetime.UTC).replace(tzinfo=None)


def canonical_json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def utc_text(value):
    if not isinstance(value, datetime.datetime) or value.tzinfo is not None:
        raise ValueError("保存时刻必须为明确UTC语义的无时区datetime")
    return value.isoformat(timespec="microseconds") + "Z"


def canonical_uuid(value):
    if not isinstance(value, str):
        raise ValueError("标识须为规范UUID字符串")
    try:
        if str(uuid.UUID(value)) != value:
            raise ValueError("标识须为规范小写UUID")
    except (ValueError, AttributeError) as exc:
        raise ValueError("标识须为规范小写UUID") from exc
    return value


def explicit_utc(value):
    """Accept only explicit ISO clocks; reject precision loss and UTC overflow."""
    if not isinstance(value, str) or ISO_TIME.fullmatch(value) is None:
        raise ValueError("测量时刻须为带明确时区的ISO日期时间，小数秒最多6位")
    if not value.endswith("Z") and (int(value[-5:-3]) > 23 or int(value[-2:]) > 59):
        raise ValueError("时区偏移小时或分钟无效，不自动进位")
    try:
        parsed = datetime.datetime.fromisoformat(value)
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("测量时刻缺少时区")
        return parsed.astimezone(datetime.UTC).replace(tzinfo=None)
    except (ValueError, OverflowError) as exc:
        raise ValueError("测量时刻无效或超出可保存的UTC范围") from exc


def decimal_text(value):
    """Keep supplied decimal text, without coercion, exponent notation or rounding."""
    if not isinstance(value, str) or DECIMAL_TEXT.fullmatch(value) is None:
        raise ValueError("数值须为普通十进制字符串，整数最多16位、小数最多8位")
    try:
        number = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError("数值须为有限十进制字符串") from exc
    if not number.is_finite() or len(number.as_tuple().digits) > 24:
        raise ValueError("数值超出有限NUMERIC(24,8)精度")
    return value


class StrictInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Measurement(StrictInput):
    value: str | None
    unit: str = Field(min_length=1, max_length=16, strict=True)
    absent_reason: ABSENT_REASONS | None

    @field_validator("value", mode="before")
    @classmethod
    def check_decimal(cls, value):
        return decimal_text(value) if value is not None else None

    @model_validator(mode="after")
    def value_or_reason(self):
        if (self.value is None) == (self.absent_reason is None):
            raise ValueError("数值和未测原因必须且只能提供一项")
        return self


class Consciousness(StrictInput):
    system: Literal["AVPU", "ACVPU"]
    code: Literal["alert", "voice", "pain", "unresponsive", "new_confusion"]

    @model_validator(mode="after")
    def defined_code(self):
        if self.system == "AVPU" and self.code == "new_confusion":
            raise ValueError("new_confusion不属于AVPU编码；须明确使用ACVPU")
        return self


class PointPayload(StrictInput):
    measurements: dict[str, Measurement] = Field(default_factory=dict, max_length=10)
    supplemental_oxygen: Literal["yes", "no", "unknown"]
    oxygen_device: str | None = Field(default=None, max_length=120)
    consciousness: Consciousness | None = None
    note: str = Field(default="", max_length=2000)

    @field_validator("oxygen_device")
    @classmethod
    def nonblank_device(cls, value):
        if value is not None and not value.strip():
            raise ValueError("氧疗装置须为明确文本，未知请保留null")
        return value

    @model_validator(mode="after")
    def measurements_are_explicit(self):
        if set(self.measurements) - MEASUREMENT_UNITS.keys():
            raise ValueError("存在未定义的观测指标")
        for key, item in self.measurements.items():
            if item.unit != MEASUREMENT_UNITS[key]:
                raise ValueError(f"{key}必须明确使用单位{MEASUREMENT_UNITS[key]}")
            if item.value is None:
                continue
            number = Decimal(item.value)
            if key != "temperature" and number < 0:
                raise ValueError(f"{key}须为非负原始测量值")
            if key in {"spo2", "fio2"} and number > 100:
                raise ValueError("百分比须在0至100之间，不自动进行比例换算")
        if not self.measurements and self.consciousness is None and self.supplemental_oxygen == "unknown":
            raise ValueError("至少明确记录一个观测项、意识或是否使用补充氧")
        return self


class PointCreate(PointPayload):
    patient_id: int = Field(strict=True, ge=1, le=2147483647)
    admission_id: str
    observed_at: datetime.datetime

    _admission_uuid = field_validator("admission_id")(canonical_uuid)
    _time = field_validator("observed_at", mode="before")(explicit_utc)

    @model_validator(mode="after")
    def not_future(self):
        if self.observed_at > utcnow():
            raise ValueError("测量时刻不能在未来")
        return self


class UrinePayload(StrictInput):
    volume_ml: str | None
    absent_reason: ABSENT_REASONS | None
    collection_completeness: Literal["complete", "partial", "unknown"]
    patient_total: bool | None = Field(strict=True)
    collection_method: str = Field(min_length=1, max_length=120)
    note: str = Field(default="", max_length=2000)

    @field_validator("volume_ml", mode="before")
    @classmethod
    def check_volume(cls, value):
        if value is not None and Decimal(decimal_text(value)) < 0:
            raise ValueError("尿量必须非负，未测保留null")
        return value

    @field_validator("collection_method")
    @classmethod
    def nonblank_method(cls, value):
        if not value.strip():
            raise ValueError("采集方法须明确填写，不能留空或猜测")
        return value

    @model_validator(mode="after")
    def volume_or_reason(self):
        if (self.volume_ml is None) == (self.absent_reason is None):
            raise ValueError("尿量和未测原因必须且只能提供一项")
        return self


class UrineCreate(UrinePayload):
    patient_id: int = Field(strict=True, ge=1, le=2147483647)
    admission_id: str
    start_at: datetime.datetime
    end_at: datetime.datetime

    _admission_uuid = field_validator("admission_id")(canonical_uuid)
    _times = field_validator("start_at", "end_at", mode="before")(explicit_utc)

    @model_validator(mode="after")
    def real_interval(self):
        if self.start_at >= self.end_at or self.end_at > utcnow():
            raise ValueError("尿量须有真实起止区间，起始早于结束且结束不在未来")
        return self


class ObservationRevoke(StrictInput):
    patient_id: int = Field(strict=True, ge=1, le=2147483647)
    admission_id: str
    expected_revision: int = Field(strict=True, ge=1)
    reason: str = Field(min_length=1, max_length=1000)

    _admission_uuid = field_validator("admission_id")(canonical_uuid)

    @field_validator("reason")
    @classmethod
    def nonblank_reason(cls, value):
        if not value.strip():
            raise ValueError("撤销依据不能为空白")
        return value


def authorize_observation_admission(db, user, patient_id, admission_id):
    """Require real prior care or a grant, never the newly created source's author."""
    from app.ai.context import authorize_patient
    from app.models import Admission, Registration, User

    actor = db.query(User).filter_by(user_id=user.user_id).populate_existing().one_or_none()
    if actor is None or actor.user_role not in OBSERVATION_ROLES:
        raise HTTPException(403, "当前用户没有住院观测资料权限")
    if type(patient_id) is not int or not 0 < patient_id <= 2147483647:
        raise HTTPException(422, "患者标识须为正整数且处于数据库标识范围")
    try:
        canonical_uuid(admission_id)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    admission = db.query(Admission).filter_by(admission_id=admission_id, patient_id=patient_id).populate_existing().one_or_none()
    if admission is None:
        raise HTTPException(404, "原住院不存在或不属于该患者")
    if db.query(Registration.registration_uuid).filter_by(registration_uuid=admission_id, patient_id=patient_id).first() is not None:
        raise HTTPException(409, "原住院标识与同患者门诊标识冲突，请核对真实就诊归属")
    authorize_patient(db, actor, patient_id, "inpatient", admission_id)
    return admission


def _frozen(row, payload):
    point = hasattr(row, "observation_id")
    data = {
        "observation_id" if point else "interval_id": row.observation_id if point else row.interval_id,
        "patient_id": row.patient_id,
        "admission_id": row.admission_id,
        "recorded_at": utc_text(row.recorded_at),
        "created_by": row.created_by,
        "schema_version": row.schema_version,
        "payload": payload,
    }
    if point:
        data["observed_at"] = utc_text(row.observed_at)
    else:
        data.update(start_at=utc_text(row.start_at), end_at=utc_text(row.end_at))
    return data


def frozen_content_hash(row, payload):
    return hashlib.sha256(canonical_json(_frozen(row, payload)).encode("utf-8")).hexdigest()


def _serialize(row, point):
    payload = json.loads(row.payload_json)
    data = _frozen(row, payload)
    data.update(
        source_id=("inpatient_observation:" + row.observation_id if point else "urine_interval:" + row.interval_id) + ":" + row.content_hash[:12],
        content_hash=row.content_hash,
        status=row.status,
        revision=row.revision,
        revoked_at=utc_text(row.revoked_at) if row.revoked_at is not None else None,
        revoked_by=row.revoked_by,
        revoke_reason=row.revoke_reason,
    )
    return data


def serialize_point(row):
    return _serialize(row, True)


def serialize_urine(row):
    return _serialize(row, False)


def source_current(db, row, *, allow_revoked=False):
    """Recheck the stored source and parent; revocation is never an implicit restore."""
    from app.models import Admission, InpatientObservation, InpatientUrineInterval

    point = isinstance(row, InpatientObservation)
    model, field = (InpatientObservation, "observation_id") if point else (InpatientUrineInterval, "interval_id")
    if not isinstance(row, model):
        raise HTTPException(409, "观测来源类型无效")
    current = db.query(model).filter(getattr(model, field) == getattr(row, field)).populate_existing().one_or_none()
    if current is None:
        raise HTTPException(409, "观测原资料已不存在")
    try:
        canonical_uuid(getattr(current, field))
        canonical_uuid(current.admission_id)
        if type(current.patient_id) is not int or current.patient_id <= 0 or type(current.created_by) is not int or current.created_by <= 0:
            raise ValueError("归属或作者无效")
        if current.schema_version != (POINT_VERSION if point else URINE_VERSION):
            raise ValueError("不支持的来源版本")
        payload = json.loads(current.payload_json)
        typed = (PointPayload if point else UrinePayload).model_validate(payload).model_dump(mode="json")
        if current.payload_json != canonical_json(typed) or current.content_hash != frozen_content_hash(current, typed):
            raise ValueError("冻结内容哈希不一致")
        if current.recorded_at > utcnow() or (point and current.observed_at > current.recorded_at) or (not point and not current.start_at < current.end_at <= current.recorded_at):
            raise ValueError("观测时间链无效")
        if current.status == "active":
            if current.revision != 1 or current.revoked_at is not None or current.revoked_by is not None or current.revoke_reason != "":
                raise ValueError("活动来源治理字段无效")
        elif current.status == "revoked":
            if (
                current.revision != 2
                or current.revoked_at is None
                or type(current.revoked_by) is not int
                or current.revoked_by <= 0
                or not 0 < len(current.revoke_reason.strip()) <= 1000
                or not current.recorded_at <= current.revoked_at <= utcnow()
            ):
                raise ValueError("撤销来源治理字段无效")
        else:
            raise ValueError("来源状态无效")
        serialized = _serialize(current, point)
    except (ValueError, TypeError, AttributeError, OverflowError) as exc:
        raise HTTPException(409, "观测原资料完整性校验失败，请核对原始来源") from exc
    admission = db.query(Admission).filter_by(admission_id=current.admission_id, patient_id=current.patient_id).populate_existing().one_or_none()
    if admission is None:
        raise HTTPException(409, "观测原住院不存在或归属已变化")
    if current.status == "revoked" and not allow_revoked:
        raise HTTPException(409, "观测来源已撤销，不能作为当前测量使用")
    return serialized
