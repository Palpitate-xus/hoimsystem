"""Authenticated real-time event stream for the clinical frontend."""

import json
from contextlib import aclosing

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from starlette.concurrency import run_in_threadpool
from starlette.responses import StreamingResponse

from app import database
from app.access_control import current_data_scope, enforce_request_permissions
from app.dependencies import resolve_access_token
from app.event_bus import can_receive, listen_events, recent_events
from app.models import Patient

router = APIRouter()


def get_event_identity(
    request: Request,
    access_token: str | None = Header(None, alias="accesstoken"),
) -> tuple[int, str, str]:
    """Authenticate an event stream without holding a request-scoped DB session."""
    with database.SessionLocal() as db:
        user = resolve_access_token(access_token, db)
        enforce_request_permissions(db, user, request)
        identity = (user.user_id, user.username, user.user_role)
    request.state.auth_identity = identity
    return identity


def _current_event_visibility(request: Request, identity: tuple[int, str, str], event: dict | None = None) -> bool:
    """Recheck authority in a short session that ends before any SSE yield."""
    with database.SessionLocal() as db:
        user = resolve_access_token(request.headers.get("accesstoken"), db)
        if (user.user_id, user.username, user.user_role) != identity:
            raise HTTPException(403, "实时通知登录身份已变更")
        enforce_request_permissions(db, user, request)
        if event is None:
            return True
        if not can_receive(event, identity):
            return False
        data = event.get("data")
        if isinstance(data, dict) and "patient_id" in data and current_data_scope(db, user) == "assigned":
            patient_id = data["patient_id"]
            if type(patient_id) is not int or patient_id <= 0:
                return False
            return db.query(Patient.patient_id).filter(Patient.patient_id == patient_id).first() is not None
        return True


def _encode_event(event: dict) -> str:
    data = json.dumps(event, ensure_ascii=False, separators=(",", ":"))
    return f"id: {event['id']}\nevent: {event['type']}\ndata: {data}\n\n"


@router.get("/events/recent")
async def get_recent_events(
    request: Request,
    limit: int = 50,
    identity: tuple[int, str, str] = Depends(get_event_identity),
):
    history = await recent_events(identity, limit)
    visible = []
    for event in history:
        if await run_in_threadpool(_current_event_visibility, request, identity, event):
            visible.append(event)
    # An empty history still needs a current check after the event-store await.
    await run_in_threadpool(_current_event_visibility, request, identity)
    return {"code": 200, "msg": "success", "data": visible}


@router.get("/events/stream")
async def event_stream(
    request: Request,
    last_event_id: str | None = Header(None, alias="Last-Event-ID"),
    identity: tuple[int, str, str] = Depends(get_event_identity),
):
    async def generate():
        # Flush streaming headers before the first event or 15-second heartbeat.
        # An SSE comment also keeps reconnects out of business event handling.
        yield ": connected\n\n"
        try:
            if last_event_id:
                history = await recent_events(identity, 100)
                ids = [event["id"] for event in history]
                if last_event_id in ids:
                    for event in history[ids.index(last_event_id) + 1:]:
                        if await request.is_disconnected():
                            return
                        if await run_in_threadpool(_current_event_visibility, request, identity, event):
                            yield _encode_event(event)
            await run_in_threadpool(_current_event_visibility, request, identity)
            async with aclosing(listen_events(identity)) as listener:
                async for event in listener:
                    if await request.is_disconnected():
                        break
                    if await run_in_threadpool(_current_event_visibility, request, identity, event):
                        yield ": keepalive\n\n" if event is None else _encode_event(event)
        except HTTPException:
            # Headers may already be sent; ending the stream prevents stale data
            # and lets the next connection return the current HTTP auth error.
            return

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
