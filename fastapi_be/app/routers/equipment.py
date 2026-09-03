import datetime

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import ADMIN_ROLES, NURSING_ROLES, PHARMACY_ROLES, ROLE_DIRECTOR, User, require_roles
from app.models import Consumable, ConsumableTrace, Equipment, EquipmentInspection, EquipmentMaintenance

router = APIRouter()
EQUIPMENT_ROLES = {*ADMIN_ROLES, ROLE_DIRECTOR, *NURSING_ROLES, *PHARMACY_ROLES}
MANAGE_ROLES = {*ADMIN_ROLES, ROLE_DIRECTOR}


def _equipment_data(item: Equipment):
    return {"equipment_id": item.equipment_id, "asset_no": item.asset_no, "name": item.name, "category": item.category or "", "model": item.model or "", "manufacturer": item.manufacturer or "", "location": item.location or "", "status": item.status, "status_text": {0: "在用", 1: "维修", 2: "报废"}.get(item.status, ""), "inventory_status": item.inventory_status, "inventory_status_text": {0: "未盘点", 1: "已盘点", 2: "异常"}.get(item.inventory_status, ""), "last_inventory_time": item.last_inventory_time.strftime("%Y-%m-%d %H:%M:%S") if item.last_inventory_time else ""}


@router.get("/equipment/list")
def list_equipment(current_user: User = Depends(require_roles(*EQUIPMENT_ROLES)), db: Session = Depends(get_db)):
    return {"code": 200, "msg": "success", "data": [_equipment_data(item) for item in db.query(Equipment).order_by(Equipment.equipment_id.desc()).all()]}


@router.post("/equipment/create")
def create_equipment(req: dict, current_user: User = Depends(require_roles(*MANAGE_ROLES)), db: Session = Depends(get_db)):
    if not req.get("asset_no") or not req.get("name"):
        return {"code": 400, "msg": "资产编号和设备名称不能为空"}
    if db.query(Equipment).filter(Equipment.asset_no == req["asset_no"]).first():
        return {"code": 409, "msg": "资产编号已存在"}
    def parse_date(value):
        return datetime.datetime.strptime(value, "%Y-%m-%d").date() if value else None
    item = Equipment(asset_no=req["asset_no"], name=req["name"], category=req.get("category"), model=req.get("model"), manufacturer=req.get("manufacturer"), department_id=req.get("department_id"), location=req.get("location"), purchase_date=parse_date(req.get("purchase_date")), expiry_date=parse_date(req.get("expiry_date")), responsible_id=req.get("responsible_id"), create_time=datetime.datetime.now())
    db.add(item)
    db.commit()
    return {"code": 200, "msg": "success", "data": {"equipment_id": item.equipment_id}}


@router.post("/equipment/status")
def update_equipment_status(req: dict, current_user: User = Depends(require_roles(*MANAGE_ROLES)), db: Session = Depends(get_db)):
    item = db.query(Equipment).filter(Equipment.equipment_id == req.get("equipment_id")).first()
    if not item or req.get("status") not in (0, 1, 2):
        return {"code": 400, "msg": "设备或状态不合法"}
    item.status = req["status"]
    db.commit()
    return {"code": 200, "msg": "success"}


@router.get("/equipment/maintenance/list")
def list_maintenance(current_user: User = Depends(require_roles(*EQUIPMENT_ROLES)), db: Session = Depends(get_db)):
    items = db.query(EquipmentMaintenance).order_by(EquipmentMaintenance.report_time.desc()).all()
    return {"code": 200, "msg": "success", "data": [{"maintenance_id": item.maintenance_id, "equipment_id": item.equipment_id, "equipment_name": item.equipment.name if item.equipment else "", "maintenance_type": item.maintenance_type, "description": item.description, "cost": item.cost, "status": item.status, "status_text": {0: "报修", 1: "处理中", 2: "完成"}.get(item.status, ""), "report_time": item.report_time.strftime("%Y-%m-%d %H:%M:%S")} for item in items]}


@router.post("/equipment/maintenance/create")
def create_maintenance(req: dict, current_user: User = Depends(require_roles(*EQUIPMENT_ROLES)), db: Session = Depends(get_db)):
    if not db.query(Equipment).filter(Equipment.equipment_id == req.get("equipment_id")).first():
        return {"code": 404, "msg": "设备不存在"}
    item = EquipmentMaintenance(equipment_id=req["equipment_id"], maintenance_type=req.get("maintenance_type", "维修"), description=req.get("description", "").strip(), cost=float(req.get("cost", 0)), operator_id=current_user.user_id, report_time=datetime.datetime.now())
    if not item.description:
        return {"code": 400, "msg": "维修描述不能为空"}
    db.add(item)
    db.commit()
    return {"code": 200, "msg": "success"}


@router.post("/equipment/maintenance/status")
def update_maintenance_status(req: dict, current_user: User = Depends(require_roles(*MANAGE_ROLES)), db: Session = Depends(get_db)):
    item = db.query(EquipmentMaintenance).filter(EquipmentMaintenance.maintenance_id == req.get("maintenance_id")).first()
    if not item or req.get("status") not in (0, 1, 2):
        return {"code": 400, "msg": "维修记录或状态不合法"}
    item.status = req["status"]
    if item.status == 2:
        item.complete_time = datetime.datetime.now()
    db.commit()
    return {"code": 200, "msg": "success"}


@router.get("/equipment/inspection/list")
def list_inspection(current_user: User = Depends(require_roles(*EQUIPMENT_ROLES)), db: Session = Depends(get_db)):
    items = db.query(EquipmentInspection).order_by(EquipmentInspection.inspection_time.desc()).all()
    return {"code": 200, "msg": "success", "data": [{"inspection_id": item.inspection_id, "equipment_id": item.equipment_id, "equipment_name": item.equipment.name if item.equipment else "", "result": item.result, "pass_flag": item.pass_flag, "inspection_time": item.inspection_time.strftime("%Y-%m-%d %H:%M:%S"), "next_date": str(item.next_date) if item.next_date else ""} for item in items]}


@router.post("/equipment/inspection/create")
def create_inspection(req: dict, current_user: User = Depends(require_roles(*EQUIPMENT_ROLES)), db: Session = Depends(get_db)):
    if not db.query(Equipment).filter(Equipment.equipment_id == req.get("equipment_id")).first():
        return {"code": 404, "msg": "设备不存在"}
    item = EquipmentInspection(equipment_id=req["equipment_id"], result=req.get("result", "").strip(), pass_flag=int(req.get("pass_flag", 1)), inspector_id=current_user.user_id, inspection_time=datetime.datetime.now())
    if not item.result:
        return {"code": 400, "msg": "保养结果不能为空"}
    db.add(item)
    db.commit()
    return {"code": 200, "msg": "success"}


@router.get("/equipment/trace/list")
def list_consumable_trace(consumable_id: int | None = None, current_user: User = Depends(require_roles(*EQUIPMENT_ROLES)), db: Session = Depends(get_db)):
    query = db.query(ConsumableTrace)
    if consumable_id:
        query = query.filter(ConsumableTrace.consumable_id == consumable_id)
    items = query.order_by(ConsumableTrace.action_time.desc()).all()
    return {"code": 200, "msg": "success", "data": [{"trace_id": item.trace_id, "consumable_name": item.consumable.name if item.consumable else "", "batch_no": item.batch_no, "serial_no": item.serial_no or "", "action": item.action, "quantity": item.quantity, "patient_name": item.patient.name if item.patient else "", "action_time": item.action_time.strftime("%Y-%m-%d %H:%M:%S")} for item in items]}


@router.post("/equipment/trace/create")
def create_consumable_trace(req: dict, current_user: User = Depends(require_roles(*EQUIPMENT_ROLES)), db: Session = Depends(get_db)):
    if not db.query(Consumable).filter(Consumable.consumable_id == req.get("consumable_id")).first():
        return {"code": 404, "msg": "耗材不存在"}
    item = ConsumableTrace(consumable_id=req["consumable_id"], batch_no=req.get("batch_no", "").strip(), serial_no=req.get("serial_no"), action=req.get("action", "use"), quantity=int(req.get("quantity", 0)), patient_id=req.get("patient_id"), operator_id=current_user.user_id, action_time=datetime.datetime.now(), remark=req.get("remark"))
    if not item.batch_no or item.quantity <= 0:
        return {"code": 400, "msg": "批次号和数量必须有效"}
    db.add(item)
    db.commit()
    return {"code": 200, "msg": "success"}


@router.post("/equipment/inventory/check")
def inventory_check(req: dict, current_user: User = Depends(require_roles(*MANAGE_ROLES)), db: Session = Depends(get_db)):
    item = db.query(Equipment).filter(Equipment.equipment_id == req.get("equipment_id")).first()
    if not item:
        return {"code": 404, "msg": "设备不存在"}
    item.inventory_status = 1 if req.get("normal", True) else 2
    item.inventory_note = req.get("note", "")
    item.last_inventory_time = datetime.datetime.now()
    db.commit()
    return {"code": 200, "msg": "盘点完成"}
