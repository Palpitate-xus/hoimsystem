"""Real hospital places, read-only routes and current appointment candidates."""

import datetime

from fastapi import HTTPException
from sqlalchemy import or_
from sqlalchemy.orm import selectinload

from app.ai.governance import digest, encode_json
from app.models import Department, Doctor, DoctorSchedule, GuideFaq, NavigationNode, ScheduleChangeRequest

WEEKDAYS = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")
WEEKDAY_ALIASES = {"星期" + suffix: "周" + suffix for suffix in "一二三四五六日"} | {"星期天": "周日"}


def _positive_id(values: dict, key: str) -> int | None:
    value = values.get(key)
    if value is None or value == "":
        return None
    if type(value) is not int or value < 1:
        raise HTTPException(422, "科室、医生、排班及导航节点标识须为正整数")
    return value


def service_options(db, number: int) -> dict:
    if number not in {58, 59}:
        raise HTTPException(422, "该功能不使用院内服务选项")
    departments = db.query(Department).order_by(Department.department_id).limit(201).all()
    data = {"departments": [{"department_id": row.department_id, "name": row.name, "location": row.location} for row in departments[:200]], "truncated": len(departments) > 200}
    if number == 58:
        nodes = db.query(NavigationNode).filter_by(status=1).order_by(NavigationNode.node_id).limit(301).all()
        data["navigation_nodes"] = [{name: getattr(row, name) for name in ("node_id", "name", "floor", "location", "department_id", "campus_id")} for row in nodes[:300]]
        data["truncated"] = data["truncated"] or len(nodes) > 300
    else:
        doctors = db.query(Doctor).filter(Doctor.department_id.is_not(None)).order_by(Doctor.doctor_id).limit(301).all()
        data["doctors"] = [{"doctor_id": row.doctor_id, "name": row.name, "department_id": row.department_id} for row in doctors[:300]]
        data["truncated"] = data["truncated"] or len(doctors) > 300
    return data


def appointment_candidates(db, values: dict, *, today: datetime.date | None = None) -> tuple[dict, list[dict]]:
    today = today or datetime.date.today()
    department_id, doctor_id, schedule_id = (_positive_id(values, key) for key in ("department_id", "doctor_id", "schedule_id"))
    requested = values.get("appointment_date")
    if requested not in (None, ""):
        try:
            requested_date = datetime.date.fromisoformat(requested) if isinstance(requested, str) and len(requested) == 10 else None
        except ValueError:
            requested_date = None
        if requested_date is None or str(requested_date) != requested:
            raise HTTPException(422, "预约日期须为 YYYY-MM-DD")
        if not today < requested_date <= today + datetime.timedelta(days=6):
            raise HTTPException(422, "预约候选范围为明日至第6日；当天就诊请使用原挂号流程")
        dates = [requested_date]
    else:
        dates = [today + datetime.timedelta(days=offset) for offset in range(1, 7)]
    if department_id and db.get(Department, department_id) is None:
        raise HTTPException(422, "所选科室不存在")
    if doctor_id:
        doctor = db.get(Doctor, doctor_id)
        if doctor is None or (department_id and doctor.department_id != department_id):
            raise HTTPException(422, "所选医生与科室不匹配或不存在")
    date_by_week = {WEEKDAYS[date.weekday()]: date for date in dates}
    valid_weeks = set(date_by_week) | {alias for alias, weekday in WEEKDAY_ALIASES.items() if weekday in date_by_week}
    query = db.query(DoctorSchedule).options(selectinload(DoctorSchedule.doctor).selectinload(Doctor.department)).join(Doctor).join(Department)
    query = query.filter(DoctorSchedule.number > 0, DoctorSchedule.week.in_(valid_weeks))
    if department_id:
        query = query.filter(Doctor.department_id == department_id)
    if doctor_id:
        query = query.filter(DoctorSchedule.doctor_id == doctor_id)
    if schedule_id:
        query = query.filter(DoctorSchedule.schedule_id == schedule_id)
    schedules = query.order_by(DoctorSchedule.schedule_id).limit(201).all()
    stops = (
        db.query(ScheduleChangeRequest.doctor_id, ScheduleChangeRequest.target_date)
        .filter(
            ScheduleChangeRequest.doctor_id.in_({row.doctor_id for row in schedules[:200]}),
            ScheduleChangeRequest.target_date.in_(dates),
            ScheduleChangeRequest.status == 1,
            ScheduleChangeRequest.request_type == "stop",
        )
        .distinct()
        .all()
    )
    stopped = set(stops)
    candidates, evidence, excluded_stops = [], [], 0
    for row in schedules[:200]:
        date = date_by_week[WEEKDAY_ALIASES.get(row.week, row.week)]
        if (row.doctor_id, date) in stopped:
            excluded_stops += 1
            continue
        if not row.time or row.specialist not in {0, 1}:
            continue
        item = {
            "schedule_id": row.schedule_id,
            "doctor_id": row.doctor_id,
            "doctor_name": row.doctor.name,
            "department_id": row.doctor.department_id,
            "department_name": row.doctor.department.name,
            "appointment_date": str(date),
            "recorded_period": row.time,
            "specialist": row.specialist,
            "current_shared_stock": row.number,
        }
        item["source_id"] = f"appointment-schedule:{row.schedule_id}:{digest(item)[:16]}"
        candidates.append(item)
        evidence.append({"source_id": item["source_id"], "kind": "hospital_record", "title": "当前排班与共享号源记录", "content": encode_json(item)})
    candidates.sort(key=lambda item: (item["appointment_date"], item["recorded_period"], item["schedule_id"]))
    return {
        "candidates": candidates,
        "business_date": str(today),
        "window_start": str(min(dates)),
        "window_end": str(max(dates)),
        "excluded_approved_stops": excluded_stops,
        "truncated": len(schedules) > 200,
        "missing_data": [] if candidates else ["当前筛选未取得可展示的排班候选；不代表其他时间没有号源"],
        "scope_note": "与现有预约列表相同的明日至第6日窗口；余量来自每条周期排班的共享库存，并非按日期独立存储。已审批加号已计入库存，不重复叠加；已审批停诊按医生当日范围排除。候选不锁号，实际预约须通过原流程重新校验身份、资格、余量及重复预约。时段保留原编码，未推测具体钟点。",
        "changes_written": [],
    }, evidence


def hospital_navigation(db, user, values: dict) -> tuple[dict, list[dict]]:
    start, end = (_positive_id(values, key) for key in ("start_node_id", "end_node_id"))
    findings = {"route": None, "missing_data": [], "scope_note": "仅使用已配置节点、路线和当前启用的院内问答；未建模开放时间、无障碍条件和实时封路，需现场确认", "changes_written": []}
    evidence = []
    if bool(start) != bool(end):
        raise HTTPException(422, "路线核对须同时选择起点和终点")
    if start and end:
        from app.routers.navigation import find_navigation_route

        response = find_navigation_route(start, end, user, db)
        if response.get("code") == 200:
            route = response["data"]
            source_id = "navigation-route:" + digest(route)[:24]
            findings["route"] = {**route, "source_id": source_id}
            evidence.append({"source_id": source_id, "kind": "hospital_record", "title": "院内已配置节点与路线", "content": encode_json(route)})
        else:
            findings["missing_data"].append(response.get("msg") or "未取得已配置路线")
    else:
        findings["missing_data"].append("未选择起终点，本次不提供推测路线")
    question = values.get("question", "")
    rows = []
    if isinstance(question, str) and question.strip():
        terms = list(dict.fromkeys(part for part in question.strip().replace("，", " ").replace("？", " ").split() if len(part) >= 2))[:8]
        if terms:
            query = db.query(GuideFaq).filter(
                GuideFaq.status == 1,
                or_(*[condition for term in terms for condition in (GuideFaq.question.contains(term[:80], autoescape=True), GuideFaq.answer.contains(term[:80], autoescape=True))]),
            )
            rows = query.order_by(GuideFaq.sort_order, GuideFaq.faq_id).limit(9).all()
    findings["hospital_faq"] = []
    for row in rows[:8]:
        item = {"question": row.question, "answer": row.answer, "category": row.category, "update_time": row.update_time}
        item["source_id"] = f"hospital-faq:{row.faq_id}:{digest(item)[:12]}"
        findings["hospital_faq"].append(item)
        evidence.append({"source_id": item["source_id"], "kind": "hospital_record", "title": "当前启用院内问答", "content": encode_json(item)})
    findings["faq_truncated"] = len(rows) > 8
    return findings, evidence
