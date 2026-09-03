"""Transactional outbox delivery for LIS, PACS, insurance and payment systems."""

import datetime
import json

import requests

from app.config import settings
from app.models import IntegrationOutbox

DESTINATIONS = {"lis", "pacs", "insurance", "payment"}


def _destination_config(destination: str) -> tuple[str, str]:
    return {
        "lis": (settings.LIS_OUTBOUND_URL, settings.LIS_INTEGRATION_KEY),
        "pacs": (settings.PACS_OUTBOUND_URL, settings.PACS_INTEGRATION_KEY),
        "insurance": (settings.MEDICAL_INSURANCE_OUTBOUND_URL, settings.MEDICAL_INSURANCE_INTEGRATION_KEY),
        "payment": (settings.PAYMENT_OUTBOUND_URL, settings.PAYMENT_INTEGRATION_KEY),
    }[destination]


def enqueue_integration_event(
    db,
    *,
    destination: str,
    event_type: str,
    aggregate_type: str,
    aggregate_id: str,
    payload: dict,
) -> IntegrationOutbox:
    """Stage an outbound event in the caller's existing database transaction."""
    if destination not in DESTINATIONS:
        raise ValueError(f"unsupported integration destination: {destination}")
    now = datetime.datetime.now()
    event = IntegrationOutbox(
        destination=destination,
        event_type=event_type,
        aggregate_type=aggregate_type,
        aggregate_id=str(aggregate_id),
        payload_json=json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str),
        status="pending",
        attempts=0,
        next_attempt_at=now,
        created_at=now,
    )
    db.add(event)
    return event


def _retry_at(attempts: int) -> datetime.datetime:
    seconds = min(3600, 30 * (2 ** max(0, attempts - 1)))
    return datetime.datetime.now() + datetime.timedelta(seconds=seconds)


def process_integration_outbox(db, batch_size: int = 50) -> dict:
    now = datetime.datetime.now()
    query = (
        db.query(IntegrationOutbox)
        .filter(
            IntegrationOutbox.status.in_(("pending", "retry")),
            IntegrationOutbox.next_attempt_at <= now,
        )
        .order_by(IntegrationOutbox.created_at)
        .limit(max(1, min(batch_size, 200)))
    )
    if db.bind.dialect.name == "postgresql":
        query = query.with_for_update(skip_locked=True)
    events = query.all()
    delivered = retried = dead = deferred = 0
    for event in events:
        endpoint, credential = _destination_config(event.destination)
        if not endpoint:
            event.status = "retry"
            event.last_error = f"{event.destination} outbound URL is not configured"
            event.next_attempt_at = now + datetime.timedelta(minutes=10)
            deferred += 1
            continue

        event.attempts += 1
        event.last_attempt_at = datetime.datetime.now()
        headers = {
            "Content-Type": "application/json",
            "Idempotency-Key": event.event_id,
            "X-HOIM-Event-ID": event.event_id,
            "X-HOIM-Event-Type": event.event_type,
        }
        if credential:
            headers["Authorization"] = f"Bearer {credential}"
        try:
            response = requests.post(
                endpoint,
                data=event.payload_json.encode("utf-8"),
                headers=headers,
                timeout=settings.INTEGRATION_HTTP_TIMEOUT_SECONDS,
                allow_redirects=False,
            )
            event.last_http_status = response.status_code
            if 200 <= response.status_code < 300:
                event.status = "delivered"
                event.delivered_at = datetime.datetime.now()
                event.last_error = None
                delivered += 1
                continue
            error = f"HTTP {response.status_code}: {response.text[:500]}"
        except requests.RequestException as exc:
            error = f"{type(exc).__name__}: {exc}"[:1000]

        event.last_error = error[:1000]
        if event.attempts >= settings.INTEGRATION_MAX_ATTEMPTS:
            event.status = "dead"
            dead += 1
        else:
            event.status = "retry"
            event.next_attempt_at = _retry_at(event.attempts)
            retried += 1
    db.commit()
    return {
        "selected": len(events),
        "delivered": delivered,
        "retried": retried,
        "dead": dead,
        "deferred_unconfigured": deferred,
    }
