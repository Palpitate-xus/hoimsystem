"""Append-only, care-authorized inpatient measurements and declared urine intervals."""

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.ai.governance import audit
from app.database import get_db
from app.dependencies import require_roles
from app.inpatient_observations import (
    OBSERVATION_ROLES,
    POINT_VERSION,
    URINE_VERSION,
    ObservationRevoke,
    PointCreate,
    PointPayload,
    UrineCreate,
    UrinePayload,
    authorize_observation_admission,
    canonical_json,
    canonical_uuid,
    frozen_content_hash,
    source_current,
    utcnow,
)
from app.models import InpatientObservation, InpatientUrineInterval, User

router = APIRouter(prefix="/inpatient-observations", default_response_class=JSONResponse)


def _view(data, user):
    return {**data, "can_revoke": data["status"] == "active" and (data["created_by"] == user.user_id or user.user_role in {"admin", "super_admin"})}


def _commit(db):
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "观测来源或关联资料已改变，请重新核对") from exc


def _real_admission(db, user, patient_id, admission_id, *, creating=False):
    admission = authorize_observation_admission(db, user, patient_id, admission_id)
    if creating and admission.status != 1:
        raise HTTPException(409, "仅在院患者可新增观测；出院后补录须另走明确的补录流程")
    return admission


def _get(db, model, primary_key, identifier, patient_id, admission_id):
    try:
        canonical_uuid(identifier)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    row = db.query(model).filter(getattr(model, primary_key) == identifier, model.patient_id == patient_id, model.admission_id == admission_id).populate_existing().one_or_none()
    if row is None:
        raise HTTPException(404, "所选观测不存在或不属于指定患者及原住院")
    return row


def _list(db, user, model, time_key, primary_key, patient_id, admission_id, status, page, page_size):
    _real_admission(db, user, patient_id, admission_id)
    query = db.query(model).filter_by(patient_id=patient_id, admission_id=admission_id)
    if status is not None:
        query = query.filter_by(status=status)
    total = query.count()
    rows = query.order_by(getattr(model, time_key).desc(), getattr(model, primary_key)).offset((page - 1) * page_size).limit(page_size).all()
    sources = [source_current(db, row, allow_revoked=True) for row in rows]
    _real_admission(db, user, patient_id, admission_id)
    items = [_view(data, user) for data in sources]
    return {"code": 200, "msg": "分页原始观测不代表完整监测或已验证风险预测", "data": {"items": items, "total": total, "page": page, "page_size": page_size}}


def _detail(db, user, model, primary_key, identifier, patient_id, admission_id):
    _real_admission(db, user, patient_id, admission_id)
    row = _get(db, model, primary_key, identifier, patient_id, admission_id)
    data = source_current(db, row, allow_revoked=True)
    _real_admission(db, user, patient_id, admission_id)
    return {"code": 200, "msg": "success", "data": _view(data, user)}


def _revoke(db, user, model, primary_key, identifier, req):
    _real_admission(db, user, req.patient_id, req.admission_id)
    row = _get(db, model, primary_key, identifier, req.patient_id, req.admission_id)
    source_current(db, row, allow_revoked=True)
    if user.user_role not in {"admin", "super_admin"} and row.created_by != user.user_id:
        raise HTTPException(403, "仅原记录人或管理员可撤销该观测")
    if row.status != "active" or row.revision != req.expected_revision:
        raise HTTPException(409, "来源已改变或撤销，不能重复撤销或恢复")
    _real_admission(db, user, req.patient_id, req.admission_id)
    changed = (
        db.query(model)
        .filter(getattr(model, primary_key) == identifier, model.status == "active", model.revision == req.expected_revision, model.content_hash == row.content_hash)
        .update({"status": "revoked", "revision": 2, "revoked_at": utcnow(), "revoked_by": user.user_id, "revoke_reason": req.reason}, synchronize_session=False)
    )
    if changed != 1:
        db.rollback()
        raise HTTPException(409, "该来源已由其他请求改变，请刷新")
    audit(db, user.user_id, "inpatient_observation.revoke" if model is InpatientObservation else "urine_interval.revoke", identifier, {"content_hash": row.content_hash, "revision": 2})
    _commit(db)
    return {"code": 200, "msg": "已撤销；原临床内容保留，不支持恢复或改写", "data": _view(source_current(db, row, allow_revoked=True), user)}


@router.get("/points")
def list_points(
    patient_id: int = Query(ge=1, le=2147483647),
    admission_id: str = Query(min_length=36, max_length=36),
    status: Literal["active", "revoked"] | None = None,
    page: int = Query(default=1, ge=1, le=2147483647),
    page_size: int = Query(default=50, ge=1, le=100),
    user: User = Depends(require_roles(*OBSERVATION_ROLES)),
    db: Session = Depends(get_db),
):
    return _list(db, user, InpatientObservation, "observed_at", "observation_id", patient_id, admission_id, status, page, page_size)


@router.post("/points")
def create_point(req: PointCreate, user: User = Depends(require_roles(*OBSERVATION_ROLES)), db: Session = Depends(get_db)):
    _real_admission(db, user, req.patient_id, req.admission_id, creating=True)
    payload = PointPayload.model_validate(req.model_dump(include=set(PointPayload.model_fields))).model_dump(mode="json")
    row = InpatientObservation(
        observation_id=str(uuid.uuid4()),
        patient_id=req.patient_id,
        admission_id=req.admission_id,
        observed_at=req.observed_at,
        recorded_at=utcnow(),
        created_by=user.user_id,
        schema_version=POINT_VERSION,
        payload_json=canonical_json(payload),
        status="active",
        revision=1,
        revoke_reason="",
    )
    row.content_hash = frozen_content_hash(row, payload)
    db.add(row)
    _real_admission(db, user, req.patient_id, req.admission_id, creating=True)
    audit(db, user.user_id, "inpatient_observation.create", row.observation_id, {"content_hash": row.content_hash, "revision": 1, "admission_id": row.admission_id})
    _commit(db)
    return {"code": 200, "msg": "已冻结原始观测；未推算风险或自动写回护理文书", "data": _view(source_current(db, row), user)}


@router.get("/points/{observation_id}")
def detail_point(
    observation_id: str,
    patient_id: int = Query(ge=1, le=2147483647),
    admission_id: str = Query(min_length=36, max_length=36),
    user: User = Depends(require_roles(*OBSERVATION_ROLES)),
    db: Session = Depends(get_db),
):
    return _detail(db, user, InpatientObservation, "observation_id", observation_id, patient_id, admission_id)


@router.post("/points/{observation_id}/revoke")
def revoke_point(observation_id: str, req: ObservationRevoke, user: User = Depends(require_roles(*OBSERVATION_ROLES)), db: Session = Depends(get_db)):
    return _revoke(db, user, InpatientObservation, "observation_id", observation_id, req)


@router.get("/urine-intervals")
def list_urine_intervals(
    patient_id: int = Query(ge=1, le=2147483647),
    admission_id: str = Query(min_length=36, max_length=36),
    status: Literal["active", "revoked"] | None = None,
    page: int = Query(default=1, ge=1, le=2147483647),
    page_size: int = Query(default=50, ge=1, le=100),
    user: User = Depends(require_roles(*OBSERVATION_ROLES)),
    db: Session = Depends(get_db),
):
    return _list(db, user, InpatientUrineInterval, "start_at", "interval_id", patient_id, admission_id, status, page, page_size)


@router.post("/urine-intervals")
def create_urine_interval(req: UrineCreate, user: User = Depends(require_roles(*OBSERVATION_ROLES)), db: Session = Depends(get_db)):
    _real_admission(db, user, req.patient_id, req.admission_id, creating=True)
    payload = UrinePayload.model_validate(req.model_dump(include=set(UrinePayload.model_fields))).model_dump(mode="json")
    row = InpatientUrineInterval(
        interval_id=str(uuid.uuid4()),
        patient_id=req.patient_id,
        admission_id=req.admission_id,
        start_at=req.start_at,
        end_at=req.end_at,
        recorded_at=utcnow(),
        created_by=user.user_id,
        schema_version=URINE_VERSION,
        payload_json=canonical_json(payload),
        status="active",
        revision=1,
        revoke_reason="",
    )
    row.content_hash = frozen_content_hash(row, payload)
    db.add(row)
    _real_admission(db, user, req.patient_id, req.admission_id, creating=True)
    audit(db, user.user_id, "urine_interval.create", row.interval_id, {"content_hash": row.content_hash, "revision": 1, "admission_id": row.admission_id})
    _commit(db)
    return {"code": 200, "msg": "已冻结原尿量区间；重叠和缺项保留，未自动相加或换算尿率", "data": _view(source_current(db, row), user)}


@router.get("/urine-intervals/{interval_id}")
def detail_urine_interval(
    interval_id: str,
    patient_id: int = Query(ge=1, le=2147483647),
    admission_id: str = Query(min_length=36, max_length=36),
    user: User = Depends(require_roles(*OBSERVATION_ROLES)),
    db: Session = Depends(get_db),
):
    return _detail(db, user, InpatientUrineInterval, "interval_id", interval_id, patient_id, admission_id)


@router.post("/urine-intervals/{interval_id}/revoke")
def revoke_urine_interval(interval_id: str, req: ObservationRevoke, user: User = Depends(require_roles(*OBSERVATION_ROLES)), db: Session = Depends(get_db)):
    return _revoke(db, user, InpatientUrineInterval, "interval_id", interval_id, req)
