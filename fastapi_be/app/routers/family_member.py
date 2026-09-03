import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import ROLE_PATIENT, require_roles
from app.models import FamilyMember, Patient, User
from app.schemas import FamilyMemberCreateRequest, FamilyMemberUpdateRequest, IdRequest

router = APIRouter()


def _owner_patient(current_user: User, db: Session) -> Patient:
    patient = db.query(Patient).filter(Patient.identity == current_user.username).first()
    if not patient:
        raise HTTPException(status_code=404, detail="患者信息不存在")
    return patient


def _parse_birthday(value: str | None):
    if not value:
        return None
    try:
        return datetime.datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="出生日期格式必须为 YYYY-MM-DD") from exc


def _serialize(item: FamilyMember):
    patient = item.member_patient
    return {
        "id": item.family_member_id,
        "family_member_id": item.family_member_id,
        "patient_id": patient.patient_id,
        "name": patient.name,
        "identity": patient.identity,
        "relation": item.relation,
        "sex": patient.sex,
        "birthday": patient.birthday.isoformat() if patient.birthday else None,
        "phone": patient.phone or "",
        "address": patient.address or "",
        "allergy_history": patient.allergy_history or "",
        "create_time": item.create_time,
        "update_time": item.update_time,
    }


@router.get("/familyMember/list")
def list_family_members(
    current_user: User = Depends(require_roles(ROLE_PATIENT)),
    db: Session = Depends(get_db),
):
    owner = _owner_patient(current_user, db)
    items = db.query(FamilyMember).filter(FamilyMember.owner_patient_id == owner.patient_id).order_by(FamilyMember.family_member_id).all()
    return {"code": 200, "msg": "success", "data": [_serialize(item) for item in items]}


@router.post("/familyMember/create")
def create_family_member(
    req: FamilyMemberCreateRequest,
    current_user: User = Depends(require_roles(ROLE_PATIENT)),
    db: Session = Depends(get_db),
):
    owner = _owner_patient(current_user, db)
    if req.identity == owner.identity:
        return {"code": 500, "msg": "不能将本人添加为家庭成员"}
    if db.query(FamilyMember).filter(FamilyMember.owner_patient_id == owner.patient_id, FamilyMember.member_patient.has(identity=req.identity)).first():
        return {"code": 500, "msg": "该家庭成员已存在"}
    existing_patient = db.query(Patient).filter(Patient.identity == req.identity).first()
    if existing_patient and db.query(FamilyMember).filter(FamilyMember.member_patient_id == existing_patient.patient_id).first():
        return {"code": 500, "msg": "该患者已被其他家庭账号绑定"}
    if existing_patient and existing_patient.permission == "allow":
        # 已独立注册/就诊的患者档案不允许他人凭身份证号直接绑定，
        # 防止通过已知身份证号读取他人联系方式与过敏史（PHI 越权）。
        return {"code": 500, "msg": "该患者已注册，不能被添加为家庭成员"}
    member_patient = existing_patient or Patient(
        name=req.name,
        sex=req.sex,
        identity=req.identity,
        birthday=_parse_birthday(req.birthday),
        phone=req.phone,
        address=req.address,
        permission="family",
        allergy_history=req.allergy_history,
    )
    if existing_patient:
        if existing_patient.name != req.name or existing_patient.sex != req.sex:
            return {"code": 500, "msg": "身份证号与已有患者资料不一致"}
    now = datetime.datetime.now()
    db.add(member_patient)
    db.flush()
    db.add(FamilyMember(owner_patient_id=owner.patient_id, member_patient_id=member_patient.patient_id, relation=req.relation, create_time=now, update_time=now))
    db.commit()
    item = db.query(FamilyMember).filter(FamilyMember.owner_patient_id == owner.patient_id, FamilyMember.member_patient_id == member_patient.patient_id).one()
    return {"code": 200, "msg": "success", "data": _serialize(item)}


@router.put("/familyMember/update")
def update_family_member(
    req: FamilyMemberUpdateRequest,
    current_user: User = Depends(require_roles(ROLE_PATIENT)),
    db: Session = Depends(get_db),
):
    owner = _owner_patient(current_user, db)
    item = db.query(FamilyMember).filter(FamilyMember.family_member_id == req.family_member_id, FamilyMember.owner_patient_id == owner.patient_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="家庭成员不存在")
    patient = item.member_patient
    patient.name = req.name
    patient.sex = req.sex
    patient.birthday = _parse_birthday(req.birthday)
    patient.phone = req.phone
    patient.address = req.address
    patient.allergy_history = req.allergy_history
    item.relation = req.relation
    item.update_time = datetime.datetime.now()
    db.commit()
    return {"code": 200, "msg": "success", "data": _serialize(item)}


@router.delete("/familyMember/delete")
def delete_family_member(
    req: IdRequest,
    current_user: User = Depends(require_roles(ROLE_PATIENT)),
    db: Session = Depends(get_db),
):
    owner = _owner_patient(current_user, db)
    item = db.query(FamilyMember).filter(FamilyMember.family_member_id == req.id, FamilyMember.owner_patient_id == owner.patient_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="家庭成员不存在")
    db.delete(item)
    db.commit()
    return {"code": 200, "msg": "success"}
