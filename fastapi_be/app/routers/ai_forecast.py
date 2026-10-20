"""Super-admin registration coverage declarations and scoped business source directory."""

import datetime
import json
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.ai.forecast_sources import (
    _typed_source,
    canonical_series_id,
    create_series,
    forecast_scope,
    preview_series,
    series_metadata,
    source_current,
)
from app.ai.governance import audit, ensure_revision
from app.ai.models import AIForecastSeries, utcnow
from app.database import get_db
from app.dependencies import get_current_user, require_roles
from app.models import User

router = APIRouter()


class ForecastPreview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scope: Literal["hospital", "department"]
    department_id: int | None = Field(default=None, strict=True, ge=1)
    date_from: str = Field(min_length=10, max_length=10)
    date_to: str = Field(min_length=10, max_length=10)
    timezone: str = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def check_scope(self):
        if (self.scope == "hospital" and self.department_id is not None) or (self.scope == "department" and self.department_id is None):
            raise ValueError("来源必须选择全院或一个明确科室")
        return self


class ForecastCreate(ForecastPreview):
    name: str = Field(min_length=1, max_length=120)
    expected_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    coverage_note: str = Field(min_length=20, max_length=2000)
    coverage_confirmed: Literal[True]
    days_ended_confirmed: Literal[True]
    timezone_confirmed: Literal[True]

    @field_validator("coverage_confirmed", "days_ended_confirmed", "timezone_confirmed", mode="before")
    @classmethod
    def explicit_confirmation(cls, value):
        if value is not True:
            raise ValueError("每项声明都必须显式确认")
        return value

    @field_validator("name")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("名称不能为空白")
        return value

    @field_validator("coverage_note")
    @classmethod
    def meaningful_note(cls, value):
        if len(value.strip()) < 20:
            raise ValueError("完整性依据须有至少20字有效说明")
        return value


class ForecastRevoke(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(strict=True, ge=1)
    reason: str = Field(min_length=1, max_length=1000)

    @field_validator("reason")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("撤销依据不能为空白")
        return value


def _current_super(db, user):
    actor = db.query(User).filter_by(user_id=user.user_id).populate_existing().one_or_none()
    if actor is None or actor.user_role != "super_admin":
        raise HTTPException(403, "当前用户不再具备AI来源管理权限")


def _commit(db):
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "来源或其关联范围已改变，请重新预览") from exc


def _get_series(db, series_id):
    canonical_series_id(series_id)
    row = db.query(AIForecastSeries).filter_by(series_id=series_id).populate_existing().one_or_none()
    if row is None:
        raise HTTPException(404, "预测来源不存在")
    return row


def _detail(db, user, row):
    current, error, source = False, None, None
    try:
        source = _typed_source(json.loads(row.source_json))
    except (ValueError, TypeError):
        error = "冻结来源格式校验失败"
    if source is not None:
        try:
            source_current(db, user, row)
            current = True
        except HTTPException as exc:
            error = str(exc.detail)
    return {
        **series_metadata(row),
        "source": source,
        "coverage_note": row.coverage_note,
        "created_by": row.created_by,
        "revoked_by": row.revoked_by,
        "revoked_at": row.revoked_at.replace(tzinfo=datetime.UTC).isoformat() if row.revoked_at else None,
        "revoke_reason": row.revoke_reason,
        "current": current,
        "current_error": error,
        "quality": {"source_checked": True, "coverage_status": "super_admin_attested", "notes": ["完整性为人工声明，原资料仍需当前复核；挂号记录数不等于实际到诊量，也不证明预测已验证"]},
    }


@router.get("/ai/admin/forecast-series", response_class=JSONResponse)
def admin_list_forecast_series(status: Literal["active", "revoked"] | None = None, db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin"))):
    query = db.query(AIForecastSeries)
    if status is not None:
        query = query.filter(AIForecastSeries.status == status)
    rows = query.order_by(AIForecastSeries.create_time.desc(), AIForecastSeries.series_id).limit(101).all()
    return {"code": 200, "msg": "success", "data": {"items": [series_metadata(row) for row in rows[:100]], "truncated": len(rows) > 100}}


@router.post("/ai/admin/forecast-series/preview", response_class=JSONResponse)
def preview_forecast_series(req: ForecastPreview, db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin"))):
    data = preview_series(db, **req.model_dump())
    _current_super(db, user)
    return {"code": 200, "msg": "尚未确认完整覆盖，所有日期的可训练值仍为未知", "data": data}


@router.post("/ai/admin/forecast-series", response_class=JSONResponse)
def create_forecast_series(req: ForecastCreate, db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin"))):
    row = create_series(db, user, req.model_dump())
    _current_super(db, user)
    audit(db, user.user_id, "forecast_series.create", row.series_id, {"content_hash": row.content_hash, "registration_digest": row.registration_digest, "revision": row.revision, "scope": row.scope})
    _commit(db)
    return {"code": 200, "msg": "已冻结来源；完整性声明不代表预测模型已验证", "data": _detail(db, user, row)}


@router.get("/ai/admin/forecast-series/{series_id}", response_class=JSONResponse)
def detail_forecast_series(series_id: str, db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin"))):
    data = _detail(db, user, _get_series(db, series_id))
    _current_super(db, user)
    return {"code": 200, "msg": "success", "data": data}


@router.post("/ai/admin/forecast-series/{series_id}/revoke", response_class=JSONResponse)
def revoke_forecast_series(series_id: str, req: ForecastRevoke, db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin"))):
    row = _get_series(db, series_id)
    ensure_revision(row.revision, req.expected_revision)
    if row.status != "active":
        raise HTTPException(409, "该来源已经撤销，不能恢复或重复修改")
    _current_super(db, user)
    changed = (
        db.query(AIForecastSeries)
        .filter_by(series_id=series_id, revision=req.expected_revision, status="active")
        .update({"status": "revoked", "revision": req.expected_revision + 1, "revoked_by": user.user_id, "revoked_at": utcnow(), "revoke_reason": req.reason}, synchronize_session=False)
    )
    if changed != 1:
        db.rollback()
        raise HTTPException(409, "来源已被其他管理员撤销，请刷新")
    audit(db, user.user_id, "forecast_series.revoke", series_id, {"revision": req.expected_revision + 1, "content_hash": row.content_hash})
    _commit(db)
    return {"code": 200, "msg": "来源已撤销，原声明保留冻结审计；需要修改请新建来源", "data": _detail(db, user, _get_series(db, series_id))}


@router.get("/ai/forecast-series", response_class=JSONResponse)
def business_forecast_series(department_id: int | None = Query(default=None, ge=1), db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    departments = forecast_scope(db, user)
    if department_id is not None and departments is not None and department_id not in departments:
        raise HTTPException(403, "不能列出其他科室的预测来源")
    query = db.query(AIForecastSeries).filter(AIForecastSeries.status == "active")
    if department_id is not None:
        query = query.filter(AIForecastSeries.scope == "department", AIForecastSeries.department_id == department_id)
    elif departments is not None:
        query = query.filter(AIForecastSeries.scope == "department", AIForecastSeries.department_id.in_(departments))
    rows = query.order_by(AIForecastSeries.create_time.desc(), AIForecastSeries.series_id).limit(101).all()
    return {"code": 200, "msg": "列表仅核对当前权限与活动状态，原资料是否仍一致须在选择后复核", "data": {"items": [series_metadata(row) for row in rows[:100]], "truncated": len(rows) > 100}}
