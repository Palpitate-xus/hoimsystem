"""医保目录对照 API：本院项目 ↔ 医保目录映射维护。"""
import datetime
import io

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import ADMIN_ROLES, CASHIER_ROLES, User, require_roles
from app.models import InsuranceCatalogMapping

router = APIRouter()

ITEM_TYPES = {"drug", "consumable", "lab", "exam", "bed", "surgery", "anesthesia", "registration"}
ITEM_TYPE_TEXT = {"drug": "药品", "consumable": "耗材", "lab": "检验", "exam": "检查", "bed": "床位", "surgery": "手术", "anesthesia": "麻醉", "registration": "挂号"}

INSURANCE_ROLES = ADMIN_ROLES | CASHIER_ROLES

HEADERS = ["本院项目类型", "本院项目名称", "医保编码", "医保名称", "类别", "自付比例", "限价"]


def _serialize(m: InsuranceCatalogMapping) -> dict:
    return {
        "mapping_id": m.mapping_id,
        "local_item_type": m.local_item_type,
        "local_item_type_text": ITEM_TYPE_TEXT.get(m.local_item_type, m.local_item_type),
        "local_item_id": m.local_item_id,
        "local_item_name": m.local_item_name,
        "insurance_code": m.insurance_code,
        "insurance_name": m.insurance_name,
        "insurance_category": m.insurance_category or "",
        "self_pay_ratio": float(m.self_pay_ratio) if m.self_pay_ratio is not None else 0,
        "unit_price_limit": float(m.unit_price_limit) if m.unit_price_limit is not None else None,
        "status": m.status,
        "create_time": m.create_time.strftime("%Y-%m-%d %H:%M:%S") if m.create_time else "",
    }


@router.get("/insuranceCatalog/getList")
def list_mappings(local_item_type: str | None = None, keyword: str | None = None, current_user: User = Depends(require_roles(*INSURANCE_ROLES)), db: Session = Depends(get_db)):
    query = db.query(InsuranceCatalogMapping)
    if local_item_type:
        query = query.filter(InsuranceCatalogMapping.local_item_type == local_item_type)
    if keyword:
        kw = f"%{keyword}%"
        query = query.filter(
            InsuranceCatalogMapping.local_item_name.like(kw)
            | InsuranceCatalogMapping.insurance_code.like(kw)
            | InsuranceCatalogMapping.insurance_name.like(kw)
        )
    rows = query.order_by(InsuranceCatalogMapping.mapping_id.desc()).limit(2000).all()
    return {"code": 200, "msg": "success", "data": [_serialize(m) for m in rows]}


@router.post("/insuranceCatalog/create")
def create_mapping(req: dict, current_user: User = Depends(require_roles(*INSURANCE_ROLES)), db: Session = Depends(get_db)):
    local_item_type = (req.get("local_item_type") or "").strip()
    if local_item_type not in ITEM_TYPES:
        return {"code": 400, "msg": "项目类型不合法"}
    if not (req.get("local_item_name") or "").strip():
        return {"code": 400, "msg": "本院项目名称不能为空"}
    if not (req.get("insurance_code") or "").strip() or not (req.get("insurance_name") or "").strip():
        return {"code": 400, "msg": "医保编码与名称不能为空"}
    ratio = req.get("self_pay_ratio", 0)
    try:
        ratio = float(ratio)
    except (TypeError, ValueError):
        return {"code": 400, "msg": "自付比例格式错误"}
    if not 0 <= ratio <= 1:
        return {"code": 400, "msg": "自付比例必须在 0-1 之间"}
    mapping = InsuranceCatalogMapping(
        local_item_type=local_item_type,
        local_item_id=req.get("local_item_id"),
        local_item_name=(req["local_item_name"] or "").strip(),
        insurance_code=(req["insurance_code"] or "").strip(),
        insurance_name=(req["insurance_name"] or "").strip(),
        insurance_category=(req.get("insurance_category") or "").strip() or None,
        self_pay_ratio=ratio,
        unit_price_limit=req.get("unit_price_limit"),
        status=1,
        create_time=datetime.datetime.now(),
    )
    db.add(mapping)
    db.commit()
    return {"code": 200, "msg": "success", "data": {"mapping_id": mapping.mapping_id}}


@router.post("/insuranceCatalog/update")
def update_mapping(req: dict, current_user: User = Depends(require_roles(*INSURANCE_ROLES)), db: Session = Depends(get_db)):
    mapping = db.query(InsuranceCatalogMapping).filter(InsuranceCatalogMapping.mapping_id == req.get("mapping_id")).first()
    if not mapping:
        return {"code": 500, "msg": "对照记录不存在"}
    for field in ("local_item_name", "insurance_code", "insurance_name", "insurance_category"):
        if req.get(field) is not None:
            setattr(mapping, field, (req[field] or "").strip() or None)
    if req.get("local_item_type") in ITEM_TYPES:
        mapping.local_item_type = req["local_item_type"]
    if req.get("self_pay_ratio") is not None:
        try:
            ratio = float(req["self_pay_ratio"])
            if not 0 <= ratio <= 1:
                return {"code": 400, "msg": "自付比例必须在 0-1 之间"}
            mapping.self_pay_ratio = ratio
        except (TypeError, ValueError):
            return {"code": 400, "msg": "自付比例格式错误"}
    if req.get("unit_price_limit") is not None:
        mapping.unit_price_limit = req.get("unit_price_limit")
    if req.get("status") in (0, 1):
        mapping.status = int(req["status"])
    db.add(mapping)
    db.commit()
    return {"code": 200, "msg": "success"}


@router.post("/insuranceCatalog/delete")
def delete_mapping(req: dict, current_user: User = Depends(require_roles(*INSURANCE_ROLES)), db: Session = Depends(get_db)):
    mapping = db.query(InsuranceCatalogMapping).filter(InsuranceCatalogMapping.mapping_id == req.get("mapping_id")).first()
    if not mapping:
        return {"code": 500, "msg": "对照记录不存在"}
    db.delete(mapping)
    db.commit()
    return {"code": 200, "msg": "success"}


@router.post("/insuranceCatalog/import")
def import_mappings(req: dict, current_user: User = Depends(require_roles(*INSURANCE_ROLES)), db: Session = Depends(get_db)):
    """批量导入：rows=[{本院项目类型,本院项目名称,医保编码,医保名称,类别,自付比例,限价}]。
    前端解析 Excel 后传 JSON 行；同名同类型记录跳过（幂等）。"""
    rows = req.get("rows") or []
    if not rows:
        return {"code": 400, "msg": "导入行不能为空"}
    imported, skipped, errors = 0, 0, []
    for i, row in enumerate(rows, start=2):
        item_type = (row.get("本院项目类型") or "").strip()
        name = (row.get("本院项目名称") or "").strip()
        code = (row.get("医保编码") or "").strip()
        ins_name = (row.get("医保名称") or "").strip()
        if item_type not in ITEM_TYPE_TEXT.values():
            errors.append(f"第{i}行：项目类型「{item_type}」不合法")
            continue
        if not name or not code:
            errors.append(f"第{i}行：本院项目名称或医保编码为空")
            continue
        type_code = next(k for k, v in ITEM_TYPE_TEXT.items() if v == item_type)
        exists = db.query(InsuranceCatalogMapping).filter(
            InsuranceCatalogMapping.local_item_type == type_code,
            InsuranceCatalogMapping.local_item_name == name,
        ).first()
        if exists:
            skipped += 1
            continue
        try:
            ratio = float(row.get("自付比例") or 0)
        except (TypeError, ValueError):
            ratio = 0.0
        db.add(InsuranceCatalogMapping(
            local_item_type=type_code,
            local_item_name=name,
            insurance_code=code,
            insurance_name=ins_name,
            insurance_category=(row.get("类别") or "").strip() or None,
            self_pay_ratio=ratio,
            status=1,
            create_time=datetime.datetime.now(),
        ))
        imported += 1
    db.commit()
    return {"code": 200, "msg": "success", "data": {"imported": imported, "skipped": skipped, "errors": errors[:20]}}


@router.get("/insuranceCatalog/template")
def download_template(current_user: User = Depends(require_roles(*INSURANCE_ROLES))):
    from openpyxl import Workbook

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "医保目录对照"
    sheet.append(HEADERS)
    output = io.BytesIO()
    workbook.save(output)
    output.seek(0)
    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="insurance_catalog_template.xlsx"'},
    )
