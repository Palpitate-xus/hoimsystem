"""Exact bedside originals and explicit current arterial sampling review, without SOFA math."""

from decimal import Decimal
from typing import Literal

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.inpatient_observations import ABSENT_REASONS, canonical_uuid, decimal_text, explicit_utc
from app.inpatient_respiratory_models import InpatientArterialPairSource, InpatientMapSource, InpatientRespiratorySource
from app.inpatient_support_common import SourceDefinition, canonical_time


class StrictPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


def canonical_clock(value):
    return canonical_time(value)


def meaningful_note(value):
    if value is not None and len(value.strip()) < 20:
        raise ValueError("核实依据须至少20字有效内容")
    return value


class MapMeasurement(StrictPayload):
    value: str | None
    unit: Literal["mm[Hg]"]
    absent_reason: ABSENT_REASONS | None

    @field_validator("value", mode="before")
    @classmethod
    def exact_nonnegative(cls, value):
        if value is not None:
            decimal_text(value)
            if Decimal(value) < 0:
                raise ValueError("MAP须为非负原始测量值")
        return value

    @model_validator(mode="after")
    def explicit_missing(self):
        if (self.value is None) == (self.absent_reason is None):
            raise ValueError("原测量数值和未测原因必须且只能提供一项")
        return self


class MapPayload(StrictPayload):
    observed_at: str
    map: MapMeasurement
    measurement_method: Literal["invasive_arterial", "oscillometric_device", "unknown"]
    measurement_basis_note: str = Field(min_length=20, max_length=1000)
    note: str = Field(max_length=1000)

    _clock = field_validator("observed_at", mode="before")(canonical_clock)
    _note = field_validator("measurement_basis_note")(meaningful_note)


class RespiratorySupportPayload(StrictPayload):
    start_at: str
    verified_until_at: str
    ended_at: str | None
    delivery_mode: Literal["none", "invasive_mechanical", "noninvasive_positive_pressure", "high_flow_nasal", "low_flow_oxygen", "other", "unknown"]
    continuity_confirmed: bool
    continuity_basis_note: str | None = Field(min_length=20, max_length=1000)
    device_description: str | None = Field(max_length=200)
    note: str = Field(max_length=1000)

    _clock = field_validator("start_at", "verified_until_at", mode="before")(canonical_clock)
    _note = field_validator("continuity_basis_note")(meaningful_note)

    @field_validator("ended_at", mode="before")
    @classmethod
    def optional_clock(cls, value):
        return canonical_clock(value) if value is not None else None

    @model_validator(mode="after")
    def actual_interval(self):
        if explicit_utc(self.start_at) >= explicit_utc(self.verified_until_at):
            raise ValueError("呼吸支持实际开始须早于已核实结束时刻")
        if self.ended_at is not None and self.ended_at != self.verified_until_at:
            raise ValueError("实际停止时刻须等于本段已核实结束时刻")
        if self.continuity_confirmed != (self.continuity_basis_note is not None):
            raise ValueError("连续性确认须有明确依据；未确认时依据保留null")
        return self


class LabReference(StrictPayload):
    lab_source_id: str
    expected_content_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    _id = field_validator("lab_source_id")(canonical_uuid)


class PointReference(StrictPayload):
    observation_id: str
    expected_content_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    _id = field_validator("observation_id")(canonical_uuid)


class SupportReference(StrictPayload):
    support_source_id: str
    expected_content_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    _id = field_validator("support_source_id")(canonical_uuid)


class ArterialPairPayload(StrictPayload):
    pao2: LabReference
    fio2: PointReference
    support: SupportReference
    arterial_sample_confirmed: bool
    same_sampling_state_confirmed: bool
    fio2_applicability_confirmed: bool
    review_note: str = Field(min_length=20, max_length=1000)
    note: str = Field(max_length=1000)
    _note = field_validator("review_note")(meaningful_note)


def prepare_map(db, patient_id, admission_id, payload, recorded_at):
    typed = MapPayload.model_validate(payload)
    event_at = explicit_utc(typed.observed_at)
    if event_at > recorded_at:
        raise HTTPException(422, "MAP实际测量不得晚于原资料登记")
    return event_at, {}


def prepare_respiratory_support(db, patient_id, admission_id, payload, recorded_at):
    typed = RespiratorySupportPayload.model_validate(payload)
    if explicit_utc(typed.verified_until_at) > recorded_at:
        raise HTTPException(422, "呼吸支持已核实区间不得延伸到登记以后")
    return explicit_utc(typed.start_at), {}


def _same_original(source, reference, patient_id, admission_id, clock_fields, recorded_at):
    if source["patient_id"] != patient_id or source["admission_id"] != admission_id:
        raise HTTPException(409, "动脉配对各来源必须属于同一原患者和原住院")
    if source["content_hash"] != reference["expected_content_hash"]:
        raise HTTPException(409, "动脉配对原来源摘要已变化")
    if source.get("eligible") is False or source.get("status") != "active":
        raise HTTPException(409, "动脉配对原来源不再有效")
    if any(explicit_utc(source[name]) > recorded_at for name in clock_fields):
        raise HTTPException(409, "动脉配对原来源实际时刻或可用时刻晚于本次登记")


def prepare_arterial_pair(db, patient_id, admission_id, payload, recorded_at):
    from app.inpatient_laboratory import source_current as lab_current
    from app.inpatient_observations import source_current as point_current
    from app.inpatient_support_common import source_current as support_current
    from app.models import InpatientLabSource, InpatientObservation

    typed = ArterialPairPayload.model_validate(payload).model_dump(mode="json")
    pao2 = lab_current(db, db.query(InpatientLabSource).filter_by(lab_source_id=typed["pao2"]["lab_source_id"]).populate_existing().one_or_none())
    fio2 = point_current(db, db.query(InpatientObservation).filter_by(observation_id=typed["fio2"]["observation_id"]).populate_existing().one_or_none())
    support_row = db.query(InpatientRespiratorySource).filter_by(support_source_id=typed["support"]["support_source_id"]).populate_existing().one_or_none()
    support = support_current(db, support_row, "respiratory_support")
    _same_original(pao2, typed["pao2"], patient_id, admission_id, ("collected_at_utc", "registered_at", "available_at"), recorded_at)
    _same_original(fio2, typed["fio2"], patient_id, admission_id, ("observed_at", "recorded_at"), recorded_at)
    _same_original(support, typed["support"], patient_id, admission_id, ("event_at", "recorded_at"), recorded_at)
    if pao2["snapshot"]["mapping"]["analyte_key"] != "arterial_oxygen_partial_pressure":
        raise HTTPException(409, "PaO2来源须经现行发布映射明确为动脉氧分压")
    measurement = fio2["payload"]["measurements"].get("fio2")
    if measurement is None or measurement["unit"] != "%":
        raise HTTPException(409, "FiO2须选择明确保留原百分比单位的原点测；不得用流量或默认值代替")
    sampled_at = explicit_utc(pao2["collected_at_utc"])
    interval = support["payload"]
    # Stopped support is [start, end); ongoing support is verified through its inclusive endpoint.
    start, end = explicit_utc(interval["start_at"]), explicit_utc(interval["verified_until_at"])
    if sampled_at < start or sampled_at > end or (interval["ended_at"] is not None and sampled_at == end):
        raise HTTPException(409, "原PaO2实际采样不在所选呼吸支持已核实区间；停止端点不属于原段")
    return sampled_at, {"pao2": pao2, "fio2": fio2, "support": support}


MAP_DEFINITION = SourceDefinition("map", "inpatient_map_v1", "map_observation", InpatientMapSource, MapPayload, False, prepare_map)
RESPIRATORY_DEFINITION = SourceDefinition(
    "respiratory_support", "respiratory_support_v1", "respiratory_support", InpatientRespiratorySource, RespiratorySupportPayload, False, prepare_respiratory_support
)
ARTERIAL_PAIR_DEFINITION = SourceDefinition("arterial_pair", "arterial_pair_review_v1", "arterial_pair", InpatientArterialPairSource, ArterialPairPayload, True, prepare_arterial_pair)
DEFINITIONS = [MAP_DEFINITION, RESPIRATORY_DEFINITION, ARTERIAL_PAIR_DEFINITION]
