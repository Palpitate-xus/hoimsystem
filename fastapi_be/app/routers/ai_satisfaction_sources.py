"""Safe complete review evidence, distinct from technical Super raw auditing."""

import datetime
from types import SimpleNamespace
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.ai import satisfaction_sources as s
from app.ai.satisfaction_contract import SOURCE_ROLES, UUID, CaptureRequest, CaseCreate, SourceReview, SourceRevoke
from app.ai.satisfaction_models import MAX_BYTES, MAX_ROOTS, AISatisfactionCase
from app.ai.satisfaction_write_guard import current_actor, current_satisfaction_rows, lock_satisfaction_write
from app.database import get_db
from app.dependencies import User, require_roles
from app.models import Doctor
from app.routers.inpatient_support import QueryPositiveInteger

router = APIRouter(prefix="/ai/satisfaction-sources", default_response_class=JSONResponse)


def response(data):
    return {"code": 200, "msg": "success", "data": data}


@router.get("/options")
def options(user: User = Depends(require_roles("admin", "director", "super_admin")), db: Session = Depends(get_db)):
    actor = current_actor(db, user, allowed_roles=SOURCE_ROLES)
    return response(
        {
            "scope_kinds": ["hospital_reviews", "explicit_doctor_cohort"] if actor.user_role != "director" else ["explicit_doctor_cohort"],
            "can_create_hospital": actor.user_role == "super_admin",
            "can_create_cohort": True,
            "can_review": actor.user_role == "super_admin",
            "can_audit_protected": actor.user_role == "super_admin",
            "max_doctors": 256,
            "max_days": 366,
            "max_roots": MAX_ROOTS,
            "max_bytes": MAX_BYTES,
            "max_scope_metadata_scanned": s.SCAN_CAP,
            "statistical_unit": "stored_review_record_not_visit_response_or_complaint",
            "time_basis": "stored_legacy_naive_calendar_timezone_unknown",
            "privacy_review": "legacy_manual_claim_not_guaranteed_anonymity",
        }
    )


@router.get("/doctors")
def doctors(
    page: QueryPositiveInteger = Query(1, ge=1),
    page_size: QueryPositiveInteger = Query(20, ge=1, le=100),
    user: User = Depends(require_roles("admin", "director", "super_admin")),
    db: Session = Depends(get_db),
):
    actor = lock_satisfaction_write(db, user, allowed_roles=SOURCE_ROLES)
    query = db.query(Doctor.doctor_id, Doctor.name, Doctor.department_id)
    if actor.user_role == "director":
        own = current_satisfaction_rows(db.query(Doctor.department_id).filter_by(user_id=actor.user_id), shared=True).all()
        departments = {r.department_id for r in own if r.department_id is not None}
        if not departments:
            raise HTTPException(403, "当前账户没有可核实的实际医生科室")
        query = query.filter(Doctor.department_id.in_(departments))
    total = current_satisfaction_rows(query, shared=True).count()
    rows = current_satisfaction_rows(query.order_by(Doctor.doctor_id), shared=True).offset((page - 1) * page_size).limit(page_size).all()
    return response(
        {
            "items": [dict(r._mapping) for r in rows],
            "total": total,
            "page": page,
            "page_size": page_size,
            "scope_note": "医生当前登记科室，仅用于显式有限医生集合权限；不代表评价时科室或全科室历史集合",
        }
    )


@router.post("/cases/preview")
def preview(req: CaptureRequest, user: User = Depends(require_roles("admin", "director", "super_admin")), db: Session = Depends(get_db)):
    return response(s.preview_input(db, user, req))


@router.post("/cases")
def create(req: CaseCreate, user: User = Depends(require_roles("admin", "director", "super_admin")), db: Session = Depends(get_db)):
    return response(s.create_case(db, user, req))


@router.get("/cases")
def cases(
    scope_kind: Literal["hospital_reviews", "explicit_doctor_cohort"] | None = None,
    doctor_ids: list[QueryPositiveInteger] = Query(default=[]),
    date_from: str | None = None,
    date_to: str | None = None,
    audit_only: bool = False,
    page: QueryPositiveInteger = Query(1, ge=1),
    page_size: QueryPositiveInteger = Query(20, ge=1, le=100),
    user: User = Depends(require_roles("admin", "director", "super_admin")),
    db: Session = Depends(get_db),
):
    actor = lock_satisfaction_write(db, user, allowed_roles={"super_admin"} if audit_only else SOURCE_ROLES)
    query = db.query(AISatisfactionCase)
    if not audit_only or scope_kind is not None:
        try:
            req = CaptureRequest(scope_kind=scope_kind, doctor_ids=doctor_ids, date_from=date_from, date_to=date_to)
        except ValueError as exc:
            raise HTTPException(422, "普通目录须提供确切医生范围及完整日期；不支持隐式全院查询") from exc
        s.authorize_scope(db, actor, req)
        query = query.filter(
            AISatisfactionCase.scope_kind == req.scope_kind,
            AISatisfactionCase.doctor_ids_json == s.canonical_json(req.doctor_ids),
            AISatisfactionCase.date_from == datetime.date.fromisoformat(req.date_from),
            AISatisfactionCase.date_to == datetime.date.fromisoformat(req.date_to),
        )
    elif doctor_ids or date_from is not None or date_to is not None:
        raise HTTPException(422, "审计过滤须提供完整范围，不能忽略残缺参数")
    total = current_satisfaction_rows(query.with_entities(AISatisfactionCase.case_id), shared=True).count()
    ids = (
        current_satisfaction_rows(query.with_entities(AISatisfactionCase.case_id).order_by(AISatisfactionCase.created_at.desc(), AISatisfactionCase.case_id), shared=True)
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    fields = ("case_id", "schema_version", "scope_kind", "date_from", "date_to", "created_at", "created_by", "content_hash", "collection_digest", *s.GOVERNANCE)
    items = []
    for (identifier,) in ids:
        row = current_satisfaction_rows(db.query(*(getattr(AISatisfactionCase, key) for key in fields)).filter(AISatisfactionCase.case_id == identifier), shared=True).one()
        meta = s.metadata(SimpleNamespace(**dict(row._mapping)))
        items.append({k: v for k, v in meta.items() if k not in {"review_basis_note", "revoke_reason"}})
    return response({"items": items, "total": total, "page": page, "page_size": page_size, "detail_required": True})


@router.get("/cases/{identifier}")
def detail(identifier: UUID, audit_only: bool = False, user: User = Depends(require_roles("admin", "director", "super_admin")), db: Session = Depends(get_db)):
    return response(s.case_current(db, user, identifier, audit_only=audit_only))


@router.post("/cases/{identifier}/review")
def review(identifier: UUID, req: SourceReview, user: User = Depends(require_roles("super_admin")), db: Session = Depends(get_db)):
    return response(s.review_case(db, user, identifier, req))


@router.post("/cases/{identifier}/revoke")
def revoke(identifier: UUID, req: SourceRevoke, user: User = Depends(require_roles("admin", "director", "super_admin")), db: Session = Depends(get_db)):
    return response(s.revoke_case(db, user, identifier, req))
