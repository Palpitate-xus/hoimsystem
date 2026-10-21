"""Pure76 bound literal proposals and fixed server explanations, not matrices.

A matching codepoint quote proves literal location, never the proposed clinical
meaning, missingness class, scientific validity or patient-purpose authority.
"""

from typing import Literal

from pydantic import Field, TypeAdapter

from app.ai.research_cohort_contract import SHA, StrictModel
from app.ai.research_variables_draft import VariableDraft, validate_draft
from app.ai.research_variables_fields import LIMITATIONS
from app.ai.research_variables_prompt import VARIABLE_TASK_VERSION
from app.ai.research_variables_task_contract import canonical, digest, validate_source


class VariableExtractionDraft(StrictModel):
    schema_version: Literal["research_variable_task_draft_v1"]
    task_version: Literal[VARIABLE_TASK_VERSION]
    source_id: str = Field(min_length=1, max_length=100)
    source_projection_hash: SHA
    documents_hash: SHA
    instructions_digest: SHA
    literal_draft: VariableDraft


class VariableResultSection(StrictModel):
    title: str = Field(min_length=1, max_length=120)
    content: str = Field(max_length=12000)
    source_ids: list[str] = Field(max_length=30)


class VariableGenerationResult(StrictModel):
    summary: str = Field(min_length=1, max_length=4000)
    sections: list[VariableResultSection] = Field(max_length=30)
    warnings: list[str] = Field(max_length=50)
    missing_data: list[str] = Field(max_length=100)
    research_variable_extraction: VariableExtractionDraft


def bind_draft(value, source, instructions_digest):
    """Only the server fills source/Prompt anchors; models return literal Draft."""
    source = validate_source(source)
    TypeAdapter(SHA).validate_python(instructions_digest, strict=True)
    canonical(value)
    literal = validate_draft(value.model_dump(mode="json") if isinstance(value, VariableDraft) else value, [row.model_dump(mode="json") for row in source.documents])
    bound = VariableExtractionDraft(
        schema_version="research_variable_task_draft_v1",
        task_version=VARIABLE_TASK_VERSION,
        source_id=source.source_id,
        source_projection_hash=digest(source),
        documents_hash=source.documents_hash,
        instructions_digest=instructions_digest,
        literal_draft=literal,
    )
    canonical(bound)
    return bound


def validate_bound_draft(value, source, instructions_digest):
    canonical(value)
    bound = VariableExtractionDraft.model_validate(value)
    expected = bind_draft(bound.literal_draft, source, instructions_digest)
    if bound != expected:
        raise ValueError("The complete original Source, literal proposals or actual instructions digest differ")
    return bound


def result_for_draft(draft, source, instructions_digest):
    source = validate_source(source)
    draft = validate_bound_draft(draft, source, instructions_digest)
    result = VariableGenerationResult(
        summary=f"已生成{len(draft.literal_draft.candidates)}项未核实科研变量原文字面候选；未生成已审核变量矩阵、缺失判定或研究结论。",
        sections=[
            VariableResultSection(title="本次明确资料范围", content="仅使用所选完整批次、明确变量字典、原字段和原记录窗口；未证明资料完整、科学有效或历史当时可得。", source_ids=[source.source_id]),
            VariableResultSection(title="候选审核状态", content="逐字候选、否定和未知保留在独立草稿中；候选分类未核实，未自动保存、选取赢家、生成CSV或发布研究数据。", source_ids=[]),
        ],
        warnings=["逐字区间正确不证明临床含义、缺失机制、变量有效性或研究适用性正确。", "空候选、NULL及未提出字段不表示未测、不适用、正常或不存在；原单位和原无时区钟点未转换。"],
        missing_data=list(LIMITATIONS),
        research_variable_extraction=draft,
    )
    canonical(result)
    return result


def validate_result(value, source, instructions_digest):
    canonical(value)
    result = VariableGenerationResult.model_validate(value)
    expected = result_for_draft(result.research_variable_extraction, source, instructions_digest)
    if result != expected:
        raise ValueError("The fixed server explanation or complete original literal draft changed")
    canonical(result)
    return result
