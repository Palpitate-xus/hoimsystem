"""Super-only exact document evidence APIs; not AI extraction or URL fetching."""

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, load_only

from app.ai import document_evidence_contract as c
from app.ai import document_evidence_sources as sources
from app.ai.document_evidence_models import AIDocumentKnowledgePublication, AIDocumentOriginal, AIDocumentSpanCandidate
from app.database import get_db
from app.dependencies import User, require_roles


class BoundedDocumentRoute(APIRoute):
    def get_route_handler(self):
        original = super().get_route_handler()

        async def bounded(request: Request):
            if request.method in {"POST", "PUT", "PATCH"}:
                if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
                    raise HTTPException(415, "原文证据请求须使用UTF8 application/json")
                lengths = request.headers.getlist("content-length")
                if len(lengths) > 1 or lengths and (not lengths[0].isascii() or not lengths[0].isdigit() or len(lengths[0]) > 10):
                    raise HTTPException(400, "请求长度不规范")
                if lengths and int(lengths[0]) > c.MAX_REQUEST_BYTES:
                    raise HTTPException(413, "完整请求超过8MiB，未读取、截断或登记")
                chunks = bytearray()
                try:
                    async with asyncio.timeout(c.UPLOAD_TIMEOUT_SECONDS):
                        async for chunk in request.stream():
                            if len(chunks) + len(chunk) > c.MAX_REQUEST_BYTES:
                                raise HTTPException(413, "完整请求超过8MiB，未截断或登记")
                            chunks.extend(chunk)
                except TimeoutError as exc:
                    raise HTTPException(408, "原文证据上传超过截止时间，未登记任何原件") from exc
                try:
                    c.parse_json(bytes(chunks).decode("utf-8", errors="strict"))
                except (ValueError, UnicodeError) as exc:
                    raise HTTPException(422, "请求必须是有效UTF8、无重复键或非有限数值的JSON") from exc
                request._body = bytes(chunks)
            try:
                return await original(request)
            except RequestValidationError as exc:
                # Do not echo a 4MiB document or a rejected surrogate in errors.
                raise HTTPException(422, "原文证据请求不符合严格字段、原字节或审核合同") from exc

        return bounded


router = APIRouter(route_class=BoundedDocumentRoute, default_response_class=JSONResponse)


def _commit(db, operation):
    try:
        data = operation()
        db.commit()
        return {"code": 200, "msg": "success", "data": data.model_dump(mode="json")}
    except HTTPException:
        db.rollback()
        raise
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(409, "原文证据事务冲突，原件、知识与审计均未接受") from exc
    except Exception as exc:
        db.rollback()
        raise HTTPException(500, "原文证据事务未完成，未接受部分登记") from exc


@router.get("/ai/admin/document-evidence/options")
def options(db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin"))):
    sources.current_super(db, user)
    return {
        "code": 200,
        "msg": "success",
        "data": {
            "schema_version": "document_evidence_options_v1",
            "source_kind": c.SOURCE_KIND,
            "uri_prefix": c.URI_PREFIX,
            "input_kinds": ["direct_text", "utf8_file"],
            "file_extensions": [".txt", ".md"],
            "original_max_utf8_bytes": c.MAX_ORIGINAL_BYTES,
            "request_max_utf8_bytes": c.MAX_REQUEST_BYTES,
            "knowledge_max_utf8_bytes": c.MAX_KNOWLEDGE_BYTES,
            "span_coordinate_space": "unicode_codepoint_half_open",
            "normalization": "none",
            "automatic_extraction": False,
            "automatic_publication": False,
            "declaration_status": c.DECLARATION,
            "clinical_validation": "not_provided",
            "knowledge_features": [{"key": key, "name": spec.name} for key, spec in sources.FEATURE_BY_KEY.items()],
        },
    }


@router.post("/ai/admin/document-evidence/originals")
def create_original(req: c.OriginalCreate, db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin"))):
    return _commit(db, lambda: sources.create_original(db, user, req))


@router.get("/ai/admin/document-evidence/originals")
def originals(page: int = Query(1, ge=1, le=1000000), page_size: int = Query(20, ge=1, le=100), db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin"))):
    sources.current_super(db, user)
    query = db.query(AIDocumentOriginal)
    total = query.with_entities(AIDocumentOriginal.original_id).count()
    columns = [
        getattr(AIDocumentOriginal, n)
        for n in ("original_id", "identity_json", "content_hash", "raw_bytes_hash", "raw_bytes_length", "codepoint_length", "created_by", "recorded_at", *sources.REVIEW_FIELDS)
    ]
    rows = query.options(load_only(*columns)).order_by(AIDocumentOriginal.recorded_at.desc(), AIDocumentOriginal.original_id).offset((page - 1) * page_size).limit(page_size).all()
    items = []
    for row in rows:
        metadata = c.parse_json(row.identity_json)["metadata"]
        items.append(
            {
                "original_id": row.original_id,
                "title": metadata["title"],
                "version": metadata["version"],
                "document_kind": metadata["document_kind"],
                "content_hash": row.content_hash,
                "raw_bytes_hash": row.raw_bytes_hash,
                "raw_bytes_length": row.raw_bytes_length,
                "codepoint_length": row.codepoint_length,
                "recorded_at": c.utc_text(row.recorded_at),
                "status": row.status,
                "revision": row.revision,
                "governance_hash": c.digest(sources._governance(row)),
                "detail_required": True,
            }
        )
    return {"code": 200, "msg": "success", "data": {"items": items, "page": page, "page_size": page_size, "total": total}}


@router.get("/ai/admin/document-evidence/originals/{original_id}")
def original_detail(original_id: str, db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin"))):
    return {"code": 200, "msg": "success", "data": sources.original_detail(db, user, original_id).model_dump(mode="json")}


@router.post("/ai/admin/document-evidence/originals/{original_id}/review")
def review_original(original_id: str, req: c.ReviewRequest, db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin"))):
    return _commit(db, lambda: sources.review_original(db, user, original_id, req))


@router.post("/ai/admin/document-evidence/originals/{original_id}/revoke")
def revoke_original(original_id: str, req: c.RevokeRequest, db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin"))):
    return _commit(db, lambda: sources.revoke_original(db, user, original_id, req))


@router.post("/ai/admin/document-evidence/candidates")
def create_candidate(req: c.CandidateCreate, db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin"))):
    return _commit(db, lambda: sources.create_candidate(db, user, req))


@router.get("/ai/admin/document-evidence/candidates")
def candidates(
    original_id: str | None = None, page: int = Query(1, ge=1, le=1000000), page_size: int = Query(20, ge=1, le=100), db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin"))
):
    sources.current_super(db, user)
    query = db.query(AIDocumentSpanCandidate)
    if original_id is not None:
        query = query.filter_by(original_id=original_id)
    total = query.with_entities(AIDocumentSpanCandidate.candidate_id).count()
    names = ("candidate_id", "original_id", "original_content_hash", "content_hash", "span_start", "span_end", "recorded_at", *sources.REVIEW_FIELDS)
    rows = (
        query.options(load_only(*[getattr(AIDocumentSpanCandidate, n) for n in names]))
        .order_by(AIDocumentSpanCandidate.recorded_at.desc(), AIDocumentSpanCandidate.candidate_id)
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    items = [
        {
            "candidate_id": row.candidate_id,
            "original_id": row.original_id,
            "content_hash": row.content_hash,
            "start": row.span_start,
            "end": row.span_end,
            "recorded_at": c.utc_text(row.recorded_at),
            "status": row.status,
            "revision": row.revision,
            "governance_hash": c.digest(sources._governance(row)),
            "detail_required": True,
        }
        for row in rows
    ]
    return {"code": 200, "msg": "success", "data": {"items": items, "page": page, "page_size": page_size, "total": total}}


@router.get("/ai/admin/document-evidence/candidates/{candidate_id}")
def candidate_detail(candidate_id: str, db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin"))):
    return {"code": 200, "msg": "success", "data": sources.candidate_detail(db, user, candidate_id).model_dump(mode="json")}


@router.post("/ai/admin/document-evidence/candidates/{candidate_id}/review")
def review_candidate(candidate_id: str, req: c.ReviewRequest, db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin"))):
    return _commit(db, lambda: sources.review_candidate(db, user, candidate_id, req))


@router.post("/ai/admin/document-evidence/candidates/{candidate_id}/revoke")
def revoke_candidate(candidate_id: str, req: c.RevokeRequest, db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin"))):
    return _commit(db, lambda: sources.revoke_candidate(db, user, candidate_id, req))


@router.post("/ai/admin/document-evidence/candidates/{candidate_id}/publish")
def publish_candidate(candidate_id: str, req: c.PublishRequest, db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin"))):
    return _commit(db, lambda: sources.publish_candidate(db, user, candidate_id, req))


@router.get("/ai/admin/document-evidence/publications")
def publications(page: int = Query(1, ge=1, le=1000000), page_size: int = Query(20, ge=1, le=100), db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin"))):
    sources.current_super(db, user)
    model = AIDocumentKnowledgePublication
    query = db.query(model)
    total = query.with_entities(model.publication_id).count()
    names = ("publication_id", "original_id", "candidate_id", "knowledge_document_id", "content_hash", "published_at", "status", "revision")
    rows = query.options(load_only(*[getattr(model, n) for n in names])).order_by(model.published_at.desc(), model.publication_id).offset((page - 1) * page_size).limit(page_size).all()
    items = [{**{n: getattr(row, n) for n in names if n != "published_at"}, "published_at": c.utc_text(row.published_at), "detail_required": True} for row in rows]
    return {"code": 200, "msg": "success", "data": {"items": items, "page": page, "page_size": page_size, "total": total}}


@router.get("/ai/admin/document-evidence/publications/{publication_id}")
def publication_detail(publication_id: str, db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin"))):
    return {"code": 200, "msg": "success", "data": sources.publication_detail(db, user, publication_id).model_dump(mode="json")}


@router.post("/ai/admin/document-evidence/publications/{publication_id}/revoke")
def revoke_publication(publication_id: str, req: c.RevokeRequest, db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin"))):
    return _commit(db, lambda: sources.revoke_publication(db, user, publication_id, req))
