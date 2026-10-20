"""Recorded ADR decisions are separate from drug allergy and legacy status ambiguity."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class AdrStatusWrite(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    reaction_id: int = Field(ge=1, strict=True)
    status: int = Field(ge=1, le=2, strict=True)
    resolution: Literal["confirmed", "processed", "excluded"] | None = None
    note: str = Field(default="", max_length=1000)


def describe_adr_status(row):
    if row.status == 0 and row.status_resolution is None:
        state = "pending"
    elif row.status == 1 and row.status_resolution in {None, "confirmed"}:
        state = "recorded_confirmation"
    elif row.status == 2 and row.status_resolution in {"processed", "excluded"}:
        state = row.status_resolution
    elif row.status == 2 and row.status_resolution is None:
        state = "legacy_ambiguous"
    else:
        state = "unknown"
    return {
        "recorded_state": state,
        "status_text": {"pending": "待评估", "recorded_confirmation": "已记录确认ADR", "processed": "已处理", "excluded": "已记录排除ADR", "legacy_ambiguous": "历史含义待核实"}.get(
            state, "状态待核实"
        ),
        "legacy_status": row.status,
        "status_resolution": row.status_resolution,
        "resolution_note": row.resolution_note,
        "status_reviewed_at": row.status_reviewed_at,
        "review_identity_recorded": row.status_reviewed_by is not None and row.status_reviewed_at is not None,
        "definition_note": "原表状态2曾用于已处理和已排除，未登记明确结果时不推测。确认或排除为原系统人工处理记录，不等于已证实药物因果关系；ADR与药物过敏分别记录，不自动写入过敏史",
    }
