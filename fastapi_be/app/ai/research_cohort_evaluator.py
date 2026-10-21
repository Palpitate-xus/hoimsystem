"""Deterministic three-valued recorded criteria, never a clinical conclusion.

No SQL, inferred diagnosis, cohort expansion, timezone repair or LLM execution.
Text absence only describes the recorded string; it is not absence of illness.
"""

import datetime as dt

from fastapi import HTTPException

from app.ai.research_cohort_contract import CohortCriteria, canonical_json
from app.ai.research_cohort_sources import hash_content

MAX_EVALUATION_BYTES = 8 * 1024 * 1024

TRUTH = {True: "true", False: "false", None: "unknown"}
LIMITATIONS = [
    "仅针对项目明确患者集合和声明的记录族/字段；不是全院或完整临床数据集。",
    "三值结果只说明原记录是否符合显式谓词，不证明疾病不存在、临床效果或研究因果。",
    "旧naive时间仅按原日历字面比较，时区和当时可得性未知；缺项和父关联矛盾保持未知。",
    "逐字引文保留BOM、CRLF和Unicode码点；标识最小化不等于匿名，不自动导出。",
]


def _all(values):
    return False if False in values else None if None in values else True


def _any(values):
    return True if True in values else None if None in values else False


def _atom(node, record):
    raw = record["original"]
    value = raw[node.field]
    evidence = {
        "family": node.family,
        "record_id": record["record_id"],
        "field": node.field,
        "original_hash": hash_content(raw),
        "field_hash": hash_content(value),
        "start": None,
        "end": None,
        "quote": None,
        "recorded_value": None if node.op == "recorded_text_contains" else value,
    }
    if record["window_status"] == "unknown_clock" or record["parent_binding"]["status"] != "patient_bound":
        return None, {**evidence, "reason": "record_scope_or_parent_unknown"}
    if value is None:
        return None, {**evidence, "reason": "original_field_missing"}
    if node.op == "recorded_scalar_equal":
        result = value == node.expected
    elif node.op == "recorded_date_compare":
        actual = dt.date.fromisoformat(value[:10])
        wanted = dt.date.fromisoformat(node.expected)
        result = actual < wanted if node.comparison == "before" else actual > wanted if node.comparison == "after" else actual == wanted
    else:
        start = value.find(node.literal)
        result = start >= 0
        # Do not send the whole raw clinical field merely to prove presence.
        # For absence, only its opaque source hash is public, not its text.
        evidence["recorded_value"] = None
        if result:
            evidence.update(start=start, end=start + len(node.literal), quote=value[start : start + len(node.literal)])
    return result, {**evidence, "reason": "recorded_predicate_only"}


def evaluate_criteria(collection, values):
    criteria = values if isinstance(values, CohortCriteria) else CohortCriteria.model_validate(values)
    allowed = collection["scope_original"]["payload"]["data_families"]
    outcomes = []
    construction_bytes = 0
    for patient_id in collection["scope_original"]["payload"]["patient_ids"]:
        records = [r for r in collection["records"] if r["patient_id"] == patient_id]
        leaves = []

        def visit(node, path):
            nonlocal construction_bytes
            if node.op in {"all", "any"}:
                results = [visit(child, f"{path}.{index}") for index, child in enumerate(node.children)]
                return _all(results) if node.op == "all" else _any(results)
            if node.op == "not":
                result = visit(node.child, path + ".not")
                return None if result is None else not result
            if node.family not in allowed:
                raise ValueError("Predicate family is outside the explicit research scope")
            candidates = [r for r in records if r["family"] == node.family]
            results, evidence = [], []
            for record in candidates:
                result, proof = _atom(node, record)
                results.append(result)
                item = {**proof, "truth": TRUTH[result]}
                construction_bytes += len(canonical_json(item).encode("utf-8"))
                if construction_bytes > MAX_EVALUATION_BYTES:
                    raise HTTPException(413, "完整三值证据构建超过8MiB，未先构造无界重复引用")
                evidence.append(item)
            # Neither empty universals nor missing documents become true.
            result = None if not candidates else _any(results) if node.quantifier == "any_record" else _all(results)
            leaves.append(
                {"path": path, "predicate": node.model_dump(), "truth": TRUTH[result], "reason": "no_recorded_members" if not candidates else "whole_declared_recorded_family", "evidence": evidence}
            )
            return result

        result = visit(criteria.root, "root")
        outcomes.append({"patient_id": patient_id, "truth": TRUTH[result], "interpretation": "recorded_criteria_only_not_clinical_eligibility", "leaves": leaves})
    result = {"schema_version": "research_recorded_evaluation_v1", "criteria_hash": hash_content(criteria.model_dump()), "outcomes": outcomes, "limitations": list(LIMITATIONS)}
    if len(canonical_json(result).encode("utf-8")) > MAX_EVALUATION_BYTES:
        raise HTTPException(413, "完整三值研究证据超过8MiB，未裁剪原成员")
    return result
