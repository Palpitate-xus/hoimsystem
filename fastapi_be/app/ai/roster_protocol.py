"""Strict version-10 roster response, with original native proof at the top level."""

from typing import Literal

from pydantic import Field, field_validator

from app.ai.roster_contract import RosterAnalysis, StrictModel
from app.ai.schemas import GenerationResult


class RosterUsage(StrictModel):
    input_tokens: int = Field(ge=0, le=2000000)
    output_tokens: int = Field(ge=0, le=2000000)


class RosterEnvelope(StrictModel):
    schema_version: Literal["10"]
    feature_key: Literal["roster_optimization"]
    model_version: str = Field(pattern=r"^roster:[a-f0-9]{64}$")
    handled: Literal[True]
    result: GenerationResult
    roster_analysis: RosterAnalysis
    usage: RosterUsage

    @field_validator("handled", mode="before")
    @classmethod
    def actual_boolean(cls, value):
        if value is not True:
            raise ValueError("排班处理回执须为实际布尔true")
        return value


def parse_roster_envelope(value, model_version):
    envelope = RosterEnvelope.model_validate(value)
    if envelope.model_version != model_version:
        raise ValueError("排班实际模型版本与登记版本不符")
    return (
        {**envelope.result.model_dump(mode="json"), "roster_analysis": envelope.roster_analysis.model_dump(mode="json")},
        envelope.usage.input_tokens,
        envelope.usage.output_tokens,
    )
