"""病案首页 ICD 编码工作台：文本诊断/手术 → ICD 码绑定，主要诊断唯一。"""
import datetime

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import ADMIN_ROLES, CLINICAL_ROLES, User, require_roles
from app.models import HomeIcdBinding, Icd10Diagnosis, Icd10Operation, MedicalRecordHome

router = APIRouter()

CODER_ROLES = ADMIN_ROLES | CLINICAL_ROLES  # 病案编码员/医生/管理员


def _ser(b: HomeIcdBinding) -> dict:
    return {
        "binding_id": b.binding_id,
        "home_id": b.home_id,
        "kind": b.kind,
        "kind_text": "诊断编码" if b.kind == "diagnosis" else "手术编码",
        "icd_code": b.icd_code,
        "icd_name": b.icd_name,
        "is_primary": b.is_primary,
        "coder_name": b.coder.username if b.coder else "",
        "code_time": b.code_time.strftime("%Y-%m-%d %H:%M:%S") if b.code_time else "",
        "remark": b.remark or "",
    }


@router.get("/homeIcd/getList")
def list_bindings(home_id: str | None = None, kind: str | None = None, current_user: User = Depends(require_roles(*CODER_ROLES)), db: Session = Depends(get_db)):
    query = db.query(HomeIcdBinding)
    if home_id:
        query = query.filter(HomeIcdBinding.home_id == home_id)
    if kind:
        query = query.filter(HomeIcdBinding.kind == kind)
    rows = query.order_by(HomeIcdBinding.binding_id.desc()).limit(2000).all()
    return {"code": 200, "msg": "success", "data": [_ser(b) for b in rows]}


@router.get("/homeIcd/uncoded")
def list_uncoded(current_user: User = Depends(require_roles(*CODER_ROLES)), db: Session = Depends(get_db)):
    """编码工作台待办：已提交/已归档首页中尚无诊断编码绑定的病案。"""
    homes = db.query(MedicalRecordHome).filter(MedicalRecordHome.status.in_((1, 2))).order_by(MedicalRecordHome.update_time.desc()).limit(500).all()
    coded_home_ids = {b[0] for b in db.query(HomeIcdBinding.home_id).filter(HomeIcdBinding.kind == "diagnosis").distinct().all()}
    data = [{
        "home_id": h.home_id,
        "admission_no": h.admission.admission_no if h.admission else "",
        "patient_name": h.patient.name if h.patient else "",
        "admission_diagnosis": h.admission_diagnosis,
        "discharge_diagnosis": h.discharge_diagnosis or "",
        "other_diagnosis": h.other_diagnosis or "",
        "operation_summary": h.operation_summary or "",
        "status": h.status,
        "status_text": {0: "草稿", 1: "已提交", 2: "已归档"}.get(h.status, str(h.status)),
    } for h in homes if h.home_id not in coded_home_ids]
    return {"code": 200, "msg": "success", "data": data}


@router.post("/homeIcd/bind")
def bind_icd(req: dict, current_user: User = Depends(require_roles(*CODER_ROLES)), db: Session = Depends(get_db)):
    home = db.query(MedicalRecordHome).filter(MedicalRecordHome.home_id == req.get("home_id")).first()
    if not home:
        return {"code": 500, "msg": "病案首页不存在"}
    kind = req.get("kind")
    if kind not in ("diagnosis", "operation"):
        return {"code": 400, "msg": "编码类型必须为 diagnosis/operation"}
    code = (req.get("icd_code") or "").strip().upper()
    if not code:
        return {"code": 400, "msg": "ICD 编码不能为空"}
    # 编码必须在字典内（诊断查 Icd10Diagnosis，手术查 Icd10Operation），名称取字典标准名
    if kind == "diagnosis":
        dic = db.query(Icd10Diagnosis).filter(Icd10Diagnosis.code == code, Icd10Diagnosis.status == 1).first()
    else:
        dic = db.query(Icd10Operation).filter(Icd10Operation.code == code, Icd10Operation.status == 1).first()
    if not dic:
        return {"code": 500, "msg": f"ICD 编码 [{code}] 不在{'诊断' if kind == 'diagnosis' else '手术'}字典中，请先维护字典"}
    is_primary = 1 if req.get("is_primary") else 0
    if is_primary:
        # 同首页同类型主要编码唯一：置主前清掉已有主标记
        existing_primary = db.query(HomeIcdBinding).filter(
            HomeIcdBinding.home_id == home.home_id,
            HomeIcdBinding.kind == kind,
            HomeIcdBinding.is_primary == 1,
        ).first()
        if existing_primary:
            existing_primary.is_primary = 0
            db.add(existing_primary)
    dup = db.query(HomeIcdBinding).filter(
        HomeIcdBinding.home_id == home.home_id,
        HomeIcdBinding.kind == kind,
        HomeIcdBinding.icd_code == code,
    ).first()
    if dup:
        return {"code": 500, "msg": "该首页已绑定此编码"}
    item = HomeIcdBinding(
        home_id=home.home_id,
        kind=kind,
        icd_code=dic.code,
        icd_name=dic.name,
        is_primary=is_primary,
        coder_id=current_user.user_id,
        code_time=datetime.datetime.now(),
        remark=(req.get("remark") or "").strip() or None,
    )
    db.add(item)
    db.commit()
    return {"code": 200, "msg": "success", "data": {"binding_id": item.binding_id}}


@router.post("/homeIcd/unbind")
def unbind_icd(req: dict, current_user: User = Depends(require_roles(*CODER_ROLES)), db: Session = Depends(get_db)):
    item = db.query(HomeIcdBinding).filter(HomeIcdBinding.binding_id == req.get("binding_id")).first()
    if not item:
        return {"code": 500, "msg": "编码绑定不存在"}
    db.delete(item)
    db.commit()
    return {"code": 200, "msg": "success"}


@router.post("/homeIcd/setPrimary")
def set_primary(req: dict, current_user: User = Depends(require_roles(*CODER_ROLES)), db: Session = Depends(get_db)):
    """改主诊断/主手术：清除同首页同类型其他主标记。"""
    item = db.query(HomeIcdBinding).filter(HomeIcdBinding.binding_id == req.get("binding_id")).first()
    if not item:
        return {"code": 500, "msg": "编码绑定不存在"}
    db.query(HomeIcdBinding).filter(
        HomeIcdBinding.home_id == item.home_id,
        HomeIcdBinding.kind == item.kind,
        HomeIcdBinding.is_primary == 1,
        HomeIcdBinding.binding_id != item.binding_id,
    ).update({HomeIcdBinding.is_primary: 0}, synchronize_session=False)
    item.is_primary = 1
    db.add(item)
    db.commit()
    return {"code": 200, "msg": "success"}


@router.get("/homeIcd/statistics")
def icd_statistics(current_user: User = Depends(require_roles(*CODER_ROLES)), db: Session = Depends(get_db)):
    """编码覆盖率统计：按主要诊断 ICD 码统计病案数（可用于单病种/上报汇总）。"""
    homes = db.query(MedicalRecordHome).filter(MedicalRecordHome.status.in_((1, 2))).count()
    diagnosed = db.query(HomeIcdBinding.home_id).filter(HomeIcdBinding.kind == "diagnosis").distinct().count()
    primary_rows = (
        db.query(HomeIcdBinding.icd_code, HomeIcdBinding.icd_name)
        .filter(HomeIcdBinding.kind == "diagnosis", HomeIcdBinding.is_primary == 1)
        .all()
    )
    by_code: dict[str, dict] = {}
    for code, name in primary_rows:
        by_code.setdefault(code, {"icd_code": code, "icd_name": name, "count": 0})["count"] += 1
    top10 = sorted(by_code.values(), key=lambda x: -x["count"])[:10]
    return {
        "code": 200,
        "msg": "success",
        "data": {
            "total_homes": homes,
            "coded_homes": diagnosed,
            "coverage_rate": round(diagnosed / homes * 100, 1) if homes else None,
            "top_primary_diagnosis": top10,
        },
    }
