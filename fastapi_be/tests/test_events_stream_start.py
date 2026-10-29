"""An idle SSE connection must flush its headers before the first heartbeat."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.routers import events


@pytest.fixture(autouse=True)
def isolate_frame_format_from_account_authority(monkeypatch):
    monkeypatch.setattr(events, "_current_event_visibility", lambda *_args: True)


@pytest.mark.asyncio
async def test_idle_event_stream_sends_a_comment_before_waiting_for_events(monkeypatch):
    waiting = asyncio.Event()

    async def idle_listener(_identity):
        waiting.set()
        await asyncio.Event().wait()
        yield None

    monkeypatch.setattr(events, "listen_events", idle_listener)
    request = SimpleNamespace(is_disconnected=AsyncMock(return_value=False))
    response = await events.event_stream(request, last_event_id=None, identity=(1, "synthetic-stream", "doctor"))
    try:
        first = await asyncio.wait_for(anext(response.body_iterator), timeout=1)
        assert first == ": connected\n\n"
        assert not waiting.is_set()
    finally:
        await response.body_iterator.aclose()


@pytest.mark.asyncio
async def test_initial_comment_preserves_replay_and_keepalive_frames(monkeypatch):
    async def listener(_identity):
        yield None

    old = {"id": "old", "type": "synthetic.updated", "data": {"synthetic": True}}
    new = {"id": "new", "type": "synthetic.updated", "data": {"synthetic": True}}
    monkeypatch.setattr(events, "recent_events", AsyncMock(return_value=[old, new]))
    monkeypatch.setattr(events, "listen_events", listener)
    request = SimpleNamespace(is_disconnected=AsyncMock(return_value=False))
    response = await events.event_stream(request, last_event_id="old", identity=(1, "synthetic-stream", "doctor"))
    frames = [frame async for frame in response.body_iterator]
    assert frames == [": connected\n\n", events._encode_event(new), ": keepalive\n\n"]


@pytest.mark.asyncio
async def test_disconnect_does_not_emit_stale_business_events(monkeypatch):
    async def listener(_identity):
        yield {"id": "new", "type": "synthetic.updated", "data": {}}

    monkeypatch.setattr(events, "listen_events", listener)
    request = SimpleNamespace(is_disconnected=AsyncMock(return_value=True))
    response = await events.event_stream(request, last_event_id=None, identity=(1, "synthetic-stream", "doctor"))
    assert [frame async for frame in response.body_iterator] == [": connected\n\n"]
