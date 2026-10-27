"""Governed complete inpatient ledger evidence; never money/fee business writes."""

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.ai import charge_reconciliation_contract as c
from app.ai import charge_reconciliation_sources as s
from app.ai.charge_reconciliation_contract import SOURCE_ROLES
from app.ai.charge_reconciliation_models import AIChargeCaseSnapshot
from app.ai.charge_reconciliation_write_guard import current_charge_rows
from app.database import get_db
from app.dependencies import User, require_roles
from app.sql_counts import locked_row_count

router = APIRouter(prefix="/ai/charge-reconciliation", tags=["AI charge evidence"], default_response_class=JSONResponse)


def request(model, value):
    try:
        return s.typed(model, value)
    except (ValueError, TypeError, KeyError, UnicodeError) as exc:
        raise HTTPException(422, "原件请求字段类型、完整范围或UTF8不合法") from exc


@router.get("/options")
def options(patient_id: int | None = None, admission_id: str | None = None, user: User = Depends(require_roles(*SOURCE_ROLES)), db: Session = Depends(get_db)):
    actor = s.current_actor(db, user)
    if (patient_id is None) != (admission_id is None):
        raise HTTPException(422, "须同时明确实际患者和Admission")
    can_record = patient_id is not None
    if can_record:
        s.authorize_scope(db, actor, request(c.CaptureRequest, {"patient_id": patient_id, "admission_id": admission_id}))
    return {
        "code": 200,
        "msg": "success",
        "data": {
            "scope": "single_actual_inpatient_admission",
            "patient_id": patient_id,
            "admission_id": admission_id,
            "can_record": can_record,
            "can_review": actor.user_role == "super_admin",
            "requires_actual_scope": True,
            "max_rows": c.MAX_ROWS,
            "max_bytes": c.MAX_BYTES,
            "schema_version": "charge_case_snapshot_v1",
            "cash_receipt": "not_provided",
            "cash_refund": "not_provided",
            "request_schemas": {
                name: model.model_json_schema()
                for name, model in {"CaptureRequest": c.CaptureRequest, "CaseCreate": c.CaseCreate, "SourceReview": c.SourceReview, "SourceRevoke": c.SourceRevoke}.items()
            },
        },
    }


@router.post("/cases/preview")
def preview(req: dict, user: User = Depends(require_roles(*SOURCE_ROLES)), db: Session = Depends(get_db)):
    return {"code": 200, "msg": "success", "data": s.capture_case(db, user, request(c.CaptureRequest, req))}


@router.post("/cases")
def create(req: dict, user: User = Depends(require_roles(*SOURCE_ROLES)), db: Session = Depends(get_db)):
    value = s.create_case(db, user, request(c.CaseCreate, req))
    db.commit()
    return {"code": 200, "msg": "success", "data": value}


@router.get("/cases")
def list_cases(
    patient_id: int | None = None,
    admission_id: str | None = None,
    audit_only: bool = False,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user: User = Depends(require_roles(*SOURCE_ROLES)),
    db: Session = Depends(get_db),
):
    actor = s.current_actor(db, user, {"super_admin"} if audit_only else c.SOURCE_ROLES)
    if (patient_id is None) != (admission_id is None) or (not audit_only and patient_id is None):
        raise HTTPException(422, "普通目录须明确完整患者与Admission作用域")
    if patient_id is not None:
        s.authorize_scope(db, actor, request(c.CaptureRequest, {"patient_id": patient_id, "admission_id": admission_id}))
    query = db.query(AIChargeCaseSnapshot)
    if patient_id is not None:
        query = query.filter_by(patient_id=patient_id, admission_id=admission_id)
    total = locked_row_count(current_charge_rows(query, shared=True), AIChargeCaseSnapshot.case_snapshot_id, aggregate=True)
    columns = ("case_snapshot_id", "patient_id", "admission_id", "schema_version", "created_at", "created_by", "collection_digest", "content_hash", "status", "revision", "reviewed_at", "revoked_at")
    rows = (
        current_charge_rows(query.with_entities(*(getattr(AIChargeCaseSnapshot, key) for key in columns)), shared=True)
        .order_by(AIChargeCaseSnapshot.created_at.desc(), AIChargeCaseSnapshot.case_snapshot_id)
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    items = []
    for row in rows:
        value = dict(row._mapping)
        for key in ("created_at", "reviewed_at", "revoked_at"):
            value[key] = c.utc_text(value[key]) if value[key] is not None else None
        value.update(source_id="charge_case:" + row.case_snapshot_id + ":" + row.content_hash[:12], detail_required=True)
        items.append(value)
    return {"code": 200, "msg": "success", "data": {"items": items, "total": total, "page": page, "page_size": page_size}}


@router.get("/cases/{identifier}")
def detail(identifier: str, audit_only: bool = False, user: User = Depends(require_roles(*SOURCE_ROLES)), db: Session = Depends(get_db)):
    return {"code": 200, "msg": "success", "data": s.case_current(db, user, identifier, audit_only=audit_only)}


@router.post("/cases/{identifier}/review")
def review(identifier: str, req: dict, user: User = Depends(require_roles("super_admin")), db: Session = Depends(get_db)):
    value = s.review_case(db, user, identifier, request(c.SourceReview, req))
    db.commit()
    return {"code": 200, "msg": "success", "data": value}


@router.post("/cases/{identifier}/revoke")
def revoke(identifier: str, req: dict, user: User = Depends(require_roles(*SOURCE_ROLES)), db: Session = Depends(get_db)):
    value = s.revoke_case(db, user, identifier, request(c.SourceRevoke, req))
    db.commit()
    return {"code": 200, "msg": "success", "data": value}
