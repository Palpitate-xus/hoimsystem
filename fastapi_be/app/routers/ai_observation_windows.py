"""Scoped immutable observation-window creation, inspection and revocation."""

import datetime
import json
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.ai.governance import audit, ensure_revision
from app.ai.models import AIObservationWindow, utcnow
from app.ai.observation_windows import WINDOW_ROLES, authorize_scope, canonical_id, create_window, iso, snapshot_current
from app.database import get_db
from app.dependencies import require_roles
from app.models import User

router = APIRouter(tags=["AI住院观测窗"], default_response_class=JSONResponse)


class WindowCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    patient_id: int = Field(strict=True, ge=1)
    admission_id: str = Field(min_length=36, max_length=36)
    start_at: datetime.datetime
    end_at: datetime.datetime
    as_of: datetime.datetime

    @field_validator("start_at", "end_at", "as_of", mode="before")
    @classmethod
    def explicit_utc(cls, value):
        from app.inpatient_observations import explicit_utc

        return explicit_utc(value)


class WindowRevoke(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(strict=True, ge=1)
    reason: str = Field(min_length=1, max_length=1000)

    @field_validator("reason")
    @classmethod
    def meaningful(cls, value):
        if not value.strip():
            raise ValueError("须记录撤销依据")
        return value


def _commit(db):
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "原住院或来源状态已改变，请刷新后核对") from exc


def _row(db, identifier):
    canonical_id(identifier)
    row = db.query(AIObservationWindow).filter_by(window_id=identifier).populate_existing().one_or_none()
    if row is None:
        raise HTTPException(404, "观测窗不存在")
    return row


def metadata(row, user):
    return {
        **{key: getattr(row, key) for key in ("window_id", "patient_id", "admission_id", "created_by", "schema_version", "content_hash", "status", "revision")},
        **{key: iso(getattr(row, key)) for key in ("created_at", "start_at", "end_at", "as_of")},
        "source_id": f"observation_window:{row.window_id}:{row.content_hash[:12]}",
        "can_revoke": row.status == "active" and (user.user_role == "super_admin" or row.created_by == user.user_id),
        "freshness": {"state": "not_checked"},
    }


def detail(db, user, row):
    if user.user_role != "super_admin":
        authorize_scope(db, user, row.patient_id, row.admission_id)
    snapshot, state, message = None, "current", "当前原住院权限与冻结来源一致；不代表采样完整或模型验证"
    try:
        snapshot = snapshot_current(db, user, row)
    except HTTPException:
        state = "revoked" if row.status == "revoked" else "stale"
        message = "原窗已撤销或原资料、时间归属、成员及当前权限不再一致，不能继续生成"
        if user.user_role == "super_admin":
            try:
                snapshot = json.loads(row.snapshot_json)
            except (ValueError, TypeError):
                snapshot = None
    return {
        **metadata(row, user),
        "snapshot": snapshot,
        "freshness": {"state": state, "message": message},
        "revoked_at": iso(row.revoked_at) if row.revoked_at else None,
        "revoked_by": row.revoked_by,
        "revoke_reason": row.revoke_reason,
    }


@router.post("/ai/observation-windows")
def post_window(req: WindowCreate, db: Session = Depends(get_db), user: User = Depends(require_roles(*WINDOW_ROLES))):
    row = create_window(db, user, req.model_dump())
    audit(db, user.user_id, "observation_window.create", row.window_id, {"content_hash": row.content_hash, "revision": row.revision})
    _commit(db)
    return {"code": 200, "msg": "已冻结离散原住院记录，不代表连续监护完整或模型已验证", "data": detail(db, user, row)}


@router.get("/ai/observation-windows")
def list_windows(patient_id: int = Query(ge=1), admission_id: str = Query(min_length=36, max_length=36), db: Session = Depends(get_db), user: User = Depends(require_roles(*WINDOW_ROLES))):
    authorize_scope(db, user, patient_id, admission_id)
    rows = db.query(AIObservationWindow).filter_by(patient_id=patient_id, admission_id=admission_id).order_by(AIObservationWindow.created_at.desc(), AIObservationWindow.window_id).limit(101).all()
    return {"code": 200, "msg": "列表未逐项重核原资料，选择后须查看当前一致性", "data": [metadata(row, user) for row in rows[:100]], "truncated": len(rows) > 100}


@router.get("/ai/observation-windows/{window_id}")
def get_window(
    window_id: str, patient_id: int = Query(ge=1), admission_id: str = Query(min_length=36, max_length=36), db: Session = Depends(get_db), user: User = Depends(require_roles(*WINDOW_ROLES))
):
    authorize_scope(db, user, patient_id, admission_id)
    row = _row(db, window_id)
    if row.patient_id != patient_id or row.admission_id != admission_id:
        raise HTTPException(409, "观测窗不属于本次患者与原住院")
    return {"code": 200, "msg": "success", "data": detail(db, user, row)}


@router.post("/ai/observation-windows/{window_id}/revoke")
def revoke_window(window_id: str, req: WindowRevoke, db: Session = Depends(get_db), user: User = Depends(require_roles(*WINDOW_ROLES))):
    row = _row(db, window_id)
    if user.user_role != "super_admin":
        authorize_scope(db, user, row.patient_id, row.admission_id)
        if row.created_by != user.user_id:
            raise HTTPException(403, "只能撤销本人创建的观测窗，超级管理员可管理全部")
    ensure_revision(row.revision, req.expected_revision)
    if row.status != "active":
        raise HTTPException(409, "原窗已撤销，不能恢复或重复修改")
    changed = (
        db.query(AIObservationWindow)
        .filter_by(window_id=window_id, status="active", revision=req.expected_revision)
        .update({"status": "revoked", "revision": req.expected_revision + 1, "revoked_at": utcnow(), "revoked_by": user.user_id, "revoke_reason": req.reason}, synchronize_session=False)
    )
    if changed != 1:
        db.rollback()
        raise HTTPException(409, "观测窗版本已改变，请刷新")
    audit(db, user.user_id, "observation_window.revoke", window_id, {"revision": req.expected_revision + 1})
    _commit(db)
    return {"code": 200, "msg": "观测窗已撤销，冻结记录保留，不能恢复", "data": detail(db, user, _row(db, window_id))}


@router.get("/ai/admin/observation-windows")
def admin_windows(
    patient_id: int | None = Query(None, ge=1),
    admission_id: str | None = None,
    status: Literal["active", "revoked"] | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("super_admin")),
):
    query = db.query(AIObservationWindow)
    if patient_id is not None:
        query = query.filter_by(patient_id=patient_id)
    if admission_id is not None:
        canonical_id(admission_id)
        query = query.filter_by(admission_id=admission_id)
    if status is not None:
        query = query.filter_by(status=status)
    rows = query.order_by(AIObservationWindow.created_at.desc(), AIObservationWindow.window_id).limit(101).all()
    return {"code": 200, "msg": "冻结审计目录，当前一致性须逐项复核", "data": [metadata(row, user) for row in rows[:100]], "truncated": len(rows) > 100}


@router.get("/ai/admin/observation-windows/{window_id}")
def admin_window(window_id: str, db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin"))):
    return {"code": 200, "msg": "success", "data": detail(db, user, _row(db, window_id))}
