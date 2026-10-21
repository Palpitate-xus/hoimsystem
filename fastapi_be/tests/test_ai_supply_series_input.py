"""Strict declarations first; actual governed SQL sources are tested below separately."""

import copy
import datetime
import uuid

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.ai import supply_contract as core
from app.ai.supply_series_input import SeriesPeriodRequest, SeriesRequest, TargetSelection, period_days, validate_series_period

NOTE = "隔离合成物资数量完整日与来源声明，仅验证工程过程，不代表医院实际运营验证或真实需求。"


def period_values(n=112):
    end = datetime.date(2026, 10, 19)
    return {
        "item_kind": "pharmaceutical",
        "item_id": 1,
        "scope": "hospital_inventory",
        "timezone": "UTC",
        "date_from": (end - datetime.timedelta(days=n - 1)).isoformat(),
        "date_to": end.isoformat(),
        "as_of": "2026-10-20T12:00:00.123456Z",
    }


def declared_request():
    period = SeriesPeriodRequest.model_validate(period_values())
    return {
        **period.model_dump(),
        "unit_definition_id": str(uuid.uuid4()),
        "expected_unit_content_hash": "a" * 64,
        "expected_unit_governance_hash": "b" * 64,
        "parameters": {k: {"numerator": "1", "denominator": "10"} for k in ("alpha_size", "alpha_interval", "beta_occurrence")},
        "target_coverage": [
            {"target": target, "same_scope_confirmed": "unknown", "same_definition_confirmed": "unknown", "same_method_confirmed": "unknown", "basis_note": NOTE} for target in core.TARGETS
        ],
        "days": [
            {
                "date": day["date"],
                "selections": [{"target": target, "source_record_id": None, "absent_reason": "missing_selected_original", "group_digest": "c" * 64, "basis_note": NOTE} for target in core.TARGETS],
            }
            for day in period_days(period)
        ],
        "member_reviews": [],
    }


@pytest.mark.parametrize("n", [112, 366])
def test_exact_full_periods_and_no_default_parameters(n):
    value = SeriesPeriodRequest.model_validate(period_values(n))
    assert len(period_days(value)) == n
    request = declared_request()
    assert SeriesRequest.model_validate(request).model_dump() == request
    del request["parameters"]
    with pytest.raises(ValidationError):
        SeriesRequest.model_validate(request)


@pytest.mark.parametrize(
    "change",
    [
        {"item_id": True},
        {"item_id": "1"},
        {"scope": "department"},
        {"timezone": "Invalid/Timezone"},
        {"date_from": "2026-7-01"},
        {"date_to": "2026-10-20"},
        {"as_of": "2026-10-20T12:00:00Z"},
        {"date_from": "2026-07-01"},
        {"date_from": "2025-10-18"},
        {"as_of": "9999-12-31T12:00:00.123456Z", "date_to": "9999-12-30", "date_from": "9999-09-10"},
    ],
)
def test_noncanonical_scope_clock_and_whole_horizon_rejected(change):
    with pytest.raises(ValidationError):
        SeriesPeriodRequest.model_validate(period_values() | change)


@pytest.mark.parametrize(
    "number",
    [
        {"numerator": "2", "denominator": "4"},
        {"numerator": "0", "denominator": "1"},
        {"numerator": "1", "denominator": "1001"},
        {"numerator": 1, "denominator": "10"},
        {"numerator": "11", "denominator": "10"},
    ],
)
def test_parameters_are_exact_reviewed_rationals_not_inferred_or_tuned(number):
    body = declared_request()
    body["parameters"]["alpha_size"] = number
    with pytest.raises(ValidationError):
        SeriesRequest.model_validate(body)


@pytest.mark.parametrize("fault", ["day_omitted", "duplicate_date", "target_swapped", "unit_null", "unknown_extra", "whitespace_basis", "too_many_utf8", "duplicate_member"])
def test_whole_private_request_rejects_incomplete_or_ambiguous_declarations(fault):
    body = declared_request()
    if fault == "day_omitted":
        body["days"].pop()
    elif fault == "duplicate_date":
        body["days"][1]["date"] = body["days"][0]["date"]
    elif fault == "target_swapped":
        body["target_coverage"].reverse()
    elif fault == "unit_null":
        body["unit_definition_id"] = None
    elif fault == "unknown_extra":
        body["auto_latest"] = True
    elif fault == "whitespace_basis":
        body["target_coverage"][0]["basis_note"] = " " * 30
    elif fault == "too_many_utf8":
        body["target_coverage"][0]["basis_note"] = "物" * 1400
    else:
        member = {
            "source_record_id": str(uuid.uuid4()),
            "source_kind": "daily_quantity",
            "expected_content_hash": "a" * 64,
            "expected_governance_hash": "b" * 64,
            "selection": "unknown",
            "basis_note": NOTE,
        }
        body["member_reviews"] = [member, copy.deepcopy(member)]
    with pytest.raises(ValidationError):
        SeriesRequest.model_validate(body)


def test_nullable_day_selection_is_explicit_and_never_silently_zero():
    item = declared_request()["days"][0]["selections"][0]
    assert TargetSelection.model_validate(item).source_record_id is None
    with pytest.raises(ValidationError):
        TargetSelection.model_validate(item | {"absent_reason": None})
    with pytest.raises(ValidationError):
        TargetSelection.model_validate(item | {"source_record_id": str(uuid.uuid4())})


def test_history_own_period_does_not_age_but_new_execution_requires_current_closed_day():
    period = SeriesPeriodRequest.model_validate(period_values())
    assert len(validate_series_period(period, now=datetime.datetime(2026, 10, 20, 23))) == 112
    assert SeriesPeriodRequest.model_validate(period.model_dump()) == period
    with pytest.raises(HTTPException) as e:
        validate_series_period(period, now=datetime.datetime(2026, 10, 21, 0))
    assert e.value.status_code == 409


def test_actual_dst_day_is25_hours_without_guessing_naive_clocks():
    end = datetime.date(2026, 11, 2)
    period = SeriesPeriodRequest.model_validate(
        period_values() | {"timezone": "America/New_York", "date_from": (end - datetime.timedelta(days=111)).isoformat(), "date_to": end.isoformat(), "as_of": "2026-11-03T12:00:00.123456Z"}
    )
    day = next(r for r in period_days(period) if r["date"] == "2026-11-01")
    left = datetime.datetime.fromisoformat(day["day_start_at"].replace("Z", "+00:00"))
    right = datetime.datetime.fromisoformat(day["day_end_at"].replace("Z", "+00:00"))
    assert (right - left).total_seconds() == 25 * 3600
