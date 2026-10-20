"""Explicit drug identity governance and immutable actual vasoactive intervals.

No dose normalization, default weight, inferred infusion clocks or SOFA scoring.
"""

import datetime
import json
import uuid
from decimal import Decimal
from typing import Annotated, Literal

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy.exc import IntegrityError

from app.inpatient_laboratory import hash_content
from app.inpatient_observations import canonical_json, canonical_uuid, decimal_text, explicit_utc, utc_text
from app.inpatient_support_common import SourceDefinition, canonical_time
from app.inpatient_vasoactive_models import AIVasoactiveDrugMapping, InpatientVasoactiveSource

MAPPING_SCHEMA_VERSION = "vasoactive_drug_mapping_v1"
MAPPING_ROLES = frozenset({"super_admin"})
RATE_UNITS = ("ug/kg/min", "ug/min", "mg/h", "mL/h")
DRUG_KEYS = {"dopamine": "多巴胺", "dobutamine": "多巴酚丁胺", "epinephrine": "肾上腺素", "norepinephrine": "去甲肾上腺素", "other": "其他明确原药物"}
MAX_MAPPING_BYTES = 32768


def utcnow():
    return datetime.datetime.now(datetime.UTC).replace(tzinfo=None)


class StrictInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


def meaningful(value, minimum=20):
    if value is not None and (len(value.strip()) < minimum or value != value.strip()):
        raise ValueError("须提供足够有效原文，不接受空白补长或隐式修剪")
    return value


class MappingCreate(StrictInput):
    name: str = Field(min_length=1, max_length=120)
    source_namespace: str = Field(min_length=2, max_length=120)
    pharmaceutical_id: int = Field(ge=1, le=2147483647)
    expected_original_drug_identity_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    drug_key: Literal["dopamine", "dobutamine", "epinephrine", "norepinephrine", "other"]
    active_moiety_basis: Literal["base", "salt", "unknown"]
    allowed_rate_units: list[Literal["ug/kg/min", "ug/min", "mg/h", "mL/h"]] = Field(min_length=1, max_length=4)
    evidence_reference: str = Field(min_length=5, max_length=1000)
    rationale: str = Field(min_length=20, max_length=2000)

    @field_validator("name", "source_namespace", "evidence_reference", "rationale")
    @classmethod
    def exact_text(cls, value, info):
        return meaningful(value, {"name": 1, "source_namespace": 2, "evidence_reference": 5, "rationale": 20}[info.field_name])

    @field_validator("allowed_rate_units")
    @classmethod
    def distinct_units(cls, value):
        if len(value) != len(set(value)):
            raise ValueError("实际允许单位不可重复，不自动合并或替换单位")
        return value


def original_drug_identity(db, pharmaceutical_id):
    from app.models import Pharmaceutical

    if type(pharmaceutical_id) is not int or not 0 < pharmaceutical_id <= 2147483647:
        raise HTTPException(422, "原药品标识须为严格正整数")
    row = db.query(Pharmaceutical).filter_by(pharmaceutical_id=pharmaceutical_id).populate_existing().one_or_none()
    if row is None:
        raise HTTPException(409, "原实际药品不存在")
    if not isinstance(row.name, str) or not row.name.strip():
        raise HTTPException(409, "原实际药品缺少明确名称，不能发布身份映射")
    return {"pharmaceutical_id": row.pharmaceutical_id, "name": row.name, "barcode": row.barcode}


def identity_hash(namespace, original):
    return hash_content({"source_namespace": namespace, "original_drug_identity": original})


def mapping_super(db, user):
    from app.models import User

    actor = db.query(User).filter_by(user_id=user.user_id).with_for_update().populate_existing().one_or_none()
    if actor is None or actor.user_role != "super_admin":
        raise HTTPException(403, "当前身份不能管理血管活性药物映射")
    return actor


def create_mapping(db, user, values):
    actor = mapping_super(db, user)
    values = MappingCreate.model_validate(values).model_dump(mode="json")
    original = original_drug_identity(db, values["pharmaceutical_id"])
    if hash_content(original) != values["expected_original_drug_identity_hash"]:
        raise HTTPException(409, "原药品名称、条码或实际身份已变化，请重新核对")
    identifier, now = str(uuid.uuid4()), utcnow()
    payload = {"mapping_id": identifier, "schema_version": MAPPING_SCHEMA_VERSION, **values, "original_drug_identity": original, "created_by": actor.user_id, "created_at": utc_text(now)}
    serialized = canonical_json(payload)
    if len(serialized.encode("utf-8")) > MAX_MAPPING_BYTES:
        raise HTTPException(422, "完整药物映射超过UTF-8容量，未保存或截断")
    row = AIVasoactiveDrugMapping(
        mapping_id=identifier,
        schema_version=MAPPING_SCHEMA_VERSION,
        source_namespace=values["source_namespace"],
        pharmaceutical_id=values["pharmaceutical_id"],
        drug_key=values["drug_key"],
        active_moiety_basis=values["active_moiety_basis"],
        identity_hash=identity_hash(values["source_namespace"], original),
        published_key=None,
        payload_json=serialized,
        content_hash=hash_content(payload),
        created_by=actor.user_id,
        created_at=now,
        status="draft",
        revision=1,
        review_note="",
        revoke_reason="",
    )
    db.add(row)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "原药物或映射登记发生竞争，请刷新") from exc
    return row


def mapping_detail(db, mapping_or_id):
    identifier = mapping_or_id.mapping_id if isinstance(mapping_or_id, AIVasoactiveDrugMapping) else mapping_or_id
    try:
        canonical_uuid(identifier)
    except ValueError as exc:
        raise HTTPException(422, "映射标识须为规范UUID") from exc
    row = db.query(AIVasoactiveDrugMapping).filter_by(mapping_id=identifier).populate_existing().one_or_none()
    if row is None:
        raise HTTPException(404, "血管活性药物映射不存在")
    try:
        if not isinstance(row.payload_json, str) or len(row.payload_json.encode("utf-8")) > MAX_MAPPING_BYTES:
            raise ValueError("原文容量无效")
        raw = json.loads(row.payload_json)
        values = MappingCreate.model_validate({key: raw[key] for key in MappingCreate.model_fields}).model_dump(mode="json")
        original = raw["original_drug_identity"]
        if (
            set(original) != {"pharmaceutical_id", "name", "barcode"}
            or original["pharmaceutical_id"] != values["pharmaceutical_id"]
            or hash_content(original) != values["expected_original_drug_identity_hash"]
        ):
            raise ValueError("原药物摘要绑定无效")
        expected = {
            "mapping_id": identifier,
            "schema_version": MAPPING_SCHEMA_VERSION,
            **values,
            "original_drug_identity": original,
            "created_by": row.created_by,
            "created_at": utc_text(row.created_at),
        }
        if row.schema_version != MAPPING_SCHEMA_VERSION or canonical_json(expected) != row.payload_json or row.content_hash != hash_content(expected):
            raise ValueError("映射原文不一致")
        if (
            any(getattr(row, key) != values[key] for key in ("source_namespace", "pharmaceutical_id", "drug_key", "active_moiety_basis"))
            or row.identity_hash != identity_hash(values["source_namespace"], original)
            or row.created_at > utcnow()
        ):
            raise ValueError("原身份索引不一致")
        never_published = row.published_at is None and row.published_by is None and row.review_note == ""
        published = (
            isinstance(row.published_at, datetime.datetime)
            and row.published_at.tzinfo is None
            and row.created_at <= row.published_at <= utcnow()
            and type(row.published_by) is int
            and row.published_by > 0
            and 20 <= len(row.review_note.strip()) <= 2000
        )
        never_revoked = row.revoked_at is None and row.revoked_by is None and row.revoke_reason == ""
        revoked = (
            isinstance(row.revoked_at, datetime.datetime)
            and row.revoked_at.tzinfo is None
            and (row.published_at or row.created_at) <= row.revoked_at <= utcnow()
            and type(row.revoked_by) is int
            and row.revoked_by > 0
            and 5 <= len(row.revoke_reason.strip()) <= 1000
        )
        valid = (
            (row.status == "draft" and row.revision == 1 and row.published_key is None and never_published and never_revoked)
            or (row.status == "published" and row.revision == 2 and row.published_key == row.identity_hash and published and never_revoked)
            or (row.status == "revoked" and row.published_key is None and revoked and ((row.revision == 2 and never_published) or (row.revision == 3 and published)))
        )
        if not valid:
            raise ValueError("映射治理不一致")
        governance = {
            "status": row.status,
            "revision": row.revision,
            "published_at": utc_text(row.published_at) if row.published_at else None,
            "published_by": row.published_by,
            "review_note": row.review_note,
            "revoked_at": utc_text(row.revoked_at) if row.revoked_at else None,
            "revoked_by": row.revoked_by,
            "revoke_reason": row.revoke_reason,
        }
    except (ValueError, TypeError, KeyError, AttributeError, UnicodeError, OverflowError, RecursionError) as exc:
        raise HTTPException(409, "药物映射原文、身份或治理完整性校验失败") from exc
    try:
        current = original_drug_identity(db, row.pharmaceutical_id) == original
    except HTTPException:
        current = False
    excluded = ([] if current else ["original_drug_identity_changed"]) + ([] if row.status == "published" else ["mapping_not_published"])
    return {
        **expected,
        "identity_hash": row.identity_hash,
        "source_id": f"vasoactive_drug_mapping:{identifier}:{row.content_hash[:12]}",
        "content_hash": row.content_hash,
        **governance,
        "governance_hash": hash_content(governance),
        "original_identity_current": current,
        "eligible": not excluded,
        "exclusion_reasons": excluded,
    }


def mapping_current(db, mapping_id, allow_revoked=False):
    data = mapping_detail(db, mapping_id)
    if not data["original_identity_current"] or (data["status"] != "published" and not (allow_revoked and data["status"] == "revoked" and data["published_at"] is not None)):
        raise HTTPException(409, "原药品身份已变化或映射尚未发布/已撤销")
    return data


class OriginalReference(StrictInput):
    observation_id: str
    expected_content_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    _id = field_validator("observation_id")(canonical_uuid)


class MappingReference(StrictInput):
    mapping_id: str
    expected_content_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    _id = field_validator("mapping_id")(canonical_uuid)


class OriginReference(StrictInput):
    administration_id: str
    expected_content_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    _id = field_validator("administration_id")(canonical_uuid)


class StreamIdentity(StrictInput):
    source_namespace: str = Field(min_length=2, max_length=120)
    external_stream_id: str = Field(min_length=1, max_length=120)
    identity_basis_note: str = Field(min_length=20, max_length=1000)

    @field_validator("source_namespace", "external_stream_id", "identity_basis_note")
    @classmethod
    def exact_text(cls, value, info):
        return meaningful(value, {"source_namespace": 2, "external_stream_id": 1, "identity_basis_note": 20}[info.field_name])


class Quantity(StrictInput):
    value: str | None
    unit: str
    absent_reason: Literal["unknown", "not_performed", "measurement_error"] | None

    @field_validator("value", mode="before")
    @classmethod
    def original_value(cls, value):
        if value is None:
            return None
        value = decimal_text(value)
        if Decimal(value) < 0:
            raise ValueError("原剂量、浓度或泵速不能为负；0不作为缺测")
        return value

    @model_validator(mode="after")
    def explicit_value(self):
        if (self.value is None) == (self.absent_reason is None):
            raise ValueError("原量与未测原因须且只能提供一项")
        return self


class NormalizedRate(Quantity):
    unit: Literal["ug/kg/min"]


class AbsoluteRate(Quantity):
    unit: Literal["ug/min", "mg/h"]


class Concentration(Quantity):
    unit: Literal["ug/mL", "mg/mL"]


class PumpRate(Quantity):
    unit: Literal["mL/h"]


class WeightReview(StrictInput):
    weight_ref: OriginalReference | None
    weight_applicability_confirmed: bool
    weight_basis_note: str | None = Field(min_length=20, max_length=1000)

    @field_validator("weight_basis_note")
    @classmethod
    def valid_note(cls, value):
        return meaningful(value)

    @model_validator(mode="after")
    def explicit_review(self):
        if self.weight_applicability_confirmed:
            if self.weight_ref is None or self.weight_basis_note is None:
                raise ValueError("确认体重适用须明确原体重及临床依据")
        elif self.weight_basis_note is not None:
            raise ValueError("未确认体重适用时须保留null依据")
        return self


class WeightNormalizedDose(WeightReview):
    mode: Literal["weight_normalized"]
    rate: NormalizedRate


class AbsoluteDose(WeightReview):
    mode: Literal["absolute"]
    rate: AbsoluteRate


class PumpDose(WeightReview):
    mode: Literal["pump"]
    concentration: Concentration
    pump_rate: PumpRate


class VasoactivePayload(StrictInput):
    start_at: str
    verified_until_at: str
    ended_at: str | None
    drug_mapping: MappingReference
    stream_identity: StreamIdentity
    origin: OriginReference | None
    continuity_confirmed: bool
    continuity_basis_note: str | None = Field(min_length=20, max_length=1000)
    dose_input: Annotated[WeightNormalizedDose | AbsoluteDose | PumpDose, Field(discriminator="mode")]
    note: str = Field(default="", max_length=1000)

    @field_validator("start_at", "verified_until_at", "ended_at", mode="before")
    @classmethod
    def exact_utc(cls, value):
        return canonical_time(value) if value is not None else None

    @field_validator("continuity_basis_note")
    @classmethod
    def valid_note(cls, value):
        return meaningful(value)

    @model_validator(mode="after")
    def actual_interval(self):
        if explicit_utc(self.start_at) >= explicit_utc(self.verified_until_at) or self.ended_at is not None and self.ended_at != self.verified_until_at:
            raise ValueError("原段须有真实开始及已核至时刻；已结束时刻须等于已核至时刻")
        if self.continuity_confirmed != (self.continuity_basis_note is not None):
            raise ValueError("连续性确认须有独立依据，未确认须保留null依据")
        return self


def _raw_orm(row):
    def raw(value):
        if isinstance(value, datetime.datetime):
            return value.isoformat(timespec="microseconds")
        if isinstance(value, datetime.date):
            return value.isoformat()
        if isinstance(value, Decimal):
            return str(value)
        return value

    return {column.name: raw(getattr(row, column.name)) for column in row.__table__.columns}


def origin_snapshot(db, patient_id, admission_id, administration_id, mapping=None):
    from app.models import InpatientOrder, InpatientOrderItem, MedicationAdministration, OrderExecution

    try:
        canonical_uuid(administration_id)
    except ValueError as exc:
        raise HTTPException(422, "原给药记录须为规范UUID") from exc
    administration = db.query(MedicationAdministration).filter_by(administration_id=administration_id).populate_existing().one_or_none()
    if administration is None or administration.patient_id != patient_id or administration.status != 2 or administration.administration_time is None:
        raise HTTPException(409, "须明确同一原患者已经实际给药的eMAR状态2来源，不用扫码通过或计划代替")
    execution = db.query(OrderExecution).filter_by(execution_id=administration.execution_id).populate_existing().one_or_none()
    order = db.query(InpatientOrder).filter_by(order_id=administration.order_id).populate_existing().one_or_none()
    if (
        execution is None
        or order is None
        or execution.order_id != order.order_id
        or execution.status != 1
        or execution.nurse_id != administration.nurse_id
        or order.patient_id != patient_id
        or order.admission_id != admission_id
    ):
        raise HTTPException(409, "原eMAR、实际执行、医嘱与患者/住院链不一致")
    items = db.query(InpatientOrderItem).filter_by(order_id=order.order_id).order_by(InpatientOrderItem.item_id).populate_existing().limit(1001).all()
    if len(items) > 1000:
        raise HTTPException(422, "原医嘱项目超过1000条，不能截断实际给药原链")
    if mapping is not None and not any(item.item_type == "drug" and item.item_id_ref == mapping["pharmaceutical_id"] for item in items):
        raise HTTPException(409, "原已给药医嘱不包含所选映射的真实药物")
    payload = {
        "schema_version": "vasoactive_origin_v1",
        "patient_id": patient_id,
        "admission_id": admission_id,
        "administration": _raw_orm(administration),
        "execution": _raw_orm(execution),
        "order": _raw_orm(order),
        "items": [_raw_orm(item) for item in items],
        "time_basis": "legacy_naive_unknown_not_continuous_utc_evidence",
    }
    content_hash = hash_content(payload)
    return {**payload, "content_hash": content_hash, "source_id": f"medication_administration:{administration_id}:{content_hash[:12]}"}


def origin_candidates(db, patient_id, admission_id, mapping_id=None, page=1, page_size=20):
    from app.models import InpatientOrder, InpatientOrderItem, MedicationAdministration

    if type(page) is not int or page < 1 or type(page_size) is not int or not 0 < page_size <= 100:
        raise HTTPException(422, "给药原来源分页须为明确正整数")
    mapping = mapping_current(db, mapping_id) if mapping_id else None
    query = (
        db.query(MedicationAdministration)
        .join(InpatientOrder, MedicationAdministration.order_id == InpatientOrder.order_id)
        .filter(MedicationAdministration.patient_id == patient_id, MedicationAdministration.status == 2, InpatientOrder.patient_id == patient_id, InpatientOrder.admission_id == admission_id)
    )
    if mapping:
        query = query.filter(
            InpatientOrder.order_id.in_(db.query(InpatientOrderItem.order_id).filter(InpatientOrderItem.item_type == "drug", InpatientOrderItem.item_id_ref == mapping["pharmaceutical_id"]))
        )
    total = query.count()
    rows = query.order_by(MedicationAdministration.administration_id).offset((page - 1) * page_size).limit(page_size).all()
    items = []
    for row in rows:
        snapshot = origin_snapshot(db, patient_id, admission_id, row.administration_id, mapping)
        items.append({"administration_id": row.administration_id, "content_hash": snapshot["content_hash"], "source_id": snapshot["source_id"], "snapshot": snapshot})
    return {"items": items, "total": total, "page": page, "page_size": page_size}


def prepare(db, patient_id, admission_id, payload_dict, recorded_at):
    from app.inpatient_observations import source_current
    from app.models import InpatientObservation

    payload = VasoactivePayload.model_validate(payload_dict).model_dump(mode="json")
    start, until = explicit_utc(payload["start_at"]), explicit_utc(payload["verified_until_at"])
    if until > recorded_at:
        raise HTTPException(409, "实际已核至时刻不能在原登记之后，不自动延长输注")
    mapping_ref = payload["drug_mapping"]
    mapping = mapping_current(db, mapping_ref["mapping_id"])
    if mapping["content_hash"] != mapping_ref["expected_content_hash"] or explicit_utc(mapping["published_at"]) > recorded_at:
        raise HTTPException(409, "原药物映射摘要或发布可用时刻不一致")
    dose = payload["dose_input"]
    unit = dose["pump_rate"]["unit"] if dose["mode"] == "pump" else dose["rate"]["unit"]
    if unit not in mapping["allowed_rate_units"]:
        raise HTTPException(409, "所选原单位尚未在此药物映射中明确审核，不自动转换")
    refs = {"drug_mapping": mapping, "weight": None, "origin": None}
    if dose["weight_ref"] is not None:
        reference = dose["weight_ref"]
        row = db.query(InpatientObservation).filter_by(observation_id=reference["observation_id"]).populate_existing().one_or_none()
        weight = source_current(db, row)
        measurement = weight["payload"]["measurements"].get("body_weight")
        if (
            weight["patient_id"] != patient_id
            or weight["admission_id"] != admission_id
            or weight["content_hash"] != reference["expected_content_hash"]
            or measurement is None
            or measurement["unit"] != "kg"
            or explicit_utc(weight["observed_at"]) > start
            or explicit_utc(weight["recorded_at"]) > recorded_at
        ):
            raise HTTPException(409, "原体重须同患者/住院、kg、实测不晚于开始且登记不晚于本来源，完整摘要一致")
        refs["weight"] = weight
    if payload["origin"] is not None:
        reference = payload["origin"]
        origin = origin_snapshot(db, patient_id, admission_id, reference["administration_id"], mapping)
        if origin["content_hash"] != reference["expected_content_hash"]:
            raise HTTPException(409, "实际给药原链摘要变化，不能借旧naive钟点推定本UTC输注段")
        refs["origin"] = origin
    return start, refs


DEFINITIONS = [SourceDefinition("vasoactive", "vasoactive_interval_v1", "vasoactive_interval", InpatientVasoactiveSource, VasoactivePayload, False, prepare)]
