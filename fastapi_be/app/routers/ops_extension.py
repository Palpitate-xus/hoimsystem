"""运营扩展：CSSD 器械包 / PIVAS 批次 / ICU-PACU 评分 / 临床路径入组。"""
import datetime
import json

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import ADMIN_ROLES, CLINICAL_ROLES, NURSING_ROLES, PHARMACY_ROLES, User, require_roles
from app.models import CssdInstrument, IcuScoreRecord, PathwayEnrollment, Patient, PivasBatch

router = APIRouter()

CSSD_ROLES = ADMIN_ROLES | NURSING_ROLES
PIVAS_ROLES = ADMIN_ROLES | PHARMACY_ROLES | NURSING_ROLES
SCORE_ROLES = ADMIN_ROLES | CLINICAL_ROLES | NURSING_ROLES
PATHWAY_ROLES = ADMIN_ROLES | CLINICAL_ROLES

# ---------------- CSSD ----------------

CSSD_STATUS = {0: "待回收", 1: "清洗中", 2: "检查打包", 3: "灭菌中", 4: "无菌可用", 5: "发放使用中", 6: "报损"}
CSSD_FLOW = {0: {1}, 1: {2}, 2: {3}, 3: {4, 6}, 4: {5, 6}, 5: {0, 6}, 6: set()}


def _cssd_ser(c: CssdInstrument) -> dict:
    return {
        "instrument_id": c.instrument_id,
        "package_name": c.package_name,
        "package_code": c.package_code or "",
        "contents": c.contents or "",
        "sterilize_method": c.sterilize_method or "",
        "status": c.status,
        "status_text": CSSD_STATUS.get(c.status, str(c.status)),
        "sterilize_date": c.sterilize_date.isoformat() if c.sterilize_date else "",
        "expire_date": c.expire_date.isoformat() if c.expire_date else "",
        "bd_test": c.bd_test,
        "biological_monitor": c.biological_monitor,
        "current_location": c.current_location or "",
        "update_time": c.update_time.strftime("%Y-%m-%d %H:%M:%S") if c.update_time else "",
    }


@router.get("/cssd/getList")
def list_cssd(status: int | None = None, keyword: str | None = None, current_user: User = Depends(require_roles(*CSSD_ROLES)), db: Session = Depends(get_db)):
    query = db.query(CssdInstrument)
    if status is not None:
        query = query.filter(CssdInstrument.status == status)
    if keyword:
        kw = f"%{keyword}%"
        query = query.filter(CssdInstrument.package_name.like(kw) | CssdInstrument.package_code.like(kw))
    rows = query.order_by(CssdInstrument.instrument_id.desc()).limit(2000).all()
    return {"code": 200, "msg": "success", "data": [_cssd_ser(c) for c in rows]}


@router.post("/cssd/create")
def create_cssd(req: dict, current_user: User = Depends(require_roles(*CSSD_ROLES)), db: Session = Depends(get_db)):
    name = (req.get("package_name") or "").strip()
    if not name:
        return {"code": 400, "msg": "器械包名称不能为空"}
    code = (req.get("package_code") or "").strip() or None
    if code:
        dup = db.query(CssdInstrument).filter(CssdInstrument.package_code == code).first()
        if dup:
            return {"code": 500, "msg": "包内卡编号已存在"}
    item = CssdInstrument(
        package_name=name,
        package_code=code,
        contents=(req.get("contents") or "").strip() or None,
        sterilize_method=(req.get("sterilize_method") or "压力蒸汽").strip(),
        status=0,
        current_location=(req.get("current_location") or "CSSD").strip(),
        create_time=datetime.datetime.now(),
    )
    db.add(item)
    db.commit()
    return {"code": 200, "msg": "success", "data": {"instrument_id": item.instrument_id}}


@router.post("/cssd/transition")
def transition_cssd(req: dict, current_user: User = Depends(require_roles(*CSSD_ROLES)), db: Session = Depends(get_db)):
    """状态流转（回收→清洗→打包→灭菌→无菌→发放→回收…）。
    进入灭菌中(3)时可登记 BD 试验；进入无菌可用(4)时必须生物监测通过并填效期。"""
    item = db.query(CssdInstrument).filter(CssdInstrument.instrument_id == req.get("instrument_id")).first()
    if not item:
        return {"code": 500, "msg": "器械包不存在"}
    target = req.get("status")
    if target not in CSSD_FLOW.get(item.status, set()):
        return {"code": 400, "msg": f"状态不允许从「{CSSD_STATUS.get(item.status)}」迁移到「{CSSD_STATUS.get(target, target)}」"}
    if target == 3:
        if "bd_test" in req:
            item.bd_test = 1 if req["bd_test"] else 0
        if item.bd_test == 0:
            return {"code": 400, "msg": "BD 试验未通过，不能进入灭菌"}
    if target == 4:
        bio = req.get("biological_monitor")
        if bio is None and item.biological_monitor != 1:
            return {"code": 400, "msg": "进入无菌可用必须生物监测通过"}
        if bio is not None:
            item.biological_monitor = 1 if bio else 0
        if item.biological_monitor != 1:
            return {"code": 400, "msg": "生物监测未通过，不能置为无菌可用"}
        if not req.get("expire_date"):
            return {"code": 400, "msg": "进入无菌可用必须填写无菌效期"}
        try:
            item.expire_date = datetime.datetime.strptime(req["expire_date"], "%Y-%m-%d").date()
        except (TypeError, ValueError):
            return {"code": 400, "msg": "效期格式必须为 YYYY-MM-DD"}
        item.sterilize_date = datetime.date.today()
    if target == 5 and req.get("current_location"):
        item.current_location = (req["current_location"]).strip()
    item.status = target
    item.update_time = datetime.datetime.now()
    db.add(item)
    db.commit()
    return {"code": 200, "msg": "success"}


# ---------------- PIVAS ----------------

PIVAS_STATUS = {0: "待排药", 1: "已排药贴签", 2: "配置中", 3: "成品核对", 4: "已配送", 5: "病区签收"}
PIVAS_FLOW = {0: {1}, 1: {2}, 2: {3}, 3: {4}, 4: {5}, 5: set()}


def _pivas_ser(b: PivasBatch) -> dict:
    return {
        "batch_id": b.batch_id,
        "batch_no": b.batch_no,
        "plan_date": b.plan_date.isoformat() if b.plan_date else "",
        "ward_id": b.ward_id,
        "ward_name": b.ward.name if b.ward else "",
        "status": b.status,
        "status_text": PIVAS_STATUS.get(b.status, str(b.status)),
        "label_count": b.label_count or 0,
        "cytotoxic": b.cytotoxic or 0,
        "tpn": b.tpn or 0,
        "receive_time": b.receive_time.strftime("%Y-%m-%d %H:%M:%S") if b.receive_time else "",
        "remark": b.remark or "",
    }


@router.get("/pivas/getList")
def list_pivas(status: int | None = None, plan_date: str | None = None, current_user: User = Depends(require_roles(*PIVAS_ROLES)), db: Session = Depends(get_db)):
    query = db.query(PivasBatch)
    if status is not None:
        query = query.filter(PivasBatch.status == status)
    if plan_date:
        try:
            query = query.filter(PivasBatch.plan_date == datetime.datetime.strptime(plan_date, "%Y-%m-%d").date())
        except ValueError:
            pass
    rows = query.order_by(PivasBatch.batch_id.desc()).limit(1000).all()
    return {"code": 200, "msg": "success", "data": [_pivas_ser(b) for b in rows]}


@router.post("/pivas/create")
def create_pivas(req: dict, current_user: User = Depends(require_roles(*PIVAS_ROLES)), db: Session = Depends(get_db)):
    batch_no = (req.get("batch_no") or "").strip()
    if not batch_no:
        return {"code": 400, "msg": "批次号不能为空"}
    try:
        plan_date = datetime.datetime.strptime(req.get("plan_date"), "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return {"code": 400, "msg": "调配日期格式必须为 YYYY-MM-DD"}
    dup = db.query(PivasBatch).filter(PivasBatch.batch_no == batch_no, PivasBatch.plan_date == plan_date).first()
    if dup:
        return {"code": 500, "msg": "该日期批次号已存在"}
    label_count = int(req.get("label_count", 0) or 0)
    if label_count < 0:
        return {"code": 400, "msg": "贴签数不能为负"}
    item = PivasBatch(
        batch_no=batch_no,
        plan_date=plan_date,
        ward_id=req.get("ward_id"),
        status=0,
        label_count=label_count,
        cytotoxic=1 if req.get("cytotoxic") else 0,
        tpn=1 if req.get("tpn") else 0,
        remark=(req.get("remark") or "").strip() or None,
        create_time=datetime.datetime.now(),
    )
    db.add(item)
    db.commit()
    return {"code": 200, "msg": "success", "data": {"batch_id": item.batch_id}}


@router.post("/pivas/transition")
def transition_pivas(req: dict, current_user: User = Depends(require_roles(*PIVAS_ROLES)), db: Session = Depends(get_db)):
    """状态流转：排药→配置→核对→配送→签收。配置人/核对人/配送人按当前登录人登记。"""
    item = db.query(PivasBatch).filter(PivasBatch.batch_id == req.get("batch_id")).first()
    if not item:
        return {"code": 500, "msg": "批次不存在"}
    target = req.get("status")
    if target not in PIVAS_FLOW.get(item.status, set()):
        return {"code": 400, "msg": f"状态不允许从「{PIVAS_STATUS.get(item.status)}」迁移到「{PIVAS_STATUS.get(target, target)}」"}
    if target == 2:
        item.dispenser_id = current_user.user_id
    elif target == 3:
        if item.dispenser_id == current_user.user_id:
            return {"code": 400, "msg": "成品核对不能由调配人本人执行（双人复核）"}
        item.checker_id = current_user.user_id
    elif target == 4:
        item.courier_id = current_user.user_id
    elif target == 5:
        item.receive_time = datetime.datetime.now()
    item.status = target
    db.add(item)
    db.commit()
    return {"code": 200, "msg": "success"}


# ---------------- ICU/PACU 评分 ----------------

GCS_ITEMS = {"eye": (4, "睁眼"), "verbal": (5, "语言"), "motor": (6, "运动")}


def _compute_score(score_type: str, detail: dict) -> tuple[int, str]:
    """按评分类型汇总得分并给出结论。分项值由录入者按评分表填写。"""
    if score_type == "gcs":
        eye = int(detail.get("eye", 4))
        verbal = int(detail.get("verbal", 5))
        motor = int(detail.get("motor", 6))
        for (low, _), val in zip(GCS_ITEMS.values(), (eye, verbal, motor)):
            if not 1 <= val <= low + 0:  # eye 1-4, verbal 1-5, motor 1-6
                raise ValueError("GCS 分项取值不合法（睁眼1-4/语言1-5/运动1-6）")
        total = eye + verbal + motor
        interp = "轻度" if total >= 13 else "中度" if total >= 9 else "重度意识障碍"
        return total, interp
    if score_type == "apache2":
        age = int(detail.get("age_points", 0))
        chronic = int(detail.get("chronic_health_points", 0))
        aps = detail.get("aps_total")
        if aps is None:
            raise ValueError("APACHE II 必须填写急性生理学评分合计（APS）")
        total = age + int(aps) + chronic
        if not 0 <= total <= 71:
            raise ValueError("APACHE II 总分应在 0-71 之间")
        interp = f"死亡风险分级：{'低' if total <= 9 else '中' if total <= 19 else '高' if total <= 29 else '极高'}（{total} 分）"
        return total, interp
    if score_type == "sofa":
        items = {k: v for k, v in detail.items() if k.endswith("_score")}
        total = sum(int(v) for v in items.values())
        if not 0 <= total <= 24:
            raise ValueError("SOFA 总分应在 0-24 之间")
        interp = "脏器功能：良好" if total < 6 else "损伤" if total < 11 else "衰竭风险高"
        return total, interp
    if score_type == "aldrete":
        total = sum(int(v) for k, v in detail.items() if k.endswith("_score"))
        if not 0 <= total <= 10:
            raise ValueError("Aldrete 总分应在 0-10 之间")
        interp = "达 PACU 转出标准（≥9）" if total >= 9 else "未达转出标准（需 ≥9）"
        return total, interp
    if score_type == "steward":
        total = sum(int(v) for k, v in detail.items() if k.endswith("_score"))
        if not 0 <= total <= 6:
            raise ValueError("Steward 总分应在 0-6 之间")
        interp = "达转出标准（≥4）" if total >= 4 else "未达转出标准（需 ≥4）"
        return total, interp
    raise ValueError("评分类型必须为 apache2/sofa/gcs/aldrete/steward")


def _score_ser(s: IcuScoreRecord) -> dict:
    return {
        "score_id": s.score_id,
        "patient_id": s.patient_id,
        "patient_name": s.patient.name if s.patient else "",
        "admission_id": s.admission_id or "",
        "score_type": s.score_type,
        "score_type_text": {"apache2": "APACHE II", "sofa": "SOFA", "gcs": "GCS", "aldrete": "Aldrete", "steward": "Steward"}.get(s.score_type, s.score_type),
        "scene": s.scene,
        "total_score": s.total_score,
        "interpretation": s.interpretation or "",
        "assess_time": s.assess_time.strftime("%Y-%m-%d %H:%M:%S") if s.assess_time else "",
    }


@router.get("/icuScore/getList")
def list_scores(patient_id: int | None = None, score_type: str | None = None, scene: str | None = None, current_user: User = Depends(require_roles(*SCORE_ROLES)), db: Session = Depends(get_db)):
    query = db.query(IcuScoreRecord)
    if patient_id is not None:
        query = query.filter(IcuScoreRecord.patient_id == patient_id)
    if score_type:
        query = query.filter(IcuScoreRecord.score_type == score_type)
    if scene:
        query = query.filter(IcuScoreRecord.scene == scene)
    rows = query.order_by(IcuScoreRecord.score_id.desc()).limit(1000).all()
    return {"code": 200, "msg": "success", "data": [_score_ser(s) for s in rows]}


@router.post("/icuScore/create")
def create_score(req: dict, current_user: User = Depends(require_roles(*SCORE_ROLES)), db: Session = Depends(get_db)):
    patient = db.query(Patient).filter(Patient.patient_id == req.get("patient_id")).first()
    if not patient:
        return {"code": 500, "msg": "患者不存在"}
    score_type = (req.get("score_type") or "").strip()
    detail = req.get("detail") or {}
    try:
        total, interp = _compute_score(score_type, detail)
    except ValueError as e:
        return {"code": 400, "msg": str(e)}
    item = IcuScoreRecord(
        patient_id=patient.patient_id,
        admission_id=(req.get("admission_id") or "").strip() or None,
        score_type=score_type,
        scene=(req.get("scene") or "icu").strip(),
        total_score=total,
        detail_json=json.dumps(detail, ensure_ascii=False),
        interpretation=interp,
        assessor_id=current_user.user_id,
        assess_time=datetime.datetime.now(),
        create_time=datetime.datetime.now(),
    )
    db.add(item)
    db.commit()
    return {"code": 200, "msg": "success", "data": {"score_id": item.score_id, "total_score": total, "interpretation": interp}}


# ---------------- 临床路径入组 ----------------

ENROLL_STATUS = {1: "在径", 2: "变异", 3: "完成出径", 4: "退出"}


def _enroll_ser(e: PathwayEnrollment) -> dict:
    return {
        "enrollment_id": e.enrollment_id,
        "pathway_id": e.pathway_id,
        "pathway_name": e.pathway.name if e.pathway else "",
        "patient_id": e.patient_id,
        "patient_name": e.patient.name if e.patient else "",
        "admission_id": e.admission_id or "",
        "doctor_id": e.doctor_id,
        "status": e.status,
        "status_text": ENROLL_STATUS.get(e.status, str(e.status)),
        "enroll_date": e.enroll_date.isoformat() if e.enroll_date else "",
        "exit_date": e.exit_date.isoformat() if e.exit_date else "",
        "variation_reason": e.variation_reason or "",
        "variation_type": e.variation_type or "",
        "exit_reason": e.exit_reason or "",
        "completed_items": e.completed_items or 0,
        "total_items": e.total_items or 0,
        "completion_rate": round(e.completed_items / e.total_items * 100, 1) if e.total_items else None,
    }


@router.get("/pathwayEnrollment/getList")
def list_enrollments(status: int | None = None, pathway_id: int | None = None, current_user: User = Depends(require_roles(*PATHWAY_ROLES)), db: Session = Depends(get_db)):
    query = db.query(PathwayEnrollment)
    if status is not None:
        query = query.filter(PathwayEnrollment.status == status)
    if pathway_id is not None:
        query = query.filter(PathwayEnrollment.pathway_id == pathway_id)
    rows = query.order_by(PathwayEnrollment.enrollment_id.desc()).limit(1000).all()
    return {"code": 200, "msg": "success", "data": [_enroll_ser(e) for e in rows]}


@router.post("/pathwayEnrollment/enroll")
def enroll_pathway(req: dict, current_user: User = Depends(require_roles(*PATHWAY_ROLES)), db: Session = Depends(get_db)):
    from app.models import ClinicalPathway, Doctor

    pathway = db.query(ClinicalPathway).filter(ClinicalPathway.pathway_id == req.get("pathway_id")).first()
    if not pathway or pathway.status != 0:
        return {"code": 500, "msg": "路径不存在或已停用"}
    patient = db.query(Patient).filter(Patient.patient_id == req.get("patient_id")).first()
    if not patient:
        return {"code": 500, "msg": "患者不存在"}
    active = db.query(PathwayEnrollment).filter(
        PathwayEnrollment.patient_id == patient.patient_id,
        PathwayEnrollment.status.in_((1, 2)),
    ).first()
    if active:
        return {"code": 500, "msg": "该患者已有在径/变异记录，不能重复入组"}
    doctor = db.query(Doctor).filter(Doctor.user_id == current_user.user_id).first()
    try:
        total_items = int(req.get("total_items", 0) or 0)
    except (TypeError, ValueError):
        total_items = 0
    item = PathwayEnrollment(
        pathway_id=pathway.pathway_id,
        patient_id=patient.patient_id,
        admission_id=(req.get("admission_id") or "").strip() or None,
        doctor_id=doctor.doctor_id if doctor else None,
        status=1,
        enroll_date=datetime.date.today(),
        total_items=total_items,
        create_time=datetime.datetime.now(),
    )
    db.add(item)
    db.commit()
    return {"code": 200, "msg": "success", "data": {"enrollment_id": item.enrollment_id}}


@router.post("/pathwayEnrollment/record")
def record_progress(req: dict, current_user: User = Depends(require_roles(*PATHWAY_ROLES)), db: Session = Depends(get_db)):
    """登记完成节点数（completed_items 递增累计）。"""
    item = db.query(PathwayEnrollment).filter(PathwayEnrollment.enrollment_id == req.get("enrollment_id")).first()
    if not item:
        return {"code": 500, "msg": "入组记录不存在"}
    if item.status not in (1, 2):
        return {"code": 500, "msg": "已出径/退出记录不能继续登记进度"}
    try:
        done = int(req.get("completed_items", 0) or 0)
    except (TypeError, ValueError):
        return {"code": 400, "msg": "完成节点数必须为整数"}
    if done < 0 or (item.total_items and done > item.total_items):
        return {"code": 400, "msg": f"完成节点数应在 0-{item.total_items or done} 之间"}
    item.completed_items = done
    item.update_time = datetime.datetime.now()
    db.add(item)
    db.commit()
    return {"code": 200, "msg": "success"}


@router.post("/pathwayEnrollment/variation")
def record_variation(req: dict, current_user: User = Depends(require_roles(*PATHWAY_ROLES)), db: Session = Depends(get_db)):
    item = db.query(PathwayEnrollment).filter(PathwayEnrollment.enrollment_id == req.get("enrollment_id")).first()
    if not item:
        return {"code": 500, "msg": "入组记录不存在"}
    if item.status != 1:
        return {"code": 500, "msg": "仅在径状态可登记变异"}
    reason = (req.get("variation_reason") or "").strip()
    vtype = (req.get("variation_type") or "").strip()
    if not reason or vtype not in ("病情变异", "医方变异", "患方变异", "系统变异"):
        return {"code": 400, "msg": "变异原因必填，类型必须为 病情/医方/患方/系统变异"}
    item.status = 2
    item.variation_reason = reason
    item.variation_type = vtype
    item.update_time = datetime.datetime.now()
    db.add(item)
    db.commit()
    return {"code": 200, "msg": "success"}


@router.post("/pathwayEnrollment/exit")
def exit_pathway(req: dict, current_user: User = Depends(require_roles(*PATHWAY_ROLES)), db: Session = Depends(get_db)):
    """完成出径（3，应完成节点全部完成）或退出（4，填原因）。"""
    item = db.query(PathwayEnrollment).filter(PathwayEnrollment.enrollment_id == req.get("enrollment_id")).first()
    if not item:
        return {"code": 500, "msg": "入组记录不存在"}
    target = req.get("status")
    if target not in (3, 4):
        return {"code": 400, "msg": "出径操作只能为 3 完成出径 / 4 退出"}
    if item.status not in (1, 2):
        return {"code": 500, "msg": "已终态记录不能再次出径"}
    if target == 3:
        if item.total_items and item.completed_items < item.total_items:
            return {"code": 400, "msg": f"尚有 {item.total_items - item.completed_items} 个节点未完成，不能完成出径"}
    else:
        if not (req.get("exit_reason") or "").strip():
            return {"code": 400, "msg": "退出必须填写原因"}
        item.exit_reason = (req["exit_reason"]).strip()
    item.status = target
    item.exit_date = datetime.date.today()
    item.update_time = datetime.datetime.now()
    db.add(item)
    db.commit()
    return {"code": 200, "msg": "success"}
