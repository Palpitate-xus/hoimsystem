"""Scoped rating facts; unreviewed patient comment text never enters an AI snapshot."""

import datetime

from sqlalchemy import and_, case, func, or_

from app.models import Doctor, MedicalRecord, Registration, Review


def attach_feedback_sources(db, departments, start, end, bundle, add):
    department = case((MedicalRecord.registration_uuid.is_not(None), Registration.department_id), else_=Doctor.department_id)
    query = (
        db.query(Review)
        .join(MedicalRecord, MedicalRecord.medical_record_id == Review.visit_id)
        .join(Doctor, Doctor.doctor_id == MedicalRecord.doctor_id)
        .outerjoin(Registration, Registration.registration_uuid == MedicalRecord.registration_uuid)
        .filter(
            Review.patient_id == MedicalRecord.patient_id,
            Review.doctor_id == MedicalRecord.doctor_id,
            or_(
                MedicalRecord.registration_uuid.is_(None),
                and_(Registration.patient_id == MedicalRecord.patient_id, Registration.doctor_id == MedicalRecord.doctor_id),
            ),
            Review.review_time >= datetime.datetime.combine(start, datetime.time.min),
            Review.review_time < datetime.datetime.combine(end + datetime.timedelta(days=1), datetime.time.min),
        )
    )
    if departments is not None:
        query = query.filter(department.in_(departments))
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
            "definition_note": "仅同患者、同医生、关联可核实的就诊评价；有挂号关联时使用其科室，无挂号关联时使用医生当前科室，后者不代表历史科室。评分原范围1至5，缺失或越界不进入均值。计数是评价行和关联就诊数，不是独立患者数、总体满意率或全体就诊分母；原评论未读取、未发送",
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
            "definition_note": "未知评分桶包括缺失和越界，并单列越界数量；未记录日期不补零。汇总不读取评论，不反推出投诉主题、就诊满意率或因果结论。日分组已截断时，整体汇总仍按整个所选范围独立计算",
        },
    )
    if len(rows) > 1000:
        bundle.data["truncated_sources"].append({"source": "feedback_rating_series", "limit": 1000, "note": "评分日分组已截断，请缩小范围"})
    bundle.data["missing_data"].extend(
        [
            "现有来源为就诊评价评分，并非完整投诉工单；原评论可能含直接或间接身份线索，未取得逐条审核的脱敏版本，未向模型提供原文，不能生成投诉主题聚类或典型原文引述",
            "缺少全体可评价就诊分母、应答率、经核实的投诉事实与流程调查；仅可描述已记录评分分布，不能代表全体患者满意度或认定责任",
        ]
    )
