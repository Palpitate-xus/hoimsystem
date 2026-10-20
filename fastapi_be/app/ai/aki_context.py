"""Compact original AKI evidence without repeating a whole window or clinical notes."""

import copy

from fastapi import HTTPException

from app.ai.aki_contract import AkiSource
from app.inpatient_laboratory import hash_content
from app.inpatient_observations import canonical_json, utc_text

NOTE_FIELDS = {"age_basis_note", "creatinine_review_note", "baseline_review_note", "weight_basis_note", "rrt_basis_note"}


def _pick(value, keys):
    return {key: copy.deepcopy(value[key]) for key in keys if key in value}


def _compact_lab(item):
    if item is None:
        return None
    result = _pick(
        item,
        (
            "lab_source_id",
            "patient_id",
            "admission_id",
            "observation_id",
            "mapping_id",
            "schema_version",
            "raw_original_hash",
            "mapping_content_hash",
            "collected_at_utc",
            "registered_at",
            "available_at",
            "source_id",
            "content_hash",
            "governance_hash",
            "identity_hash",
            "conflict",
            "status",
            "revision",
            "assessment_projection",
        ),
    )
    result["mapping_current"] = _pick(item["mapping_current"], ("mapping_id", "source_id", "content_hash", "governance_hash", "status", "revision"))
    frozen = _pick(
        item["snapshot"],
        (
            "lab_source_id",
            "patient_id",
            "admission_id",
            "observation_id",
            "mapping_id",
            "schema_version",
            "raw_original_hash",
            "mapping_content_hash",
            "collected_at_utc",
            "registered_at",
            "available_at",
            "source_namespace",
            "mapping",
            "original",
        ),
    )
    result["snapshot"] = frozen
    mapping = frozen["mapping"]
    frozen["mapping"] = _pick(mapping, ("mapping_id", "source_id", "content_hash", "governance_hash", "source_namespace", "signature", "analyte_key", "status", "revision", "published_at"))
    original = frozen["original"]
    original["observation"] = _pick(
        original["observation"], ("observation_id", "lab_result_id", "code_system", "code", "value_num", "unit", "method", "specimen_type", "collected_at", "time_basis", "value_representation")
    )
    original["report"] = _pick(original["report"], ("lab_result_id", "lab_order_id", "sample_id", "audit_status", "auditor_id", "audit_time", "time_basis"))
    original["order"] = _pick(original["order"], ("lab_order_id", "patient_id", "status", "sample_status", "time_basis"))
    return result


def frozen_assessment_projection(current):
    """The original full hash still binds omitted free text; never truncate quantities."""
    result = _pick(
        current,
        (
            "assessment_id",
            "patient_id",
            "admission_id",
            "window_id",
            "window_content_hash",
            "rule_profile_id",
            "rule_profile_content_hash",
            "recipe_digest",
            "evaluation_at",
            "created_by",
            "created_at",
            "schema_version",
            "status",
            "revision",
            "source_id",
            "content_hash",
            "governance_hash",
        ),
    )
    snapshot = copy.deepcopy(current["snapshot"])
    snapshot["rule_profile"] = _pick(snapshot["rule_profile"], ("rule_profile_id", "rule_id", "recipe_digest", "source_id", "content_hash", "governance_hash", "status", "revision", "published_at"))
    attestation = snapshot["attestation"]
    snapshot["provenance_note_hashes"] = {key: hash_content(attestation[key]) for key in sorted(NOTE_FIELDS) if attestation.get(key) is not None}
    for key in NOTE_FIELDS:
        attestation.pop(key, None)
    for key in ("index_creatinine", "comparison_48h", "baseline_creatinine"):
        snapshot[key] = _compact_lab(snapshot.get(key))
    point = snapshot.get("weight_point")
    if point is not None:
        point["payload"] = {"measurements": _pick(point["payload"]["measurements"], ("body_weight",))}
    for item in snapshot["urine_intervals"]:
        item["payload"] = _pick(item["payload"], ("volume_ml", "absent_reason", "collection_completeness", "patient_total"))
    snapshot["urine_intervals"] = [
        _pick(item, ("interval_id", "patient_id", "admission_id", "source_id", "content_hash", "governance_hash", "start_at", "end_at", "recorded_at", "payload"))
        for item in snapshot["urine_intervals"]
    ]
    result["context_projection"] = "aki_review_v1"
    result["snapshot"] = snapshot
    return result


def aki_context(db, user, patient_id, admission_id, references):
    from app.ai.aki_sources import authorize_assessment
    from app.ai.context import ContextBundle
    from app.ai.models import utcnow
    from app.models import Admission

    if (
        not isinstance(references, dict)
        or set(references) - {"observation_window_id", "aki_assessment_id", "question"}
        or not references.get("aki_assessment_id")
        or not references.get("observation_window_id")
    ):
        raise HTTPException(422, "AKI规则仅接受明确原住院窗口和已核实评估引用，不接受客户端数值、基线或RRT覆盖")
    if "question" in references and (not isinstance(references["question"], str) or len(references["question"]) > 12000):
        raise HTTPException(422, "AKI问题须为最多12000字文本，不能作为原测量或人工适用性事实")
    current = authorize_assessment(db, user, patient_id, admission_id, references["aki_assessment_id"], window_id=references["observation_window_id"])
    source = AkiSource.model_validate(current["specialist_source"]).model_dump(mode="json")
    frozen = frozen_assessment_projection(current)
    window = frozen["snapshot"]["window_binding"]
    if source["window_content_hash"] != window["content_hash"] or source["window_source_id"] != window["source_id"]:
        raise HTTPException(409, "AKI原评估与所选窗口绑定不一致")
    evidence = [
        {
            "source_id": source["source_id"],
            "kind": "clinical_record",
            "title": "明确原资料与人工适用性核实；完整原件另存，不代表临床效果验证",
            "observed_at": source["evaluation_at"],
            "content": canonical_json({"context_path": "context.aki_assessment"}),
        },
        {
            "source_id": source["window_source_id"],
            "kind": "clinical_record",
            "title": "原冻结窗绑定；本任务仅计算明确所选资料",
            "observed_at": source["as_of"],
            "content": canonical_json({"context_path": "context.observation_window_binding"}),
        },
        {
            "source_id": source["rule_profile_source_id"],
            "kind": "rule",
            "title": "已审核固定KDIGO成人判据及明确输入策略",
            "content": canonical_json({"context_path": "context.aki_assessment.snapshot.rule_profile"}),
        },
    ]
    unique = {item["source_id"] for item in evidence}
    members = [(key, source[key]) for key in ("index_creatinine", "comparison_48h", "baseline_creatinine", "weight")]
    members.extend((f"urine_intervals[{index}]", item) for index, item in enumerate(source["urine_intervals"]))
    for path, item in members:
        if item is not None and item["source_id"] not in unique:
            unique.add(item["source_id"])
            evidence.append(
                {
                    "source_id": item["source_id"],
                    "kind": "clinical_record",
                    "title": "原资料索引",
                    "content": canonical_json({"context_path": f"context.aki_source.{path}"}),
                }
            )
    admission = db.get(Admission, admission_id)
    return ContextBundle(
        data={
            "scope": "inpatient_aki_assessment",
            "aki_source": source,
            "aki_assessment": frozen,
            "observation_window_binding": window,
            "selected_sources": {"observation_window_id": source["window_id"], "aki_assessment_id": source["assessment_id"]},
            "missing_data": ["只核对所选原资料和明确区间，不能据此排除未观察的AKI或声称完整病程最高分期", "年龄、肌酐用途、旧基线和RRT是明确人工声明，未独立验证其临床真实性"],
            "snapshot_time": utc_text(utcnow()),
        },
        evidence=evidence,
        department_ids={admission.department_id} if admission.department_id else set(),
    )


def authorize_aki_snapshot(db, user, context, patient_id, admission_id):
    if user.user_role == "super_admin":
        return
    try:
        source = context["aki_source"]
        current = aki_context(db, user, patient_id, admission_id, {"observation_window_id": source["window_id"], "aki_assessment_id": source["assessment_id"]})
        if current.data["aki_source"] != source or current.data["aki_assessment"] != context.get("aki_assessment"):
            raise ValueError("AKI source changed")
    except (HTTPException, ValueError, TypeError, KeyError) as exc:
        raise HTTPException(403, "原AKI评估、基线、尿量、规则、签署身份或当前照护权限已变化，不能继续读取旧分期") from exc
