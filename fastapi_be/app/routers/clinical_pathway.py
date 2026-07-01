import datetime

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import CLINICAL_ROLES, User, require_roles
from app.models import ClinicalPathway

router = APIRouter()


@router.post("/clinicalPathway/create")
def create_pathway(req: dict, current_user: User = Depends(require_roles(*CLINICAL_ROLES)), db: Session = Depends(get_db)):
    p = ClinicalPathway(
        name=req.get("name", ""),
        disease_code=req.get("disease_code", ""),
        disease_name=req.get("disease_name", ""),
        steps=req.get("steps", "[]"),
        expected_days=req.get("expected_days", 7),
        status=0,
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
                "status_text": "启用" if it.status == 0 else "停用",
                "create_time": (it.create_time.strftime("%Y-%m-%d %H:%M:%S") if it.create_time else None) if it.create_time else "",
            }
        )
    return {"code": 200, "msg": "success", "data": data}


@router.post("/clinicalPathway/update")
def update_pathway(req: dict, current_user: User = Depends(require_roles(*CLINICAL_ROLES)), db: Session = Depends(get_db)):
    p = db.query(ClinicalPathway).filter(ClinicalPathway.pathway_id == req.get("pathway_id")).first()
    if not p:
        return {"code": 500, "msg": "记录不存在"}
    for field in ["name", "disease_code", "disease_name", "steps", "expected_days", "status"]:
        if field in req:
            setattr(p, field, req[field])
    db.commit()
    return {"code": 200, "msg": "success"}


@router.post("/clinicalPathway/delete")
def delete_pathway(req: dict, current_user: User = Depends(require_roles(*CLINICAL_ROLES)), db: Session = Depends(get_db)):
    p = db.query(ClinicalPathway).filter(ClinicalPathway.pathway_id == req.get("pathway_id")).first()
    if not p:
        return {"code": 500, "msg": "记录不存在"}
    db.delete(p)
    db.commit()
    return {"code": 200, "msg": "success"}
