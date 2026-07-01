from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import NURSING_ROLES, User, require_roles
from app.models import Bed, Department, Ward
from app.schemas import BedCreateRequest, BedUpdateRequest, WardCreateRequest, WardUpdateRequest

router = APIRouter()

WARD_READ_ROLES = {*NURSING_ROLES}
WARD_WRITE_ROLES = {*NURSING_ROLES}


@router.get("/ward/getList")
def get_ward_list(keyword: str | None = None, current_user: User = Depends(require_roles(*WARD_READ_ROLES)), db: Session = Depends(get_db)):
    wards = db.query(Ward).filter(Ward.status == 0).all()
    data = []
    for item in wards:
        bed_total = db.query(Bed).filter(Bed.ward_id == item.ward_id).count()
        bed_used = db.query(Bed).filter(Bed.ward_id == item.ward_id, Bed.status == 1).count()
        data.append(
            {
                "ward_id": item.ward_id,
                "name": item.name,
                "department_id": item.department_id,
                "department_name": item.department.name if item.department else "",
                "bed_count": item.bed_count,
                "bed_total": bed_total,
                "bed_used": bed_used,
                "bed_free": bed_total - bed_used,
                "nurse_station_phone": item.nurse_station_phone or "",
                "location": item.location or "",
            }
        )
    if keyword:
        kw = keyword.lower()
        data = [item for item in data if any(kw in str(val).lower() for val in item.values())]
    return {"code": 200, "msg": "success", "data": data}


@router.post("/ward/create")
def create_ward(req: WardCreateRequest, current_user: User = Depends(require_roles(*WARD_WRITE_ROLES)), db: Session = Depends(get_db)):
    ward = Ward(
        name=req.name,
        department_id=req.department_id,
        bed_count=req.bed_count,
        nurse_station_phone=req.nurse_station_phone,
        location=req.location,
        status=0,
    )
    db.add(ward)
    db.commit()
    return {"code": 200, "msg": "success"}


@router.post("/ward/update")
def update_ward(req: WardUpdateRequest, current_user: User = Depends(require_roles(*WARD_WRITE_ROLES)), db: Session = Depends(get_db)):
    ward = db.query(Ward).filter(Ward.ward_id == req.ward_id).first()
    if not ward:
        return {"code": 500, "msg": "病区不存在"}
    if req.name is not None:
        ward.name = req.name
    if req.department_id is not None:
        ward.department_id = req.department_id
    if req.bed_count is not None:
        ward.bed_count = req.bed_count
    if req.nurse_station_phone is not None:
        ward.nurse_station_phone = req.nurse_station_phone
    if req.location is not None:
        ward.location = req.location
    if req.status is not None:
        ward.status = req.status
    db.add(ward)
    db.commit()
    return {"code": 200, "msg": "success"}


@router.post("/ward/delete")
def delete_ward(req: dict, current_user: User = Depends(require_roles(*WARD_WRITE_ROLES)), db: Session = Depends(get_db)):
    ward = db.query(Ward).filter(Ward.ward_id == req.get("ward_id")).first()
    if not ward:
        return {"code": 500, "msg": "病区不存在"}
    ward.status = 1
    db.add(ward)
    db.commit()
    return {"code": 200, "msg": "success"}


@router.get("/bed/getList")
def get_bed_list(ward_id: int | None = None, keyword: str | None = None, current_user: User = Depends(require_roles(*WARD_READ_ROLES)), db: Session = Depends(get_db)):
    query = db.query(Bed)
    if ward_id:
        query = query.filter(Bed.ward_id == ward_id)
    beds = query.all()
    data = []
    for item in beds:
        ward = db.query(Ward).filter(Ward.ward_id == item.ward_id).first()
        status_map = ["空闲", "占用", "禁用", "预订"]
        data.append(
            {
                "bed_id": item.bed_id,
                "ward_id": item.ward_id,
                "ward_name": ward.name if ward else "",
                "bed_no": item.bed_no,
                "room_no": item.room_no or "",
                "bed_type": item.bed_type,
                "price_per_day": item.price_per_day,
                "status": item.status,
                "status_text": status_map[item.status] if item.status < len(status_map) else "",
            }
        )
    if keyword:
        kw = keyword.lower()
        data = [item for item in data if any(kw in str(val).lower() for val in item.values())]
    return {"code": 200, "msg": "success", "data": data}


@router.post("/bed/create")
def create_bed(req: BedCreateRequest, current_user: User = Depends(require_roles(*WARD_WRITE_ROLES)), db: Session = Depends(get_db)):
    bed = Bed(
        ward_id=req.ward_id,
        bed_no=req.bed_no,
        room_no=req.room_no,
        bed_type=req.bed_type,
        price_per_day=req.price_per_day,
        status=0,
    )
    db.add(bed)
    db.commit()
    return {"code": 200, "msg": "success"}


@router.post("/bed/update")
def update_bed(req: BedUpdateRequest, current_user: User = Depends(require_roles(*WARD_WRITE_ROLES)), db: Session = Depends(get_db)):
    bed = db.query(Bed).filter(Bed.bed_id == req.bed_id).first()
    if not bed:
        return {"code": 500, "msg": "床位不存在"}
    if req.bed_no is not None:
        bed.bed_no = req.bed_no
    if req.room_no is not None:
        bed.room_no = req.room_no
    if req.bed_type is not None:
        bed.bed_type = req.bed_type
    if req.price_per_day is not None:
        bed.price_per_day = req.price_per_day
    if req.status is not None:
        bed.status = req.status
    db.add(bed)
    db.commit()
    return {"code": 200, "msg": "success"}


@router.post("/bed/delete")
def delete_bed(req: dict, current_user: User = Depends(require_roles(*WARD_WRITE_ROLES)), db: Session = Depends(get_db)):
    bed = db.query(Bed).filter(Bed.bed_id == req.get("bed_id")).first()
    if not bed:
        return {"code": 500, "msg": "床位不存在"}
    bed.status = 2
    db.add(bed)
    db.commit()
    return {"code": 200, "msg": "success"}
