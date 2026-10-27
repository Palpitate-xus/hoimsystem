"""Exercise real Locust event dispatch and persisted percentile evidence."""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

from locust.env import Environment
from locust.event import Events

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from benchmark_metadata import register_metadata_hooks


def test_real_locust_keyword_events_capture_start_and_configured_load(tmp_path, monkeypatch):
    events = Events()
    environment = Environment(events=events)
    environment.parsed_options = SimpleNamespace(num_users=50)
    environment.host = "http://127.0.0.1:18127"
    monkeypatch.setenv("BENCHMARK_RESULTS_DIR", str(tmp_path))
    monkeypatch.setenv("BENCHMARK_RUN_ID", "keyword-event")
    register_metadata_hooks(events)
    events.test_start.fire(environment=environment)
    for duration in [10, 20, 30, 40, 50]:
        environment.stats.log_request("GET", "/synthetic", duration, 10)
    events.test_stop.fire(environment=environment)
    data = json.loads((tmp_path / "keyword-event.metadata.json").read_text())
    assert data["started_at"] < data["finished_at"]
    assert data["configured_users"] == 50
    assert data["requests"] == 5
    assert data["failures"] == 0
    assert data["p50_response_time_ms"] <= data["p95_response_time_ms"] <= data["p99_response_time_ms"]
