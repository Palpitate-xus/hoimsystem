"""Read-only calculations over reviewed source values; no medical thresholds are inferred."""

from collections import defaultdict
from decimal import Decimal


def laboratory_trends(context: dict) -> dict:
    """Compare only exact code, unit, method and specimen matches using collection times."""
    grouped = defaultdict(list)
    excluded = []
    for item in context.get("reviewed_observations", []):
        missing = [name for name in ("code_system", "code", "unit", "method", "specimen_type", "collected_at") if not item.get(name)]
        if item.get("value_num") is None:
            missing.append("numeric_value")
        if missing:
            excluded.append({"source_id": item["source_id"], "display": item["display"], "reason": "缺少可比条件或为定性结果", "missing_fields": missing})
            continue
        grouped[(item["code_system"], item["code"], item["unit"], item["method"], item["specimen_type"])].append(item)
    series = []
    for (code_system, code, unit, method, specimen_type), items in sorted(grouped.items()):
        points = sorted(items, key=lambda item: (item["collected_at"], item["source_id"]))
        values = [Decimal(item["value_num"]) for item in points]
        references = {(item.get("reference_low"), item.get("reference_high"), item.get("reference_text")) for item in points}
        same_sample_time = len({item["collected_at"] for item in points}) != len(points)
        comparable = len(points) > 1 and not same_sample_time
        series.append(
            {
                "code_system": code_system,
                "code": code,
                "display": points[-1]["display"],
                "unit": unit,
                "method": method,
                "specimen_type": specimen_type,
                "points": [{key: item.get(key) for key in ("source_id", "value_num", "collected_at", "reference_low", "reference_high", "reference_text", "flag")} for item in points],
                "comparable": comparable,
                "comparison_status": "exact_source_match" if comparable else "duplicate_sample_times" if same_sample_time else "insufficient_points",
                "absolute_change": format(values[-1] - values[0], "f") if comparable else None,
                "reference_range_changed": len(references) > 1,
            }
        )
    truncated = any(item["source"] == "结构化检验指标" for item in context.get("truncated_sources", []))
    return {
        "series": series,
        "excluded_from_numeric_comparison": excluded,
        "history_truncated": truncated,
        "unit_conversion_performed": False,
        "medical_thresholds_applied": False,
        "limitations": [
            "只比较已审核且编码、原始单位、方法及标本完全一致的数值；不作单位换算或临床因果推断",
            "缺少方法或标本时保留原始事实并交实验室核实",
            "参考区间变化保留逐项区间；数值变化不等同于病情改善或恶化",
        ],
    }


def critical_value_workflow(context: dict) -> dict:
    """Expose original critical-value lifecycle states without changing or closing alerts."""
    labels = {1: "待通知", 2: "已通知待确认", 3: "已确认待处理", 4: "已记录处理"}
    return {
        "source": "existing_lab_critical_workflow",
        "reports": [{**item, "workflow_state": labels.get(item["critical_status"], "未知状态")} for item in context.get("reviewed_lab_reports", []) if item.get("critical_status")],
        "actions_executed": [],
        "note": "此工具仅展示既有危急值状态，通知、确认与处置仍在原业务流程完成",
    }
