"""Super-only laboratory identity drafts, explicit publication and withdrawal."""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.ai.governance import audit
from app.ai.lab_mappings import ANALYTES, MAPPING_ROLES, MappingCreate, canonical_id, create_mapping, mapping_detail
from app.ai.models import AILabMapping, utcnow
from app.database import get_db
from app.dependencies import require_roles
from app.models import User

router = APIRouter(tags=["AI检验项目映射"], default_response_class=JSONResponse)


class MappingPublish(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    expected_revision: int = Field(ge=1)
    semantic_confirmed: Literal[True]
    source_signature_confirmed: Literal[True]
    review_note: str = Field(min_length=20, max_length=2000)

    @field_validator("semantic_confirmed", "source_signature_confirmed", mode="before")
    @classmethod
    def explicit_true(cls, value):
        if value is not True:
            raise ValueError("须分别明确核对项目定义及原命名空间/编码/单位/方法/标本")
        return value

    @field_validator("review_note")
    @classmethod
    def meaningful(cls, value):
        if len(value.strip()) < 20:
            raise ValueError("审核说明须至少20字有效内容")
        return value


class MappingRevoke(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    expected_revision: int = Field(ge=1)
    reason: str = Field(min_length=5, max_length=1000)

    @field_validator("reason")
    @classmethod
    def meaningful(cls, value):
        if len(value.strip()) < 5:
            raise ValueError("撤销说明须至少5字有效内容")
        return value


def _super(db, user):
    current = db.query(User).filter_by(user_id=user.user_id).with_for_update().populate_existing().one_or_none()
    if current is None or current.user_role != "super_admin":
        raise HTTPException(403, "当前身份不再具有AI项目映射管理权限")
    return current


def _commit(db):
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "当前命名空间/身份已有已发布版本或版本发生竞争，请刷新核对") from exc


@router.get("/ai/admin/lab-mappings/options")
def options(db: Session = Depends(get_db), user: User = Depends(require_roles(*MAPPING_ROLES))):
    _super(db, user)
    return {
        "code": 200,
        "data": {
            "analytes": [{"key": key, "label": label} for key, label in ANALYTES.items()],
            "states": ["draft", "published", "revoked"],
            "clinical_mapping_seeded": False,
            "scope_note": "仅项目分类选项；无预置原项目映射、单位换算或风险模型验证",
        },
    }


@router.get("/ai/admin/lab-mappings")
def list_mappings(
    status: Literal["draft", "published", "revoked"] | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*MAPPING_ROLES)),
):
    _super(db, user)
    query = db.query(AILabMapping)
    if status:
        query = query.filter_by(status=status)
    total = query.count()
    rows = query.order_by(AILabMapping.created_at.desc(), AILabMapping.mapping_id).offset((page - 1) * page_size).limit(page_size).all()
    return {"code": 200, "data": {"items": [mapping_detail(db, row) for row in rows], "total": total, "page": page, "page_size": page_size}}


@router.post("/ai/admin/lab-mappings")
def post_mapping(req: MappingCreate, db: Session = Depends(get_db), user: User = Depends(require_roles(*MAPPING_ROLES))):
    user = _super(db, user)
    row = create_mapping(db, user, req.model_dump())
    audit(db, user.user_id, "lab_mapping.create", row.mapping_id, {"content_hash": row.content_hash, "revision": row.revision})
    _commit(db)
    return {"code": 200, "msg": "映射草稿已保存，尚未审核发布或改变模型验证", "data": mapping_detail(db, row)}


@router.get("/ai/admin/lab-mappings/{mapping_id}")
def get_mapping(mapping_id: str, db: Session = Depends(get_db), user: User = Depends(require_roles(*MAPPING_ROLES))):
    _super(db, user)
    return {"code": 200, "data": mapping_detail(db, mapping_id)}


@router.post("/ai/admin/lab-mappings/{mapping_id}/publish")
def publish_mapping(mapping_id: str, req: MappingPublish, db: Session = Depends(get_db), user: User = Depends(require_roles(*MAPPING_ROLES))):
    user = _super(db, user)
    data = mapping_detail(db, canonical_id(mapping_id))
    if data["status"] != "draft" or req.expected_revision != data["revision"]:
        raise HTTPException(409, "仅当前草稿可发布；撤销版本不可恢复")
    now = utcnow()
    try:
        count = (
            db.query(AILabMapping)
            .filter_by(mapping_id=mapping_id, status="draft", revision=req.expected_revision, content_hash=data["content_hash"])
            .update(
                {
                    "status": "published",
                    "revision": 2,
                    "published_key": db.query(AILabMapping.identity_hash).filter_by(mapping_id=mapping_id).scalar(),
                    "published_at": now,
                    "published_by": user.user_id,
                    "review_note": req.review_note,
                },
                synchronize_session=False,
            )
        )
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "此命名空间与原身份已有发布映射，请先核对并撤销旧版本") from exc
    if count != 1:
        db.rollback()
        raise HTTPException(409, "草稿已变化，请重新核对")
    audit(db, user.user_id, "lab_mapping.publish", mapping_id, {"content_hash": data["content_hash"], "revision": 2})
    _commit(db)
    return {"code": 200, "msg": "项目身份已审核；不代表临床风险模型已验证", "data": mapping_detail(db, mapping_id)}


@router.post("/ai/admin/lab-mappings/{mapping_id}/revoke")
def revoke_mapping(mapping_id: str, req: MappingRevoke, db: Session = Depends(get_db), user: User = Depends(require_roles(*MAPPING_ROLES))):
    user = _super(db, user)
    data = mapping_detail(db, mapping_id)
    if data["status"] == "revoked" or req.expected_revision != data["revision"]:
        raise HTTPException(409, "映射已撤销或版本改变，不能重复撤销或恢复")
    count = (
        db.query(AILabMapping)
        .filter_by(mapping_id=mapping_id, status=data["status"], revision=req.expected_revision, content_hash=data["content_hash"])
        .update(
            {"status": "revoked", "revision": req.expected_revision + 1, "published_key": None, "revoked_at": utcnow(), "revoked_by": user.user_id, "revoke_reason": req.reason},
            synchronize_session=False,
        )
    )
    if count != 1:
        db.rollback()
        raise HTTPException(409, "映射已改变，请刷新后核对")
    audit(db, user.user_id, "lab_mapping.revoke", mapping_id, {"content_hash": data["content_hash"], "revision": req.expected_revision + 1})
    _commit(db)
    return {"code": 200, "msg": "映射已撤销，原正文与审核历史保留", "data": mapping_detail(db, mapping_id)}
