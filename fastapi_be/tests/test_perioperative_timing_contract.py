"""Preserve the existing statistics bounds and identify missing or incompatible time inputs."""

import datetime

import pytest

from app.perioperative_review import assess_existing_timing, existing_timing_rule


@pytest.mark.parametrize("minutes,within", [(29, False), (30, True), (60, True), (120, True), (121, False), (-5, False)])
def test_existing_statistics_window_is_inclusive_and_keeps_post_start_values(minutes, within):
    start = datetime.datetime(2026, 10, 20, 10)
    result = assess_existing_timing(start - datetime.timedelta(minutes=minutes), start)
    assert result["within_existing_window"] is within
    assert result["minutes_before_start"] == minutes
    assert result["clinical_appropriateness"] is None
    assert existing_timing_rule()["reference_field"] == "SurgerySchedule.start_time"


def test_missing_time_and_mixed_timezone_are_not_invented_as_normal():
    assert assess_existing_timing(None, datetime.datetime(2026, 10, 20))["within_existing_window"] is None
    mixed = assess_existing_timing(datetime.datetime(2026, 10, 20, tzinfo=datetime.UTC), datetime.datetime(2026, 10, 20))
    assert mixed["status"] == "not_evaluated"
