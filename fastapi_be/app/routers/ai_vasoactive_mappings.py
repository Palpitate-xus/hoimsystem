"""Super-only explicit actual drug identity mapping drafts and CAS governance."""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.ai.governance import audit
from app.database import get_db
from app.dependencies import require_roles
from app.inpatient_laboratory import hash_content
from app.inpatient_vasoactive import DRUG_KEYS, MAPPING_ROLES, RATE_UNITS, MappingCreate, create_mapping, mapping_detail, mapping_super, original_drug_identity, utcnow
from app.inpatient_vasoactive_models import AIVasoactiveDrugMapping
from app.models import Pharmaceutical, User

router = APIRouter(tags=["AI血管活性药物原身份映射"], default_response_class=JSONResponse)


class MappingPublish(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    expected_revision: int = Field(ge=1)
    original_identity_confirmed: Literal[True]
    drug_semantics_confirmed: Literal[True]
    rate_units_confirmed: Literal[True]
    review_note: str = Field(min_length=20, max_length=2000)

    @field_validator("original_identity_confirmed", "drug_semantics_confirmed", "rate_units_confirmed", mode="before")
    @classmethod
    def explicit_true(cls, value):
        if value is not True:
            raise ValueError("须分别明确核实实际药物身份、成分语义及原单位，不接受默认确认")
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


def finish(db, user, action, identifier, details):
    try:
        audit(db, user.user_id, action, identifier, details)
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "原身份已有已发布映射或版本发生竞争，请刷新") from exc
    except Exception:
        db.rollback()
        raise


@router.get("/ai/admin/vasoactive-drug-mappings/options")
def options(
    keyword: str = Query("", max_length=120),
    page: str = Query("1", pattern=r"^[1-9][0-9]{0,6}$"),
    page_size: str = Query("20", pattern=r"^(?:[1-9]|[1-9][0-9]|100)$"),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*MAPPING_ROLES)),
):
    mapping_super(db, user)
    page, page_size = int(page), int(page_size)
    query = db.query(Pharmaceutical).filter(Pharmaceutical.name.is_not(None), func.trim(Pharmaceutical.name) != "")
    if keyword:
        query = query.filter(or_(Pharmaceutical.name.contains(keyword, autoescape=True), Pharmaceutical.barcode.contains(keyword, autoescape=True)))
    total = query.count()
    rows = query.order_by(Pharmaceutical.pharmaceutical_id).offset((page - 1) * page_size).limit(page_size).all()
    items = []
    for row in rows:
        identity = original_drug_identity(db, row.pharmaceutical_id)
        items.append({**identity, "original_drug_identity_hash": hash_content(identity)})
    return {
        "code": 200,
        "data": {
            "drug_keys": [{"key": key, "label": label} for key, label in DRUG_KEYS.items()],
            "active_moiety_bases": ["base", "salt", "unknown"],
            "allowed_rate_units": list(RATE_UNITS),
            "states": ["draft", "published", "revoked"],
            "clinical_mapping_seeded": False,
            "pharmaceuticals": {"items": items, "total": total, "page": page, "page_size": page_size},
            "scope_note": "仅返回实际原药品身份和分类选项；没有默认临床映射、剂量换算或SOFA验证",
        },
    }


@router.get("/ai/admin/vasoactive-drug-mappings")
def list_mappings(
    status: Literal["draft", "published", "revoked"] | None = None,
    page: str = Query("1", pattern=r"^[1-9][0-9]{0,6}$"),
    page_size: str = Query("20", pattern=r"^(?:[1-9]|[1-9][0-9]|100)$"),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*MAPPING_ROLES)),
):
    mapping_super(db, user)
    page, page_size = int(page), int(page_size)
    query = db.query(AIVasoactiveDrugMapping)
    if status:
        query = query.filter_by(status=status)
    total = query.count()
    rows = query.order_by(AIVasoactiveDrugMapping.created_at.desc(), AIVasoactiveDrugMapping.mapping_id).offset((page - 1) * page_size).limit(page_size).all()
    return {"code": 200, "data": {"items": [mapping_detail(db, row) for row in rows], "total": total, "page": page, "page_size": page_size}}


@router.post("/ai/admin/vasoactive-drug-mappings")
def post_mapping(req: MappingCreate, db: Session = Depends(get_db), user: User = Depends(require_roles(*MAPPING_ROLES))):
    actor = mapping_super(db, user)
    row = create_mapping(db, actor, req.model_dump())
    finish(db, actor, "vasoactive_drug_mapping.create", row.mapping_id, {"content_hash": row.content_hash, "revision": row.revision})
    return {"code": 200, "data": mapping_detail(db, row)}


@router.get("/ai/admin/vasoactive-drug-mappings/{mapping_id}")
def get_mapping(mapping_id: str, db: Session = Depends(get_db), user: User = Depends(require_roles(*MAPPING_ROLES))):
    mapping_super(db, user)
    return {"code": 200, "data": mapping_detail(db, mapping_id)}


@router.post("/ai/admin/vasoactive-drug-mappings/{mapping_id}/publish")
def publish_mapping(mapping_id: str, req: MappingPublish, db: Session = Depends(get_db), user: User = Depends(require_roles(*MAPPING_ROLES))):
    actor = mapping_super(db, user)
    data = mapping_detail(db, mapping_id)
    if data["status"] != "draft" or req.expected_revision != data["revision"] or not data["original_identity_current"]:
        raise HTTPException(409, "须发布原身份仍一致的当前草稿；撤销版本不可恢复")
    now = utcnow()
    try:
        count = (
            db.query(AIVasoactiveDrugMapping)
            .filter_by(mapping_id=mapping_id, status="draft", revision=req.expected_revision, content_hash=data["content_hash"])
            .update(
                {"status": "published", "revision": 2, "published_key": data["identity_hash"], "published_at": now, "published_by": actor.user_id, "review_note": req.review_note},
                synchronize_session=False,
            )
        )
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "同一命名空间与实际药物身份已有已发布映射，请先核对并撤销旧版本") from exc
    if count != 1:
        db.rollback()
        raise HTTPException(409, "映射在发布时发生竞争，请刷新")
    finish(db, actor, "vasoactive_drug_mapping.publish", mapping_id, {"content_hash": data["content_hash"], "revision": 2})
    return {"code": 200, "data": mapping_detail(db, mapping_id)}


@router.post("/ai/admin/vasoactive-drug-mappings/{mapping_id}/revoke")
def revoke_mapping(mapping_id: str, req: MappingRevoke, db: Session = Depends(get_db), user: User = Depends(require_roles(*MAPPING_ROLES))):
    actor = mapping_super(db, user)
    data = mapping_detail(db, mapping_id)
    if data["status"] == "revoked" or req.expected_revision != data["revision"]:
        raise HTTPException(409, "映射已变化或撤销，不重复撤销或恢复")
    count = (
        db.query(AIVasoactiveDrugMapping)
        .filter_by(mapping_id=mapping_id, status=data["status"], revision=req.expected_revision, content_hash=data["content_hash"])
        .update(
            {"status": "revoked", "revision": req.expected_revision + 1, "published_key": None, "revoked_at": utcnow(), "revoked_by": actor.user_id, "revoke_reason": req.reason},
            synchronize_session=False,
        )
    )
    if count != 1:
        db.rollback()
        raise HTTPException(409, "映射在撤销时发生竞争，请刷新")
    finish(db, actor, "vasoactive_drug_mapping.revoke", mapping_id, {"content_hash": data["content_hash"], "revision": req.expected_revision + 1})
    return {"code": 200, "data": mapping_detail(db, mapping_id)}
