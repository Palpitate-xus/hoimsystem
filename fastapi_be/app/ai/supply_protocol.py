"""Strict schema13 receipt with the complete recorded-quantity forecast proof."""

from typing import Literal

from pydantic import Field, model_validator

from app.ai.schemas import GenerationResult
from app.ai.supply_contract import StrictModel, SupplyAnalysis


class SupplyGenerationResult(GenerationResult):
    supply_analysis: SupplyAnalysis


class SupplyExplanation(GenerationResult):
    @model_validator(mode="before")
    @classmethod
    def explicit_explanation(cls, value):
        if not isinstance(value, dict) or set(value) != {"summary", "sections", "warnings", "missing_data"}:
            raise ValueError("Supply explanation must explicitly contain four fixed fields")
        return value


class SupplyUsage(StrictModel):
    input_tokens: int = Field(ge=0, le=2000000)
    output_tokens: int = Field(ge=0, le=2000000)


class SupplyEnvelope(StrictModel):
    schema_version: Literal["13"]
    feature_key: Literal["supply_forecast"]
    model_version: str = Field(pattern=r"^supply:[a-f0-9]{64}$")
    handled: Literal[True]
    result: SupplyExplanation
    supply_analysis: SupplyAnalysis
    usage: SupplyUsage


def parse_supply_envelope(value, model_version):
    envelope = SupplyEnvelope.model_validate(value)
    if envelope.model_version != model_version:
        raise ValueError("物资预测实际模型版本与登记版本不符")
    return (
        {**envelope.result.model_dump(mode="json"), "supply_analysis": envelope.supply_analysis.model_dump(mode="json")},
        envelope.usage.input_tokens,
        envelope.usage.output_tokens,
    )
