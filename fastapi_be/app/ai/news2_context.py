"""Bind an explicit reviewed NEWS2 selection to the same immutable inpatient window."""

import copy

from fastapi import HTTPException

from app.ai.observation_windows import canonical_json, observation_context


def _frozen_assessment(current, patient):
    from app.ai.context import minimize_identifiers

    frozen = {key: current[key] for key in ("assessment_id", "patient_id", "admission_id", "window_id", "status", "revision", "source_id", "content_hash", "snapshot")}
    frozen = copy.deepcopy(frozen)
    # Only explicitly free text is minimized. Quantities, units, timestamps,
    # UUIDs and original/governance hashes remain the server-owned originals.
    free_text = {
        "age_basis_note",
        "pregnancy_basis_note",
        "blood_gas_reference",
        "clinical_decision_reference",
        "note",
        "oxygen_device",
        "review_note",
        "rationale",
        "evidence_reference",
        "implementation_terms_reference",
        "revoke_reason",
    }

    def visit(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if key in free_text and isinstance(item, str):
                    value[key] = minimize_identifiers(item, patient)
                else:
                    visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)

    visit(frozen)
    return frozen


def news2_context(db, user, patient_id, admission_id, references):
    from app.ai.news2_contract import News2Source
    from app.ai.news2_sources import authorize_assessment
    from app.models import Patient

    if not isinstance(references, dict) or set(references) - {"observation_window_id", "news2_assessment_id", "question"}:
        raise HTTPException(422, "NEWS2只接受原住院窗口和已核实评估来源，不接受客户端测量值或适用性覆盖")
    if not references.get("news2_assessment_id"):
        raise HTTPException(422, "请选择明确的NEWS2点测与适用性评估来源")
    bundle = observation_context(db, user, patient_id, admission_id, {key: value for key, value in references.items() if key != "news2_assessment_id"})
    window = bundle.data["observation_window"]
    current = authorize_assessment(db, user, patient_id, admission_id, references["news2_assessment_id"], window_id=window["window_id"])
    source = News2Source.model_validate(current["specialist_source"]).model_dump(mode="json")
    if source["window_content_hash"] != window["content_hash"] or source["window_source_id"] != window["source_id"]:
        raise HTTPException(409, "NEWS2评估与当前所选冻结窗口不一致")
    frozen = _frozen_assessment(current, db.get(Patient, patient_id))
    bundle.data["news2_source"] = source
    bundle.data["news2_assessment"] = frozen
    bundle.data["selected_sources"]["news2_assessment_id"] = current["assessment_id"]
    bundle.evidence.append(
        {"source_id": source["source_id"], "kind": "clinical_record", "title": "明确原点测与人工适用性核实，非临床效果验证", "observed_at": source["observed_at"], "content": canonical_json(frozen)}
    )
    bundle.evidence.append(
        {
            "source_id": source["rule_profile_source_id"],
            "kind": "rule",
            "title": "已发布的NEWS2原算法与固定输入策略",
            "content": canonical_json({key: source[key] for key in ("rule_id", "recipe_digest", "rule_profile_id", "rule_profile_content_hash", "rule_profile_governance_hash")}),
        }
    )
    return bundle


def authorize_news2_snapshot(db, user, context, patient_id, admission_id):
    """Retain Super frozen audits; ordinary reads must still match active sources."""
    if user.user_role == "super_admin":
        return
    source = context.get("news2_source")
    if not source:
        return
    try:
        current = news2_context(db, user, patient_id, admission_id, {"observation_window_id": source["window_id"], "news2_assessment_id": source["assessment_id"]})
        if current.data["news2_source"] != source or current.data["news2_assessment"] != context.get("news2_assessment"):
            raise ValueError("NEWS2 source changed")
    except (HTTPException, ValueError, TypeError, KeyError) as exc:
        raise HTTPException(403, "原NEWS2评估、规则审核、窗口或当前照护权限已变化，不能继续读取旧评分") from exc
