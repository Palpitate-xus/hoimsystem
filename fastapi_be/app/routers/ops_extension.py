"""运营扩展：CSSD 器械包 / PIVAS 批次 / ICU-PACU 评分 / 临床路径入组。"""

import datetime
import json

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.clinical_scores import CALCULATION_VERSION, LEGACY_CALCULATION_VERSION, SCORE_DEFINITIONS, ManualScoreRequest, compute_manual_score, inspect_manual_components
from app.database import get_db
from app.dependencies import ADMIN_ROLES, CLINICAL_ROLES, NURSING_ROLES, PHARMACY_ROLES, User, require_roles
from app.models import Admission, CssdInstrument, IcuScoreRecord, PathwayEnrollment, Patient, PivasBatch
from app.pathway_progress import pathway_progress

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

def _compute_score(score_type: str, detail: dict) -> tuple[int, str]:
    """Compatibility helper for the strict, explicitly versioned manual sum."""
    return compute_manual_score(score_type, detail)


def _score_ser(s: IcuScoreRecord) -> dict:
    try:
        detail = json.loads(s.detail_json) if s.detail_json is not None else None
    except (ValueError, TypeError):
        detail = None
    version = getattr(s, "calculation_version", None) or LEGACY_CALCULATION_VERSION
    legacy = version != CALCULATION_VERSION
    definition = SCORE_DEFINITIONS.get(s.score_type)
    assessed_at = getattr(s, "assessed_at", None)
    assessed_iso = None
    if assessed_at is not None:
        assessed_at = assessed_at.replace(tzinfo=datetime.UTC) if assessed_at.tzinfo is None else assessed_at.astimezone(datetime.UTC)
        assessed_iso = assessed_at.isoformat().replace("+00:00", "Z")
    return {
        "score_id": s.score_id,
        "patient_id": s.patient_id,
        "patient_name": s.patient.name if s.patient else "",
        "admission_id": s.admission_id or None,
        "admission_linkage": "recorded_not_independently_verified" if s.admission_id else "not_recorded",
        "score_type": s.score_type,
        "score_type_text": definition.label
        if definition and not legacy
        else {"apache2": "APACHE II", "sofa": "SOFA", "gcs": "GCS", "aldrete": "Aldrete", "steward": "Steward"}.get(s.score_type, s.score_type),
        "score_definition": definition.edition if definition and not legacy else "legacy_unverified",
        "scene": s.scene,
        "total_score": s.total_score,
        "detail": detail,
        "calculation_version": version,
        "legacy_unverified": legacy,
        "component_integrity": inspect_manual_components(s.score_type, detail, s.total_score, version),
        "source_verification": "not_independently_verified",
        "clinical_validation": "not_provided",
        "calculation_method": "legacy_unverified" if legacy else "manual_component_sum",
        "interpretation": s.interpretation or "",
        "assessed_at": assessed_iso,
        "time_basis": "assessed_at_declared" if assessed_iso else "assessment_time_unknown",
        "assess_time": s.assess_time.strftime("%Y-%m-%d %H:%M:%S") if s.assess_time else "",
        "create_time": s.create_time.strftime("%Y-%m-%d %H:%M:%S") if s.create_time else "",
        "scope_note": "分项完整性仅核对固定字段、整数范围与汇总，不证明原始观察、人工赋分或临床判断正确；assess_time/create_time是原录入记录时间，不替代实际评估时间。未绑定住院时不按场景或日期推定住院归属。"
        + ("历史版本保留原总分与原解释，未经本版核实，不能视为当前计算结论。" if legacy else ""),
    }


@router.get("/icuScore/getList", response_class=JSONResponse)
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


@router.post("/icuScore/create", response_class=JSONResponse)
def create_score(req: dict, response: Response, current_user: User = Depends(require_roles(*SCORE_ROLES)), db: Session = Depends(get_db)):
    try:
        parsed = ManualScoreRequest.model_validate(req)
        total, interp = compute_manual_score(parsed.score_type, parsed.detail)
    except ValidationError as exc:
        response.status_code = 400
        problem = exc.errors(include_input=False, include_url=False)[0]
        return {"code": 400, "msg": "评分请求无效：" + ".".join(map(str, problem["loc"])) + " " + problem["msg"]}
    except ValueError as e:
        response.status_code = 400
        return {"code": 400, "msg": str(e)}
    patient = db.get(Patient, parsed.patient_id)
    if patient is None:
        response.status_code = 404
        return {"code": 404, "msg": "患者不存在"}
    if parsed.admission_id is not None:
        admission = db.get(Admission, parsed.admission_id)
        if admission is None or admission.patient_id != patient.patient_id:
            response.status_code = 400
            return {"code": 400, "msg": "住院记录不存在或不属于所选患者"}
    recorded_at = datetime.datetime.now(datetime.UTC).replace(tzinfo=None)
    item = IcuScoreRecord(
        patient_id=patient.patient_id,
        admission_id=parsed.admission_id,
        score_type=parsed.score_type,
        scene=parsed.scene,
        total_score=total,
        detail_json=json.dumps(parsed.detail, ensure_ascii=False),
        interpretation=interp,
        calculation_version=CALCULATION_VERSION,
        assessed_at=parsed.assessed_at,
        assessor_id=current_user.user_id,
        assess_time=recorded_at,
        create_time=recorded_at,
    )
    db.add(item)
    db.commit()
    return {"code": 200, "msg": "success", "data": _score_ser(item)}


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
        "completed_items": e.completed_items,
        "total_items": e.total_items,
        **pathway_progress(e.completed_items, e.total_items),
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
    admission_id = req.get("admission_id")
    if admission_id is not None and (not isinstance(admission_id, str) or len(admission_id) > 36):
        raise HTTPException(422, "住院标识格式不正确")
    admission_id = (admission_id or "").strip() or None
    if admission_id:
        admission = db.get(Admission, admission_id)
        if admission is None or admission.patient_id != patient.patient_id:
            raise HTTPException(422, "所选住院不存在或不属于入径患者")
    active = (
        db.query(PathwayEnrollment)
        .filter(
            PathwayEnrollment.patient_id == patient.patient_id,
            PathwayEnrollment.status.in_((1, 2)),
        )
        .first()
    )
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
        admission_id=admission_id,
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
