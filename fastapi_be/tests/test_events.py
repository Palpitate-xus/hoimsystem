import pytest

from app import event_bus


@pytest.mark.asyncio
async def test_event_history_filters_by_role(monkeypatch):
    monkeypatch.setattr(event_bus.settings, "REDIS_URL", "")
    event_bus._recent.clear()
    await event_bus.publish_event("queue.called", {"queue_number": 8}, audience_roles=["doctor", "nurse"])
    await event_bus.publish_event("admin.changed", {"kind": "config"}, audience_roles=["admin"])

    doctor_events = await event_bus.recent_events((1, "doc", "doctor"))
    patient_events = await event_bus.recent_events((2, "patient", "patient"))

    assert [event["type"] for event in doctor_events] == ["queue.called"]
    assert patient_events == []


@pytest.mark.asyncio
async def test_recent_event_endpoint_requires_auth(async_client):
    response = await async_client.get("/api/events/recent")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_recent_event_endpoint_returns_authorized_events(async_client, seed_data, auth_headers, monkeypatch):
    monkeypatch.setattr(event_bus.settings, "REDIS_URL", "")
    event_bus._recent.clear()
    await event_bus.publish_event("queue.called", {"queue_number": 9}, audience_roles=["doctor"])

    response = await async_client.get(
        "/api/events/recent",
        headers=auth_headers(seed_data["doctor_user"].username),
    )

    assert response.status_code == 200
    assert response.json()["data"][0]["type"] == "queue.called"
