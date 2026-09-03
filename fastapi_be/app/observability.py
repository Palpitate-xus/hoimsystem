"""Low-overhead request telemetry shared by metrics and the admin dashboard."""

import re
import threading
import time
import uuid
from collections import Counter, deque

from prometheus_client import Counter as PrometheusCounter
from prometheus_client import Gauge, Histogram

REQUESTS = PrometheusCounter(
    "hoimsystem_http_requests_total",
    "HTTP requests handled by the API",
    ("method", "route", "status"),
)
LATENCY = Histogram(
    "hoimsystem_http_request_duration_seconds",
    "HTTP request latency",
    ("method", "route"),
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10),
)
IN_PROGRESS = Gauge(
    "hoimsystem_http_requests_in_progress",
    "HTTP requests currently in progress",
    ("method",),
    multiprocess_mode="livesum",
)

REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,64}$")


class RequestStats:
    """A bounded current-worker window for the interactive admin summary."""

    def __init__(self, max_events: int = 100_000):
        self._events = deque(maxlen=max_events)
        self._lock = threading.Lock()

    def record(self, status: int, duration_seconds: float, route: str, username: str | None) -> None:
        with self._lock:
            self._events.append((time.time(), status, duration_seconds, route, username))

    def snapshot(self, window_seconds: int = 86_400) -> dict:
        cutoff = time.time() - window_seconds
        with self._lock:
            events = [event for event in self._events if event[0] >= cutoff]
            sample_limited = len(self._events) == self._events.maxlen
        total = len(events)
        failed = sum(status >= 400 for _, status, _, _, _ in events)
        average_ms = sum(duration for _, _, duration, _, _ in events) * 1000 / total if total else 0
        users = {username for _, _, _, _, username in events if username}
        routes = Counter(route for _, _, _, route, _ in events)
        return {
            "total_requests": total,
            "failed_requests": failed,
            "error_rate": round(failed / total * 100, 2) if total else 0,
            "average_response_time_ms": round(average_ms, 2),
            "online_users": len(users),
            "top_endpoints": [{"path": route, "count": count} for route, count in routes.most_common(10)],
            "sample_limited": sample_limited,
        }


request_stats = RequestStats()


class ObservabilityMiddleware:
    """Pure ASGI telemetry middleware that never buffers response bodies."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("path") == "/metrics":
            await self.app(scope, receive, send)
            return

        method = scope.get("method", "UNKNOWN")
        incoming_headers = dict(scope.get("headers", []))
        candidate = incoming_headers.get(b"x-request-id", b"").decode("ascii", errors="ignore")
        request_id = candidate if REQUEST_ID_PATTERN.fullmatch(candidate) else uuid.uuid4().hex
        scope.setdefault("state", {})["request_id"] = request_id
        status_code = 500
        started_at = time.perf_counter()
        IN_PROGRESS.labels(method).inc()

        async def send_with_request_id(message):
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                headers = list(message.get("headers", []))
                headers.append((b"x-request-id", request_id.encode("ascii")))
                message["headers"] = headers
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        finally:
            duration = time.perf_counter() - started_at
            route = getattr(scope.get("route"), "path", "unmatched")
            auth_identity = scope.get("state", {}).get("auth_identity")
            username = auth_identity[1] if auth_identity else None
            REQUESTS.labels(method, route, str(status_code)).inc()
            LATENCY.labels(method, route).observe(duration)
            IN_PROGRESS.labels(method).dec()
            request_stats.record(status_code, duration, route, username)
