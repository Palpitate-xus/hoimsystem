"""Typed laboratory values that retain units, collection time and parent report review."""

import datetime
from decimal import Decimal
from typing import Literal

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import Numeric, String
from sqlalchemy.orm import Session
from sqlalchemy.types import TypeDecorator


class ObservationDecimal(TypeDecorator):
    """Keep exact decimal values in SQLite development and native PostgreSQL NUMERIC."""

    impl = Numeric(24, 8)
    cache_ok = True

    def load_dialect_impl(self, dialect):
        return dialect.type_descriptor(String(32) if dialect.name == "sqlite" else Numeric(24, 8))

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        value = Decimal(str(value))
        return format(value, "f") if dialect.name == "sqlite" else value

    def process_result_value(self, value, dialect):
        return Decimal(str(value)) if value is not None else None


class LabObservationInput(BaseModel):
    """A numeric or qualitative result with explicit provenance and no inferred units."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    code: str = Field(min_length=1, max_length=80)
    code_system: str = Field(default="local", min_length=1, max_length=80)
    display: str = Field(min_length=1, max_length=120)
    value_num: Decimal | None = Field(default=None, max_digits=24, decimal_places=8, allow_inf_nan=False)
    value_text: str | None = Field(default=None, min_length=1, max_length=500)
    unit: str | None = Field(default=None, min_length=1, max_length=40)
    reference_low: Decimal | None = Field(default=None, max_digits=24, decimal_places=8, allow_inf_nan=False)
    reference_high: Decimal | None = Field(default=None, max_digits=24, decimal_places=8, allow_inf_nan=False)
    reference_text: str | None = Field(default=None, max_length=200)
    collected_at: datetime.datetime
    method: str = Field(default="", max_length=100)
    specimen_type: str = Field(default="", max_length=80)
    flag: Literal["unknown", "normal", "high", "low", "critical"] = "unknown"

    @field_validator("collected_at")
    @classmethod
    def require_offset(cls, value: datetime.datetime) -> datetime.datetime:
        """Require an explicit offset so collection times cannot silently shift timezones."""
        if value.tzinfo is None:
            raise ValueError("采样时间必须包含明确时区")
        return value.astimezone(datetime.UTC).replace(tzinfo=None)

    @model_validator(mode="after")
    def validate_result(self):
        """Reject ambiguous values, missing numeric units and reversed reference intervals."""
        if (self.value_num is None) == (self.value_text is None):
            raise ValueError("数值结果和定性结果必须且只能提供一项")
        if self.value_num is not None and not self.unit:
            raise ValueError("数值检验结果必须提供原始单位")
        if self.reference_low is not None and self.reference_high is not None and self.reference_low > self.reference_high:
            raise ValueError("参考范围下限不能高于上限")
        return self


def persist_observations(db: Session, report, observations: list[LabObservationInput]) -> None:
    """Stage all typed values in the same transaction as the original report."""
    from app.models import LabObservation

    if not observations:
        return
    seen = set()
    for item in observations:
        identity = (item.code_system, item.code, item.collected_at, item.method)
        if identity in seen:
            raise HTTPException(422, "同一报告中检验编码、方法和采样时间不能重复")
        seen.add(identity)
    db.flush()
    for item in observations:
        db.add(LabObservation(lab_result_id=report.lab_result_id, **item.model_dump()))


def serialize_observation(item) -> dict:
    """Return exact decimal text, raw units and UTC sample times."""
    fields = ("observation_id", "code", "code_system", "display", "unit", "reference_text", "method", "specimen_type", "flag")
    data = {name: getattr(item, name) for name in fields}
    for name in ("value_num", "reference_low", "reference_high"):
        value = getattr(item, name)
        data[name] = format(value.normalize(), "f") if value is not None else None
    data["value_text"] = item.value_text
    data["collected_at"] = item.collected_at.replace(tzinfo=datetime.UTC).isoformat()
    return data
