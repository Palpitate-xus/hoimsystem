"""Scoped rating facts; unreviewed patient comment text never enters an AI snapshot."""

from sqlalchemy import and_, case, func

from app.ai.review_curation import published_feedback_sources, verified_review_query
from app.models import Review


def attach_feedback_sources(db, departments, start, end, bundle, add):
    query = verified_review_query(db, departments, start, end)
    valid_score = case((Review.score.between(1, 5), Review.score), else_=None)
    with_comment = case((and_(Review.comment.is_not(None), func.length(func.trim(Review.comment)) > 0), 1), else_=0)
    invalid_score = case((and_(Review.score.is_not(None), ~Review.score.between(1, 5)), 1), else_=0)
    summary = query.with_entities(
        func.count(Review.review_id), func.count(func.distinct(Review.visit_id)), func.count(valid_score), func.avg(valid_score), func.sum(with_comment), func.sum(invalid_score)
    ).one()
    add(
        "feedback_rating_summary",
        "可核实就诊关联的评价评分汇总",
        {
            "record_count": summary[0],
            "distinct_recorded_visit_count": summary[1],
            "valid_score_record_count": summary[2],
            "mean_recorded_score": summary[3],
            "withheld_comment_record_count": summary[4] if summary[0] else 0,
            "out_of_range_score_record_count": summary[5] if summary[0] else 0,
            "definition_note": "仅同患者、同医生、关联可核实的就诊评价；有挂号关联时使用其科室，无挂号关联时使用医生当前科室，后者不代表历史科室。评分原范围1至5，缺失或越界不进入均值。计数是评价行和关联就诊数，不是独立患者数、总体满意率或全体就诊分母；原评论不发送给模型，已审核片段另列",
        },
    )
    day = func.date(Review.review_time)
    rows = query.with_entities(day, valid_score, func.count(Review.review_id), func.sum(with_comment), func.sum(invalid_score)).group_by(day, valid_score).order_by(day, valid_score).limit(1001).all()
    add(
        "feedback_rating_series",
        "原评分按日期与有效分值分组",
        {
            "columns": ["date", "recorded_score", "record_count", "withheld_comment_record_count", "out_of_range_score_record_count"],
            "rows": [list(row) for row in rows[:1000]],
            "truncated": len(rows) > 1000,
            "definition_note": "未知评分桶包括缺失和越界，并单列越界数量；未记录日期不补零。评分汇总不读取评论，不反推出投诉主题、就诊满意率或因果结论。日分组已截断时，整体汇总仍按整个所选范围独立计算",
        },
    )
    if len(rows) > 1000:
        bundle.data["truncated_sources"].append({"source": "feedback_rating_series", "limit": 1000, "note": "评分日分组已截断，请缩小范围"})
    excerpts, stale, truncated = published_feedback_sources(db, departments, start, end)
    bundle.data["reviewed_feedback_excerpts"] = {
        "items": [add("feedback-excerpt:" + item["excerpt_ref"], "已审核脱敏评价片段", item, store=False) for item in excerpts],
        "included_excerpt_count": len(excerpts),
        "excluded_changed_source_count": stale,
        "truncated": truncated,
        "scope_note": "仅所选科室和原评价日期范围内、原文与就诊关联仍匹配的已发布审核版本。最多核对60条最新发布候选后纳入20条，非全部评论或完整投诉工单；未审核原文不发送，不以审核代替事实调查",
    }
    if not excerpts:
        bundle.data["missing_data"].append("现有评分并非完整投诉工单；未取得本次范围内当前有效的逐条审核脱敏版本，未提供原文，不能生成投诉主题聚类或典型原文引述")
    if stale:
        bundle.data["missing_data"].append("部分已发布摘录的原评价、关联或文本校验已失效，已排除，不能据缺失断言不存在相关反馈")
    if truncated:
        bundle.data["truncated_sources"].append({"source": "reviewed_feedback_excerpts", "limit": 20, "note": "已审核片段候选或纳入清单已截断，仅描述所载片段，不外推总体主题占比"})
    bundle.data["missing_data"].append("缺少全体可评价就诊分母、应答率、经核实的投诉事实与流程调查；所载评分和审核片段不代表全体患者满意度，不用于推定因果或个人责任")
