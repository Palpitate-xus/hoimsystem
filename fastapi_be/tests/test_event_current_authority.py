"""SSE rechecks real account authority without retaining sessions across frames."""

import datetime
import json
import threading
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import delete, update

from app import database, event_bus
from app.access_models import AccessPolicy
from app.models import User
from app.routers import events

CHANGES = ("user_revoke", "role_revoke", "user_disable", "role_disable", "role", "identity", "epoch", "delete")


def _event(identifier, **data):
    return {"id": identifier, "type": "clinical.updated", "data": data, "audience_roles": ["doctor"]}


@pytest.fixture
def stream_case(db_session, seed_data, auth_headers, monkeypatch):
    actor = seed_data["doctor_user"]
    actor_id, username = actor.user_id, actor.username
    headers = auth_headers(username)
    request = SimpleNamespace(
        headers=headers,
        method="GET",
        scope={"route": SimpleNamespace(path="/api/events/stream")},
        state=SimpleNamespace(),
        is_disconnected=AsyncMock(return_value=False),
    )
    identity = events.get_event_identity(request, access_token=headers["accesstoken"])

    async def finite_listener(_identity):
        yield None

    monkeypatch.setattr(events, "listen_events", finite_listener)
    monkeypatch.setattr(event_bus.settings, "REDIS_URL", "")
    yield SimpleNamespace(
        db=db_session,
        actor_id=actor_id,
        request=request,
        identity=identity,
        headers=headers,
        patient_id=seed_data["patient"].patient_id,
        outside_id=seed_data["patient2"].patient_id,
    )
    db_session.rollback()
    for key in (("role", "doctor"), ("user", str(actor_id))):
        policy = db_session.get(AccessPolicy, key)
        if policy is not None:
            db_session.delete(policy)
    db_session.commit()


def _change(case, change):
    if change in {"user_revoke", "role_revoke", "user_disable", "role_disable"}:
        kind = "user" if change.startswith("user") else "role"
        policy = AccessPolicy(kind=kind, subject_key=str(case.actor_id) if kind == "user" else "doctor")
        if change.endswith("revoke"):
            policy.allowed_json = "[]"
        else:
            policy.disabled = True
        case.db.add(policy)
    elif change == "role":
        case.db.execute(update(User).where(User.user_id == case.actor_id).values(user_role="patient"))
    elif change == "identity":
        case.db.execute(update(User).where(User.user_id == case.actor_id).values(username=f"renamed-{case.actor_id}"))
    elif change == "epoch":
        invalid_before = datetime.datetime.now(datetime.UTC).replace(tzinfo=None) + datetime.timedelta(seconds=1)
        case.db.execute(update(User).where(User.user_id == case.actor_id).values(token_invalid_before=invalid_before))
    else:
        case.db.execute(delete(User).where(User.user_id == case.actor_id))
    case.db.commit()


@pytest.mark.asyncio
@pytest.mark.parametrize("change", CHANGES)
@pytest.mark.parametrize("next_frame", ["event", "heartbeat"])
async def test_open_stream_closes_before_sending_after_authority_changes(stream_case, monkeypatch, change, next_frame):
    first = _event("first", status="before")
    closed = []

    async def listener(_identity):
        try:
            yield first
            yield None if next_frame == "heartbeat" else _event("stale", status="after")
        finally:
            closed.append(True)

    monkeypatch.setattr(events, "listen_events", listener)
    response = await events.event_stream(stream_case.request, last_event_id=None, identity=stream_case.identity)
    iterator = response.body_iterator
    assert await anext(iterator) == ": connected\n\n"
    assert await anext(iterator) == events._encode_event(first)
    _change(stream_case, change)
    with pytest.raises(StopAsyncIteration):
        await anext(iterator)
    assert closed == [True]


@pytest.mark.asyncio
@pytest.mark.parametrize("change", CHANGES)
async def test_replayed_history_rechecks_authority_before_each_event(stream_case, monkeypatch, change):
    old, first, stale = (_event(key) for key in ("old", "first", "stale"))
    monkeypatch.setattr(events, "recent_events", AsyncMock(return_value=[old, first, stale]))
    response = await events.event_stream(stream_case.request, last_event_id="old", identity=stream_case.identity)
    iterator = response.body_iterator
    assert await anext(iterator) == ": connected\n\n"
    assert await anext(iterator) == events._encode_event(first)
    _change(stream_case, change)
    with pytest.raises(StopAsyncIteration):
        await anext(iterator)


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/api/events/recent", "/api/events/stream"])
@pytest.mark.parametrize("change", ["user_revoke", "role_revoke", "user_disable", "role_disable"])
async def test_new_event_request_enforces_configured_permission(async_client, stream_case, path, change):
    _change(stream_case, change)
    response = await async_client.get(path, headers=stream_case.headers)
    assert response.status_code == 403
    assert "connected" not in response.text


@pytest.mark.asyncio
async def test_new_stream_request_requires_authentication(async_client, stream_case):
    response = await async_client.get("/api/events/stream")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_new_stream_request_with_current_authority_emits_frames(async_client, stream_case):
    response = await async_client.get("/api/events/stream", headers=stream_case.headers)
    assert response.status_code == 200, response.text
    assert response.text == ": connected\n\n: keepalive\n\n"


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/health/live", "/api/publicKey", "/api/version"])
async def test_event_restrictions_leave_public_health_and_bootstrap_accessible(async_client, stream_case, path):
    _change(stream_case, "user_revoke")
    response = await async_client.get(path)
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_unchanged_stream_retains_events_heartbeat_and_audience_filter(stream_case, monkeypatch):
    wanted = _event("wanted", status="visible")
    hidden = {**_event("hidden", secret="admin"), "audience_roles": ["admin"]}

    async def listener(_identity):
        yield hidden
        yield wanted
        yield None

    monkeypatch.setattr(events, "listen_events", listener)
    response = await events.event_stream(stream_case.request, last_event_id=None, identity=stream_case.identity)
    frames = [frame async for frame in response.body_iterator]
    assert frames == [": connected\n\n", events._encode_event(wanted), ": keepalive\n\n"]


@pytest.mark.asyncio
@pytest.mark.parametrize("transport", ["recent", "replay", "live"])
async def test_assigned_patient_scope_filters_every_event_transport(async_client, stream_case, monkeypatch, transport):
    stream_case.db.add(AccessPolicy(kind="user", subject_key=str(stream_case.actor_id), data_scope="assigned"))
    stream_case.db.commit()
    old = _event("old")
    outside = _event("outside", patient_id=stream_case.outside_id)
    malformed = _event("malformed", patient_id=True)
    own = _event("own", patient_id=stream_case.patient_id)
    history = [old, outside, malformed, own]
    monkeypatch.setattr(events, "recent_events", AsyncMock(return_value=history))

    async def listener(_identity):
        if transport == "live":
            for row in history[1:]:
                yield row
        yield None

    monkeypatch.setattr(events, "listen_events", listener)
    if transport == "recent":
        response = await async_client.get("/api/events/recent", headers=stream_case.headers)
        assert response.status_code == 200, response.text
        assert [row["id"] for row in response.json()["data"]] == ["old", "own"]
    else:
        response = await events.event_stream(
            stream_case.request, last_event_id="old" if transport == "replay" else None, identity=stream_case.identity
        )
        assert [frame async for frame in response.body_iterator] == [": connected\n\n", events._encode_event(own), ": keepalive\n\n"]


@pytest.mark.asyncio
async def test_recent_history_rechecks_authority_after_event_store_await(async_client, stream_case, monkeypatch):
    async def stale_history(_identity, _limit):
        _change(stream_case, "user_revoke")
        return [_event("stale")]

    monkeypatch.setattr(events, "recent_events", stale_history)
    response = await async_client.get("/api/events/recent", headers=stream_case.headers)
    assert response.status_code == 403
    assert "stale" not in response.text


@pytest.mark.asyncio
async def test_sse_database_work_runs_off_event_loop_and_closes_between_frames(stream_case, monkeypatch):
    event_loop_thread = threading.get_ident()
    original_factory = database.SessionLocal
    active, worker_threads = [], []

    @contextmanager
    def tracked_session():
        worker_threads.append(threading.get_ident())
        active.append(True)
        try:
            with original_factory() as db:
                yield db
        finally:
            active.pop()

    async def listener(_identity):
        yield _event("safe")
        yield None

    monkeypatch.setattr(database, "SessionLocal", tracked_session)
    monkeypatch.setattr(events, "listen_events", listener)
    response = await events.event_stream(stream_case.request, last_event_id=None, identity=stream_case.identity)
    frames = []
    async for frame in response.body_iterator:
        assert active == []
        frames.append(frame)
    assert len(frames) == 3
    assert len(worker_threads) == 3
    assert all(identifier != event_loop_thread for identifier in worker_threads)
    assert json.loads(frames[1].split("data: ", 1)[1])["id"] == "safe"
