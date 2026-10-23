"""Super-governed RCA Source APIs. No model call or clinical write-back."""

import asyncio
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.ai import rca_evidence_case_contract as k
from app.ai import rca_evidence_cases as cases
from app.ai import rca_evidence_contract as c
from app.ai import rca_evidence_directory as directories
from app.ai import rca_evidence_grants as grants
from app.ai import rca_evidence_input as i
from app.ai import rca_evidence_source_contract as s
from app.ai import rca_evidence_sources as sources
from app.database import get_db
from app.dependencies import User, require_roles

UPLOAD_TIMEOUT_SECONDS = 15


class BoundedRcaRoute(APIRoute):
    def get_route_handler(self):
        original = super().get_route_handler()
        query_names = {parameter.alias for parameter in self.dependant.query_params}

        async def bounded(request: Request):
            if set(request.query_params) - query_names or any(len(request.query_params.getlist(key)) != 1 for key in request.query_params):
                raise HTTPException(422, "须使用明确且不重复的本项查询字段")
            if request.method in {"POST", "PUT", "PATCH"}:
                if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
                    raise HTTPException(415, "人工RCA证据请求须为UTF8 JSON")
                lengths = request.headers.getlist("content-length")
                if len(lengths) > 1 or lengths and (not lengths[0].isascii() or not lengths[0].isdigit() or len(lengths[0]) > 10):
                    raise HTTPException(400, "完整请求长度字段无效")
                if lengths and int(lengths[0]) > c.MAX_WIRE_BYTES:
                    raise HTTPException(413, "完整请求超过8MiB，未读取或截断")
                body = bytearray()
                try:
                    async with asyncio.timeout(UPLOAD_TIMEOUT_SECONDS):
                        async for chunk in request.stream():
                            if len(body) + len(chunk) > c.MAX_WIRE_BYTES:
                                raise HTTPException(413, "完整请求超过8MiB，未截断或登记")
                            body.extend(chunk)
                except TimeoutError as exc:
                    raise HTTPException(408, "上传超过明确截止时间，未登记任何证据") from exc
                try:
                    c._strict_reply(bytes(body).decode("utf-8", errors="strict"))
                except (ValueError, UnicodeError, RecursionError) as exc:
                    raise HTTPException(422, "须为完整UTF8、无重复键和非有限数值且符合结构预算的JSON") from exc
                request._body = bytes(body)
            try:
                return await original(request)
            except RequestValidationError as exc:
                # Never echo rejected source text, a free basis or surrogates.
                raise HTTPException(422, "人工RCA证据字段、范围或明确签署不符合闭集合同") from exc

        return bounded


router = APIRouter(route_class=BoundedRcaRoute, default_response_class=JSONResponse)


def _commit(db, operation):
    try:
        response = cases.wire(operation())
        db.commit()
        return response
    except HTTPException:
        db.rollback()
        raise
    except (SQLAlchemyError, ValueError, TypeError, UnicodeError) as exc:
        db.rollback()
        raise HTTPException(409, "完整证据、当前授权或独立SQL审计冲突，整笔未接受") from exc


@router.get("/ai/admin/rca-evidence/options")
def options(db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin"))):
    grants.current_actor(db, user, grants.SOURCE_ROLES)
    return cases.wire(
        {
            "schema_version": "rca_evidence_options_v1",
            "purpose": "incident_rca",
            "requires_event_purpose": True,
            "requires_patient_purpose_if_associated": True,
            "original_max_utf8_bytes": c.MAX_ORIGINAL_BYTES,
            "whole_response_max_utf8_bytes": c.MAX_WIRE_BYTES,
            "combined_dependency_cap": c.MAX_MEMBERS,
            "span_coordinate_space": "unicode_codepoint_half_open",
            "normalization": "none",
            "automatic_model_calls": False,
            "automatic_clinical_writes": False,
            "causal_verification": "not_provided",
        }
    )


@router.post("/ai/admin/rca-evidence/grants")
def create_grant(body: i.GrantCreate, db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin"))):
    return _commit(db, lambda: grants.create_grant(db, user, body))


@router.get("/ai/admin/rca-evidence/grants/{grant_id}")
def grant_detail(grant_id: str, db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin"))):
    return cases.wire(grants.grant_detail(db, user, grant_id))


@router.post("/ai/admin/rca-evidence/grants/{grant_id}/revoke")
def revoke_grant(grant_id: str, body: i.Revoke, db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin"))):
    return _commit(db, lambda: grants.revoke_grant(db, user, grant_id, body))


@router.get("/ai/admin/rca-evidence/events/{event_id}/directory/{kind}")
def directory(
    kind: Literal["originals", "cases", "grants"],
    event_id: int = Path(ge=1, le=2147483647),
    page: int = Query(1, ge=1, le=4096),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("super_admin")),
):
    return cases.wire(directories.directory(db, user, event_id, kind, page=page, page_size=page_size))


@router.get("/ai/admin/rca-evidence/events/{event_id}/capture")
def capture(event_id: int = Path(ge=1, le=2147483647), db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin"))):
    return cases.wire(cases.capture_event(db, user, event_id))


@router.get("/ai/admin/rca-evidence/events/{event_id}/legacy-witness")
def legacy_witness(
    event_id: int = Path(ge=1, le=2147483647),
    kind: Literal["legacy_event", "legacy_rca"] = "legacy_event",
    record_id: int = Query(..., ge=1, le=2147483647),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("super_admin")),
):
    return cases.wire(sources.legacy_witness(db, user, event_id, kind, record_id))


@router.post("/ai/admin/rca-evidence/originals")
def create_original(body: s.OriginalCreate, db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin"))):
    return _commit(db, lambda: sources.create_original(db, user, body))


@router.get("/ai/admin/rca-evidence/originals/{original_id}")
def original_detail(original_id: str, db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin"))):
    return cases.wire(sources.original_detail(db, user, original_id))


@router.post("/ai/admin/rca-evidence/originals/{original_id}/review")
def review_original(original_id: str, body: i.SourceReview, db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin"))):
    return _commit(db, lambda: sources.review_original(db, user, original_id, body))


@router.post("/ai/admin/rca-evidence/originals/{original_id}/revoke")
def revoke_original(original_id: str, body: i.Revoke, db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin"))):
    return _commit(db, lambda: sources.revoke_original(db, user, original_id, body))


@router.post("/ai/admin/rca-evidence/cases")
def create_case(body: k.CaseCreate, db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin"))):
    return _commit(db, lambda: cases.create_case(db, user, body))


@router.get("/ai/admin/rca-evidence/cases/{case_id}")
def case_detail(case_id: str, db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin"))):
    return cases.wire(cases.case_detail(db, user, case_id))


@router.get("/ai/admin/rca-evidence/cases/{case_id}/public-source")
def public_source(case_id: str, db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin"))):
    return cases.wire(cases.public_source(db, user, case_id))


@router.post("/ai/admin/rca-evidence/cases/{case_id}/review")
def review_case(case_id: str, body: i.SourceReview, db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin"))):
    return _commit(db, lambda: cases.review_case(db, user, case_id, body))


@router.post("/ai/admin/rca-evidence/cases/{case_id}/revoke")
def revoke_case(case_id: str, body: i.Revoke, db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin"))):
    return _commit(db, lambda: cases.revoke_case(db, user, case_id, body))
