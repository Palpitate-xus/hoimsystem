"""Super-only human-declared comparison sources; no automatic impact decisions."""

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import TypeAdapter, ValidationError
from sqlalchemy.orm import Session, load_only

from app.ai import document_change_contract as c
from app.ai import document_change_sources as sources
from app.ai import document_evidence_sources as originals
from app.ai.document_change_targets import target_snapshot
from app.database import get_db
from app.dependencies import User, require_roles
from app.routers.ai_document_evidence import BoundedDocumentRoute, _commit

router = APIRouter(route_class=BoundedDocumentRoute, default_response_class=JSONResponse)


def _response(value):
    data = value.model_dump(mode="json") if hasattr(value, "model_dump") else value
    payload = {"code": 200, "msg": "success", "data": data}
    try:
        c.byte_bound(payload)
    except ValueError as exc:
        raise HTTPException(413, "完整响应超过8MiB，未截断或接受部分内容") from exc
    return payload


def _commit_bounded(db, operation):
    def complete():
        value = operation()
        _response(value)
        return value

    return _commit(db, complete)


@router.get("/ai/admin/document-changes/options")
def options(db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin"))):
    originals.current_super(db, user)
    return {
        "code": 200,
        "msg": "success",
        "data": {
            "schema_version": "document_change_options_v1",
            "target_kinds": ["risk_rule_profile", "clinical_pathway"],
            "span_coordinate_space": "unicode_codepoint_half_open",
            "maximum_case_utf8_bytes": c.MAX_CASE_BYTES,
            "maximum_combined_members": c.MAX_MEMBERS,
            "maximum_declared_targets": c.MAX_DECLARED_TARGETS,
            "hospital_wide_rule_inventory": "not_provided",
            "automatic_supersession": False,
            "clinical_validation": "not_provided",
            "declaration_status": c.DECLARATION,
        },
    }


@router.post("/ai/admin/document-changes/target-snapshot")
def target(req: c.TargetReference, db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin"))):
    actor = originals.current_super(db, user)
    epoch = originals._epoch(actor)
    try:
        value = target_snapshot(db, req)
        originals.current_super(db, actor, expected=epoch)
    except ValueError as exc:
        raise HTTPException(409, "完整目标超过限制或当前原量无法核对") from exc
    return _response({"snapshot": value.model_dump(mode="json"), "snapshot_hash": c.e.digest(value)})


@router.post("/ai/admin/document-changes/capture")
def capture(req: c.ScopeCaptureRequest, db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin"))):
    value = sources.capture_scope(db, user, req)
    return _response(value)


@router.post("/ai/admin/document-changes/links")
def create_link(req: c.LinkCreate, db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin"))):
    return _commit_bounded(db, lambda: sources.create_link(db, user, req))


@router.get("/ai/admin/document-changes/links/{link_id}")
def link_detail(link_id: str, db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin"))):
    value = sources.link_detail(db, user, link_id)
    return _response(value)


@router.post("/ai/admin/document-changes/links/{link_id}/review")
def review_link(link_id: str, req: c.ReviewRequest, db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin"))):
    return _commit_bounded(db, lambda: sources.review_link(db, user, link_id, req))


@router.post("/ai/admin/document-changes/links/{link_id}/revoke")
def revoke_link(link_id: str, req: c.e.RevokeRequest, db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin"))):
    return _commit_bounded(db, lambda: sources.revoke_link(db, user, link_id, req))


@router.post("/ai/admin/document-changes/scopes")
def create_scope(req: c.ScopeCreate, db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin"))):
    return _commit_bounded(db, lambda: sources.create_scope(db, user, req))


@router.get("/ai/admin/document-changes/scopes/{scope_id}")
def scope_detail(scope_id: str, db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin"))):
    value = sources.scope_detail(db, user, scope_id)
    return _response(value)


@router.get("/ai/admin/document-changes/scopes/{scope_id}/public-source")
def scope_public_source(scope_id: str, db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin"))):
    _, value = sources.authorize_scope(db, user, scope_id)
    return _response(value)


@router.post("/ai/admin/document-changes/scopes/{scope_id}/review")
def review_scope(scope_id: str, req: c.ReviewRequest, db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin"))):
    return _commit_bounded(db, lambda: sources.review_scope(db, user, scope_id, req))


@router.post("/ai/admin/document-changes/scopes/{scope_id}/revoke")
def revoke_scope(scope_id: str, req: c.e.RevokeRequest, db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin"))):
    return _commit_bounded(db, lambda: sources.revoke_scope(db, user, scope_id, req))


def _directory(db, user, kind, original_id, page, page_size):
    actor = originals.current_super(db, user)
    epoch = originals._epoch(actor)
    if original_id is not None:
        try:
            TypeAdapter(c.e.UUID).validate_python(original_id)
        except ValidationError as exc:
            raise HTTPException(422, "原文标识须为规范UUID") from exc
    model, key, _, _ = sources.MODELS[kind]
    query = db.query(model)
    if original_id is not None:
        query = query.filter(model.original_id == original_id) if kind == "link" else query.filter((model.baseline_original_id == original_id) | (model.candidate_original_id == original_id))
    # Standalone metadata only: current ID directory determines both total and
    # page, never ordinary RR COUNT. No parent/target locks follow this read.
    with db.no_autoflush:
        identifiers = query.with_entities(getattr(model, key)).order_by(model.recorded_at.desc(), getattr(model, key)).with_for_update(read=True).all()
        selected = [value[0] for value in identifiers[(page - 1) * page_size : page * page_size]]
        columns = [getattr(model, name) for name in (key, "content_hash", "recorded_at", *sources.GOV_FIELDS)]
        rows = query.options(load_only(*columns)).filter(getattr(model, key).in_(selected)).populate_existing().with_for_update(read=True).all() if selected else []
    by_id = {getattr(row, key): row for row in rows}
    if set(by_id) != set(selected):
        raise HTTPException(409, "当前目录已改变，请刷新")
    items = []
    for identifier in selected:
        row = by_id[identifier]
        gov = sources.governance(row)
        items.append(
            {
                key: identifier,
                "content_hash": row.content_hash,
                "governance_hash": c.e.digest(gov),
                "status": gov.status,
                "revision": gov.revision,
                "recorded_at": c.e.utc_text(row.recorded_at),
                "detail_required": True,
            }
        )
    originals.current_super(db, actor, expected=epoch)
    return _response({"items": items, "page": page, "page_size": page_size, "total": len(identifiers)})


@router.get("/ai/admin/document-changes/links")
def links(
    original_id: str | None = None, page: int = Query(1, ge=1, le=1000000), page_size: int = Query(20, ge=1, le=100), db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin"))
):
    return _directory(db, user, "link", original_id, page, page_size)


@router.get("/ai/admin/document-changes/scopes")
def scopes(
    original_id: str | None = None, page: int = Query(1, ge=1, le=1000000), page_size: int = Query(20, ge=1, le=100), db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin"))
):
    return _directory(db, user, "scope", original_id, page, page_size)
