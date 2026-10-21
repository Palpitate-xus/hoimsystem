"""Released drug-label evidence; pharmacist signs self, Super governs release."""

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session, load_only

from app.ai import document_evidence_contract as d
from app.ai import drug_label_contract as c
from app.ai import drug_label_sources as sources
from app.ai.drug_label_models import AIDrugLabelSource
from app.ai.inventory_write_guard import current_inventory_rows
from app.database import get_db
from app.dependencies import User, require_roles
from app.models import Pharmaceutical
from app.routers.ai_document_evidence import BoundedDocumentRoute, _commit

router = APIRouter(prefix="/ai/drug-label-sources", route_class=BoundedDocumentRoute, default_response_class=JSONResponse)


@router.get("/options")
def options(db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin", "pharmacist"))):
    actor = sources.current_actor(db, user)
    return {
        "code": 200,
        "msg": "success",
        "data": {
            "schema_version": "drug_label_source_options_v1",
            "comparison_fields": list(c.COMPARISON_FIELDS),
            "can_release": actor.user_role == "super_admin",
            "can_technical_review": actor.user_role == "super_admin",
            "can_professional_sign": actor.user_role == "pharmacist",
            "professional_signer_user_id": actor.user_id if actor.user_role == "pharmacist" else None,
            "licensure_verification": "not_provided",
            "clinical_validation": "not_provided",
            "missing_evidence": list(c.UNKNOWN_EVIDENCE),
            "source_max_utf8_bytes": c.MAX_SOURCE_BYTES,
            "automatic_extraction": False,
            "automatic_clinical_rule": False,
        },
    }


@router.get("/catalog")
def catalog(after_id: int = Query(0, ge=0, le=2147483647), page_size: int = Query(20, ge=1, le=100), db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin", "pharmacist"))):
    sources.current_actor(db, user)
    columns = [getattr(Pharmaceutical, field) for field in c.COMPARISON_FIELDS]
    rows = current_inventory_rows(db.query(*columns).filter(Pharmaceutical.pharmaceutical_id > after_id).order_by(Pharmaceutical.pharmaceutical_id), shared=True).limit(page_size + 1).all()
    more = len(rows) > page_size
    items = []
    for row in rows[:page_size]:
        value = c.Identity(**dict(zip(c.COMPARISON_FIELDS, tuple(row), strict=True)))
        items.append({"identity": value.model_dump(mode="json"), "identity_hash": d.digest(value)})
    return {"code": 200, "msg": "success", "data": {"items": items, "next_cursor": items[-1]["identity"]["pharmaceutical_id"] if more else None, "complete": not more}}


@router.get("")
def directory(
    pharmaceutical_id: int | None = Query(None, ge=1, le=2147483647),
    after_id: str | None = None,
    page_size: int = Query(20, ge=1, le=100),
    audit_only: bool = False,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("super_admin", "pharmacist")),
):
    actor = sources.current_actor(db, user)
    if (audit_only or pharmaceutical_id is None) and actor.user_role != "super_admin":
        raise HTTPException(403, "药师目录须明确真实药品；全院审计仅限当前超级管理员")
    if after_id is not None:
        try:
            sources._key(after_id)
        except ValueError as exc:
            raise HTTPException(422, "目录游标不规范") from exc
    fields = [getattr(AIDrugLabelSource, column.name) for column in AIDrugLabelSource.__table__.columns if column.name != "snapshot_json"]
    query = db.query(AIDrugLabelSource).options(load_only(*fields))
    if pharmaceutical_id is not None:
        query = query.filter_by(pharmaceutical_id=pharmaceutical_id)
    if after_id is not None:
        query = query.filter(AIDrugLabelSource.source_binding_id > after_id)
    rows = current_inventory_rows(query.order_by(AIDrugLabelSource.source_binding_id), shared=True).limit(page_size + 1).all()
    items = []
    for row in rows[:page_size]:
        gov = sources._governance(row)
        items.append(
            {
                "source_binding_id": row.source_binding_id,
                "source_id": f"drug_label_source:{row.source_binding_id}:{row.content_hash[:12]}",
                "pharmaceutical_id": row.pharmaceutical_id,
                "original_id": row.original_id,
                "recorded_at": d.utc_text(row.recorded_at),
                "content_hash": row.content_hash,
                "identity_hash": row.identity_hash,
                "status": gov.status,
                "revision": gov.revision,
                "governance_hash": d.digest(gov),
                "detail_required": True,
            }
        )
    more = len(rows) > page_size
    return {"code": 200, "msg": "success", "data": {"items": items, "next_cursor": items[-1]["source_binding_id"] if more else None, "complete": not more, "audit_only": audit_only}}


@router.post("")
def create(request: c.SourceCreate, db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin"))):
    return _commit(db, lambda: sources.create_source(db, user, request))


@router.get("/{binding_id}")
def detail(binding_id: str, audit_only: bool = False, db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin", "pharmacist"))):
    return {"code": 200, "msg": "success", "data": sources.source_current(db, user, binding_id, audit_only=audit_only).model_dump(mode="json")}


@router.post("/{binding_id}/professional-review")
def professional_sign(binding_id: str, request: c.ProfessionalSign, db: Session = Depends(get_db), user: User = Depends(require_roles("pharmacist"))):
    return _commit(db, lambda: sources.sign_source(db, user, binding_id, request))


@router.post("/{binding_id}/professional-review/revoke")
def professional_revoke(binding_id: str, request: c.RevokeRequest, db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin", "pharmacist"))):
    return _commit(db, lambda: sources.revoke_professional(db, user, binding_id, request))


@router.post("/{binding_id}/review")
def review(binding_id: str, request: c.SourceReview, db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin"))):
    return _commit(db, lambda: sources.review_source(db, user, binding_id, request))


@router.post("/{binding_id}/revoke")
def revoke(binding_id: str, request: c.RevokeRequest, db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin"))):
    return _commit(db, lambda: sources.revoke_source(db, user, binding_id, request))
