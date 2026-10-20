"""One explicitly selected original for handover, with private provenance kept local."""

import copy

from fastapi import HTTPException

from app.inpatient_laboratory import hash_content
from app.inpatient_observations import canonical_json, utc_text
from app.inpatient_support_common import authorize_source

SOURCE_KEYS = frozenset({"support_source_id", "support_source_kind"})
SOURCE_FEATURE = 47
SOURCE_SCOPE = "inpatient_support_original"
MISSING_DATA = (
    "仅所选一条原资料及其明确关联，不代表完整交班、24小时最差状态或完整SOFA",
    "原件记录与医生当前核实不代替独立临床验证；不提供脓毒症确诊、排除、概率或自动治疗",
)


def source_evidence(source):
    return {"source_id": source["source_id"], "kind": "clinical_record", "title": "明确选择的原器官支持资料", "content": canonical_json({"context_path": "context.support_source"})}


def pick(value, fields):
    return {key: copy.deepcopy(value[key]) for key in fields if key in value}


def header(source):
    return pick(source, ("source_id", "content_hash", "governance_hash", "support_source_id", "kind", "schema_version", "event_at", "recorded_at"))


def laboratory_facts(source):
    snapshot = source["snapshot"]
    return {
        **pick(source, ("source_id", "content_hash", "lab_source_id", "collected_at_utc", "registered_at", "available_at")),
        "analyte_key": snapshot["mapping"]["analyte_key"],
        "original": pick(snapshot["original"]["observation"], ("value_kind", "value_num", "unit")),
        "qualitative_text_provided": False,
    }


def point_facts(source, measurement):
    return {**pick(source, ("source_id", "content_hash", "observation_id", "observed_at", "recorded_at")), "measurement": copy.deepcopy(source["payload"]["measurements"][measurement])}


def respiratory_facts(source):
    return {**header(source), "facts": pick(source["payload"], ("start_at", "verified_until_at", "ended_at", "delivery_mode", "continuity_confirmed"))}


def public_source(source):
    """Only fixed native quantities, clocks, typed states and technical references leave."""
    kind, payload, references = source["kind"], source["payload"], source["reference_snapshots"]
    result = {
        **header(source),
        "source_verification": "explicit_human_record_not_independently_verified",
        "clinical_review_signed": source["author_qualification"].get("clinical_review_signed") is True,
        "historical_prediction": False,
        "quantity_conversion_performed": False,
        "sofa_provided": False,
        "diagnosis_provided": False,
        "probability_provided": False,
        "complete_handover_provided": False,
    }
    if kind == "map":
        result["facts"] = pick(payload, ("observed_at", "map", "measurement_method"))
    elif kind == "respiratory_support":
        result["facts"] = respiratory_facts(source)["facts"]
    elif kind == "arterial_pair":
        result["facts"] = pick(payload, ("arterial_sample_confirmed", "same_sampling_state_confirmed", "fio2_applicability_confirmed"))
        result["reference_facts"] = {"pao2": laboratory_facts(references["pao2"]), "fio2": point_facts(references["fio2"], "fio2"), "support": respiratory_facts(references["support"])}
    elif kind == "vasoactive":
        result["facts"] = pick(payload, ("start_at", "verified_until_at", "ended_at", "continuity_confirmed"))
        result["facts"]["dose_input"] = pick(payload["dose_input"], ("mode", "rate", "concentration", "pump_rate", "weight_applicability_confirmed"))
        result["reference_facts"] = {
            "drug_mapping": pick(references["drug_mapping"], ("mapping_id", "source_id", "content_hash", "governance_hash", "drug_key", "active_moiety_basis")),
            "weight": point_facts(references["weight"], "body_weight") if references.get("weight") else None,
            "origin": pick(references["origin"], ("source_id", "content_hash", "administration_id", "time_basis")) if references.get("origin") else None,
        }
        # Stable stream membership is disclosed only as a technical digest.
        result["stream_identity_hash"] = hash_content(payload["stream_identity"])
    else:
        result["facts"] = pick(payload, ("infection_status", "clinical_scope_start_at", "clinical_scope_end_at", "first_suspected_at", "onset_at", "onset_time_basis"))
        evidence = []
        for item in references["evidence"]:
            if item.get("schema_version") == "diagnosis_review_evidence_v1":
                evidence.append({**pick(item, ("source_id", "content_hash", "review_id", "time_basis")), "certainty": item["facts"]["review"]["certainty"], "diagnosis_text_provided": False})
            else:
                evidence.append(laboratory_facts(item))
        result["reference_facts"] = {"evidence": evidence}
    return result


def support_context(db, user, patient_id, admission_id, references):
    from app.ai.context import ContextBundle
    from app.ai.models import utcnow
    from app.models import Admission

    if not isinstance(references, dict) or set(references) - (SOURCE_KEYS | {"question"}) or not all(references.get(key) for key in SOURCE_KEYS):
        raise HTTPException(422, "单条支持资料整理须同时选择明确原资料标识与类型，不接受客户端测量或其他原件覆盖")
    if "question" in references and (not isinstance(references["question"], str) or len(references["question"]) > 12000):
        raise HTTPException(422, "补充问题须为最多12000字文本，不能成为原事实或覆盖原量")
    original = authorize_source(db, user, patient_id, admission_id, references["support_source_kind"], references["support_source_id"])
    source = public_source(original)
    admission = db.get(Admission, admission_id)
    return ContextBundle(
        data={
            "scope": SOURCE_SCOPE,
            "support_source": source,
            "support_source_provenance": original,
            "support_public_hash": hash_content(source),
            "selected_sources": {key: references[key] for key in sorted(SOURCE_KEYS)},
            "missing_data": list(MISSING_DATA),
            "snapshot_time": utc_text(utcnow()),
        },
        evidence=[source_evidence(source)],
        department_ids={admission.department_id} if admission.department_id else set(),
    )


def authorize_support_snapshot(db, user, context, patient_id, admission_id):
    if user.user_role == "super_admin":
        return
    try:
        source = context["support_source"]
        current = support_context(db, user, patient_id, admission_id, {"support_source_id": source["support_source_id"], "support_source_kind": source["kind"]})
        if any(context.get(key) != current.data[key] for key in ("scope", "missing_data", "support_source", "support_source_provenance", "support_public_hash", "selected_sources")):
            raise ValueError("Original organ-support context changed")
    except (HTTPException, ValueError, TypeError, KeyError) as exc:
        raise HTTPException(403, "原支持资料、当前依赖、明确关联、签署医生或当前原住院访问权限已变化；旧结果仅保留冻结审计") from exc


def outbound_support_payload(spec, data):
    context = data.get("context", {})
    if context.get("support_source") is None:
        return data
    try:
        if spec.number != SOURCE_FEATURE:
            raise ValueError("Wrong handover feature")
        original = context["support_source_provenance"]
        frozen = pick(
            original, ("support_source_id", "kind", "patient_id", "admission_id", "event_at", "recorded_at", "created_by", "schema_version", "payload", "reference_snapshots", "author_qualification")
        )
        if hash_content(frozen) != original["content_hash"] or hash_content(pick(original, ("status", "revision", "revoked_at", "revoked_by", "revoke_reason"))) != original["governance_hash"]:
            raise ValueError("Full original or governance hash differs")
        if (
            context["scope"] != SOURCE_SCOPE
            or context["missing_data"] != list(MISSING_DATA)
            or original["kind"] not in {"map", "respiratory_support", "arterial_pair", "vasoactive", "infection_episode"}
        ):
            raise ValueError("Wrong source scope or kind")
        public = public_source(original)
        if public != context["support_source"] or hash_content(public) != context["support_public_hash"]:
            raise ValueError("Public source projection differs from original")
        if data["input"]["support_source_id"] != public["support_source_id"] or data["input"]["support_source_kind"] != public["kind"]:
            raise ValueError("Explicit source references differ")
        evidence = data["evidence"]
        if not isinstance(evidence, list) or not evidence or evidence[0] != source_evidence(public) or any(item.get("kind") != "knowledge" for item in evidence[1:]):
            raise ValueError("Original source evidence differs")
    except (ValueError, TypeError, KeyError) as exc:
        from app.ai.gateway import AIExecutionError

        raise AIExecutionError("SUPPORT_BINDING_MISMATCH", "单条原支持资料与类型、公开原量或私有完整件绑定不一致") from exc
    # Preserve the actual reviewed knowledge and source evidence, never private
    # clinical notes, full parent chains, patient IDs or the free question.
    return {
        "context": {"scope": SOURCE_SCOPE, "support_source": public, "missing_data": list(MISSING_DATA)},
        "evidence": copy.deepcopy(evidence),
    }
