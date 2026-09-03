"""Authenticated real-time event stream for the clinical frontend."""

import json

from fastapi import APIRouter, Depends, Header, Request
from starlette.responses import StreamingResponse

from app import database
from app.dependencies import resolve_access_token
from app.event_bus import listen_events, recent_events

router = APIRouter()


def get_event_identity(
    request: Request,
    access_token: str | None = Header(None, alias="accesstoken"),
) -> tuple[int, str, str]:
    """Authenticate an event stream without holding a request-scoped DB session."""
    with database.SessionLocal() as db:
        user = resolve_access_token(access_token, db)
        identity = (user.user_id, user.username, user.user_role)
    request.state.auth_identity = identity
    return identity


def _encode_event(event: dict) -> str:
    data = json.dumps(event, ensure_ascii=False, separators=(",", ":"))
    return f"id: {event['id']}\nevent: {event['type']}\ndata: {data}\n\n"


@router.get("/events/recent")
async def get_recent_events(
    limit: int = 50,
    identity: tuple[int, str, str] = Depends(get_event_identity),
):
    return {"code": 200, "msg": "success", "data": await recent_events(identity, limit)}


@router.get("/events/stream")
async def event_stream(
    request: Request,
    last_event_id: str | None = Header(None, alias="Last-Event-ID"),
    identity: tuple[int, str, str] = Depends(get_event_identity),
):
    async def generate():
        if last_event_id:
            history = await recent_events(identity, 100)
            ids = [event["id"] for event in history]
            if last_event_id in ids:
                for event in history[ids.index(last_event_id) + 1:]:
                    yield _encode_event(event)
        async for event in listen_events(identity):
            if await request.is_disconnected():
                break
            yield ": keepalive\n\n" if event is None else _encode_event(event)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
