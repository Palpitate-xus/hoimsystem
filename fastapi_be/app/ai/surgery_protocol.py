"""Strict schema12 receipts with a separate, complete surgery optimization proof."""

from typing import Literal

from pydantic import Field, model_validator

from app.ai.schemas import GenerationResult
from app.ai.surgery_contract import StrictModel, SurgeryAnalysis


class SurgeryGenerationResult(GenerationResult):
    surgery_analysis: SurgeryAnalysis


class SurgeryExplanation(GenerationResult):
    @model_validator(mode="before")
    @classmethod
    def four_explicit_fields(cls, value):
        if not isinstance(value, dict) or set(value) != {"summary", "sections", "warnings", "missing_data"}:
            raise ValueError("Surgery explanation must explicitly contain four fixed fields")
        return value


class SurgeryUsage(StrictModel):
    input_tokens: int = Field(ge=0, le=2000000)
    output_tokens: int = Field(ge=0, le=2000000)


class SurgeryEnvelope(StrictModel):
    schema_version: Literal["12"]
    feature_key: Literal["surgery_scheduling"]
    model_version: str = Field(pattern=r"^surgery:[a-f0-9]{64}$")
    handled: Literal[True]
    result: SurgeryExplanation
    surgery_analysis: SurgeryAnalysis
    usage: SurgeryUsage


def parse_surgery_envelope(value, model_version):
    envelope = SurgeryEnvelope.model_validate(value)
    if envelope.model_version != model_version:
        raise ValueError("手术排程实际模型版本与登记版本不符")
    return (
        {**envelope.result.model_dump(mode="json"), "surgery_analysis": envelope.surgery_analysis.model_dump(mode="json")},
        envelope.usage.input_tokens,
        envelope.usage.output_tokens,
    )
