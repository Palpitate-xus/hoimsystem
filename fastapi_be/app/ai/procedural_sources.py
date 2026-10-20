"""Selected surgery, schedule, prophylaxis and anesthesia facts with verified patient links."""

from fastapi import HTTPException
from sqlalchemy.orm import selectinload

from app.models import Admission, AnesthesiaRecord, PerioperativeAntibiotic, SurgeryApplication, SurgerySchedule


def attach_procedural_sources(db, user, spec, patient, encounter, bundle, add, selected, bounded) -> None:
    if user.user_role == "patient" or spec.number not in {1, 8, 17, 18, 19, 23, 24, 25, 26, 27, 28, 29, 30, 48, 49, 68, 69, 76, 77}:
        return
    application = selected.get("surgery_application_id")
    schedule = selected.get("surgery_schedule_id")
    medication = selected.get("perioperative_id")
    roots = {row.application_id for row in (application, schedule, medication) if row is not None}
    if len(roots) > 1:
        raise HTTPException(422, "所选手术、排台和围术期用药不属于同一手术申请")
    if roots:
        application = db.query(SurgeryApplication).filter(SurgeryApplication.application_id == next(iter(roots)), SurgeryApplication.patient_id == patient.patient_id).first()
        if application is None:
            raise HTTPException(422, "所选手术资料缺少有效的同患者申请关联")
        if encounter is not None and (not isinstance(encounter, Admission) or application.admission_id != encounter.admission_id):
            raise HTTPException(422, "所选手术与本次住院记录不一致")
        query = db.query(SurgeryApplication).filter_by(patient_id=patient.patient_id, application_id=application.application_id)
    elif isinstance(encounter, Admission):
        query = db.query(SurgeryApplication).filter_by(patient_id=patient.patient_id, admission_id=encounter.admission_id)
    else:
        if spec.number in {48, 49}:
            bundle.data["missing_data"].append("未指定手术申请、排台或对应住院，未加载围术期资料")
        return
    applications = bounded(query.order_by(SurgeryApplication.create_time.desc(), SurgeryApplication.application_id), 6, "手术申请", "surgery_application_id", "application_id")
    ids = [row.application_id for row in applications]
    bundle.data["surgery_source_scope"] = {
        "application_ids": ids,
        "encounter_selected": encounter is not None,
        "note": "手术诊断为原记录内容，不自动作为本次已确认诊断；时间沿用原系统记录，未推断独立切皮时刻",
    }
    bundle.data["surgery_applications"] = [
        add(
            "surgery-application:" + row.application_id,
            "手术申请记录",
            {
                "application_id": row.application_id,
                **{
                    name: getattr(row, name)
                    for name in (
                        "admission_id",
                        "surgery_name",
                        "surgery_code",
                        "surgery_level",
                        "anesthesia_type",
                        "scheduled_date",
                        "preop_diagnosis",
                        "surgery_indication",
                        "contraindication",
                        "status",
                        "approve_time",
                    )
                },
                "status_meaning": {0: "待审批", 1: "已批准", 2: "已排台", 3: "已完成", 4: "已取消"}.get(row.status, "未知"),
            },
            row.create_time,
        )
        for row in applications
    ]
    schedules = bounded(
        db.query(SurgerySchedule)
        .filter(SurgerySchedule.patient_id == patient.patient_id, SurgerySchedule.application_id.in_(ids))
        .order_by(SurgerySchedule.create_time.desc(), SurgerySchedule.schedule_id),
        12,
        "手术排台",
        "surgery_schedule_id",
        "schedule_id",
    )
    bundle.data["surgery_schedules"] = [
        add(
            "surgery-schedule:" + row.schedule_id,
            "手术排台与开始记录",
            {
                "schedule_id": row.schedule_id,
                "application_id": row.application_id,
                **{name: getattr(row, name) for name in ("surgery_date", "start_time", "end_time", "status")},
                "status_meaning": {0: "待手术", 1: "手术中", 2: "已完成", 3: "已取消"}.get(row.status, "未知"),
            },
            row.start_time or row.create_time,
        )
        for row in schedules
    ]
    medications = bounded(
        db.query(PerioperativeAntibiotic)
        .options(selectinload(PerioperativeAntibiotic.pharmaceutical))
        .filter(PerioperativeAntibiotic.patient_id == patient.patient_id, PerioperativeAntibiotic.application_id.in_(ids))
        .order_by(PerioperativeAntibiotic.create_time.desc(), PerioperativeAntibiotic.perioperative_id),
        20,
        "围术期用药",
        "perioperative_id",
        "perioperative_id",
    )
    bundle.data["perioperative_antibiotics"] = [
        add(
            "perioperative-medication:" + row.perioperative_id,
            "围术期用药原始记录",
            {
                "perioperative_id": row.perioperative_id,
                "application_id": row.application_id,
                "pharmaceutical_id": row.pharmaceutical_id,
                "pharmaceutical_name": row.pharmaceutical.name if row.pharmaceutical else None,
                "dose_text": row.dose,
                "planned_minutes_before_start": row.timing_minutes,
                "indication": row.indication,
                "status": row.status,
                "status_meaning": {0: "计划用药", 1: "已记录执行", 2: "已取消"}.get(row.status, "未知"),
                "administered_time": row.administered_time,
                "dose_note": "原始用法文本，未进行剂量单位解析或换算",
            },
            row.administered_time or row.create_time,
        )
        for row in medications
    ]
    anesthesia_query = (
        db.query(AnesthesiaRecord)
        .join(SurgerySchedule)
        .filter(AnesthesiaRecord.patient_id == patient.patient_id, SurgerySchedule.patient_id == patient.patient_id, SurgerySchedule.application_id.in_(ids))
    )
    if schedule is not None:
        anesthesia_query = anesthesia_query.filter(AnesthesiaRecord.schedule_id == schedule.schedule_id)
    anesthesia = bounded(anesthesia_query.order_by(AnesthesiaRecord.create_time.desc(), AnesthesiaRecord.record_id), 4, "麻醉记录")
    fields = (
        "schedule_id",
        "enter_time",
        "consciousness",
        "preop_bp",
        "preop_hr",
        "preop_spo2",
        "anesthesia_method",
        "induction_drugs",
        "maintenance_drugs",
        "intraop_bp",
        "intraop_hr",
        "blood_loss",
        "urine_output",
        "fluid_input",
        "extubation_time",
        "leave_time",
        "postop_consciousness",
        "complications",
    )
    bundle.data["anesthesia_records"] = [
        add(
            "anesthesia:" + row.record_id,
            "麻醉工作记录",
            {
                **{name: getattr(row, name) for name in fields},
                "legacy_zero_ambiguous_fields": [name for name in ("blood_loss", "urine_output", "fluid_input") if getattr(row, name) == 0],
                "provenance_note": "旧字段存在默认0，不能据此确认未出血、无尿或未输液；原表未提供独立签署审核状态",
            },
            row.create_time,
        )
        for row in anesthesia
    ]
