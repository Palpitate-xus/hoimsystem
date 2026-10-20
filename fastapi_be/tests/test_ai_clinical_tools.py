"""Numeric tools keep incompatible units and uncertain timing out of automatic comparisons."""

from app.ai.clinical_tools import critical_value_workflow, laboratory_trends


def point(source_id, value, collected_at, **changes):
    return {
        "source_id": source_id,
        "code_system": "local",
        "code": "TEST",
        "display": "测试项目",
        "unit": "mg/L",
        "method": "测试方法",
        "specimen_type": "血清",
        "value_num": value,
        "collected_at": collected_at,
        "flag": "unknown",
        **changes,
    }


def test_trends_use_exact_decimal_arithmetic_and_collection_time_order():
    data = {"reviewed_observations": [point("new", "4.12345679", "2026-10-20T02:00:00+00:00"), point("old", "4.12345678", "2026-10-19T02:00:00+00:00")]}
    result = laboratory_trends(data)
    series = result["series"][0]
    assert series["absolute_change"] == "0.00000001"
    assert series["comparable"] is True
    assert series["points"][0]["source_id"] == "old"
    assert result["medical_thresholds_applied"] is False


def test_different_units_methods_and_specimens_never_share_a_numeric_series():
    values = [
        point("one", "1", "2026-10-19T01:00:00Z"),
        point("unit", "2", "2026-10-20T01:00:00Z", unit="mmol/L"),
        point("method", "3", "2026-10-20T01:00:00Z", method="另一方法"),
        point("specimen", "4", "2026-10-20T01:00:00Z", specimen_type="尿"),
    ]
    result = laboratory_trends({"reviewed_observations": values})
    assert len(result["series"]) == 4
    assert not any(item["comparable"] for item in result["series"])
    assert result["unit_conversion_performed"] is False


def test_missing_method_and_qualitative_values_remain_visible_as_excluded_facts():
    result = laboratory_trends({"reviewed_observations": [point("missing", "1", "2026-10-20T01:00:00Z", method=""), point("text", None, "2026-10-20T01:00:00Z", value_text="阴性")]})
    assert result["series"] == []
    assert len(result["excluded_from_numeric_comparison"]) == 2
    assert "method" in result["excluded_from_numeric_comparison"][0]["missing_fields"]


def test_equal_collection_time_does_not_invent_a_direction_and_marks_changed_ranges():
    result = laboratory_trends(
        {
            "reviewed_observations": [point("one", "1", "2026-10-20T01:00:00Z", reference_high="3"), point("two", "2", "2026-10-20T01:00:00Z", reference_high="4")],
            "truncated_sources": [{"source": "结构化检验指标"}],
        }
    )
    series = result["series"][0]
    assert series["absolute_change"] is None
    assert series["comparison_status"] == "duplicate_sample_times"
    assert series["reference_range_changed"] is True
    assert result["history_truncated"] is True


def test_critical_workflow_preserves_state_and_performs_no_actions():
    result = critical_value_workflow({"reviewed_lab_reports": [{"source_id": "lab:test", "critical_status": 2, "critical_notified_time": "2026-10-20T00:00:00"}]})
    assert result["reports"][0]["workflow_state"] == "已通知待确认"
    assert result["reports"][0]["critical_status"] == 2
    assert result["actions_executed"] == []
