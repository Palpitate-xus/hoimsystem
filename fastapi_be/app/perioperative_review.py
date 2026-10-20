"""Expose the existing perioperative statistics window without presenting it as a universal guideline."""

import datetime


def existing_timing_rule() -> dict:
    return {
        "rule_id": "perioperative-existing-window",
        "version": "legacy-30-120-v1",
        "lower_minutes": 30,
        "upper_minutes": 120,
        "reference_field": "SurgerySchedule.start_time",
        "label": "按手术开始记录计算的既有30至120分钟统计窗口",
        "scope_note": "院内既有统计口径；手术开始记录不自动等同于独立切皮时刻，临床适用性需核对已审核规范与具体药物",
    }


def assess_existing_timing(administered_time: datetime.datetime | None, start_time: datetime.datetime | None) -> dict:
    """Calculate the same interval and inclusive bounds used by the existing report."""
    if not administered_time or not start_time:
        return {"status": "not_evaluated", "minutes_before_start": None, "within_existing_window": None, "reason": "缺少实际给药时间或手术开始记录"}
    try:
        delta = start_time - administered_time
    except TypeError:
        return {"status": "not_evaluated", "minutes_before_start": None, "within_existing_window": None, "reason": "原始时间时区格式不一致，需人工核对"}
    minutes = delta.total_seconds() / 60
    return {
        "status": "evaluated",
        "minutes_before_start": minutes,
        "within_existing_window": datetime.timedelta(minutes=30) <= delta <= datetime.timedelta(minutes=120),
        "classification": "earlier_than_window" if minutes > 120 else "later_than_window" if minutes < 30 else "within_window",
        "clinical_appropriateness": None,
    }
