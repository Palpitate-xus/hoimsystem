"""Fixed server explanation plus unreviewed, literal RCA hypotheses only."""

from pydantic import Field

from app.ai import rca_evidence_contract as c
from app.ai.rca_evidence_task_contract import MISSING_DATA


class RcaResultSection(c.StrictModel):
    title: str = Field(min_length=1, max_length=120)
    content: str = Field(max_length=12000)
    source_ids: list[str] = Field(max_length=30)


class RcaEvidenceGenerationResult(c.StrictModel):
    summary: str = Field(min_length=1, max_length=4000)
    sections: list[RcaResultSection] = Field(max_length=30)
    warnings: list[str] = Field(max_length=50)
    missing_data: list[str] = Field(max_length=100)
    rca_evidence_draft: c.RcaEvidenceDraft


def result_for_draft(draft, source, instructions_digest):
    source = c.validate_source(source)
    draft = c.validate_draft(draft, source, instructions_digest)
    result = RcaEvidenceGenerationResult(
        summary=f"已生成{len(draft.hypotheses)}项未核实调查假设；逐字引用核对不认证因果或责任。",
        sections=[
            RcaResultSection(title="本次资料范围", content="仅使用所选事件的有限受审发布稿与人工时间线，未证明调查完整。", source_ids=[source.source_id]),
            RcaResultSection(title="草稿状态", content="候选假设、冲突引文和问题保留在独立草稿中，须逐项调查；未自动保存至原RCA或推进PDCA。", source_ids=[]),
        ],
        warnings=["隐私、原意和来源发布审核不认证因果解释、责任归属、临床适用或整改成效。", "空假设或空问题不表示没有事件促成因素或调查已经完成。"],
        missing_data=list(MISSING_DATA),
        rca_evidence_draft=draft,
    )
    c.canonical(result)
    return result


def validate_result(value, source, instructions_digest):
    result = RcaEvidenceGenerationResult.model_validate(value)
    expected = result_for_draft(result.rca_evidence_draft, source, instructions_digest)
    if result != expected:
        raise ValueError("The fixed server explanation or exact frozen draft has changed")
    c.canonical(result)
    return result
