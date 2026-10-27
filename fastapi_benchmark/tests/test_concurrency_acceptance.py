"""Protect the real-HTTP acceptance runner's isolation and success criteria."""

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
spec = importlib.util.spec_from_file_location("concurrency_acceptance", ROOT / "concurrency_acceptance.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

DATABASE = "postgresql://benchmark:local-only@127.0.0.1:18427/hoimsystem_benchmark"


@pytest.mark.parametrize("host", [
    "https://hospital.example.com:443", "http://127.0.0.1", "http://127.0.0.1:18127/api",
    "http://admin:password@127.0.0.1:18127", "http://127.0.0.1:18127?target=production",
    "http://127.0.0.1:18127#production", "file:///tmp/api",
])
def test_rejects_ambiguous_or_nonlocal_api_targets(host):
    with pytest.raises(ValueError):
        module.validate_targets(host, DATABASE)


@pytest.mark.parametrize("database", [
    "postgresql://benchmark:local-only@127.0.0.1:18427/hoimsystem",
    "postgresql://benchmark:local-only@hospital.example.com/hoimsystem_benchmark",
    "sqlite:///production.db",
])
def test_rejects_business_databases_and_remote_targets(database):
    with pytest.raises((ValueError, RuntimeError)):
        module.validate_targets("http://127.0.0.1:18127", database)


def test_accepts_explicit_local_benchmark_origin():
    assert module.validate_targets("http://127.0.0.1:18127/", DATABASE) == "http://127.0.0.1:18127"


def test_successful_http_responses_do_not_hide_duplicate_database_writes():
    probe = object.__new__(module.Acceptance)
    probe.results = []
    probe.record("duplicate", [{"http_status": 200, "code": 200}], {"successful_requests": 1, "rows": 1}, {"rows": 2})
    assert probe.results[0]["passed"] is False


def test_transport_errors_do_not_count_as_expected_business_conflicts():
    probe = object.__new__(module.Acceptance)
    probe.results = []
    probe.record("conflict", [{"http_status": 500, "code": 409}], {"successful_requests": 0, "rows": 0}, {"rows": 0})
    assert probe.results[0]["passed"] is False


def test_business_conflicts_and_matching_database_invariants_pass():
    probe = object.__new__(module.Acceptance)
    probe.results = []
    probe.record("once", [{"http_status": 200, "code": 200}, {"http_status": 400, "code": 500}], {"successful_requests": 1, "rows": 1}, {"rows": 1})
    assert probe.results[0]["passed"] is True
