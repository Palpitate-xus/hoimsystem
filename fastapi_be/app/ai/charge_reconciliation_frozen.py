"""Closed original provider and validation records for admission-ledger tasks."""

from datetime import datetime
from typing import Literal

from pydantic import Field, field_validator, model_validator

from app.ai.charge_reconciliation_contract import Positive, StrictModel
from app.ai.retry_policy import ProviderRetrySnapshot


class ChargeFrozenProvider(ProviderRetrySnapshot, StrictModel):
    provider_id: Positive
    revision: Positive
    name: str = Field(min_length=1, max_length=80)
    kind: Literal["chat", "responses"]
    api_base: str = Field(min_length=1, max_length=1000)
    model: str = Field(min_length=1, max_length=160)
    timeout_seconds: int = Field(strict=True, ge=3, le=120)
    max_output_tokens: int = Field(strict=True, ge=256, le=16000)
    validation_report: str = Field(max_length=5000)
    temperature: float = Field(ge=0, le=1, allow_inf_nan=False)
    allows_patient_data: Literal[True]
    effective_output_limit: int = Field(strict=True, ge=1, le=16000)

    @model_validator(mode="after")
    def declared_output_limit(self):
        if self.effective_output_limit > self.max_output_tokens:
            raise ValueError("The effective output limit exceeds its actual provider maximum")
        return self


class ChargeFrozenValidation(StrictModel):
    status: Literal["unreviewed", "pilot", "validated", "suspended"]
    note: str = Field(max_length=5000)
    validated_by: Positive | None
    validated_at: str | None
    feature_revision: Positive

    @field_validator("validated_at")
    @classmethod
    def original_naive_utc_clock(cls, value):
        if value is not None:
            parsed = datetime.fromisoformat(value)
            if parsed.tzinfo is not None or str(parsed) != value:
                raise ValueError("The original feature-validation naive-UTC spelling must remain exact")
        return value
