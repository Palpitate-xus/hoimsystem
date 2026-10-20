"""Synthetic dense histories exercise frozen-source integrity without real data."""

import copy
import hashlib
from datetime import date, timedelta

import pytest
from pydantic import ValidationError

from app.ai.forecast_contract import ForecastSource, canonical_json, source_content_hash


def make_source(count=112, *, values=None, start=date(2024, 1, 1)):
    series_id = "12345678-1234-4234-8234-123456789012"
    values = values if values is not None else [20 + index % 7 + index // 7 for index in range(count)]
    observations = [{"date": (start + timedelta(days=index)).isoformat(), "value": value} for index, value in enumerate(values)]
    source = {
        "series_id": series_id,
        "target": "registration_record_count",
        "grain": "day",
        "scope": "hospital",
        "department_id": None,
        "date_from": observations[0]["date"],
        "date_to": observations[-1]["date"],
        "timezone": "Asia/Shanghai",
        "time_basis": "naive_registration_time",
        "coverage_status": "super_admin_attested",
        "coverage_attested_at": "2026-10-20T01:02:03.123456Z",
        "coverage_note_hash": hashlib.sha256("synthetic覆盖声明".encode()).hexdigest(),
        "registration_digest": hashlib.sha256(b"synthetic-no-patient-registration-rows").hexdigest(),
        "unassigned_time_records": 3,
        "observations": observations,
    }
    return rebind(source)


def rebind(source):
    source["content_hash"] = source_content_hash(source)
    source["source_id"] = f"forecast:{source['series_id']}:{source['content_hash'][:12]}"
    return source


@pytest.mark.parametrize("count", [112, 366])
def test_exact_source_hash_and_inclusive_calendar_length(count):
    source = make_source(count)
    parsed = ForecastSource.model_validate(source)
    assert parsed.model_dump() == source
    assert source_content_hash(source) == hashlib.sha256(canonical_json({key: value for key, value in source.items() if key not in {"source_id", "content_hash"}}).encode()).hexdigest()
    assert any(item.date == "2024-02-29" for item in parsed.observations)


@pytest.mark.parametrize("value", [True, False, "0", 1.2, -1, 2147483648])
def test_observations_require_explicit_bounded_integer_counts(value):
    source = make_source()
    source["observations"][10]["value"] = value
    with pytest.raises(ValidationError):
        ForecastSource.model_validate(rebind(source))


@pytest.mark.parametrize("change", ["gap", "duplicate", "reorder", "short", "long", "start", "end", "noncanonical"])
def test_no_missing_dates_are_ever_filled(change):
    source = make_source(366 if change == "long" else 112)
    if change == "gap":
        source["observations"][10]["date"] = "2024-01-12"
    elif change == "duplicate":
        source["observations"][10]["date"] = "2024-01-10"
    elif change == "reorder":
        source["observations"][10], source["observations"][11] = source["observations"][11], source["observations"][10]
    elif change == "short":
        source["observations"].pop()
    elif change == "long":
        source["observations"].append({"date": "2025-01-01", "value": 0})
    elif change == "start":
        source["date_from"] = "2023-12-31"
    elif change == "end":
        source["date_to"] = "2024-04-22"
    else:
        source["observations"][0]["date"] = "2024-1-1"
    with pytest.raises(ValidationError):
        ForecastSource.model_validate(rebind(source))


@pytest.mark.parametrize(
    "field,value",
    [
        ("series_id", "12345678-1234-4234-8234-12345678901A"),
        ("target", "actual_visits"),
        ("grain", "hour"),
        ("time_basis", "utc_registration_time"),
        ("coverage_status", "complete"),
        ("department_id", 1),
        ("timezone", "Mars/Fake"),
        ("coverage_attested_at", "2026-10-20T01:02:03"),
        ("coverage_attested_at", "2026-10-20T01:02:03+08:00"),
        ("coverage_attested_at", "2026-02-30T01:02:03Z"),
        ("unassigned_time_records", True),
        ("unassigned_time_records", "0"),
        ("coverage_note_hash", "A" * 64),
    ],
)
def test_source_rejects_invented_identity_scope_clock_and_coverage(field, value):
    source = make_source()
    source[field] = value
    with pytest.raises(ValidationError):
        ForecastSource.model_validate(rebind(source))


def test_department_source_explicitly_requires_real_positive_integer_scope_id():
    source = make_source()
    source.update(scope="department", department_id=17)
    assert ForecastSource.model_validate(rebind(source)).department_id == 17
    for value in [None, True, "17", 0, -1, 17.2]:
        source["department_id"] = value
        with pytest.raises(ValidationError):
            ForecastSource.model_validate(rebind(source))


@pytest.mark.parametrize("change", ["value", "attestation", "unknown", "identifier"])
def test_frozen_content_and_unknown_fields_cannot_silently_change(change):
    source = make_source()
    if change == "value":
        source["observations"][0]["value"] += 1
    elif change == "attestation":
        source["coverage_attested_at"] = "2026-10-20T01:02:03+00:00"
    elif change == "unknown":
        source["coverage_note"] = "free notes must not travel to model"
        rebind(source)
    else:
        source["source_id"] = "forecast:" + "0" * 36 + ":" + source["content_hash"][:12]
    original = copy.deepcopy(source)
    with pytest.raises(ValidationError):
        ForecastSource.model_validate(source)
    assert source == original
