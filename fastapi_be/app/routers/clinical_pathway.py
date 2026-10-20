import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import CLINICAL_ROLES, User, require_roles
from app.models import ClinicalPathway, PathwayEnrollment

router = APIRouter()


def _validate_status(req):
    if "status" in req and (type(req["status"]) is not int or req["status"] not in {0, 1}):
        raise HTTPException(422, "路径状态须为0启用或1停用")
    if "steps" in req and req["steps"] is not None and (not isinstance(req["steps"], str) or len(req["steps"]) > 1000):
        raise HTTPException(422, "步骤须为不超过1000字符的原JSON文本")


@router.post("/clinicalPathway/create")
def create_pathway(req: dict, current_user: User = Depends(require_roles(*CLINICAL_ROLES)), db: Session = Depends(get_db)):
    _validate_status(req)
    p = ClinicalPathway(
        name=req.get("name", ""),
        disease_code=req.get("disease_code", ""),
        disease_name=req.get("disease_name", ""),
        steps=req.get("steps", "[]"),
        expected_days=req.get("expected_days", 7),
        status=req.get("status", 0),
        create_time=datetime.datetime.now(),
    )
    db.add(p)
    db.commit()
    return {"code": 200, "msg": "success"}


@router.get("/clinicalPathway/getList")
def get_pathway_list(current_user: User = Depends(require_roles(*CLINICAL_ROLES)), db: Session = Depends(get_db)):
    items = db.query(ClinicalPathway).order_by(ClinicalPathway.create_time.desc()).all()
    data = []
    for it in items:
        data.append(
            {
                "pathway_id": it.pathway_id,
                "name": it.name,
                "disease_code": it.disease_code,
                "disease_name": it.disease_name,
                "steps": it.steps,
                "expected_days": it.expected_days,
                "status": it.status,
                "source_revision": it.source_revision,
                "status_text": "启用" if it.status == 0 else "停用",
                "create_time": (it.create_time.strftime("%Y-%m-%d %H:%M:%S") if it.create_time else None) if it.create_time else "",
            }
        )
    return {"code": 200, "msg": "success", "data": data}


@router.post("/clinicalPathway/update")
def update_pathway(req: dict, current_user: User = Depends(require_roles(*CLINICAL_ROLES)), db: Session = Depends(get_db)):
    _validate_status(req)
    p = db.query(ClinicalPathway).filter(ClinicalPathway.pathway_id == req.get("pathway_id")).with_for_update().populate_existing().first()
    if not p:
        return {"code": 500, "msg": "记录不存在"}
    expected = req.get("expected_source_revision")
    if expected is not None and (type(expected) is not int or expected != p.source_revision):
        raise HTTPException(409, "原路径版本已变化，请重新加载后修改")
    changed = False
    for field in ["name", "disease_code", "disease_name", "steps", "expected_days", "status"]:
        if field in req and getattr(p, field) != req[field]:
            setattr(p, field, req[field])
            changed = True
    if changed:
        p.source_revision += 1
    db.commit()
    return {"code": 200, "msg": "success"}


@router.post("/clinicalPathway/delete")
def delete_pathway(req: dict, current_user: User = Depends(require_roles(*CLINICAL_ROLES)), db: Session = Depends(get_db)):
    p = db.query(ClinicalPathway).filter(ClinicalPathway.pathway_id == req.get("pathway_id")).first()
    if not p:
        return {"code": 500, "msg": "记录不存在"}
    if db.query(PathwayEnrollment.enrollment_id).filter_by(pathway_id=p.pathway_id).first():
        raise HTTPException(409, "该路径已有入径记录，请停用模板以保留历史关联")
    db.delete(p)
    db.commit()
    return {"code": 200, "msg": "success"}
