"""Bound selected bedside originals to a current, explicitly retrospective review."""

import copy

from fastapi import HTTPException

from app.ai.qsofa_contract import QsofaSource
from app.inpatient_laboratory import hash_content
from app.inpatient_observations import canonical_json, utc_text

NOTE_FIELDS = {"age_basis_note", "care_setting_basis_note", "infection_basis_note", "gcs_review_note"}


def _pick(value, keys):
    return {key: copy.deepcopy(value[key]) for key in keys if key in value}


def _compact_point(point):
    if point is None:
        return None
    result = copy.deepcopy(point)
    result["payload"] = {"measurements": _pick(result["payload"]["measurements"], ("respiratory_rate", "systolic_bp"))}
    result.pop("revoke_reason", None)
    return result


def _compact_gcs(item):
    if item is None:
        return None
    result = copy.deepcopy(item)
    payload = result["payload"]
    result["provenance_note_hashes"] = {"same_exam_basis_note": hash_content(payload["same_exam_basis_note"]) if payload["same_exam_basis_note"] is not None else None}
    result["payload"] = _pick(payload, ("components", "anchor_point", "same_exam_confirmed"))
    result["anchor_point_snapshot"] = _compact_point(result.get("anchor_point_snapshot"))
    result.pop("revoke_reason", None)
    return result


def frozen_assessment_projection(current):
    """Omitted text remains bound by full original hashes and current-source checks."""
    result = _pick(
        current,
        (
            "assessment_id",
            "patient_id",
            "admission_id",
            "window_id",
            "window_content_hash",
            "point_id",
            "point_content_hash",
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
    attestation = snapshot["attestation"]
    source = current["specialist_source"]
    snapshot["provenance_note_hashes"] = {key: hash_content(attestation[key]) for key in sorted(NOTE_FIELDS) if attestation.get(key) is not None}
    snapshot["provenance_note_hashes"].update({key: source[key] for key in ("scope_evidence_hash", "gcs_review_evidence_hash")})
    for key in NOTE_FIELDS:
        attestation.pop(key, None)
    snapshot["point"] = _compact_point(snapshot["point"])
    snapshot["gcs_observation"] = _compact_gcs(snapshot.get("gcs_observation"))
    snapshot["gcs_group"] = [_compact_gcs(item) for item in snapshot["gcs_group"]]
    snapshot["rule_profile"] = _pick(
        snapshot["rule_profile"],
        (
            "rule_profile_id",
            "source_id",
            "content_hash",
            "governance_hash",
            "rule_id",
            "recipe_digest",
            "policy_digest",
            "status",
            "revision",
            "schema_version",
            "published_at",
            "created_by",
            "created_at",
        ),
    )
    result["context_projection"] = "qsofa_review_v1"
    result["snapshot"] = snapshot
    return result


def qsofa_context(db, user, patient_id, admission_id, references):
    from app.ai.context import ContextBundle
    from app.ai.models import utcnow
    from app.ai.qsofa_sources import authorize_assessment
    from app.models import Admission

    if (
        not isinstance(references, dict)
        or set(references) - {"observation_window_id", "qsofa_assessment_id", "question"}
        or not references.get("qsofa_assessment_id")
        or not references.get("observation_window_id")
    ):
        raise HTTPException(422, "qSOFA仅接受明确原住院窗口和医生当前回顾核实的评估引用，不接受客户端测量或临床事实覆盖")
    if "question" in references and (not isinstance(references["question"], str) or len(references["question"]) > 12000):
        raise HTTPException(422, "qSOFA问题须为最多12000字文本，不能替代原量或医生核实")
    current = authorize_assessment(db, user, patient_id, admission_id, references["qsofa_assessment_id"], window_id=references["observation_window_id"])
    source = QsofaSource.model_validate(current["specialist_source"]).model_dump(mode="json")
    frozen = frozen_assessment_projection(current)
    window = frozen["snapshot"]["window_binding"]
    if source["window_content_hash"] != window["content_hash"] or source["window_source_id"] != window["source_id"]:
        raise HTTPException(409, "qSOFA原评估与所选窗口绑定不一致")
    indexes = [
        (source["source_id"], "clinical_record", "当前回顾性临床核实，原完整件另存", "context.qsofa_assessment"),
        (source["window_source_id"], "clinical_record", "原窗口绑定与资料截止", "context.observation_window_binding"),
        (source["rule_profile_source_id"], "rule", "已审核固定qSOFA与明确输入策略", "context.qsofa_assessment.snapshot.rule_profile"),
        (source["point_source_id"], "clinical_record", "原床旁点测", "context.qsofa_assessment.snapshot.point"),
    ]
    if source["gcs"] is not None:
        indexes.append((source["gcs"]["source_id"], "clinical_record", "原GCS分项与明确同次检查关联", "context.qsofa_source.gcs"))
    evidence = [{"source_id": identifier, "kind": kind, "title": title, "content": canonical_json({"context_path": path})} for identifier, kind, title, path in indexes]
    admission = db.get(Admission, admission_id)
    return ContextBundle(
        data={
            "scope": "inpatient_qsofa_assessment",
            "qsofa_source": source,
            "qsofa_assessment": frozen,
            "observation_window_binding": window,
            "selected_sources": {"observation_window_id": source["window_id"], "qsofa_assessment_id": source["assessment_id"]},
            "missing_data": ["医生现在复核原观察时的临床范围，不证明原as_of时已知感染或可进行历史风险预测", "本核对不是单一脓毒症筛查，未达三项阈值不排除脓毒症，也不提供诊断或概率"],
            "snapshot_time": utc_text(utcnow()),
        },
        evidence=evidence,
        department_ids={admission.department_id} if admission.department_id else set(),
    )


def authorize_qsofa_snapshot(db, user, context, patient_id, admission_id):
    if user.user_role == "super_admin":
        return
    try:
        source = context["qsofa_source"]
        current = qsofa_context(db, user, patient_id, admission_id, {"observation_window_id": source["window_id"], "qsofa_assessment_id": source["assessment_id"]})
        if current.data["qsofa_source"] != source or current.data["qsofa_assessment"] != context.get("qsofa_assessment"):
            raise ValueError("qSOFA source changed")
    except (HTTPException, ValueError, TypeError, KeyError) as exc:
        raise HTTPException(403, "原qSOFA评估、点测、GCS、同次关联、规则、签署身份或当前照护权限已变化，不能继续读取旧核对结果") from exc
