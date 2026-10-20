"""Recorded hourly demand and scoped periodic schedules, without invented staffing credentials."""

import datetime

from fastapi import HTTPException
from sqlalchemy import Integer, and_, case, cast, extract, func, or_

from app.models import Doctor, DoctorSchedule, Registration, ScheduleChangeRequest


def attach_hourly_demand(db, departments, start, end, bundle, add):
    day = func.date(Registration.time)
    hour = cast(extract("hour", Registration.time), Integer)
    state = case((Registration.status.in_([0, 1, 2, 3]), Registration.status), else_=-1)
    query = db.query(day, hour, state, func.count()).filter(
        Registration.time >= datetime.datetime.combine(start, datetime.time.min), Registration.time < datetime.datetime.combine(end + datetime.timedelta(days=1), datetime.time.min)
    )
    if departments is not None:
        query = query.filter(Registration.department_id.in_(departments))
    rows = query.group_by(day, hour, state).order_by(day.desc(), hour.desc(), state).limit(1001).all()
    add(
        "recorded_hourly_registrations",
        "授权范围挂号原记录小时汇总",
        {
            "columns": ["date", "recorded_hour", "current_record_status", "record_count"],
            "rows": [[str(date), clock, status, count] for date, clock, status, count in sorted(rows[:1000], key=lambda row: (str(row[0]), row[1], row[2]))],
            "truncated": len(rows) > 1000,
            "definition_note": "按数据库原始记录钟点汇总，未提供可靠历史时区时不转换；当前记录状态不回推到过去。无记录小时不补零，不等于已核实到诊需求或完整训练数据",
        },
    )
    if len(rows) > 1000:
        bundle.data["truncated_sources"].append({"source": "recorded_hourly_registrations", "limit": 1000, "note": "小时序列已截断，请缩小范围，不作为完整训练序列"})


def planning_window(values):
    today = datetime.date.today()
    dates = []
    for key, default in (("planning_date_from", today), ("planning_date_to", today + datetime.timedelta(days=13))):
        value = values.get(key)
        if value in (None, ""):
            dates.append(default)
            continue
        try:
            date = datetime.date.fromisoformat(value) if isinstance(value, str) and len(value) == 10 else None
        except ValueError:
            date = None
        if date is None or str(date) != value:
            raise HTTPException(422, "排班计划日期须为 YYYY-MM-DD")
        dates.append(date)
    start, end = dates
    if start < today or start > end or (end - start).days > 30 or end > today + datetime.timedelta(days=366):
        raise HTTPException(422, "排班计划须为未来一年内的正序区间，单次不超过31天")
    return start, end


def attach_roster_sources(db, departments, values, bundle, add):
    start, end = planning_window(values)
    query = db.query(DoctorSchedule, Doctor).join(Doctor)
    if departments is not None:
        query = query.filter(Doctor.department_id.in_(departments))
    rows = query.order_by(DoctorSchedule.schedule_id).limit(201).all()
    add(
        "recorded_schedules",
        "当前周期排班和共享号源",
        {
            "columns": ["schedule_id", "doctor_id", "department_id", "recorded_weekday", "recorded_period", "current_shared_stock", "specialist", "recorded_title"],
            "rows": [
                [schedule.schedule_id, doctor.doctor_id, doctor.department_id, schedule.week, schedule.time, schedule.number, schedule.specialist, doctor.title] for schedule, doctor in rows[:200]
            ],
            "truncated": len(rows) > 200,
            "planning_window": [str(start), str(end)],
            "definition_note": "仅当前周期排班所关联医生，非完整人员清单；档案职称不等于已核验岗位资质，时段编码没有可靠起止钟点时不换算工时。共享号源不是按日期独立的容量，已批加号不重复叠加",
        },
    )
    request = ScheduleChangeRequest
    valid_link = or_(request.schedule_id.is_(None), DoctorSchedule.doctor_id == request.doctor_id)
    query = (
        db.query(request, DoctorSchedule)
        .join(Doctor, request.doctor_id == Doctor.doctor_id)
        .outerjoin(DoctorSchedule, request.schedule_id == DoctorSchedule.schedule_id)
        .filter(request.target_date >= start, request.target_date <= end)
    )
    if departments is not None:
        query = query.filter(Doctor.department_id.in_(departments))
    invalid_count = query.filter(and_(request.schedule_id.is_not(None), or_(DoctorSchedule.schedule_id.is_(None), DoctorSchedule.doctor_id != request.doctor_id))).count()
    rows = query.filter(valid_link).order_by(request.target_date, request.request_id).limit(201).all()
    add(
        "recorded_schedule_changes",
        "计划区间内停诊与加号申请",
        {
            "columns": ["request_id", "doctor_id", "schedule_id", "target_date", "request_type", "extra_slots", "request_status"],
            "rows": [[row.request_id, row.doctor_id, row.schedule_id, row.target_date, row.request_type, row.extra_slots, row.status] for row, _ in rows[:200]],
            "excluded_inconsistent_links": invalid_count,
            "truncated": len(rows) > 200,
            "definition_note": "申请状态0待审批、1已审批、2已拒绝；待审批不作已生效。按既有审批处理口径，已批停诊涉及该医生当日范围。已批加号已影响共享库存，不再次增加；不发送申请理由或个人联系方式",
        },
    )
    bundle.data["missing_data"].append("尚未取得经审核的人员资质、请假可用性、班次实际时长及工时上下限，不得宣称候选排班已满足全部约束")
    if invalid_count:
        bundle.data["missing_data"].append("排班变更存在医生与排班关联不一致，已排除，计划资料不完整")
    if len(rows) > 200 or bundle.data["recorded_schedules"]["truncated"]:
        bundle.data["truncated_sources"].append({"source": "recorded_schedules", "limit": 200, "note": "排班或变更清单未完整纳入，请限定科室"})
