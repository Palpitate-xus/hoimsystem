"""The independent SOFA service has one strict daily/change response envelope."""

from typing import Literal

from pydantic import Field, field_validator, model_validator

from app.ai.schemas import GenerationResult
from app.ai.sofa_contract import SofaAnalysis, SofaChangeAnalysis, StrictModel


class SofaUsage(StrictModel):
    input_tokens: int = Field(ge=0, le=2000000)
    output_tokens: int = Field(ge=0, le=2000000)


class SofaEnvelope(StrictModel):
    schema_version: Literal["9"]
    feature_key: Literal["sepsis_risk"]
    model_version: str = Field(min_length=1, max_length=160)
    handled: Literal[True]
    result: GenerationResult
    sofa_analysis: SofaAnalysis | None = None
    sofa_change_analysis: SofaChangeAnalysis | None = None
    usage: SofaUsage

    @field_validator("handled", mode="before")
    @classmethod
    def actual_handled(cls, value):
        if value is not True:
            raise ValueError("SOFA处理回执须为实际布尔true")
        return value

    @model_validator(mode="before")
    @classmethod
    def one_native_key(cls, value):
        if not isinstance(value, dict) or len({"sofa_analysis", "sofa_change_analysis"} & value.keys()) != 1:
            raise ValueError("SOFA顶层须且只能含一个实际native结果字段")
        key = next(iter({"sofa_analysis", "sofa_change_analysis"} & value.keys()))
        if value[key] is None:
            raise ValueError("SOFA顶层结果不可为空")
        return value


def parse_sofa_envelope(value, model_version):
    envelope = SofaEnvelope.model_validate(value)
    if envelope.model_version != model_version:
        raise ValueError("SOFA实际模型版本与登记版本不符")
    key = "sofa_analysis" if envelope.sofa_analysis is not None else "sofa_change_analysis"
    output = {**envelope.result.model_dump(mode="json"), key: getattr(envelope, key).model_dump(mode="json")}
    return output, envelope.usage.input_tokens, envelope.usage.output_tokens
