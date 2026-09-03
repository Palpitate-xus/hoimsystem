"""Cross-worker clinical event delivery with a development in-process fallback."""

import asyncio
import datetime
import json
import logging
import uuid
from collections import deque

from redis.asyncio import Redis

from app.config import settings

logger = logging.getLogger(__name__)

CHANNEL = "hoimsystem:events"
RECENT_KEY = "hoimsystem:events:recent"
RECENT_LIMIT = 500

_subscribers: set[asyncio.Queue] = set()
_recent = deque(maxlen=RECENT_LIMIT)


def patient_user_ids(db, patient) -> list[int]:
    """Resolve a patient account without leaking identity values into an event."""
    if not patient or not patient.identity:
        return []
    from app.models import User

    user_id = db.query(User.user_id).filter(User.username == patient.identity).scalar()
    return [user_id] if user_id else []


def can_receive(event: dict, identity: tuple[int, str, str]) -> bool:
    user_id, _username, role = identity
    roles = event.get("audience_roles") or []
    users = event.get("audience_user_ids") or []
    return (not roles and not users) or role in roles or user_id in users


def _build_event(
    event_type: str,
    data: dict,
    audience_roles: list[str] | tuple[str, ...] | None,
    audience_user_ids: list[int] | tuple[int, ...] | None,
) -> dict:
    return {
        "id": uuid.uuid4().hex,
        "type": event_type,
        "created_at": datetime.datetime.now(datetime.UTC).isoformat(),
        "data": data,
        "audience_roles": list(audience_roles or ()),
        "audience_user_ids": list(audience_user_ids or ()),
    }


async def _publish_local(event: dict) -> None:
    _recent.append(event)
    for queue in tuple(_subscribers):
        if queue.full():
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
        queue.put_nowait(event)


async def publish_event(
    event_type: str,
    data: dict,
    *,
    audience_roles: list[str] | tuple[str, ...] | None = None,
    audience_user_ids: list[int] | tuple[int, ...] | None = None,
) -> dict:
    """Publish after the owning business transaction commits."""
    event = _build_event(event_type, data, audience_roles, audience_user_ids)
    if settings.REDIS_URL:
        client = Redis.from_url(settings.REDIS_URL, decode_responses=True, socket_timeout=2)
        try:
            encoded = json.dumps(event, ensure_ascii=False, separators=(",", ":"))
            async with client.pipeline(transaction=True) as pipeline:
                pipeline.publish(CHANNEL, encoded)
                pipeline.lpush(RECENT_KEY, encoded)
                pipeline.ltrim(RECENT_KEY, 0, RECENT_LIMIT - 1)
                await pipeline.execute()
            return event
        except Exception:
            logger.exception("Redis event publish failed; delivering to this worker only")
        finally:
            await client.aclose()
    await _publish_local(event)
    return event


async def recent_events(identity: tuple[int, str, str], limit: int = 50) -> list[dict]:
    bounded_limit = max(1, min(limit, 100))
    events: list[dict]
    if settings.REDIS_URL:
        client = Redis.from_url(settings.REDIS_URL, decode_responses=True, socket_timeout=2)
        try:
            rows = await client.lrange(RECENT_KEY, 0, bounded_limit * 3 - 1)
            events = [json.loads(row) for row in reversed(rows)]
        except Exception:
            logger.exception("Redis event history read failed; using this worker's history")
            events = list(_recent)
        finally:
            await client.aclose()
    else:
        events = list(_recent)
    return [event for event in events if can_receive(event, identity)][-bounded_limit:]


async def listen_events(identity: tuple[int, str, str]):
    """Yield authorized events, or None every 15 seconds as a keepalive."""
    if settings.REDIS_URL:
        client = Redis.from_url(settings.REDIS_URL, decode_responses=True, socket_timeout=20)
        pubsub = client.pubsub()
        try:
            await pubsub.subscribe(CHANNEL)
            while True:
                message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=15)
                if not message:
                    yield None
                    continue
                event = json.loads(message["data"])
                if can_receive(event, identity):
                    yield event
        finally:
            await pubsub.aclose()
            await client.aclose()
        return

    queue: asyncio.Queue = asyncio.Queue(maxsize=100)
    _subscribers.add(queue)
    try:
        while True:
            try:
                yield await asyncio.wait_for(queue.get(), timeout=15)
            except TimeoutError:
                yield None
    finally:
        _subscribers.discard(queue)
