"""Super-only fixed rule implementation review, CAS publication and irreversible withdrawal."""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.ai.governance import audit
from app.ai.models import AIRiskRuleProfile, utcnow
from app.ai.risk_rule_profiles import PROFILE_ROLES, ProfileCreate, actual_super, canonical_id, create_profile, fixed_options, profile_detail
from app.database import get_db
from app.dependencies import require_roles
from app.models import User

router = APIRouter(tags=["AI固定风险规则实施审核"], default_response_class=JSONResponse)


class ProfilePublish(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    expected_revision: int = Field(ge=1)
    expected_recipe_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    implementation_terms_confirmed: Literal[True]
    review_note: str = Field(min_length=20, max_length=2000)
    review_evidence_reference: str = Field(min_length=5, max_length=2000)

    @field_validator("implementation_terms_confirmed", mode="before")
    @classmethod
    def explicit_true(cls, value):
        if value is not True:
            raise ValueError("须显式确认实施条款，不能用数字或字符串代替")
        return value

    @field_validator("review_note", "review_evidence_reference")
    @classmethod
    def meaningful(cls, value, info):
        if len(value.strip()) < (20 if info.field_name == "review_note" else 5):
            raise ValueError("请填写有效实施审核说明及依据")
        return value


class ProfileRevoke(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    expected_revision: int = Field(ge=1)
    reason: str = Field(min_length=5, max_length=1000)

    @field_validator("reason")
    @classmethod
    def meaningful(cls, value):
        if len(value.strip()) < 5:
            raise ValueError("撤销原因至少5字有效内容")
        return value


def commit(db):
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "该规则已有发布版本或资料发生竞争；原审核与审计均未覆盖") from exc


@router.get("/ai/admin/risk-rule-profiles/options")
def options(db: Session = Depends(get_db), user: User = Depends(require_roles(*PROFILE_ROLES))):
    actual_super(db, user)
    return {"code": 200, "data": {"items": fixed_options(), "clinical_validation": "not_provided", "feature_activation_changed": False}}


@router.get("/ai/admin/risk-rule-profiles")
def profiles(
    status: Literal["draft", "published", "revoked"] | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*PROFILE_ROLES)),
):
    actual_super(db, user)
    query = db.query(AIRiskRuleProfile)
    if status is not None:
        query = query.filter_by(status=status)
    total = query.count()
    rows = query.order_by(AIRiskRuleProfile.created_at.desc(), AIRiskRuleProfile.rule_profile_id).offset((page - 1) * page_size).limit(page_size).all()
    return {"code": 200, "data": {"items": [profile_detail(db, row) for row in rows], "total": total, "page": page, "page_size": page_size}}


@router.post("/ai/admin/risk-rule-profiles")
def post_profile(req: ProfileCreate, db: Session = Depends(get_db), user: User = Depends(require_roles(*PROFILE_ROLES))):
    row = create_profile(db, user, req)
    audit(db, user.user_id, "risk_rule_profile.create", row.rule_profile_id, {"content_hash": row.content_hash, "recipe_digest": row.recipe_digest})
    commit(db)
    return {"code": 200, "data": profile_detail(db, row)}


@router.get("/ai/admin/risk-rule-profiles/{rule_profile_id}")
def get_profile(rule_profile_id: str, db: Session = Depends(get_db), user: User = Depends(require_roles(*PROFILE_ROLES))):
    actual_super(db, user)
    return {"code": 200, "data": profile_detail(db, rule_profile_id)}


@router.post("/ai/admin/risk-rule-profiles/{rule_profile_id}/publish")
def publish_profile(rule_profile_id: str, req: ProfilePublish, db: Session = Depends(get_db), user: User = Depends(require_roles(*PROFILE_ROLES))):
    actual_super(db, user)
    data = profile_detail(db, canonical_id(rule_profile_id))
    if data["status"] != "draft" or data["revision"] != req.expected_revision or not data["implementation_current"] or data["recipe_digest"] != req.expected_recipe_digest:
        raise HTTPException(409, "仅当前固定实现的原草稿可发布；请重新核对版本与摘要")
    try:
        count = (
            db.query(AIRiskRuleProfile)
            .filter_by(rule_profile_id=rule_profile_id, status="draft", revision=req.expected_revision, content_hash=data["content_hash"])
            .update(
                {
                    "status": "published",
                    "revision": 2,
                    "published_key": db.query(AIRiskRuleProfile.identity_hash).filter_by(rule_profile_id=rule_profile_id).scalar(),
                    "published_at": utcnow(),
                    "published_by": user.user_id,
                    "implementation_terms_confirmed": 1,
                    "review_note": req.review_note,
                    "review_evidence_reference": req.review_evidence_reference,
                },
                synchronize_session=False,
            )
        )
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "同规则已有发布实施版本，请先核对并撤销旧版本") from exc
    if count != 1:
        db.rollback()
        raise HTTPException(409, "规则已改变，请刷新后核对")
    audit(db, user.user_id, "risk_rule_profile.publish", rule_profile_id, {"content_hash": data["content_hash"], "recipe_digest": data["recipe_digest"]})
    commit(db)
    return {"code": 200, "msg": "实施版本已审核，不改变功能开关或临床验证状态", "data": profile_detail(db, rule_profile_id)}


@router.post("/ai/admin/risk-rule-profiles/{rule_profile_id}/revoke")
def revoke_profile(rule_profile_id: str, req: ProfileRevoke, db: Session = Depends(get_db), user: User = Depends(require_roles(*PROFILE_ROLES))):
    actual_super(db, user)
    data = profile_detail(db, rule_profile_id)
    if data["status"] == "revoked" or data["revision"] != req.expected_revision:
        raise HTTPException(409, "规则已撤销或版本改变，不可恢复")
    count = (
        db.query(AIRiskRuleProfile)
        .filter_by(rule_profile_id=rule_profile_id, status=data["status"], revision=req.expected_revision, content_hash=data["content_hash"])
        .update(
            {"status": "revoked", "revision": req.expected_revision + 1, "published_key": None, "revoked_at": utcnow(), "revoked_by": user.user_id, "revoke_reason": req.reason},
            synchronize_session=False,
        )
    )
    if count != 1:
        db.rollback()
        raise HTTPException(409, "规则发生竞争，请刷新后核对")
    audit(db, user.user_id, "risk_rule_profile.revoke", rule_profile_id, {"content_hash": data["content_hash"]})
    commit(db)
    return {"code": 200, "data": profile_detail(db, rule_profile_id)}
