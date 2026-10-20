"""Strict schema11 native response and complete fixed physical-bed forecast proof."""

from typing import Literal

from pydantic import Field

from app.ai.bed_contract import BedAnalysis, StrictModel
from app.ai.schemas import GenerationResult


class BedGenerationResult(GenerationResult):
    bed_analysis: BedAnalysis


class BedUsage(StrictModel):
    input_tokens: int = Field(ge=0, le=2000000)
    output_tokens: int = Field(ge=0, le=2000000)


class BedEnvelope(StrictModel):
    schema_version: Literal["11"]
    feature_key: Literal["bed_forecast"]
    model_version: str = Field(pattern=r"^bed:[a-f0-9]{64}$")
    handled: Literal[True]
    result: GenerationResult
    bed_analysis: BedAnalysis
    usage: BedUsage


def parse_bed_envelope(value, model_version):
    envelope = BedEnvelope.model_validate(value)
    if envelope.model_version != model_version:
        raise ValueError("床位预测实际模型版本与登记版本不符")
    return (
        {**envelope.result.model_dump(mode="json"), "bed_analysis": envelope.bed_analysis.model_dump(mode="json")},
        envelope.usage.input_tokens,
        envelope.usage.output_tokens,
    )
