import datetime

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import ADMIN_ROLES, CLINICAL_ROLES, NURSING_ROLES, ROLE_DIRECTOR, User, require_roles
from app.models import BloodCrossMatch, BloodIssue, BloodRequest, Doctor, Patient, TransfusionReaction

router = APIRouter()
BLOOD_ROLES = {*ADMIN_ROLES, ROLE_DIRECTOR, *NURSING_ROLES, *CLINICAL_ROLES}
REVIEW_ROLES = {*ADMIN_ROLES, ROLE_DIRECTOR}


def _request_data(item: BloodRequest):
    return {"request_id": item.request_id, "patient_name": item.patient.name if item.patient else "", "blood_type": item.blood_type, "component": item.component, "volume": item.volume, "reason": item.reason, "blood_type_verified": item.blood_type_verified, "status": item.status, "status_text": {0: "待审批", 1: "已批准", 2: "已退回", 3: "已发血"}.get(item.status, ""), "create_time": item.create_time.strftime("%Y-%m-%d %H:%M:%S") if item.create_time else ""}


@router.get("/blood/request/list")
def list_blood_requests(current_user: User = Depends(require_roles(*BLOOD_ROLES)), db: Session = Depends(get_db)):
    return {"code": 200, "msg": "success", "data": [_request_data(item) for item in db.query(BloodRequest).order_by(BloodRequest.create_time.desc()).all()]}


@router.post("/blood/request/create")
def create_blood_request(req: dict, current_user: User = Depends(require_roles(*CLINICAL_ROLES)), db: Session = Depends(get_db)):
    patient = db.query(Patient).filter(Patient.patient_id == req.get("patient_id")).first()
    if not patient or not req.get("blood_type") or not req.get("component") or not req.get("reason"):
        return {"code": 400, "msg": "患者、血型、血液成分和申请理由不能为空"}
    doctor = db.query(Doctor).filter(Doctor.user_id == current_user.user_id).first()
    item = BloodRequest(patient_id=patient.patient_id, doctor_id=doctor.doctor_id if doctor else None, blood_type=req["blood_type"], component=req["component"], volume=int(req.get("volume", 0)), reason=req["reason"], applicant_id=current_user.user_id, create_time=datetime.datetime.now())
    if item.volume <= 0:
        return {"code": 400, "msg": "申请量必须大于0"}
    db.add(item)
    db.commit()
    return {"code": 200, "msg": "success", "data": {"request_id": item.request_id}}


@router.post("/blood/request/review")
def review_blood_request(req: dict, current_user: User = Depends(require_roles(*REVIEW_ROLES)), db: Session = Depends(get_db)):
    item = db.query(BloodRequest).filter(BloodRequest.request_id == req.get("request_id"), BloodRequest.status == 0).first()
    if not item:
        return {"code": 404, "msg": "待审批用血申请不存在"}
    if req.get("status") not in (1, 2):
        return {"code": 400, "msg": "审批状态必须为1或2"}
    item.status = req["status"]
    item.reviewer_id = current_user.user_id
    item.review_time = datetime.datetime.now()
    db.commit()
    return {"code": 200, "msg": "审批完成"}


@router.post("/blood/recheck")
def recheck_blood_type(req: dict, current_user: User = Depends(require_roles(*BLOOD_ROLES)), db: Session = Depends(get_db)):
    item = db.query(BloodRequest).filter(BloodRequest.request_id == req.get("request_id")).first()
    if not item:
        return {"code": 404, "msg": "用血申请不存在"}
    if not req.get("verified"):
        return {"code": 400, "msg": "血型复核未通过"}
    item.blood_type_verified = 1
    db.commit()
    return {"code": 200, "msg": "血型复核通过"}


# ABO 相容表：受血者血型 → 可接受的供血者血型（红细胞输注规则）
ABO_COMPATIBLE = {
    "A": {"A", "O"},
    "B": {"B", "O"},
    "AB": {"A", "B", "AB", "O"},
    "O": {"O"},
}


def _abo_group(blood_type: str) -> str | None:
    """提取 ABO 血型族（去掉 Rh 的 +/- 后缀），如 'A+' -> 'A'。"""
    text = (blood_type or "").strip().upper().replace("ＲＨ", "").replace("RH", "")
    for group in ("AB", "A", "B", "O"):
        if text.startswith(group):
            return group
    return None


@router.post("/blood/crossMatch")
def cross_match(req: dict, current_user: User = Depends(require_roles(*BLOOD_ROLES)), db: Session = Depends(get_db)):
    request = db.query(BloodRequest).filter(BloodRequest.request_id == req.get("request_id"), BloodRequest.status == 1, BloodRequest.blood_type_verified == 1).first()
    if not request:
        return {"code": 400, "msg": "申请未批准或血型尚未复核"}
    item = BloodCrossMatch(request_id=request.request_id, donor_blood_type=req.get("donor_blood_type", ""), result=req.get("result", "").strip(), pass_flag=int(req.get("pass_flag", 0)), operator_id=current_user.user_id, match_time=datetime.datetime.now())
    if not item.donor_blood_type or not item.result:
        return {"code": 400, "msg": "供血血型和配血结果不能为空"}
    # ABO 相容性校验：供受血型不相容时禁止标记配血合格（防急性溶血反应）
    recipient = _abo_group(request.blood_type)
    donor = _abo_group(item.donor_blood_type)
    if recipient is None:
        return {"code": 400, "msg": f"受血者血型 [{request.blood_type}] 无法识别，请先维护血型"}
    if donor is None:
        return {"code": 400, "msg": f"供血血型 [{item.donor_blood_type}] 无法识别"}
    if donor not in ABO_COMPATIBLE[recipient]:
        return {"code": 400, "msg": f"ABO 血型不相容：{recipient} 型受血者不可接受 {donor} 型供血"}
    db.add(item)
    db.commit()
    return {"code": 200, "msg": "success", "data": {"cross_match_id": item.cross_match_id}}


@router.post("/blood/issue")
def issue_blood(req: dict, current_user: User = Depends(require_roles(*BLOOD_ROLES)), db: Session = Depends(get_db)):
    request = db.query(BloodRequest).filter(BloodRequest.request_id == req.get("request_id"), BloodRequest.status == 1, BloodRequest.blood_type_verified == 1).first()
    if not request:
        return {"code": 400, "msg": "申请未达到发血条件"}
    match = db.query(BloodCrossMatch).filter(BloodCrossMatch.request_id == request.request_id, BloodCrossMatch.pass_flag == 1).first()
    if not match:
        return {"code": 400, "msg": "请先完成合格交叉配血"}
    volume = int(req.get("volume") or request.volume or 0)
    # 超量校验：累计已发量 + 本次 ≤ 批准申请量
    issued_total = (
        db.query(func.coalesce(func.sum(BloodIssue.volume), 0))
        .filter(BloodIssue.request_id == request.request_id)
        .scalar()
    ) or 0
    if volume <= 0:
        return {"code": 400, "msg": "发血量必须大于0"}
    if issued_total + volume > (request.volume or 0):
        return {"code": 400, "msg": f"发血量超出申请量：已发 {issued_total}，本次 {volume}，申请 {(request.volume or 0)}"}
    # 血袋号唯一性：同一血袋不得重复发放
    unit_no = req.get("unit_no", "").strip()
    if not unit_no:
        return {"code": 400, "msg": "血袋编号不能为空"}
    dup = db.query(BloodIssue).filter(BloodIssue.unit_no == unit_no).first()
    if dup:
        return {"code": 400, "msg": f"血袋 [{unit_no}] 已发放过，禁止重复发放"}
    item = BloodIssue(request_id=request.request_id, unit_no=unit_no, component=request.component, volume=volume, issuer_id=current_user.user_id, issue_time=datetime.datetime.now())
    # 分次发血：发满申请量才终态化申请单
    request.status = 3 if issued_total + volume >= (request.volume or 0) else request.status
    db.add(item)
    db.commit()
    return {"code": 200, "msg": "发血完成", "data": {"issue_id": item.issue_id}}


@router.get("/blood/reaction/list")
def list_reactions(current_user: User = Depends(require_roles(*BLOOD_ROLES)), db: Session = Depends(get_db)):
    items = db.query(TransfusionReaction).order_by(TransfusionReaction.report_time.desc()).all()
    return {"code": 200, "msg": "success", "data": [{"reaction_id": item.reaction_id, "patient_name": item.request.patient.name if item.request and item.request.patient else "", "symptoms": item.symptoms, "severity": item.severity, "action_taken": item.action_taken, "status": item.status, "report_time": item.report_time.strftime("%Y-%m-%d %H:%M:%S")} for item in items]}


@router.post("/blood/reaction/create")
def create_reaction(req: dict, current_user: User = Depends(require_roles(*NURSING_ROLES, *CLINICAL_ROLES)), db: Session = Depends(get_db)):
    request = db.query(BloodRequest).filter(BloodRequest.request_id == req.get("request_id")).first()
    if not request:
        return {"code": 404, "msg": "用血申请不存在"}
    item = TransfusionReaction(request_id=request.request_id, symptoms=req.get("symptoms", "").strip(), severity=int(req.get("severity", 1)), action_taken=req.get("action_taken", "").strip(), reporter_id=current_user.user_id, report_time=datetime.datetime.now())
    if not item.symptoms or not item.action_taken:
        return {"code": 400, "msg": "症状和处置措施不能为空"}
    db.add(item)
    db.commit()
    return {"code": 200, "msg": "success"}
