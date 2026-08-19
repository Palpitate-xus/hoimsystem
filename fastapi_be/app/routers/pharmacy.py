import datetime
import math
import traceback

from fastapi import APIRouter, Depends
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import NURSING_ROLES, PHARMACY_ROLES, User, require_roles
from app.models import (
    DispenseVerification,
    Pharmaceutical,
    PharmaceuticalBatch,
    PharmaceuticalStockLedger,
    PrePha,
    Prescription,
)
from app.pagination import paginate
from app.schemas import PharmacyAuditRequest, PharmacyDispenseRequest, PharmacyReturnRequest, PharmacyVerificationRequest

router = APIRouter()


@router.get("/pharmacy/batch/list")
def get_batch_list(
    pharmaceutical_id: int | None = None,
    status: int | None = None,
    current_user: User = Depends(require_roles(*PHARMACY_ROLES)),
    db: Session = Depends(get_db),
):
    query = db.query(PharmaceuticalBatch).join(Pharmaceutical)
    if pharmaceutical_id is not None:
        query = query.filter(PharmaceuticalBatch.pharmaceutical_id == pharmaceutical_id)
    if status is not None:
        query = query.filter(PharmaceuticalBatch.status == status)
    batches = query.order_by(PharmaceuticalBatch.expiry_date.is_(None), PharmaceuticalBatch.expiry_date.asc(), PharmaceuticalBatch.batch_id.asc()).all()
    return {
        "code": 200,
        "msg": "success",
        "data": [
            {
                "batch_id": batch.batch_id,
                "pharmaceutical_id": batch.pharmaceutical_id,
                "pharmaceutical_name": batch.pharmaceutical.name if batch.pharmaceutical else "",
                "batch_no": batch.batch_no,
                "expiry_date": batch.expiry_date,
                "stock": batch.stock,
                "location": batch.location,
                "status": batch.status,
                "status_text": "在用" if batch.status == 0 else "冻结",
            }
            for batch in batches
        ],
    }


@router.get("/pharmacy/batch/ledger")
def get_batch_ledger(
    batch_id: int | None = None,
    pharmaceutical_id: int | None = None,
    current_user: User = Depends(require_roles(*PHARMACY_ROLES)),
    db: Session = Depends(get_db),
):
    query = db.query(PharmaceuticalStockLedger).join(PharmaceuticalBatch).join(Pharmaceutical)
    if batch_id is not None:
        query = query.filter(PharmaceuticalStockLedger.batch_id == batch_id)
    if pharmaceutical_id is not None:
        query = query.filter(PharmaceuticalStockLedger.pharmaceutical_id == pharmaceutical_id)
    entries = query.order_by(PharmaceuticalStockLedger.ledger_id.desc()).all()
    return {
        "code": 200,
        "msg": "success",
        "data": [
            {
                "ledger_id": entry.ledger_id,
                "batch_id": entry.batch_id,
                "pharmaceutical_id": entry.pharmaceutical_id,
                "batch_no": entry.batch.batch_no if entry.batch else "",
                "transaction_type": entry.transaction_type,
                "quantity": entry.quantity,
                "before_stock": entry.before_stock,
                "after_stock": entry.after_stock,
                "reference_type": entry.reference_type,
                "reference_id": entry.reference_id,
                "operator_name": entry.operator.username if entry.operator else "",
                "reason": entry.reason,
                "create_time": entry.create_time,
            }
            for entry in entries
        ],
    }


@router.get("/pharmacy/dispenseList")
def get_dispense_list(keyword: str | None = None, page: int | None = None, page_size: int | None = None, current_user: User = Depends(require_roles(*PHARMACY_ROLES)), db: Session = Depends(get_db)):
    query = db.query(Prescription).filter(Prescription.status.in_([0, 1, 2]))
    prescriptions, total = paginate(query, page, page_size)
    data = []
    for item in prescriptions:
        phas = []
        for j in item.pre_phas:
            phas.append(
                {
                    "name": j.pharmaceutical.name if j.pharmaceutical else "",
                    "number": j.number,
                    "pharmaceutical_id": j.pharmaceutical_id,
                }
            )
        data.append(
            {
                "uuid": str(item.prescription_id),
                "patient_name": item.patient.name if item.patient else "",
                "doctor_name": item.doctor.name if item.doctor else "",
                "phas": phas,
                "status": item.status,
                "create_time": (item.create_time.strftime("%Y-%m-%d %H:%M:%S") if item.create_time else None),
            }
        )
    if keyword:
        kw = keyword.lower()
        data = [item for item in data if any(kw in str(val).lower() for val in item.values())]
    result = {"code": 200, "msg": "success", "data": data}
    if page and page_size:
        result["total"] = total
    return result


@router.post("/pharmacy/audit")
def audit_prescription(req: PharmacyAuditRequest, current_user: User = Depends(require_roles(*PHARMACY_ROLES)), db: Session = Depends(get_db)):
    pre = db.query(Prescription).filter(Prescription.prescription_id == req.prescription_id).first()
    if not pre:
        return {"code": 500, "msg": "处方不存在"}
    if pre.status != 0:
        return {"code": 500, "msg": "处方状态不正确"}

    # Use a conditional update so two concurrent audit requests cannot both
    # observe status=0 and report success.
    updated = (
        db.query(Prescription)
        .filter(Prescription.prescription_id == req.prescription_id, Prescription.status == 0)
        .update({Prescription.status: 1}, synchronize_session=False)
    )
    if updated != 1:
        db.rollback()
        return {"code": 500, "msg": "处方状态不正确"}
    db.commit()
    return {"code": 200, "msg": "success"}


def _deduct_batches_fefo(db: Session, pharmaceutical_id: int, quantity: int, operator_id: int, reference_id: str) -> str | None:
    """按 FEFO（先过期先出）从批次扣减库存并写台账；库存不足返回错误信息。

    未启用批次管理（无在用批次）的药品跳过批次扣减——其总量库存
    已在开方时预留扣减（doctor.py），批次账仅对有批次的药品生效。
    """
    now = datetime.datetime.now()
    has_batches = (
        db.query(PharmaceuticalBatch)
        .filter(PharmaceuticalBatch.pharmaceutical_id == pharmaceutical_id, PharmaceuticalBatch.status == 0)
        .count()
        > 0
    )
    if not has_batches:
        return None
    remaining = quantity
    batches = (
        db.query(PharmaceuticalBatch)
        .filter(
            PharmaceuticalBatch.pharmaceutical_id == pharmaceutical_id,
            PharmaceuticalBatch.status == 0,
            PharmaceuticalBatch.stock > 0,
        )
        .order_by(
            PharmaceuticalBatch.expiry_date.is_(None),
            PharmaceuticalBatch.expiry_date.asc(),
            PharmaceuticalBatch.batch_id.asc(),
        )
        .with_for_update()
        .all()
    )
    for batch in batches:
        if remaining <= 0:
            break
        take = min(batch.stock, remaining)
        before = batch.stock
        batch.stock = before - take
        batch.update_time = now
        db.add(batch)
        db.add(PharmaceuticalStockLedger(
            batch_id=batch.batch_id,
            pharmaceutical_id=pharmaceutical_id,
            transaction_type="outbound",
            quantity=take,
            before_stock=before,
            after_stock=batch.stock,
            reference_type="prescription",
            reference_id=str(reference_id),
            operator_id=operator_id,
            reason="发药出库",
            create_time=now,
        ))
        remaining -= take
    if remaining > 0:
        return f"批次库存不足，尚缺 {remaining}"
    return None


def _return_to_batches(db: Session, pharmaceutical_id: int, quantity: int, operator_id: int, reference_id: str) -> str | None:
    """退药回冲：优先回到最近出库的未过期批次，其次最早未过期批次；写台账。"""
    now = datetime.datetime.now()
    batch = (
        db.query(PharmaceuticalBatch)
        .filter(
            PharmaceuticalBatch.pharmaceutical_id == pharmaceutical_id,
            PharmaceuticalBatch.status == 0,
            or_(PharmaceuticalBatch.expiry_date.is_(None), PharmaceuticalBatch.expiry_date >= datetime.date.today()),
        )
        .order_by(PharmaceuticalBatch.update_time.desc())
        .first()
    )
    if not batch:
        # 没有可用批次时退回到"默认批次"（首次退药自动建）
        batch = PharmaceuticalBatch(
            pharmaceutical_id=pharmaceutical_id,
            batch_no=f"RET-{str(reference_id)[:12]}",
            expiry_date=None,
            stock=0,
            status=0,
            create_time=now,
            update_time=now,
        )
        db.add(batch)
        db.flush()
    before = batch.stock
    batch.stock = before + quantity
    batch.update_time = now
    db.add(batch)
    db.add(PharmaceuticalStockLedger(
        batch_id=batch.batch_id,
        pharmaceutical_id=pharmaceutical_id,
        transaction_type="return",
        quantity=quantity,
        before_stock=before,
        after_stock=batch.stock,
        reference_type="prescription_return",
        reference_id=str(reference_id),
        operator_id=operator_id,
        reason="退药回冲",
        create_time=now,
    ))
    return None


@router.post("/pharmacy/dispense")
def dispense_prescription(req: PharmacyDispenseRequest, current_user: User = Depends(require_roles(*PHARMACY_ROLES)), db: Session = Depends(get_db)):
    pre = db.query(Prescription).filter(Prescription.prescription_id == req.prescription_id).first()
    if not pre:
        return {"code": 500, "msg": "处方不存在"}
    if pre.status != 1:
        return {"code": 500, "msg": "处方未审核或已发药"}
    expired_names = [
        line.pharmaceutical.name
        for line in pre.pre_phas
        if line.pharmaceutical and line.pharmaceutical.expireddate and line.pharmaceutical.expireddate < datetime.date.today() and line.number > 0
    ]
    if expired_names:
        return {"code": 400, "msg": f"药品已过期，禁止发药：{', '.join(expired_names)}"}

    # 缴费校验：处方关联收费未结清禁止发药（原缺陷：未缴费即可发药形成漏费通道）
    from app.models import Charge

    unpaid = (
        db.query(Charge)
        .filter(Charge.prescription_id == str(req.prescription_id), Charge.status == 0)
        .count()
    )
    if unpaid:
        return {"code": 400, "msg": "该处方存在未缴费收费记录，请先缴费再发药"}

    # 皮试闭环校验：该患者对该药有皮试医嘱时，阳性(3)禁止发药；
    # 未完成（0 医嘱/1 待判定）也禁止——皮试结果未出不能发药
    from app.models import SkinTestOrder

    for line in pre.pre_phas:
        if not line.pharmaceutical or line.number <= 0:
            continue
        st = (
            db.query(SkinTestOrder)
            .filter(
                SkinTestOrder.patient_id == pre.patient_id,
                SkinTestOrder.pharmaceutical_id == line.pharmaceutical_id,
                SkinTestOrder.status.in_((0, 1, 3)),
            )
            .order_by(SkinTestOrder.skin_test_id.desc())
            .first()
        )
        if st and st.status == 3:
            return {"code": 400, "msg": f"皮试阳性，禁止发药：{line.pharmaceutical.name}"}
        if st and st.status in (0, 1):
            return {"code": 400, "msg": f"皮试尚未完成，禁止发药：{line.pharmaceutical.name}"}

    # 抗菌药审批闭环校验：限制级/特殊使用级(antibiotic_level>=2)必须有已批准
    # 且绑定本处方的审批单（原缺陷：只在开方端校验，直发已审处方可绕过）
    from app.models import AntibioticApproval

    for line in pre.pre_phas:
        if not line.pharmaceutical or line.number <= 0:
            continue
        if line.pharmaceutical.antibiotic_level and line.pharmaceutical.antibiotic_level >= 2:
            bound = (
                db.query(AntibioticApproval)
                .filter(
                    AntibioticApproval.prescription_id == str(req.prescription_id),
                    AntibioticApproval.pharmaceutical_id == line.pharmaceutical_id,
                    AntibioticApproval.status == 1,
                )
                .first()
            )
            if not bound:
                return {"code": 400, "msg": f"抗菌药 [{line.pharmaceutical.name}] 无有效审批，禁止发药"}

    # 发药时按批次 FEFO 扣减库存并写台账（库存不足则整单拒绝回滚）
    for line in pre.pre_phas:
        if not line.pharmaceutical or line.number <= 0:
            continue
        error = _deduct_batches_fefo(db, line.pharmaceutical_id, line.number, current_user.user_id, req.prescription_id)
        if error:
            db.rollback()
            return {"code": 500, "msg": f"{line.pharmaceutical.name}：{error}"}
        # 总量库存同步扣减（处方开立时是预留语义；未走处方开立入口的数据以此为准）
        updated_total = (
            db.query(Pharmaceutical)
            .filter(Pharmaceutical.pharmaceutical_id == line.pharmaceutical_id, Pharmaceutical.stock >= line.number)
            .update({Pharmaceutical.stock: Pharmaceutical.stock - line.number}, synchronize_session=False)
        )
        if updated_total != 1:
            db.rollback()
            return {"code": 500, "msg": f"{line.pharmaceutical.name}：总量库存不足"}

    # Only the audited state may transition to dispensed.  Keeping the state
    # predicate in the UPDATE closes the duplicate-dispense race window.
    updated = (
        db.query(Prescription)
        .filter(Prescription.prescription_id == req.prescription_id, Prescription.status == 1)
        .update({Prescription.status: 2}, synchronize_session=False)
    )
    if updated != 1:
        db.rollback()
        return {"code": 500, "msg": "处方未审核或已发药"}
    if not db.query(DispenseVerification).filter(DispenseVerification.prescription_id == req.prescription_id).first():
        db.add(DispenseVerification(prescription_id=req.prescription_id, pharmacist_id=current_user.user_id, status=0, create_time=datetime.datetime.now()))
    db.commit()
    return {"code": 200, "msg": "success"}


@router.get("/pharmacy/verificationList")
def get_verification_list(current_user: User = Depends(require_roles(*(PHARMACY_ROLES | NURSING_ROLES))), db: Session = Depends(get_db)):
    items = db.query(DispenseVerification).join(Prescription).order_by(DispenseVerification.create_time.desc()).all()
    data = []
    for item in items:
        data.append({
            "verification_id": item.verification_id,
            "prescription_id": item.prescription_id,
            "patient_name": item.prescription.patient.name if item.prescription and item.prescription.patient else "",
            "doctor_name": item.prescription.doctor.name if item.prescription and item.prescription.doctor else "",
            "pharmaceuticals": [{"name": line.pharmaceutical.name if line.pharmaceutical else "", "number": line.number} for line in item.prescription.pre_phas] if item.prescription else [],
            "status": item.status,
            "status_text": {0: "待护士核对", 1: "已核对", 2: "核对异常"}.get(item.status, "未知"),
            "note": item.note or "",
            "pharmacist_name": item.pharmacist.username if item.pharmacist else "",
            "verifier_name": item.verifier.username if item.verifier else "",
            "create_time": item.create_time,
            "verify_time": item.verify_time,
        })
    return {"code": 200, "msg": "success", "data": data}


@router.post("/pharmacy/verify")
def verify_dispense(req: PharmacyVerificationRequest, current_user: User = Depends(require_roles(*NURSING_ROLES)), db: Session = Depends(get_db)):
    updated = db.query(DispenseVerification).filter(DispenseVerification.verification_id == req.verification_id, DispenseVerification.status == 0).update({DispenseVerification.status: 1, DispenseVerification.verifier_id: current_user.user_id, DispenseVerification.note: req.note.strip(), DispenseVerification.verify_time: datetime.datetime.now()}, synchronize_session=False)
    if updated != 1:
        return {"code": 500, "msg": "核对记录不存在或已处理"}
    db.commit()
    return {"code": 200, "msg": "success"}


@router.post("/pharmacy/return")
def return_medicine(req: PharmacyReturnRequest, current_user: User = Depends(require_roles(*PHARMACY_ROLES)), db: Session = Depends(get_db)):
    pre = db.query(Prescription).filter(Prescription.prescription_id == req.prescription_id).first()
    if not pre:
        return {"code": 500, "msg": "处方不存在"}
    if pre.status != 2:
        return {"code": 500, "msg": "处方未发药或已退药"}
    if req.number <= 0:
        return {"code": 500, "msg": "退药数量必须大于0"}

    pp = db.query(PrePha).filter(PrePha.prescription_id == req.prescription_id, PrePha.pharmaceutical_id == req.pha_id).first()
    if not pp:
        return {"code": 500, "msg": "药品记录不存在"}

    # Make the quantity check part of the update so concurrent return
    # requests cannot both consume the same remaining prescription quantity.
    updated = (
        db.query(PrePha)
        .filter(
            PrePha.prescription_id == req.prescription_id,
            PrePha.pharmaceutical_id == req.pha_id,
            PrePha.number >= req.number,
        )
        .update({PrePha.number: PrePha.number - req.number}, synchronize_session=False)
    )
    if updated != 1:
        db.rollback()
        return {"code": 500, "msg": "退药数量超过处方数量"}

    db.expire_all()
    pp = db.query(PrePha).filter(PrePha.prescription_id == req.prescription_id, PrePha.pharmaceutical_id == req.pha_id).first()
    if not pp:
        db.rollback()
        return {"code": 500, "msg": "药品记录不存在"}
    if pp.number <= 0:
        db.delete(pp)

    try:
        pha = db.query(Pharmaceutical).filter(Pharmaceutical.pharmaceutical_id == req.pha_id).first()
        if pha:
            pha.stock += req.number
            db.add(pha)
        # 回冲到批次并写台账（原先只加总库存不动批次，批次账与总量账永久背离）
        _return_to_batches(db, req.pha_id, req.number, current_user.user_id, req.prescription_id)

        # Status 4 is the documented fully-returned state.  Partial returns
        # keep status=2 so the remaining dispensed medicines can be returned.
        remaining = db.query(PrePha).filter(PrePha.prescription_id == req.prescription_id, PrePha.number > 0).count()
        if remaining == 0:
            pre.status = 4
            db.add(pre)

        db.commit()
        return {"code": 200, "msg": "success"}
    except Exception:
        db.rollback()
        traceback.print_exc()
        return {"code": 500, "msg": "退药失败"}


@router.post("/pharmacy/stockCheck")
def stock_check(req: dict, current_user: User = Depends(require_roles(*PHARMACY_ROLES)), db: Session = Depends(get_db)):
    """库存盘点：传入 {items: [{pharmaceutical_id, actual_stock}]}，返回盈亏"""
    items = req.get("items", [])
    if not isinstance(items, list):
        return {"code": 500, "msg": "盘点明细格式错误"}
    seen_ids = set()
    for item in items:
        pha_id = item.get("pharmaceutical_id") if isinstance(item, dict) else None
        actual = item.get("actual_stock") if isinstance(item, dict) else None
        if pha_id in seen_ids:
            return {"code": 500, "msg": "同一药品不能重复盘点"}
        seen_ids.add(pha_id)
        try:
            actual_value = float(actual)
        except (TypeError, ValueError, OverflowError):
            return {"code": 500, "msg": "实盘库存必须是非负整数"}
        if not math.isfinite(actual_value) or actual_value < 0 or not actual_value.is_integer():
            return {"code": 500, "msg": "实盘库存必须是非负整数"}
    result = []
    for item in items:
        pha_id = item.get("pharmaceutical_id")
        actual = int(item.get("actual_stock"))
        pha = db.query(Pharmaceutical).filter(Pharmaceutical.pharmaceutical_id == pha_id).first()
        if pha:
            diff = actual - pha.stock
            result.append(
                {
                    "pharmaceutical_id": pha_id,
                    "name": pha.name,
                    "system_stock": pha.stock,
                    "actual_stock": actual,
                    "diff": diff,
                }
            )
            # 以实盘数为准更新库存
            pha.stock = actual
            db.add(pha)
    db.commit()
    return {"code": 200, "msg": "success", "data": result}


@router.post("/pharmacy/review")
def review_prescription(req: dict, current_user: User = Depends(require_roles(*PHARMACY_ROLES)), db: Session = Depends(get_db)):
    """处方点评"""
    pre = db.query(Prescription).filter(Prescription.prescription_id == req.get("prescription_id")).first()
    if not pre:
        return {"code": 500, "msg": "处方不存在"}
    pre.review_score = req.get("score")
    pre.review_comment = req.get("comment", "")
    pre.review_time = datetime.datetime.now()
    db.add(pre)
    db.commit()
    return {"code": 200, "msg": "success"}


@router.get("/pharmacy/reviewList")
def get_review_list(keyword: str | None = None, current_user: User = Depends(require_roles(*PHARMACY_ROLES)), db: Session = Depends(get_db)):
    """已点评处方列表"""
    prescriptions = db.query(Prescription).filter(Prescription.review_score.isnot(None)).order_by(Prescription.review_time.desc()).all()
    data = []
    for item in prescriptions:
        phas = []
        for j in item.pre_phas:
            phas.append({"name": j.pharmaceutical.name if j.pharmaceutical else "", "number": j.number})
        data.append(
            {
                "uuid": str(item.prescription_id),
                "patient_name": item.patient.name if item.patient else "",
                "doctor_name": item.doctor.name if item.doctor else "",
                "phas": phas,
                "review_score": item.review_score,
                "review_comment": item.review_comment or "",
                "review_time": (item.review_time.strftime("%Y-%m-%d %H:%M:%S") if item.review_time else None) if item.review_time else "",
            }
        )
    if keyword:
        kw = keyword.lower()
        data = [item for item in data if any(kw in str(val).lower() for val in item.values())]
    return {"code": 200, "msg": "success", "data": data}


@router.get("/pharmacy/dispenseStats")
def dispense_statistics(
    start_date: str | None = None,
    end_date: str | None = None,
    current_user: User = Depends(require_roles(*PHARMACY_ROLES)),
    db: Session = Depends(get_db),
):
    """统计已发药/已退药处方的发药量，日期口径为处方创建时间。"""
    query = db.query(Prescription).filter(Prescription.status.in_([2, 4]))
    try:
        if start_date:
            query = query.filter(Prescription.create_time >= datetime.datetime.strptime(start_date, "%Y-%m-%d"))
        if end_date:
            query = query.filter(Prescription.create_time < datetime.datetime.strptime(end_date, "%Y-%m-%d") + datetime.timedelta(days=1))
    except ValueError:
        return {"code": 500, "msg": "日期格式必须为 YYYY-MM-DD"}
    prescriptions = query.order_by(Prescription.create_time).all()
    by_date = {}
    by_drug = {}
    for prescription in prescriptions:
        date_key = prescription.create_time.strftime("%Y-%m-%d") if prescription.create_time else "未知日期"
        date_item = by_date.setdefault(date_key, {"date": date_key, "prescription_count": 0, "item_count": 0})
        date_item["prescription_count"] += 1
        for line in prescription.pre_phas:
            drug_key = line.pharmaceutical_id
            quantity = int(line.number or 0)
            date_item["item_count"] += quantity
            drug_item = by_drug.setdefault(
                drug_key,
                {"pharmaceutical_id": drug_key, "name": line.pharmaceutical.name if line.pharmaceutical else "", "quantity": 0, "prescription_count": 0},
            )
            drug_item["quantity"] += quantity
            drug_item["prescription_count"] += 1
    return {
        "code": 200,
        "msg": "success",
        "data": {
            "summary": {"prescription_count": len(prescriptions), "item_count": sum(item["item_count"] for item in by_date.values())},
            "by_date": list(by_date.values()),
            "by_drug": list(by_drug.values()),
        },
    }
