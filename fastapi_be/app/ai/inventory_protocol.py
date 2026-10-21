"""Strict schema14 receipt with the complete finite-candidate comparison proof."""

from typing import Literal

from pydantic import Field, model_validator

from app.ai.inventory_contract import MAX_CANDIDATES, InventoryAnalysis, StrictModel
from app.ai.schemas import GenerationResult


class InventoryText(GenerationResult):
    # Every declared unknown candidate and the candidate-set gap must survive.
    missing_data: list[str] = Field(default_factory=list, max_length=MAX_CANDIDATES + 1)


class InventoryGenerationResult(InventoryText):
    inventory_analysis: InventoryAnalysis


class InventoryExplanation(InventoryText):
    @model_validator(mode="before")
    @classmethod
    def explicit_explanation(cls, value):
        if not isinstance(value, dict) or set(value) != {"summary", "sections", "warnings", "missing_data"}:
            raise ValueError("Inventory explanation must explicitly contain four fixed fields")
        return value


class InventoryUsage(StrictModel):
    input_tokens: int = Field(ge=0, le=2000000)
    output_tokens: int = Field(ge=0, le=2000000)


class InventoryEnvelope(StrictModel):
    schema_version: Literal["14"]
    feature_key: Literal["inventory_optimization"]
    model_version: str = Field(pattern=r"^inventory:[a-f0-9]{64}$")
    handled: Literal[True]
    result: InventoryExplanation
    inventory_analysis: InventoryAnalysis
    usage: InventoryUsage


def parse_inventory_envelope(value, model_version):
    envelope = InventoryEnvelope.model_validate(value)
    if envelope.model_version != model_version:
        raise ValueError("库存候选方案比较实际模型版本与登记版本不符")
    return (
        {**envelope.result.model_dump(mode="json"), "inventory_analysis": envelope.inventory_analysis.model_dump(mode="json")},
        envelope.usage.input_tokens,
        envelope.usage.output_tokens,
    )
