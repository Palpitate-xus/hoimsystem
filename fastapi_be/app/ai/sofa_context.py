"""Freeze small verified bindings; expand complete SOFA facts only after authorization."""

from typing import Literal

from fastapi import HTTPException
from pydantic import Field

from app.ai.sofa_contract import RULE_ID, SofaSource, hash_content
from app.inpatient_observations import canonical_json, canonical_uuid, utc_text
from app.inpatient_support_common import StrictInput

REFERENCE_KEYS = {"sofa_assessment_id", "sofa_change_assessment_id"}


class SofaBinding(StrictInput):
    schema_version: Literal["sofa_context_binding_v1"]
    kind: Literal["daily", "change"]
    patient_id: int = Field(ge=1, le=2147483647)
    admission_id: str
    assessment_id: str
    source_id: str
    content_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    governance_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    projection_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    rule_id: Literal["sofa1_native_observed_v1"]
    recipe_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    policy_digest: str = Field(pattern=r"^[a-f0-9]{64}$")


def selection(references):
    if not isinstance(references, dict) or set(references) - REFERENCE_KEYS - {"question"} or len(REFERENCE_KEYS & references.keys()) != 1:
        raise HTTPException(422, "SOFA仅接受一件日评估或一件变化核实引用，不接受混用、原量、分数或临床事实覆盖")
    if "question" in references and (not isinstance(references["question"], str) or len(references["question"]) > 12000):
        raise HTTPException(422, "SOFA问题最多12000字。")
    key = next(iter(REFERENCE_KEYS & references.keys()))
    try:
        identifier = canonical_uuid(references[key])
    except (ValueError, TypeError, AttributeError) as exc:
        raise HTTPException(422, "SOFA来源须为规范UUID") from exc
    return ("daily" if key == "sofa_assessment_id" else "change"), identifier


def _source(current, kind):
    if kind == "daily":
        source_type = SofaSource
    else:
        from app.ai.sofa_contract import SofaChangeSource

        source_type = SofaChangeSource
    source = source_type.model_validate(current["specialist_source"]).model_dump(mode="json")
    if hash_content(source) != current["projection_hash"]:
        raise HTTPException(409, "完整SOFA公开原件与冻结摘要不一致")
    return source


def binding(current, kind):
    source = _source(current, kind)
    rule_source = source if kind == "daily" else source["current"]
    result = {
        "schema_version": "sofa_context_binding_v1",
        "kind": kind,
        "patient_id": current["patient_id"],
        "admission_id": current["admission_id"],
        "assessment_id": current["assessment_id" if kind == "daily" else "change_assessment_id"],
        "source_id": source["source_id"],
        "content_hash": source["content_hash"],
        "governance_hash": source["assessment_governance_hash"],
        "projection_hash": current["projection_hash"],
        "rule_id": RULE_ID,
        "recipe_digest": rule_source["recipe_digest"],
        "policy_digest": rule_source["policy_digest"],
    }
    return SofaBinding.model_validate(result).model_dump(mode="json")


def _load(db, user, patient_id, admission_id, kind, identifier, *, current=True):
    if kind == "daily":
        from app.ai.sofa_sources import assessment_detail, authorize_assessment

        value = authorize_assessment(db, user, patient_id, admission_id, identifier) if current else assessment_detail(db, identifier, audit_only=True)
    else:
        from app.ai.sofa_change_sources import authorize_change, change_detail

        value = authorize_change(db, user, patient_id, admission_id, identifier) if current else change_detail(db, identifier, audit_only=True)
    if value["patient_id"] != patient_id or value["admission_id"] != admission_id:
        raise HTTPException(409, "SOFA完整原件不属于冻结原患者及住院")
    return value


def sofa_context(db, user, patient_id, admission_id, references):
    from app.ai.context import ContextBundle
    from app.ai.models import utcnow
    from app.models import Admission

    kind, identifier = selection(references)
    current = _load(db, user, patient_id, admission_id, kind, identifier)
    bound = binding(current, kind)
    source = _source(current, kind)
    indexes = [(source["source_id"], "clinical_record", "完整24小时原件与当前医生回顾核实")]
    if kind == "daily":
        indexes.append((source["rule_profile_source_id"], "rule", "已审核本地SOFA-1原单位和持续时间实施规则"))
    else:
        indexes.append((source["current"]["rule_profile_source_id"], "rule", "两日共同审核的SOFA-1实施规则"))
        indexes.append((source["current"]["source_id"], "clinical_record", "当前完整24小时原评估"))
        indexes.append((source["infection"]["source_id"], "clinical_record", "医生实际感染原声明与当前归因核实"))
        if source["baseline"]["mode"] == "observed":
            indexes.append((source["baseline"]["source"]["source_id"], "clinical_record", "独立授权的真实完整24小时基线"))
    evidence = [{"source_id": identifier, "kind": category, "title": title, "content": canonical_json({"sofa_binding": bound})} for identifier, category, title in indexes]
    admission = db.get(Admission, admission_id)
    return ContextBundle(
        data={
            "scope": "inpatient_sofa1_assessment" if kind == "daily" else "inpatient_sofa1_change",
            "sofa_binding": bound,
            "selected_sources": {"sofa_assessment_id" if kind == "daily" else "sofa_change_assessment_id": identifier},
            "missing_data": ["当前回顾性医生核实；原资料截止与当前声明签署时刻分别保留，不构成历史风险预测", "本地SOFA-1实施政策和原单位边界须结合来源核对；未提供自动脓毒症诊断、概率或治疗"],
            "snapshot_time": utc_text(utcnow()),
        },
        evidence=evidence,
        department_ids={admission.department_id} if admission.department_id else set(),
    )


def expand_context(db, context, *, user=None, current=False):
    """Caller authorizes the run first; current=True also rebuilds every source chain."""
    try:
        bound = SofaBinding.model_validate(context["sofa_binding"])
        canonical_uuid(bound.assessment_id)
        canonical_uuid(bound.admission_id)
        value = _load(db, user, bound.patient_id, bound.admission_id, bound.kind, bound.assessment_id, current=current)
        if binding(value, bound.kind) != bound.model_dump(mode="json"):
            raise ValueError("frozen root binding differs from complete original")
        source_key, assessment_key = ("sofa_source", "sofa_assessment") if bound.kind == "daily" else ("sofa_change_source", "sofa_change_assessment")
        return {**context, source_key: _source(value, bound.kind), assessment_key: value}
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError, RecursionError) as exc:
        raise HTTPException(409, "SOFA任务引用、完整原件或公开投影绑定校验失败") from exc


def authorize_sofa_snapshot(db, user, context, patient_id, admission_id):
    try:
        bound = SofaBinding.model_validate(context["sofa_binding"])
        if bound.patient_id != patient_id or bound.admission_id != admission_id:
            raise ValueError("run scope differs from frozen SOFA binding")
        # Super may inspect intact frozen originals; execution never uses this bypass.
        expand_context(db, context, user=user, current=user.user_role != "super_admin")
    except (HTTPException, ValueError, TypeError, KeyError, AttributeError) as exc:
        raise HTTPException(403, "SOFA原件集合、父件、规则、签署资格或当前照护权限已变化，不能继续读取原核对结果") from exc
