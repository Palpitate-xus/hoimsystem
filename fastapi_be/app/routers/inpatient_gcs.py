"""Explicit original GCS recording and audit; no score inference or model calls."""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.ai.governance import audit
from app.ai.risk_rule_profiles import actual_super, canonical_id
from app.database import get_db
from app.dependencies import require_roles
from app.inpatient_gcs import READ_ROLES, GcsCreate, GcsRevoke, authorize_scope, create_source, current_actor, source_current, utcnow
from app.models import InpatientGcsObservation, User

router = APIRouter(tags=["原住院GCS观测"], default_response_class=JSONResponse)


def row_by_id(db, identifier):
    canonical_id(identifier)
    row = db.query(InpatientGcsObservation).filter_by(gcs_observation_id=identifier).populate_existing().one_or_none()
    if row is None:
        raise HTTPException(404, "原GCS观测不存在")
    return row


def finish(db, actor, action, target, detail):
    try:
        audit(db, actor.user_id, action, target, detail)
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "GCS原资料或治理版本竞争，本次变更与审计均未覆盖") from exc
    except Exception:
        db.rollback()
        raise


def can_record(db, user, patient_id, admission_id):
    try:
        authorize_scope(db, user, patient_id, admission_id, creating=True)
        return True
    except HTTPException:
        return False


def detail(db, user, row):
    actor = current_actor(db, user)
    if actor.user_role != "super_admin":
        authorize_scope(db, actor, row.patient_id, row.admission_id)
    data = source_current(db, row, allow_revoked=True)
    if actor.user_role != "super_admin":
        authorize_scope(db, actor, row.patient_id, row.admission_id)
    return {
        **data,
        "can_revoke": row.status == "active" and (actor.user_role == "super_admin" or row.created_by == actor.user_id),
        "can_record": can_record(db, actor, row.patient_id, row.admission_id),
    }


def scoped_row(db, user, identifier, patient_id, admission_id):
    actor = authorize_scope(db, user, patient_id, admission_id)
    row = row_by_id(db, identifier)
    if row.patient_id != patient_id or row.admission_id != admission_id:
        raise HTTPException(409, "原GCS不属于指定患者及原住院")
    return actor, row


def listing(db, user, patient_id, admission_id, status, page, page_size):
    query = db.query(InpatientGcsObservation)
    if patient_id is not None:
        query = query.filter_by(patient_id=patient_id)
    if admission_id is not None:
        query = query.filter_by(admission_id=canonical_id(admission_id))
    if status is not None:
        query = query.filter_by(status=status)
    total = query.count()
    rows = query.order_by(InpatientGcsObservation.observed_at.desc(), InpatientGcsObservation.gcs_observation_id).offset((page - 1) * page_size).limit(page_size).all()
    return {"items": [detail(db, user, row) for row in rows], "total": total, "page": page, "page_size": page_size}


@router.get("/inpatient-gcs")
def sources(
    patient_id: int = Query(ge=1, le=2147483647),
    admission_id: str = Query(min_length=36, max_length=36),
    status: Literal["active", "revoked"] | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*READ_ROLES)),
):
    actor = authorize_scope(db, user, patient_id, admission_id)
    data = {**listing(db, actor, patient_id, admission_id, status, page, page_size), "can_record": can_record(db, actor, patient_id, admission_id)}
    authorize_scope(db, actor, patient_id, admission_id)
    return {"code": 200, "data": data}


@router.post("/inpatient-gcs")
def post_source(req: GcsCreate, db: Session = Depends(get_db), user: User = Depends(require_roles(*READ_ROLES))):
    row = create_source(db, user, req)
    actor = authorize_scope(db, user, row.patient_id, row.admission_id, creating=True)
    finish(db, actor, "gcs_observation.create", row.gcs_observation_id, {"content_hash": row.content_hash, "revision": 1})
    return {"code": 200, "msg": "已冻结GCS原分项与真实UTC时刻；NT不补分，未调用AI", "data": detail(db, actor, row)}


@router.get("/inpatient-gcs/{gcs_observation_id}")
def source(
    gcs_observation_id: str,
    patient_id: int = Query(ge=1, le=2147483647),
    admission_id: str = Query(min_length=36, max_length=36),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*READ_ROLES)),
):
    actor, row = scoped_row(db, user, gcs_observation_id, patient_id, admission_id)
    return {"code": 200, "data": detail(db, actor, row)}


@router.post("/inpatient-gcs/{gcs_observation_id}/revoke")
def revoke(gcs_observation_id: str, req: GcsRevoke, db: Session = Depends(get_db), user: User = Depends(require_roles(*READ_ROLES))):
    actor, row = scoped_row(db, user, gcs_observation_id, req.patient_id, req.admission_id)
    source_current(db, row, allow_revoked=True)
    if actor.user_role != "super_admin" and row.created_by != actor.user_id:
        raise HTTPException(403, "仅原记录人或超级管理员可撤销GCS原观测")
    if row.status != "active" or row.revision != req.expected_revision:
        raise HTTPException(409, "GCS来源已改变或撤销，不重复撤销或恢复")
    authorize_scope(db, actor, req.patient_id, req.admission_id)
    changed = (
        db.query(InpatientGcsObservation)
        .filter_by(gcs_observation_id=gcs_observation_id, status="active", revision=req.expected_revision, content_hash=row.content_hash)
        .update({"status": "revoked", "revision": 2, "revoked_at": utcnow(), "revoked_by": actor.user_id, "revoke_reason": req.reason}, synchronize_session=False)
    )
    if changed != 1:
        db.rollback()
        raise HTTPException(409, "GCS来源已被并发修改，请刷新")
    finish(db, actor, "gcs_observation.revoke", gcs_observation_id, {"content_hash": row.content_hash, "revision": 2})
    return {"code": 200, "data": detail(db, actor, row_by_id(db, gcs_observation_id))}


@router.get("/ai/admin/gcs-sources")
def admin_sources(
    patient_id: int | None = Query(None, ge=1, le=2147483647),
    admission_id: str | None = None,
    status: Literal["active", "revoked"] | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("super_admin")),
):
    actor = actual_super(db, user)
    return {"code": 200, "data": listing(db, actor, patient_id, admission_id, status, page, page_size)}


@router.get("/ai/admin/gcs-sources/{gcs_observation_id}")
def admin_source(gcs_observation_id: str, db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin"))):
    actor = actual_super(db, user)
    return {"code": 200, "data": detail(db, actor, row_by_id(db, gcs_observation_id))}
