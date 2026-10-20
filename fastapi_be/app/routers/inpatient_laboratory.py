"""Scoped lab candidates and immutable registrations; Super keeps frozen withdrawal audit."""

import json
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.ai.governance import audit
from app.ai.lab_mappings import matching_mappings
from app.database import get_db
from app.dependencies import require_roles
from app.inpatient_laboratory import (
    LAB_READ_ROLES,
    LAB_SOURCE_ROLES,
    SourceCreate,
    SourceRevoke,
    authorize_scope,
    create_source,
    load_original,
    metadata,
    source_current,
    utcnow,
)
from app.inpatient_observations import canonical_uuid
from app.models import InpatientLabSource, LabObservation, LabOrder, LabResult, User

router = APIRouter(tags=["原住院检验来源"], default_response_class=JSONResponse)


def _commit(db):
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "原检验已有活动登记或来源发生竞争，请重新核对；不会覆盖原值") from exc


def _super(db, user):
    current = db.query(User).filter_by(user_id=user.user_id).with_for_update().populate_existing().one_or_none()
    if current is None or current.user_role != "super_admin":
        raise HTTPException(403, "当前身份没有全院检验来源审计权限")
    return current


def _get(db, identifier):
    try:
        canonical_uuid(identifier)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    row = db.query(InpatientLabSource).filter_by(lab_source_id=identifier).populate_existing().one_or_none()
    if row is None:
        raise HTTPException(404, "检验登记来源不存在")
    return row


def _can_revoke(row, user):
    return row.status == "active" and (row.created_by == user.user_id or user.user_role == "super_admin")


def detail(db, user, row):
    if user.user_role == "super_admin":
        _super(db, user)
    else:
        authorize_scope(db, user, row.patient_id, row.admission_id)
    data = {**metadata(row), "snapshot": None, "mapping_current": None, "eligible": False, "exclusion_reasons": ["source_stale"]}
    state, message = "stale", "原检验、归属、审核或映射已变化，不能作为当前风险输入"
    try:
        current = source_current(db, row, allow_revoked=True)
        data.update(current)
        state = "revoked" if row.status == "revoked" else "stale" if not current["eligible"] else "current"
        message = "当前原住院、检验及映射一致；仅本次受控登记可用，不代表历史发布UTC或模型验证" if state == "current" else "来源或映射已撤销，保留治理事实但不作为有效数值输入"
        if state != "current" and user.user_role != "super_admin":
            data["snapshot"] = None
    except HTTPException:
        if user.user_role == "super_admin":
            try:
                data["snapshot"] = json.loads(row.snapshot_json)
            except (ValueError, TypeError, RecursionError):
                data["snapshot"] = None
    if user.user_role != "super_admin":
        authorize_scope(db, user, row.patient_id, row.admission_id)
    return {**data, "freshness": {"state": state, "message": message}, "can_revoke": _can_revoke(row, user)}


def _scope_row(db, user, identifier, patient_id, admission_id):
    authorize_scope(db, user, patient_id, admission_id)
    row = _get(db, identifier)
    if row.patient_id != patient_id or row.admission_id != admission_id:
        raise HTTPException(409, "所选来源不属于本次患者与原住院")
    return row


def _list(db, user, *, patient_id, admission_id, status, page, page_size):
    query = db.query(InpatientLabSource)
    if patient_id is not None:
        query = query.filter_by(patient_id=patient_id)
    if admission_id is not None:
        try:
            canonical_uuid(admission_id)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        query = query.filter_by(admission_id=admission_id)
    if status is not None:
        query = query.filter_by(status=status)
    total = query.count()
    rows = query.order_by(InpatientLabSource.registered_at.desc(), InpatientLabSource.lab_source_id).offset((page - 1) * page_size).limit(page_size).all()
    return {"code": 200, "data": {"items": [detail(db, user, row) for row in rows], "total": total, "page": page, "page_size": page_size}}


@router.get("/inpatient-laboratory/candidates")
def candidates(
    patient_id: int = Query(ge=1, le=2147483647),
    admission_id: str = Query(min_length=36, max_length=36),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*LAB_READ_ROLES)),
):
    authorize_scope(db, user, patient_id, admission_id)
    rows = (
        db.query(LabObservation)
        .join(LabResult, LabObservation.lab_result_id == LabResult.lab_result_id)
        .join(LabOrder, LabResult.lab_order_id == LabOrder.lab_order_id)
        .filter(LabOrder.patient_id == patient_id, LabResult.audit_status == 1, LabOrder.status == 2)
        .order_by(LabObservation.collected_at.desc(), LabObservation.observation_id)
        .limit(101)
        .populate_existing()
        .all()
    )
    items = []
    for row in rows[:100]:
        observation, original, raw_hash = load_original(db, row.observation_id, patient_id)
        registration = db.query(InpatientLabSource.lab_source_id).filter_by(active_observation_id=observation.observation_id).first()
        items.append(
            {
                "observation_id": observation.observation_id,
                "original": original,
                "raw_original_hash": raw_hash,
                "matching_mappings": matching_mappings(db, observation),
                "registration": {"active_lab_source_id": registration[0] if registration else None, "status": "already_registered" if registration else "unregistered"},
                "scope_note": "仅同患者已审核候选，不证明属于本次住院；原钟点无时区依据，项目命名空间须另行明确核实",
            }
        )
    authorize_scope(db, user, patient_id, admission_id)
    return {"code": 200, "data": {"items": items, "truncated": len(rows) > 100}}


@router.get("/inpatient-laboratory/sources")
def list_sources(
    patient_id: int = Query(ge=1, le=2147483647),
    admission_id: str = Query(min_length=36, max_length=36),
    status: Literal["active", "revoked"] | None = None,
    page: int = Query(1, ge=1, le=2147483647),
    page_size: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*LAB_READ_ROLES)),
):
    authorize_scope(db, user, patient_id, admission_id)
    return _list(db, user, patient_id=patient_id, admission_id=admission_id, status=status, page=page, page_size=page_size)


@router.post("/inpatient-laboratory/sources")
def post_source(req: SourceCreate, db: Session = Depends(get_db), user: User = Depends(require_roles(*LAB_SOURCE_ROLES))):
    row = create_source(db, user, req)
    authorize_scope(db, user, req.patient_id, req.admission_id, creating=True)
    audit(
        db,
        user.user_id,
        "inpatient_lab_source.create",
        row.lab_source_id,
        {"content_hash": row.content_hash, "raw_original_hash": row.raw_original_hash, "mapping_content_hash": row.mapping_content_hash},
    )
    _commit(db)
    return {"code": 200, "msg": "已登记原住院检验来源；可用UTC仅为本次核实登记，不改旧钟点或模型验证", "data": detail(db, user, row)}


@router.get("/inpatient-laboratory/sources/{lab_source_id}")
def get_source(
    lab_source_id: str,
    patient_id: int = Query(ge=1, le=2147483647),
    admission_id: str = Query(min_length=36, max_length=36),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*LAB_READ_ROLES)),
):
    return {"code": 200, "data": detail(db, user, _scope_row(db, user, lab_source_id, patient_id, admission_id))}


@router.post("/inpatient-laboratory/sources/{lab_source_id}/revoke")
def revoke_source(lab_source_id: str, req: SourceRevoke, db: Session = Depends(get_db), user: User = Depends(require_roles(*LAB_READ_ROLES))):
    if user.user_role == "super_admin":
        user = _super(db, user)
        row = _get(db, lab_source_id)
        if row.patient_id != req.patient_id or row.admission_id != req.admission_id:
            raise HTTPException(409, "撤销请求与冻结来源的原患者/住院不一致")
    else:
        row = _scope_row(db, user, lab_source_id, req.patient_id, req.admission_id)
    if row.created_by != user.user_id and user.user_role != "super_admin":
        raise HTTPException(403, "仅原登记人或超级管理员可撤销该来源")
    if row.status != "active" or row.revision != req.expected_revision:
        raise HTTPException(409, "来源已改变或撤销，不可重复撤销或恢复")
    # Withdrawal deliberately does not require a still-valid original or mapping.
    # Broken and deleted parents must not strand an unusable active registration.
    count = (
        db.query(InpatientLabSource)
        .filter_by(lab_source_id=lab_source_id, status="active", revision=req.expected_revision)
        .update({"status": "revoked", "revision": 2, "active_observation_id": None, "revoked_at": utcnow(), "revoked_by": user.user_id, "revoke_reason": req.reason}, synchronize_session=False)
    )
    if count != 1:
        db.rollback()
        raise HTTPException(409, "来源已被其他请求撤销，请刷新")
    audit(db, user.user_id, "inpatient_lab_source.revoke", lab_source_id, {"content_hash": row.content_hash, "revision": 2})
    _commit(db)
    return {"code": 200, "msg": "来源已撤销，冻结原文保留；更正须新建，不支持恢复", "data": detail(db, user, _get(db, lab_source_id))}


@router.get("/ai/admin/lab-sources")
def admin_sources(
    patient_id: int | None = Query(None, ge=1, le=2147483647),
    admission_id: str | None = None,
    status: Literal["active", "revoked"] | None = None,
    page: int = Query(1, ge=1, le=2147483647),
    page_size: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("super_admin")),
):
    user = _super(db, user)
    return _list(db, user, patient_id=patient_id, admission_id=admission_id, status=status, page=page, page_size=page_size)


@router.get("/ai/admin/lab-sources/{lab_source_id}")
def admin_source(lab_source_id: str, db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin"))):
    user = _super(db, user)
    return {"code": 200, "data": detail(db, user, _get(db, lab_source_id))}
