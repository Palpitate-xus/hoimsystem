"""Deterministic exact rating statistics around unreviewed, partial themes."""

from typing import Annotated

from pydantic import ConfigDict, Field

from app.ai.satisfaction_contract import Count, ScoreStatistics
from app.ai.satisfaction_draft import MAX_BYTES, Closed, SatisfactionEvidenceDraft, canonical_json, validate_draft, validate_source
from app.ai.schemas import GenerationResult

WARNINGS = [
    "模型仅提出部分待人工核实的摘录主题；逐字引文一致不证明主题解释、代表性、因果、总体满意率或医疗责任，未提出主题不表示全部满意。",
    "评价条数不是去重人数、就诊次数或应答次数；有效1–5评分统计与人工摘录主题分别核对，不计算NPS、应答率或投诉处理率。",
    "本功能没有写入评分、评价、投诉工单、收费、编码或任何业务处理结论。",
]
MISSING = [
    "原记录时钟时区未知；NULL或无法解释的时钟独立保留，审核时间字面量不证明其实际发生时间。",
    "人工隐私及原意核查声明不是匿名保证或事实、专业确认；模型不可见原评论、患者或就诊身份。",
    "未提供投诉工单、处理结果、去重就诊分母、总体人群和医疗责任依据；医生当前科室不表示评价当时科室。",
]


class RecordedStatistics(Closed):
    all_member_statistics: ScoreStatistics
    known_period_statistics: ScoreStatistics
    unknown_date_member_count: Count
    unresolved_parent_count: Count
    complete_member_root_count: Count
    selected_excerpt_count: Count
    proposed_theme_count: Annotated[int, Field(strict=True, ge=0, le=64)]


class SatisfactionGenerationResult(GenerationResult):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=False)
    recorded_statistics: RecordedStatistics
    satisfaction_analysis: SatisfactionEvidenceDraft


def _mean(value):
    return "未知（没有有效1–5评分）" if value is None else f"{value['numerator']}/{value['denominator']}"


def result_for_draft(source, draft):
    checked_source = validate_source(source)
    checked_draft = validate_draft(checked_source, draft)
    safe = checked_source["safe_snapshot"]
    statistics = RecordedStatistics(
        all_member_statistics=safe["all_member_statistics"],
        known_period_statistics=safe["known_period_statistics"],
        unknown_date_member_count=safe["unknown_date_member_count"],
        unresolved_parent_count=safe["unresolved_parent_count"],
        complete_member_root_count=len(safe["member_manifest"]),
        selected_excerpt_count=len(safe["selected_excerpts"]),
        proposed_theme_count=len(checked_draft.themes),
    )
    all_rows, known = safe["all_member_statistics"], safe["known_period_statistics"]
    result = SatisfactionGenerationResult(
        summary=f"本次完整保留{all_rows['record_count']}条已记录评价，形成{len(checked_draft.themes)}项待人工复核的部分摘录主题，未作总体或因果结论。",
        sections=[
            {
                "title": "完整记录与原日期缺口",
                "content": f"全部{all_rows['record_count']}条评价、{len(safe['member_manifest'])}个评价及摘录版本根；原日期未知{safe['unknown_date_member_count']}条，实际父链未能核实{safe['unresolved_parent_count']}条。日期范围仅指原存储日历，时区未知。",
                "source_ids": [checked_source["source_id"]],
            },
            {
                "title": "全成员原评分精确统计",
                "content": f"有效1–5评分{all_rows['valid_score_count']}条，NULL评分{all_rows['null_score_count']}条，异常评分{all_rows['invalid_score_count']}条；有效评分精确均分{_mean(all_rows['mean_valid_score'])}。直方图1至5分别为"
                + "、".join(str(all_rows["histogram"][str(score)]) for score in range(1, 6))
                + "条。",
                "source_ids": [checked_source["source_id"]],
            },
            {
                "title": "已知日期属于本期的原评分",
                "content": f"已知日期本期成员{known['record_count']}条，有效1–5评分{known['valid_score_count']}条，NULL评分{known['null_score_count']}条，异常评分{known['invalid_score_count']}条；有效评分精确均分{_mean(known['mean_valid_score'])}，不把未知日期成员强行归入本期。",
                "source_ids": [checked_source["source_id"]],
            },
        ],
        warnings=list(WARNINGS),
        missing_data=list(MISSING),
        recorded_statistics=statistics,
        satisfaction_analysis=checked_draft,
    )
    if len(canonical_json(result.model_dump(mode="json")).encode("utf-8")) > MAX_BYTES:
        raise ValueError("The complete result exceeds its UTF8 storage budget")
    return result


def validate_result(value, source):
    checked = SatisfactionGenerationResult.model_validate(value)
    expected = result_for_draft(source, checked.satisfaction_analysis)
    if checked.model_dump(mode="json") != expected.model_dump(mode="json"):
        raise ValueError("The fixed explanation, exact ratings or complete partial draft differ")
    return checked
