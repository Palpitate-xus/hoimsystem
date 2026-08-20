import datetime

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import CLINICAL_ROLES, NURSING_ROLES, User, require_roles
from app.models import (
    Admission,
    AnesthesiaRecord,
    InpatientCharge,
    PerioperativeAntibiotic,
    Pharmaceutical,
    SurgeryApplication,
    SurgerySchedule,
)

router = APIRouter()


def _perioperative_data(item: PerioperativeAntibiotic):
    return {
        "perioperative_id": item.perioperative_id,
        "application_id": item.application_id,
        "patient_id": item.patient_id,
        "patient_name": item.patient.name if item.patient else "",
        "surgery_name": item.application.surgery_name if item.application else "",
        "pharmaceutical_id": item.pharmaceutical_id,
        "pharmaceutical_name": item.pharmaceutical.name if item.pharmaceutical else "",
        "dose": item.dose,
        "timing_minutes": item.timing_minutes,
        "indication": item.indication or "",
        "status": item.status,
        "status_text": {0: "计划用药", 1: "已执行", 2: "已取消"}.get(item.status, ""),
        "administered_time": item.administered_time.strftime("%Y-%m-%d %H:%M:%S") if item.administered_time else "",
        "create_time": item.create_time.strftime("%Y-%m-%d %H:%M:%S") if item.create_time else "",
    }


@router.get("/surgery/perioperative/list")
def get_perioperative_antibiotic_list(application_id: str | None = None, current_user: User = Depends(require_roles(*CLINICAL_ROLES)), db: Session = Depends(get_db)):
    query = db.query(PerioperativeAntibiotic)
    if application_id:
        query = query.filter(PerioperativeAntibiotic.application_id == application_id)
    items = query.order_by(PerioperativeAntibiotic.create_time.desc()).all()
    return {"code": 200, "msg": "success", "data": [_perioperative_data(item) for item in items]}


@router.post("/surgery/perioperative/create")
def create_perioperative_antibiotic(req: dict, current_user: User = Depends(require_roles(*CLINICAL_ROLES)), db: Session = Depends(get_db)):
    application = db.query(SurgeryApplication).filter(SurgeryApplication.application_id == req.get("application_id")).first()
    if not application:
        return {"code": 404, "msg": "手术申请不存在"}
    if application.status not in (1, 2):
        return {"code": 400, "msg": "手术申请未批准或已取消"}
    pharmaceutical = db.query(Pharmaceutical).filter(Pharmaceutical.pharmaceutical_id == req.get("pharmaceutical_id"), Pharmaceutical.status == 0).first()
    if not pharmaceutical:
        return {"code": 404, "msg": "抗菌药品不存在或已停用"}
    if not pharmaceutical.antibiotic_level:
        return {"code": 400, "msg": "该药品不是抗菌药，不能用于围术期预防用药"}
    try:
        timing_minutes = int(req.get("timing_minutes", 30))
    except (TypeError, ValueError):
        return {"code": 400, "msg": "给药提前时间不合法"}
    if timing_minutes < 0 or timing_minutes > 240:
        return {"code": 400, "msg": "给药提前时间应在0至240分钟之间"}
    item = PerioperativeAntibiotic(
        application_id=application.application_id,
        patient_id=application.patient_id,
        pharmaceutical_id=pharmaceutical.pharmaceutical_id,
        prescriber_id=current_user.user_id,
        dose=str(req.get("dose", "")).strip(),
        timing_minutes=timing_minutes,
        indication=str(req.get("indication", "")).strip()[:300],
        create_time=datetime.datetime.now(),
    )
    if not item.dose:
        return {"code": 400, "msg": "用药剂量不能为空"}
    db.add(item)
    db.commit()
    return {"code": 200, "msg": "围术期预防用药已创建", "data": _perioperative_data(item)}


@router.post("/surgery/perioperative/status")
def update_perioperative_antibiotic_status(req: dict, current_user: User = Depends(require_roles(*CLINICAL_ROLES)), db: Session = Depends(get_db)):
    item = db.query(PerioperativeAntibiotic).filter(PerioperativeAntibiotic.perioperative_id == req.get("perioperative_id")).first()
    if not item:
        return {"code": 404, "msg": "围术期用药记录不存在"}
    status = req.get("status")
    if status not in (1, 2) or (item.status == 1 and status == 2):
        return {"code": 400, "msg": "用药状态不合法"}
    item.status = status
    item.administered_time = datetime.datetime.now() if status == 1 else None
    db.commit()
    return {"code": 200, "msg": "围术期用药状态已更新", "data": _perioperative_data(item)}


@router.get("/surgeryApplication/getList")
def get_surgery_application_list(
    status: int | None = None,
    keyword: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(*CLINICAL_ROLES)),
):
    query = db.query(SurgeryApplication).order_by(SurgeryApplication.create_time.desc())
    if status is not None:
        query = query.filter(SurgeryApplication.status == status)
    applications = query.all()

    status_map = ["待审批", "已批准", "已排台", "已完成", "已取消"]
    level_map = ["", "一级", "二级", "三级", "四级"]
    data = []
    for item in applications:
        data.append(
            {
                "application_id": item.application_id,
                "admission_id": item.admission_id,
                "patient_id": item.patient_id,
                "patient_name": item.patient.name if item.patient else "",
                "patient_identity": item.patient.identity if item.patient else "",
                "doctor_id": item.doctor_id,
                "doctor_name": item.doctor.name if item.doctor else "",
                "surgery_name": item.surgery_name,
                "surgery_code": item.surgery_code or "",
                "surgery_level": item.surgery_level,
                "surgery_level_text": level_map[item.surgery_level] if item.surgery_level and item.surgery_level < len(level_map) else "",
                "anesthesia_type": item.anesthesia_type,
                "scheduled_date": str(item.scheduled_date) if item.scheduled_date else "",
                "preop_diagnosis": item.preop_diagnosis or "",
                "status": item.status,
                "status_text": status_map[item.status] if item.status is not None and item.status < len(status_map) else "",
                "approver_name": item.approver.name if item.approver else "",
                "approve_time": (item.approve_time.strftime("%Y-%m-%d %H:%M:%S") if item.approve_time else None) if item.approve_time else "",
                "create_time": (item.create_time.strftime("%Y-%m-%d %H:%M:%S") if item.create_time else None) if item.create_time else "",
            }
        )
    if keyword:
        kw = keyword.lower()
        data = [item for item in data if any(kw in str(val).lower() for val in item.values())]
    return {"code": 200, "msg": "success", "data": data}


def _parse_date(value):
    """JSON 无原生 date：把 ISO 字符串安全转为 date，非法输入返回 None（附错误标记）。"""
    if value is None or isinstance(value, datetime.date) and not isinstance(value, datetime.datetime):
        return value
    if isinstance(value, datetime.datetime):
        return value.date()
    if isinstance(value, str):
        s = value.strip()
        for fmt in ("%Y-%m-%d", "%Y/%m/%d"):
            try:
                return datetime.datetime.strptime(s, fmt).date()
            except ValueError:
                continue
    return None


def _parse_datetime(value):
    """把 ISO/常见格式字符串安全转为 datetime。"""
    if value is None or isinstance(value, datetime.datetime):
        return value
    if isinstance(value, datetime.date):
        return datetime.datetime.combine(value, datetime.time())
    if isinstance(value, str):
        s = value.strip().replace("T", " ")
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d", "%Y/%m/%d %H:%M:%S", "%Y/%m/%d"):
            try:
                return datetime.datetime.strptime(s, fmt)
            except ValueError:
                continue
    return None


@router.post("/surgeryApplication/create")
def create_surgery_application(req: dict, current_user: User = Depends(require_roles(*CLINICAL_ROLES)),
    db: Session = Depends(get_db)):
    admission = db.query(Admission).filter(Admission.admission_id == req.get("admission_id")).first()
    if not admission:
        return {"code": 500, "msg": "入院记录不存在"}
    if admission.status != 1:
        return {"code": 500, "msg": "病人不在院状态，无法申请手术"}
    if req.get("patient_id") is not None and req["patient_id"] != admission.patient_id:
        return {"code": 500, "msg": "患者与入院记录不一致"}
    scheduled_date = _parse_date(req.get("scheduled_date"))
    if req.get("scheduled_date") is not None and scheduled_date is None:
        return {"code": 500, "msg": "预手术日期格式错误，应为 YYYY-MM-DD"}

    application = SurgeryApplication(
        admission_id=req.get("admission_id"),
        patient_id=admission.patient_id,
        doctor_id=req.get("doctor_id"),
        surgery_name=req.get("surgery_name", ""),
        surgery_code=req.get("surgery_code"),
        surgery_level=req.get("surgery_level", 1),
        anesthesia_type=req.get("anesthesia_type", "局部麻醉"),
        scheduled_date=scheduled_date,
        preop_diagnosis=req.get("preop_diagnosis"),
        surgery_indication=req.get("surgery_indication"),
        contraindication=req.get("contraindication"),
        status=0,
        create_time=datetime.datetime.now(),
    )
    db.add(application)
    db.commit()
    return {"code": 200, "msg": "success", "data": {"application_id": application.application_id}}


@router.post("/surgeryApplication/approve")
def approve_surgery_application(req: dict, current_user: User = Depends(require_roles(*CLINICAL_ROLES)), db: Session = Depends(get_db)):
    application = db.query(SurgeryApplication).filter(SurgeryApplication.application_id == req.get("application_id")).first()
    if not application:
        return {"code": 500, "msg": "申请不存在"}
    if application.status != 0:
        return {"code": 500, "msg": "申请状态不正确"}
    # 审批人与申请人不能是同一人（防自审自批）
    if application.doctor and application.doctor.user_id == current_user.user_id:
        return {"code": 500, "msg": "审批人不能是手术申请人本人"}
    application.status = 1
    application.approver_id = current_user.user_id
    application.approve_time = datetime.datetime.now()
    db.add(application)
    db.commit()
    return {"code": 200, "msg": "success"}


@router.post("/surgeryApplication/cancel")
def cancel_surgery_application(req: dict, current_user: User = Depends(require_roles(*CLINICAL_ROLES)),
    db: Session = Depends(get_db)):
    application = db.query(SurgeryApplication).filter(SurgeryApplication.application_id == req.get("application_id")).first()
    if not application:
        return {"code": 500, "msg": "申请不存在"}
    # 已完成的手术不能取消（会造成术后记录与病历矛盾）；已取消的幂等拒绝
    if application.status == 3:
        return {"code": 500, "msg": "手术已完成，不能取消"}
    if application.status == 4:
        return {"code": 500, "msg": "申请已取消，无需重复操作"}
    application.status = 4
    db.add(application)
    # 取消已排台的手术（仅待手术/手术中的排台可取消）
    schedule = db.query(SurgerySchedule).filter(SurgerySchedule.application_id == req.get("application_id")).first()
    if schedule and schedule.status in (0, 1):
        schedule.status = 3
        db.add(schedule)
    db.commit()
    return {"code": 200, "msg": "success"}


@router.get("/surgerySchedule/getList")
def get_surgery_schedule_list(
    surgery_date: str | None = None,
    status: int | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(*CLINICAL_ROLES)),
):
    query = db.query(SurgerySchedule).order_by(SurgerySchedule.surgery_date.desc())
    if surgery_date:
        try:
            from datetime import date as dt_date
            d = dt_date.fromisoformat(surgery_date)
            query = query.filter(SurgerySchedule.surgery_date == d)
        except ValueError:
            pass
    if status is not None:
        query = query.filter(SurgerySchedule.status == status)
    schedules = query.all()

    status_map = ["待手术", "手术中", "已完成", "已取消"]
    data = []
    for item in schedules:
        data.append(
            {
                "schedule_id": item.schedule_id,
                "application_id": item.application_id,
                "patient_id": item.patient_id,
                "patient_name": item.patient.name if item.patient else "",
                "surgery_name": item.application.surgery_name if item.application else "",
                "operating_room": item.operating_room,
                "surgery_date": str(item.surgery_date) if item.surgery_date else "",
                "start_time": (item.start_time.strftime("%Y-%m-%d %H:%M:%S") if item.start_time else None) if item.start_time else "",
                "end_time": str(item.end_time) if item.end_time else "",
                "surgeon_name": item.surgeon.name if item.surgeon else "",
                "anesthesiologist_name": item.anesthesiologist.name if item.anesthesiologist else "",
                "status": item.status,
                "status_text": status_map[item.status] if item.status is not None and item.status < len(status_map) else "",
            }
        )
    return {"code": 200, "msg": "success", "data": data}


@router.post("/surgerySchedule/create")
def create_surgery_schedule(req: dict, current_user: User = Depends(require_roles(*CLINICAL_ROLES)),
    db: Session = Depends(get_db)):
    application = db.query(SurgeryApplication).filter(SurgeryApplication.application_id == req.get("application_id")).first()
    if not application:
        return {"code": 500, "msg": "手术申请不存在"}
    if application.status != 1:
        return {"code": 500, "msg": "申请未批准，无法排台"}
    surgery_date = _parse_date(req.get("surgery_date"))
    if req.get("surgery_date") is not None and surgery_date is None:
        return {"code": 500, "msg": "手术日期格式错误，应为 YYYY-MM-DD"}

    # 冲突检测：同手术室同日已有未取消（0/1/2）排台时拒绝
    operating_room = (req.get("operating_room") or "").strip()
    if operating_room and surgery_date:
        conflict = (
            db.query(SurgerySchedule)
            .filter(
                SurgerySchedule.operating_room == operating_room,
                SurgerySchedule.surgery_date == surgery_date,
                SurgerySchedule.status.in_((0, 1, 2)),
            )
            .first()
        )
        if conflict:
            return {"code": 500, "msg": f"手术室 {operating_room} 在 {surgery_date} 已有排台（申请单 {conflict.application_id}），请更换手术室或日期"}
    # 主刀医生同日冲突（同一医生同日只能有一台未完成排台）
    surgeon_id = req.get("surgeon_id")
    if surgeon_id and surgery_date:
        doc_conflict = (
            db.query(SurgerySchedule)
            .filter(
                SurgerySchedule.surgeon_id == surgeon_id,
                SurgerySchedule.surgery_date == surgery_date,
                SurgerySchedule.status.in_((0, 1, 2)),
            )
            .first()
        )
        if doc_conflict:
            return {"code": 500, "msg": f"主刀医生同日已有排台（申请单 {doc_conflict.application_id}），请更换医生或日期"}

    schedule = SurgerySchedule(
        application_id=req.get("application_id"),
        patient_id=application.patient_id,
        operating_room=req.get("operating_room", ""),
        surgery_date=surgery_date,
        surgeon_id=req.get("surgeon_id"),
        assistant_ids=req.get("assistant_ids"),
        anesthesiologist_id=req.get("anesthesiologist_id"),
        scrub_nurse_id=req.get("scrub_nurse_id"),
        circulating_nurse_id=req.get("circulating_nurse_id"),
        status=0,
        create_time=datetime.datetime.now(),
    )
    db.add(schedule)

    application.status = 2
    db.add(application)
    db.commit()
    return {"code": 200, "msg": "success", "data": {"schedule_id": schedule.schedule_id}}


@router.post("/surgerySchedule/start")
def start_surgery(req: dict, current_user: User = Depends(require_roles(*CLINICAL_ROLES)),
    db: Session = Depends(get_db)):
    schedule = db.query(SurgerySchedule).filter(SurgerySchedule.schedule_id == req.get("schedule_id")).first()
    if not schedule:
        return {"code": 500, "msg": "排台记录不存在"}
    # 只有待手术(0)的排台可以开始；已取消/已完成的拒绝
    if schedule.status != 0:
        return {"code": 500, "msg": "排台状态不允许开始手术"}
    schedule.status = 1
    schedule.start_time = datetime.datetime.now()
    db.add(schedule)
    db.commit()
    return {"code": 200, "msg": "success"}


@router.post("/surgerySchedule/complete")
def complete_surgery(req: dict, current_user: User = Depends(require_roles(*CLINICAL_ROLES)),
    db: Session = Depends(get_db)):
    schedule = db.query(SurgerySchedule).filter(SurgerySchedule.schedule_id == req.get("schedule_id")).first()
    if not schedule:
        return {"code": 500, "msg": "排台记录不存在"}
    # 只有手术中(1)的排台可以完成；待手术应先 start，已取消/已完成的拒绝
    if schedule.status != 1:
        return {"code": 500, "msg": "排台状态不允许完成手术（需先开始手术）"}
    schedule.status = 2
    schedule.end_time = datetime.datetime.now()
    db.add(schedule)

    application = db.query(SurgeryApplication).filter(SurgeryApplication.application_id == schedule.application_id).first()
    if application:
        application.status = 3
        db.add(application)

    # 手术费自动计费（原缺陷：手术全程不产生任何住院费用，出院结算漏计）
    # 费用 = 基础起价 × 等级系数^(级别-1)，参数管理员可配置（config 表）
    if application:
        from decimal import Decimal

        from app.config_service import get_config_float
        from app.models import Admission, InpatientCharge

        admission = (
            db.query(Admission)
            .filter(Admission.patient_id == application.patient_id, Admission.status == 1)
            .order_by(Admission.admission_time.desc())
            .first()
        )
        if admission:
            base = Decimal(str(get_config_float(db, "surgery_fee_base", 500.0)))
            multiplier = Decimal(str(get_config_float(db, "surgery_fee_level_multiplier", 1.5)))
            level = application.surgery_level or 1
            amount = base * (multiplier ** max(level - 1, 0))
            db.add(InpatientCharge(
                admission_id=admission.admission_id,
                patient_id=application.patient_id,
                item_name=f"手术费({application.surgery_name or '手术'}·{level}级)",
                item_type="surgery",
                quantity=1,
                unit_price=amount,
                total_amount=amount,
                charge_date=datetime.date.today(),
                status=0,
                create_time=datetime.datetime.now(),
            ))

    db.commit()
    return {"code": 200, "msg": "success"}


@router.get("/anesthesiaRecord/getList")
def get_anesthesia_record_list(schedule_id: str | None = None, current_user: User = Depends(require_roles(*CLINICAL_ROLES, *NURSING_ROLES)),
    db: Session = Depends(get_db)):
    query = db.query(AnesthesiaRecord).order_by(AnesthesiaRecord.create_time.desc())
    if schedule_id:
        query = query.filter(AnesthesiaRecord.schedule_id == schedule_id)
    records = query.all()
    data = []
    for item in records:
        data.append(
            {
                "record_id": item.record_id,
                "schedule_id": item.schedule_id,
                "patient_id": item.patient_id,
                "patient_name": item.patient.name if item.patient else "",
                "anesthesiologist_name": item.anesthesiologist.name if item.anesthesiologist else "",
                "enter_time": (item.enter_time.strftime("%Y-%m-%d %H:%M:%S") if item.enter_time else None) if item.enter_time else "",
                "anesthesia_method": item.anesthesia_method or "",
                "blood_loss": item.blood_loss,
                "urine_output": item.urine_output,
                "fluid_input": item.fluid_input,
                "leave_time": (item.leave_time.strftime("%Y-%m-%d %H:%M:%S") if item.leave_time else None) if item.leave_time else "",
                "complications": item.complications or "",
                "create_time": (item.create_time.strftime("%Y-%m-%d %H:%M:%S") if item.create_time else None) if item.create_time else "",
            }
        )
    return {"code": 200, "msg": "success", "data": data}


@router.post("/anesthesiaRecord/create")
def create_anesthesia_record(req: dict, current_user: User = Depends(require_roles(*CLINICAL_ROLES)),
    db: Session = Depends(get_db)):
    schedule = db.query(SurgerySchedule).filter(SurgerySchedule.schedule_id == req.get("schedule_id")).first()
    if not schedule:
        return {"code": 500, "msg": "手术排台不存在"}

    record = AnesthesiaRecord(
        schedule_id=req.get("schedule_id"),
        patient_id=schedule.patient_id,
        anesthesiologist_id=req.get("anesthesiologist_id"),
        enter_time=_parse_datetime(req.get("enter_time")),
        consciousness=req.get("consciousness"),
        preop_bp=req.get("preop_bp"),
        preop_hr=req.get("preop_hr"),
        preop_spo2=req.get("preop_spo2"),
        anesthesia_method=req.get("anesthesia_method"),
        induction_drugs=req.get("induction_drugs"),
        maintenance_drugs=req.get("maintenance_drugs"),
        intraop_bp=req.get("intraop_bp"),
        intraop_hr=req.get("intraop_hr"),
        blood_loss=req.get("blood_loss", 0),
        urine_output=req.get("urine_output", 0),
        fluid_input=req.get("fluid_input", 0),
        extubation_time=_parse_datetime(req.get("extubation_time")),
        leave_time=_parse_datetime(req.get("leave_time")),
        postop_consciousness=req.get("postop_consciousness"),
        complications=req.get("complications"),
        create_time=datetime.datetime.now(),
    )
    db.add(record)

    # 麻醉费自动计费（基础起价可配置；原缺陷：麻醉不产生任何住院费用）
    from decimal import Decimal

    from app.config_service import get_config_float
    from app.models import Admission

    admission = (
        db.query(Admission)
        .filter(Admission.patient_id == schedule.patient_id, Admission.status == 1)
        .order_by(Admission.admission_time.desc())
        .first()
    )
    if admission:
        amount = Decimal(str(get_config_float(db, "anesthesia_fee_base", 300.0)))
        method = req.get("anesthesia_method") or "麻醉"
        db.add(InpatientCharge(
            admission_id=admission.admission_id,
            patient_id=schedule.patient_id,
            item_name=f"麻醉费({method})",
            item_type="anesthesia",
            quantity=1,
            unit_price=amount,
            total_amount=amount,
            charge_date=datetime.date.today(),
            status=0,
            create_time=datetime.datetime.now(),
        ))

    db.commit()
    return {"code": 200, "msg": "success", "data": {"record_id": record.record_id}}


@router.get("/surgery/antibioticCompliance")
def antibiotic_compliance_statistics(
    start_date: str | None = None,
    end_date: str | None = None,
    current_user: User = Depends(require_roles(*(CLINICAL_ROLES | NURSING_ROLES))),
    db: Session = Depends(get_db),
):
    """围术期预防用药时限依从统计。

    判定规则（以手术开始时间为基准）：
    - 依从：术前 30-120 分钟内给药（切皮前 0.5-2h，国家抗菌药临床应用指导原则）
    - 过早：> 120 分钟；过晚/未给：< 30 分钟或未执行
    汇总：总体依从率、按时给药率、按手术级别人群分布。
    """

    from app.models import PerioperativeAntibiotic, SurgerySchedule

    query = (
        db.query(PerioperativeAntibiotic, SurgerySchedule)
        .join(SurgerySchedule, SurgerySchedule.application_id == PerioperativeAntibiotic.application_id)
        .filter(PerioperativeAntibiotic.status == 1)
        .filter(SurgerySchedule.start_time.isnot(None))
        .filter(PerioperativeAntibiotic.administered_time.isnot(None))
    )
    try:
        if start_date:
            query = query.filter(SurgerySchedule.start_time >= datetime.datetime.strptime(start_date, "%Y-%m-%d"))
        if end_date:
            query = query.filter(SurgerySchedule.start_time < datetime.datetime.strptime(end_date, "%Y-%m-%d") + datetime.timedelta(days=1))
    except ValueError:
        return {"code": 400, "msg": "日期格式必须为 YYYY-MM-DD"}
    rows = query.all()
    from app.models import SurgeryApplication

    app_ids = {pa.application_id for pa, _ in rows}
    levels = {a.application_id: a.surgery_level for a in db.query(SurgeryApplication).filter(SurgeryApplication.application_id.in_(app_ids)).all()} if app_ids else {}
    total = compliant = on_time_or_early = late_or_missing = 0
    by_level: dict[int, dict] = {}
    for pa, sch in rows:
        total += 1
        delta_min = (sch.start_time - pa.administered_time).total_seconds() / 60
        is_ok = 30 <= delta_min <= 120
        if is_ok:
            compliant += 1
        lv = levels.get(pa.application_id) or 0
        bucket = by_level.setdefault(lv, {"level": lv, "total": 0, "compliant": 0})
        bucket["total"] += 1
        if is_ok:
            bucket["compliant"] += 1
        if delta_min > 120:
            on_time_or_early += 1
        elif delta_min < 30:
            late_or_missing += 1
    for bucket in by_level.values():
        bucket["rate"] = round(bucket["compliant"] / bucket["total"] * 100, 1) if bucket["total"] else None
    return {
        "code": 200,
        "msg": "success",
        "data": {
            "total_executed": total,
            "compliant": compliant,
            "compliance_rate": round(compliant / total * 100, 1) if total else None,
            "too_early_gt120min": on_time_or_early,
            "too_late_lt30min": late_or_missing,
            "by_level": [by_level[k] for k in sorted(by_level)],
            "rule": "切皮前 30-120 分钟给药为依从（0.5-2h）",
        },
    }
