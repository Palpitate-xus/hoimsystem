"""Read recorded surgical resources without inventing capacity, qualifications or estimates."""

from sqlalchemy import case, or_

from app.ai.roster_sources import planning_window
from app.models import Admission, Doctor, SurgeryApplication, SurgerySchedule, User


def _applications(db, departments):
    application = SurgeryApplication
    department = case((application.admission_id.is_not(None), Admission.department_id), else_=Doctor.department_id)
    query = (
        db.query(application, department.label("department_id"))
        .outerjoin(Admission, Admission.admission_id == application.admission_id)
        .outerjoin(Doctor, Doctor.doctor_id == application.doctor_id)
        .filter(or_(application.admission_id.is_(None), Admission.patient_id == application.patient_id))
    )
    if departments is not None:
        query = query.filter(department.in_(departments))
    return query


def _assistants(value):
    tokens = (value or "").split(",")
    ids = {int(token.strip()) for token in tokens if token.strip().isascii() and token.strip().isdigit() and int(token.strip()) > 0}
    malformed = any(token.strip() and (not token.strip().isascii() or not token.strip().isdigit() or int(token.strip()) < 1) for token in tokens)
    return ids, malformed


def _resources(db, rows):
    doctor_ids, user_ids, malformed = set(), set(), 0
    for schedule, _, _ in rows:
        assistants, invalid = _assistants(schedule.assistant_ids)
        malformed += int(invalid)
        doctor_ids.update(assistants | {value for value in (schedule.surgeon_id, schedule.anesthesiologist_id) if value is not None})
        user_ids.update(value for value in (schedule.scrub_nurse_id, schedule.circulating_nurse_id) if value is not None)
    doctors = {row.doctor_id: row.user_id for row in db.query(Doctor).filter(Doctor.doctor_id.in_(doctor_ids)).all()}
    user_ids.update(value for value in doctors.values() if value is not None)
    users = {row[0] for row in db.query(User.user_id).filter(User.user_id.in_(user_ids)).all()}
    result = {}
    unknown = set()
    for schedule, _, _ in rows:
        resources = set()
        if schedule.operating_room and schedule.operating_room.strip():
            resources.add("room:" + schedule.operating_room.strip())
        assistants, _ = _assistants(schedule.assistant_ids)
        for doctor_id in assistants | {value for value in (schedule.surgeon_id, schedule.anesthesiologist_id) if value is not None}:
            if doctor_id not in doctors:
                unknown.add(("doctor", doctor_id))
                continue
            user_id = doctors[doctor_id]
            resources.add("user:" + str(user_id) if user_id in users else "doctor:" + str(doctor_id))
        for user_id in (schedule.scrub_nurse_id, schedule.circulating_nurse_id):
            if user_id is None:
                continue
            if user_id not in users:
                unknown.add(("user", user_id))
                continue
            resources.add("user:" + str(user_id))
        result[schedule.schedule_id] = resources
    return result, malformed, len(unknown)


def attach_surgical_resources(db, departments, start, end, values, bundle, add):
    planning_start, planning_end = planning_window(values)
    base = _applications(db, departments)
    applications = (
        base.filter(or_(SurgeryApplication.scheduled_date.between(planning_start, planning_end), SurgeryApplication.scheduled_date.is_(None)))
        .order_by(SurgeryApplication.scheduled_date, SurgeryApplication.application_id)
        .limit(201)
        .all()
    )
    add(
        "surgical_applications",
        "计划区间手术申请与未定日期申请",
        {
            "planning_window": [str(planning_start), str(planning_end)],
            "columns": ["application_id", "department_id", "surgery_name", "surgery_code", "surgery_level", "anesthesia_type", "scheduled_date", "application_status"],
            "rows": [
                [row.application_id, department, row.surgery_name, row.surgery_code, row.surgery_level, row.anesthesia_type, row.scheduled_date, row.status] for row, department in applications[:200]
            ],
            "truncated": len(applications) > 200,
            "definition_note": "科室按同患者的关联住院确定；无住院关联时采用申请医生科室。状态0待审批、1已批准、2已排台、3已完成、4已取消。未定日期需先确认手术时间。",
        },
    )

    def schedules(first, last):
        return (
            base.add_columns(SurgerySchedule)
            .join(SurgerySchedule, SurgerySchedule.application_id == SurgeryApplication.application_id)
            .filter(SurgerySchedule.patient_id == SurgeryApplication.patient_id, SurgerySchedule.surgery_date.between(first, last))
            .order_by(SurgerySchedule.surgery_date, SurgerySchedule.schedule_id)
            .limit(201)
            .all()
        )

    planned = [(schedule, application, department) for application, department, schedule in schedules(planning_start, planning_end)]
    resources, malformed, unknown_staff = _resources(db, planned[:200])
    add(
        "surgical_schedules",
        "计划区间已记录排台与人员",
        {
            "planning_window": [str(planning_start), str(planning_end)],
            "columns": [
                "schedule_id",
                "application_id",
                "department_id",
                "operating_room",
                "surgery_date",
                "recorded_start",
                "recorded_end",
                "surgeon_id",
                "anesthesiologist_id",
                "assistant_doctor_ids",
                "scrub_nurse_id",
                "circulating_nurse_id",
                "schedule_status",
                "application_status",
            ],
            "rows": [
                [
                    row.schedule_id,
                    row.application_id,
                    department,
                    row.operating_room,
                    row.surgery_date,
                    row.start_time,
                    row.end_time,
                    row.surgeon_id,
                    row.anesthesiologist_id,
                    sorted(_assistants(row.assistant_ids)[0]),
                    row.scrub_nurse_id,
                    row.circulating_nurse_id,
                    row.status,
                    application.status,
                ]
                for row, application, department in planned[:200]
            ],
            "truncated": len(planned) > 200,
            "malformed_assistant_lists": malformed,
            "unresolved_staff_references": unknown_staff,
            "definition_note": "状态0待手术、1手术中、2已完成、3已取消。起止时间保留原字段，请核对预约时段、人员资质和资源可用时间。",
        },
    )
    eligible = [
        row
        for row, application, _ in planned[:200]
        if row.status in {0, 1}
        and application.status in {1, 2}
        and row.start_time is not None
        and row.end_time is not None
        and row.end_time > row.start_time
        and row.start_time.date() == row.surgery_date
    ]
    conflicts = []
    for index, left in enumerate(eligible):
        for right in eligible[index + 1 :]:
            shared = sorted(resources[left.schedule_id] & resources[right.schedule_id])
            if shared and left.start_time < right.end_time and right.start_time < left.end_time:
                conflicts.append([left.schedule_id, right.schedule_id, shared])
    add(
        "surgical_recorded_overlaps",
        "已记录区间的同资源交叠线索",
        {
            "columns": ["left_schedule_id", "right_schedule_id", "shared_resource_references"],
            "rows": conflicts[:100],
            "checked_intervals": len(eligible),
            "uncheckable_or_inactive_schedules": min(len(planned), 200) - len(eligible),
            "truncated": len(conflicts) > 100,
            "definition_note": "核对已批准申请和活动排台中起止完整、时间正序的区间；跨医生和护士共用账号时按同一人员检查。未解析关联和超出访问范围的记录单列为缺项，时区未知时保留原时间。",
        },
    )
    historical_rows = schedules(start, end)
    historical = [(application, department, schedule) for application, department, schedule in historical_rows[:200] if schedule.status == 2]
    add(
        "surgical_completed_intervals",
        "历史范围已完成排台的原始起止",
        {
            "columns": ["schedule_id", "surgery_code", "department_id", "surgery_date", "recorded_start", "recorded_end"],
            "rows": [[row.schedule_id, application.surgery_code, department, row.surgery_date, row.start_time, row.end_time] for application, department, row in historical[:200]],
            "truncated": len(historical_rows) > 200,
            "definition_note": "仅原排台状态为已完成的起止，不填补缺失、异常区间，不等同切皮至缝合时长或已验证预测。历史排台先按日期与标识限200行再取已完成记录，可能不完整",
        },
    )
    if len(applications) > 200 or len(planned) > 200 or len(historical_rows) > 200 or len(conflicts) > 100:
        bundle.data["truncated_sources"].append({"source": "surgical_resources", "limit": 200, "note": "申请、排台或交叠线索已截断，不能宣称完整可行性核验"})
    bundle.data["missing_data"].extend(
        [
            "尚无独立手术室与设备资源目录、可用时段、人员资质/休假/工时、清台与转运间隔及已验证手术时长估计；仅凭这些记录不能确认候选排台可行",
            "候选范围还包含未审批、已完成、取消或未定日期原记录，必须逐条按状态和真实资源约束复核；不发布排台，不修改申请或执行状态",
        ]
    )
    if malformed or unknown_staff:
        bundle.data["missing_data"].append("助手清单或人员关联存在无法解析的原记录，交叠核查不完整")
