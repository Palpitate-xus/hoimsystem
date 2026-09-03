import datetime

from app.integration_outbox import enqueue_integration_event, process_integration_outbox
from app.models import IntegrationOutbox


class StubResponse:
    status_code = 202
    text = "accepted"


def test_outbox_delivery_is_idempotent_and_durable(db_session, monkeypatch):
    from app import integration_outbox

    monkeypatch.setattr(integration_outbox.settings, "LIS_OUTBOUND_URL", "https://lis.example.test/events")
    calls = []

    def post(url, **kwargs):
        calls.append((url, kwargs))
        return StubResponse()

    monkeypatch.setattr(integration_outbox.requests, "post", post)
    event = enqueue_integration_event(
        db_session,
        destination="lis",
        event_type="lab.order.created",
        aggregate_type="lab_order",
        aggregate_id="LAB-1",
        payload={"lab_order_id": "LAB-1"},
    )
    db_session.commit()
    event_id = event.event_id

    result = process_integration_outbox(db_session)

    assert result["delivered"] == 1
    assert db_session.get(IntegrationOutbox, event_id).status == "delivered"
    assert calls[0][1]["headers"]["Idempotency-Key"] == event_id
    assert process_integration_outbox(db_session)["selected"] == 0


def test_outbox_moves_permanent_failures_to_dead_letter(db_session, monkeypatch):
    from app import integration_outbox

    monkeypatch.setattr(integration_outbox.settings, "PACS_OUTBOUND_URL", "https://pacs.example.test/events")
    monkeypatch.setattr(integration_outbox.settings, "INTEGRATION_MAX_ATTEMPTS", 1)

    def fail(*args, **kwargs):
        raise integration_outbox.requests.ConnectionError("offline")

    monkeypatch.setattr(integration_outbox.requests, "post", fail)
    event = enqueue_integration_event(
        db_session,
        destination="pacs",
        event_type="imaging.order.created",
        aggregate_type="imaging_order",
        aggregate_id="IMG-1",
        payload={"imaging_order_id": "IMG-1"},
    )
    db_session.commit()

    assert process_integration_outbox(db_session)["dead"] == 1
    assert event.status == "dead"
    assert event.last_attempt_at <= datetime.datetime.now()
