"""Governed finite infection report sources; not a diagnosis or signal-model API."""

import asyncio
import json
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from pydantic import BaseModel, ValidationError
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.ai import infection_cluster_contract as c
from app.ai import infection_cluster_input as i
from app.ai import infection_cluster_registry as r
from app.ai import infection_cluster_sources as s
from app.ai.infection_cluster_input import SOURCE_ROLES
from app.database import get_db
from app.dependencies import User, require_roles


class BoundedSourceRoute(APIRoute):
    def get_route_handler(self):
        original = super().get_route_handler()

        async def bounded(request: Request):
            if request.method in {"POST", "PUT", "PATCH"}:
                if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
                    raise HTTPException(415, "来源请求需UTF8 application/json")
                lengths = request.headers.getlist("content-length")
                if len(lengths) > 1 or lengths and (not lengths[0].isascii() or not lengths[0].isdigit() or len(lengths[0]) > 10):
                    raise HTTPException(400, "不规范请求长度")
                if lengths and int(lengths[0]) > c.MAX_BYTES:
                    raise HTTPException(413, "完整请求超过8MiB")
                chunks, size = [], 0
                try:
                    async with asyncio.timeout(15):
                        async for chunk in request.stream():
                            size += len(chunk)
                            if size > c.MAX_BYTES:
                                raise HTTPException(413, "完整请求超过8MiB")
                            chunks.append(chunk)
                except TimeoutError as exc:
                    raise HTTPException(408, "完整来源上传已超时，未接受登记") from exc
                raw = b"".join(chunks)
                try:
                    source = raw.decode("utf-8", errors="strict")
                    c._lexical_budget(source)
                    parsed = json.loads(source, object_pairs_hook=c._pairs, parse_constant=c._nonfinite)
                    c.canonical(parsed)
                except (ValueError, UnicodeError) as exc:
                    raise HTTPException(422, "来源JSON须原样UTF8、无重复键或非法数值") from exc
                request._body = raw
            try:
                return await original(request)
            except RequestValidationError as exc:
                raise HTTPException(422, "来源请求不符合闭集字段与明确声明合同") from exc

        return bounded


router = APIRouter(prefix="/ai/infection-cluster", tags=["受控院感上报来源"], default_response_class=JSONResponse, route_class=BoundedSourceRoute)
Kind = Literal["grant", "definition", "review"]


def response(db, function, *args, write=False, **kwargs):
    try:
        value = function(db, *args, **kwargs)
        if isinstance(value, BaseModel):
            value = value.model_dump(mode="json")
        result = {"code": 200, "msg": "success", "data": value}
        c.canonical(result)  # whole HTTP wrapper has its own8MiB bound
        if write:
            db.commit()
        else:
            db.rollback()
        return result
    except (ValidationError, ValueError) as exc:
        db.rollback()
        raise HTTPException(409, "完整来源结构、字节预算或原件绑定无法核对") from exc
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(409, "来源事务冲突，未接受部分原件或审计") from exc
    except Exception:
        db.rollback()
        raise


@router.post("/grants")
def grant_create(req: i.GrantCreate, user: User = Depends(require_roles("super_admin")), db: Session = Depends(get_db)):
    return response(db, r.create_grant, user, req.model_dump(mode="json"), write=True)


@router.post("/definitions")
def definition_create(req: i.DefinitionCreate, user: User = Depends(require_roles("super_admin")), db: Session = Depends(get_db)):
    return response(db, r.create_definition, user, req.model_dump(mode="json"), write=True)


@router.post("/case-reviews")
def case_review_create(req: i.CaseReviewCreate, user: User = Depends(require_roles("super_admin")), db: Session = Depends(get_db)):
    return response(db, r.create_case_review, user, req.model_dump(mode="json"), write=True)


@router.get("/registry/{kind}")
def registry_directory(kind: Kind, page: int = 1, size: int = 20, user: User = Depends(require_roles("super_admin")), db: Session = Depends(get_db)):
    return response(db, r.directory, user, kind, page=page, size=size)


@router.get("/registry/{kind}/{record_id}")
def registry_detail(kind: Kind, record_id: c.UUID, user: User = Depends(require_roles("super_admin")), db: Session = Depends(get_db)):
    return response(db, r.detail, user, kind, record_id)


@router.post("/registry/{kind}/{record_id}/review")
def registry_review(kind: Kind, record_id: c.UUID, req: i.GovernReview, user: User = Depends(require_roles("super_admin")), db: Session = Depends(get_db)):
    return response(db, r.review_record, user, kind, record_id, req.model_dump(mode="json"), write=True)


@router.post("/registry/{kind}/{record_id}/revoke")
def registry_revoke(kind: Kind, record_id: c.UUID, req: i.CAS, user: User = Depends(require_roles("super_admin")), db: Session = Depends(get_db)):
    return response(db, r.revoke_record, user, kind, record_id, req.model_dump(mode="json"), write=True)


@router.post("/roots/preview")
def roots_preview(req: i.SnapshotCreate, user: User = Depends(require_roles("super_admin")), db: Session = Depends(get_db)):
    return response(db, s.preview_roots, user, req.model_dump(mode="json"))


@router.post("/snapshots")
def snapshot_create(req: i.SnapshotCreate, user: User = Depends(require_roles("super_admin")), db: Session = Depends(get_db)):
    return response(db, s.create_snapshot, user, req.model_dump(mode="json"), write=True)


@router.get("/snapshots")
def snapshots(page: int = 1, size: int = 20, user: User = Depends(require_roles(*SOURCE_ROLES)), db: Session = Depends(get_db)):
    return response(db, s.snapshot_directory, user, page=page, size=size)


@router.get("/snapshots/{snapshot_id}/parts/{part}")
def snapshot_part(snapshot_id: c.UUID, part: Literal["private", "public"], user: User = Depends(require_roles(*SOURCE_ROLES)), db: Session = Depends(get_db)):
    return response(db, s.snapshot_part, user, snapshot_id, part)
