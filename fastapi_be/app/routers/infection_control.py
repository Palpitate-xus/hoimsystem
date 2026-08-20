"""院感扩展：MDRO 隔离 / 手卫生观察 / 传染病报告卡。"""
import datetime

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import ADMIN_ROLES, CLINICAL_ROLES, LAB_ROLES, NURSING_ROLES, User, require_roles
from app.models import HandHygieneObservation, MdroIsolation, NotifiableDiseaseReport, Patient

router = APIRouter()


def _pdate(val):
    if not val:
        return None
    if isinstance(val, datetime.date):
        return val
    try:
        return datetime.datetime.strptime(str(val)[:10], "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


INFECTION_ROLES = ADMIN_ROLES | CLINICAL_ROLES | NURSING_ROLES
REPORT_ROLES = ADMIN_ROLES | CLINICAL_ROLES | LAB_ROLES

DISEASE_CLASS = {
    "甲类": ["霍乱", "鼠疫"],
    "乙类": [
        "传染性非典型肺炎", "艾滋病", "病毒性肝炎", "脊髓灰质炎", "人感染高致病性禽流感",
        "麻疹", "流行性出血热", "狂犬病", "流行性乙型脑炎", "登革热", "炭疽",
        "细菌性和阿米巴性痢疾", "肺结核", "伤寒和副伤寒", "流行性脑脊髓膜炎", "百日咳",
        "白喉", "新生儿破伤风", "猩红热", "布鲁氏菌病", "淋病", "梅毒", "钩端螺旋体病",
        "血吸虫病", "疟疾", "人感染H7N9禽流感", "新型冠状病毒感染",
    ],
    "丙类": [
        "流行性感冒", "流行性腮腺炎", "风疹", "急性出血性结膜炎", "麻风病",
        "流行性和地方性斑疹伤寒", "黑热病", "包虫病", "丝虫病", "手足口病",
        "除霍乱、细菌性和阿米巴性痢疾、伤寒和副伤寒以外的感染性腹泻病",
    ],
}


def _infer_class(name: str) -> str | None:
    for cls, names in DISEASE_CLASS.items():
        if any(n in name for n in names):
            return cls
    return None


# ---------------- MDRO ----------------

def _mdro_ser(m: MdroIsolation) -> dict:
    return {
        "mdro_id": m.mdro_id,
        "patient_id": m.patient_id,
        "patient_name": m.patient.name if m.patient else "",
        "pathogen": m.pathogen,
        "specimen": m.specimen or "",
        "isolation_type": m.isolation_type,
        "start_date": m.start_date.isoformat() if m.start_date else "",
        "end_date": m.end_date.isoformat() if m.end_date else "",
        "bed_label": m.bed_label,
        "status": m.status,
        "status_text": "隔离中" if m.status == 1 else "已解除",
        "remark": m.remark or "",
        "create_time": m.create_time.strftime("%Y-%m-%d %H:%M:%S") if m.create_time else "",
    }


@router.get("/mdro/getList")
def list_mdro(status: int | None = None, patient_id: int | None = None, current_user: User = Depends(require_roles(*INFECTION_ROLES)), db: Session = Depends(get_db)):
    query = db.query(MdroIsolation)
    if status is not None:
        query = query.filter(MdroIsolation.status == status)
    if patient_id is not None:
        query = query.filter(MdroIsolation.patient_id == patient_id)
    rows = query.order_by(MdroIsolation.mdro_id.desc()).limit(1000).all()
    return {"code": 200, "msg": "success", "data": [_mdro_ser(m) for m in rows]}


@router.post("/mdro/create")
def create_mdro(req: dict, current_user: User = Depends(require_roles(*INFECTION_ROLES)), db: Session = Depends(get_db)):
    patient = db.query(Patient).filter(Patient.patient_id == req.get("patient_id")).first()
    if not patient:
        return {"code": 500, "msg": "患者不存在"}
    pathogen = (req.get("pathogen") or "").strip()
    if not pathogen:
        return {"code": 400, "msg": "耐药菌种不能为空"}
    try:
        start_date = datetime.datetime.strptime(req.get("start_date"), "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return {"code": 400, "msg": "隔离开始日期格式必须为 YYYY-MM-DD"}
    # 同患者同菌种已有隔离中记录 → 拒绝重复
    dup = db.query(MdroIsolation).filter(
        MdroIsolation.patient_id == patient.patient_id,
        MdroIsolation.pathogen == pathogen,
        MdroIsolation.status == 1,
    ).first()
    if dup:
        return {"code": 500, "msg": "该患者此菌种已在隔离中，不能重复登记"}
    item = MdroIsolation(
        patient_id=patient.patient_id,
        pathogen=pathogen,
        specimen=(req.get("specimen") or "").strip() or None,
        isolation_type=(req.get("isolation_type") or "接触隔离").strip(),
        start_date=start_date,
        bed_label=1 if req.get("bed_label", 1) else 0,
        status=1,
        remark=(req.get("remark") or "").strip() or None,
        reporter_id=current_user.user_id,
        create_time=datetime.datetime.now(),
    )
    db.add(item)
    db.commit()
    return {"code": 200, "msg": "success", "data": {"mdro_id": item.mdro_id}}


@router.post("/mdro/release")
def release_mdro(req: dict, current_user: User = Depends(require_roles(*INFECTION_ROLES)), db: Session = Depends(get_db)):
    item = db.query(MdroIsolation).filter(MdroIsolation.mdro_id == req.get("mdro_id"), MdroIsolation.status == 1).first()
    if not item:
        return {"code": 500, "msg": "隔离记录不存在或已解除"}
    try:
        end_date = datetime.datetime.strptime(req.get("end_date") or datetime.date.today().isoformat(), "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return {"code": 400, "msg": "解除日期格式必须为 YYYY-MM-DD"}
    if end_date < item.start_date:
        return {"code": 400, "msg": "解除日期不能早于隔离开始日期"}
    item.status = 0
    item.end_date = end_date
    db.add(item)
    db.commit()
    return {"code": 200, "msg": "success"}


# ---------------- 手卫生 ----------------

@router.get("/handHygiene/getList")
def list_hand_hygiene(
    department: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    current_user: User = Depends(require_roles(*INFECTION_ROLES)),
    db: Session = Depends(get_db),
):
    query = db.query(HandHygieneObservation)
    if department:
        query = query.filter(HandHygieneObservation.department == department)
    if start_date:
        try:
            query = query.filter(HandHygieneObservation.observe_date >= datetime.datetime.strptime(start_date, "%Y-%m-%d").date())
        except ValueError:
            pass
    if end_date:
        try:
            query = query.filter(HandHygieneObservation.observe_date <= datetime.datetime.strptime(end_date, "%Y-%m-%d").date())
        except ValueError:
            pass
    rows = query.order_by(HandHygieneObservation.observe_date.desc()).limit(2000).all()
    data = [{
        "observation_id": o.observation_id,
        "observe_date": o.observe_date.isoformat() if o.observe_date else "",
        "department": o.department,
        "moment": o.moment or "",
        "opportunities": o.opportunities,
        "actions": o.actions,
        "compliance": round(o.actions / o.opportunities * 100, 1) if o.opportunities else None,
        "remark": o.remark or "",
    } for o in rows]
    return {"code": 200, "msg": "success", "data": data}


@router.post("/handHygiene/create")
def create_hand_hygiene(req: dict, current_user: User = Depends(require_roles(*INFECTION_ROLES)), db: Session = Depends(get_db)):
    department = (req.get("department") or "").strip()
    if not department:
        return {"code": 400, "msg": "观察科室不能为空"}
    try:
        opportunities = int(req.get("opportunities", 0))
        actions = int(req.get("actions", 0))
    except (TypeError, ValueError):
        return {"code": 400, "msg": "应执行/实际执行次数必须为整数"}
    if opportunities < 0 or actions < 0:
        return {"code": 400, "msg": "次数不能为负数"}
    if actions > opportunities:
        return {"code": 400, "msg": "实际执行次数不能大于应执行次数"}
    if opportunities == 0:
        return {"code": 400, "msg": "应执行次数必须大于0"}
    try:
        observe_date = datetime.datetime.strptime(req.get("observe_date"), "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return {"code": 400, "msg": "观察日期格式必须为 YYYY-MM-DD"}
    item = HandHygieneObservation(
        observe_date=observe_date,
        department=department,
        moment=(req.get("moment") or "").strip() or None,
        opportunities=opportunities,
        actions=actions,
        observer_id=current_user.user_id,
        remark=(req.get("remark") or "").strip() or None,
        create_time=datetime.datetime.now(),
    )
    db.add(item)
    db.commit()
    return {"code": 200, "msg": "success", "data": {"observation_id": item.observation_id}}


# ---------------- 传染病报告卡 ----------------

STATUS_TEXT = {0: "待上报", 1: "已上报网直", 2: "已审核", 3: "订正"}


def _report_ser(r: NotifiableDiseaseReport) -> dict:
    return {
        "report_id": r.report_id,
        "patient_id": r.patient_id,
        "patient_name": r.patient.name if r.patient else "",
        "patient_identity": r.patient.identity if r.patient else "",
        "disease_name": r.disease_name,
        "disease_class": r.disease_class or "",
        "onset_date": r.onset_date.isoformat() if r.onset_date else "",
        "diagnosis_date": r.diagnosis_date.isoformat() if r.diagnosis_date else "",
        "death_date": r.death_date.isoformat() if r.death_date else "",
        "case_classification": r.case_classification or "",
        "report_status": r.report_status,
        "report_status_text": STATUS_TEXT.get(r.report_status, str(r.report_status)),
        "report_card_no": r.report_card_no or "",
        "report_time": r.report_time.strftime("%Y-%m-%d %H:%M:%S") if r.report_time else "",
        "audit_time": r.audit_time.strftime("%Y-%m-%d %H:%M:%S") if r.audit_time else "",
        "remark": r.remark or "",
    }


@router.get("/notifiableDisease/getList")
def list_reports(report_status: int | None = None, current_user: User = Depends(require_roles(*REPORT_ROLES)), db: Session = Depends(get_db)):
    query = db.query(NotifiableDiseaseReport)
    if report_status is not None:
        query = query.filter(NotifiableDiseaseReport.report_status == report_status)
    rows = query.order_by(NotifiableDiseaseReport.report_id.desc()).limit(2000).all()
    return {"code": 200, "msg": "success", "data": [_report_ser(r) for r in rows]}


@router.post("/notifiableDisease/create")
def create_report(req: dict, current_user: User = Depends(require_roles(*REPORT_ROLES)), db: Session = Depends(get_db)):
    patient = db.query(Patient).filter(Patient.patient_id == req.get("patient_id")).first()
    if not patient:
        return {"code": 500, "msg": "患者不存在"}
    disease_name = (req.get("disease_name") or "").strip()
    if not disease_name:
        return {"code": 400, "msg": "病种名称不能为空"}
    try:
        diagnosis_date = datetime.datetime.strptime(req.get("diagnosis_date"), "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return {"code": 400, "msg": "诊断日期格式必须为 YYYY-MM-DD"}
    onset_date = None
    if req.get("onset_date"):
        try:
            onset_date = datetime.datetime.strptime(req["onset_date"], "%Y-%m-%d").date()
        except (TypeError, ValueError):
            return {"code": 400, "msg": "发病日期格式必须为 YYYY-MM-DD"}
    item = NotifiableDiseaseReport(
        patient_id=patient.patient_id,
        disease_name=disease_name,
        disease_class=_infer_class(disease_name),
        onset_date=onset_date,
        diagnosis_date=diagnosis_date,
        death_date=_pdate(req.get("death_date")),
        case_classification=(req.get("case_classification") or "").strip() or None,
        report_status=0,
        reporter_id=current_user.user_id,
        report_time=datetime.datetime.now(),
        remark=(req.get("remark") or "").strip() or None,
        create_time=datetime.datetime.now(),
    )
    db.add(item)
    db.commit()
    return {"code": 200, "msg": "success", "data": {"report_id": item.report_id, "disease_class": item.disease_class}}


@router.post("/notifiableDisease/submit")
def submit_report(req: dict, current_user: User = Depends(require_roles(*REPORT_ROLES)), db: Session = Depends(get_db)):
    """标记为已上报网直（回填卡号）。实际网直传输由外部网关完成。"""
    item = db.query(NotifiableDiseaseReport).filter(NotifiableDiseaseReport.report_id == req.get("report_id")).first()
    if not item:
        return {"code": 500, "msg": "报告卡不存在"}
    if item.report_status not in (0, 3):
        return {"code": 500, "msg": "仅待上报/订正状态可执行上报"}
    card_no = (req.get("report_card_no") or "").strip()
    if not card_no:
        return {"code": 400, "msg": "网直报卡编号不能为空"}
    item.report_status = 1
    item.report_card_no = card_no
    db.add(item)
    db.commit()
    return {"code": 200, "msg": "success"}


@router.post("/notifiableDisease/audit")
def audit_report(req: dict, current_user: User = Depends(require_roles(*ADMIN_ROLES)), db: Session = Depends(get_db)):
    item = db.query(NotifiableDiseaseReport).filter(NotifiableDiseaseReport.report_id == req.get("report_id")).first()
    if not item:
        return {"code": 500, "msg": "报告卡不存在"}
    if item.report_status != 1:
        return {"code": 500, "msg": "仅已上报状态可审核"}
    item.report_status = 2
    item.audit_time = datetime.datetime.now()
    item.auditor_id = current_user.user_id
    db.add(item)
    db.commit()
    return {"code": 200, "msg": "success"}


@router.post("/notifiableDisease/correct")
def correct_report(req: dict, current_user: User = Depends(require_roles(*REPORT_ROLES)), db: Session = Depends(get_db)):
    """订正：已审核卡发现错误时置订正态，重新上报走 submit。"""
    item = db.query(NotifiableDiseaseReport).filter(NotifiableDiseaseReport.report_id == req.get("report_id")).first()
    if not item:
        return {"code": 500, "msg": "报告卡不存在"}
    if item.report_status != 2:
        return {"code": 500, "msg": "仅已审核状态可订正"}
    for field in ("disease_name", "case_classification"):
        if req.get(field):
            setattr(item, field, (req[field] or "").strip())
    if req.get("disease_name"):
        item.disease_class = _infer_class(item.disease_name)
    item.report_status = 3
    db.add(item)
    db.commit()
    return {"code": 200, "msg": "success"}
