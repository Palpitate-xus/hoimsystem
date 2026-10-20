"""Separate current retrospective review of observed SOFA change and infection attribution."""

import json
import uuid
from typing import Annotated, Literal

from fastapi import HTTPException
from pydantic import Field

from app.ai import sofa_sources as daily
from app.ai.sofa_models import AISofaChangeAssessment
from app.inpatient_laboratory import hash_content
from app.inpatient_observations import canonical_json, explicit_utc, utc_text
from app.inpatient_support_common import StrictInput

SCHEMA_VERSION = "sofa1_change_assessment_v1"
MAX_PRIVATE_BYTES = 8 * 1024 * 1024
MAX_PUBLIC_BYTES = 6 * 1024 * 1024
ASSESSMENT_ROLES = daily.ASSESSMENT_ROLES
actor_current = daily.actor_current
authorize_scope = daily.authorize_scope
clinical_qualification = daily.clinical_qualification
AssessmentRevoke = daily.AssessmentRevoke
ChangeRevoke = AssessmentRevoke
FROZEN_FIELDS = ("change_assessment_id", "patient_id", "admission_id", "current_assessment_id", "baseline_assessment_id", "infection_source_id", "created_by", "schema_version")


def utcnow():
    return daily.utcnow()


class ChangeCandidatesRequest(StrictInput):
    patient_id: int = Field(ge=1, le=2147483647)
    admission_id: daily.CanonicalId
    current_assessment_id: daily.CanonicalId
    expected_current_content_hash: daily.HashText
    expected_current_projection_hash: daily.HashText


class ObservedBaseline(StrictInput):
    mode: Literal["observed"]
    assessment_id: daily.CanonicalId
    expected_content_hash: daily.HashText
    expected_projection_hash: daily.HashText


class ConditionalZeroBaseline(StrictInput):
    mode: Literal["conditional_zero"]
    no_known_preexisting_organ_dysfunction: bool
    preinfection_baseline_assumption_confirmed: bool
    basis_note: daily.BasisNote


class UnknownBaseline(StrictInput):
    mode: Literal["unknown"]
    basis_note: daily.BasisNote


Baseline = Annotated[ObservedBaseline | ConditionalZeroBaseline | UnknownBaseline, Field(discriminator="mode")]


class InfectionReview(StrictInput):
    current_presence: Literal["yes", "no", "unknown"]
    current_presence_basis_note: daily.BasisNote
    onset_review: Literal["known", "unknown"]
    onset_review_basis_note: daily.BasisNote


class ChangeReview(StrictInput):
    acute_change: Literal["confirmed", "not_confirmed", "unknown"]
    acute_change_basis_note: daily.BasisNote
    attribution: Literal["infection_related", "not_related", "uncertain"]
    attribution_basis_note: daily.BasisNote
    temporal_relation: Literal["before", "overlapping", "after", "unknown"]
    temporal_relation_basis_note: daily.BasisNote


class ChangeCreate(ChangeCandidatesRequest):
    baseline: Baseline
    infection_source_id: daily.CanonicalId
    expected_infection_content_hash: daily.HashText
    expected_infection_governance_hash: daily.HashText
    infection_review: InfectionReview
    review: ChangeReview
    note: str = Field(max_length=1000)


def frozen_metadata(row):
    return {**{key: getattr(row, key) for key in FROZEN_FIELDS}, "evaluation_at": utc_text(row.evaluation_at), "created_at": utc_text(row.created_at)}


def metadata(row):
    governance = {key: utc_text(row.revoked_at) if key == "revoked_at" and row.revoked_at is not None else getattr(row, key) for key in daily.GOVERNANCE_FIELDS}
    return {
        **frozen_metadata(row),
        "source_id": f"sofa_change_assessment:{row.change_assessment_id}:{row.content_hash[:12]}",
        "content_hash": row.content_hash,
        **governance,
        "governance_hash": hash_content(governance),
        "projection_hash": row.projection_hash,
    }


def _bound_current(db, user, req):
    current = daily.authorize_assessment(db, user, req.patient_id, req.admission_id, req.current_assessment_id)
    if current["content_hash"] != req.expected_current_content_hash or current["projection_hash"] != req.expected_current_projection_hash:
        raise HTTPException(409, "当前完整SOFA原评估或完整公开投影摘要已变化")
    return current


def _baseline(db, user, req, current):
    if req.baseline.mode != "observed":
        return None
    row = daily._row(db, req.baseline.assessment_id)
    # A separate original admission authorization is required, even for the same patient.
    baseline = daily.authorize_assessment(db, user, req.patient_id, row.admission_id, row.assessment_id)
    if baseline["content_hash"] != req.baseline.expected_content_hash or baseline["projection_hash"] != req.baseline.expected_projection_hash:
        raise HTTPException(409, "真实基线原评估或完整投影摘要已变化")
    if baseline["assessment_id"] == current["assessment_id"] or baseline["period_end"] > current["period_start"] or baseline["as_of"] > current["as_of"]:
        raise HTTPException(409, "真实基线须为独立且结束不晚于当前开始的完整24小时，资料截止亦不得更晚")
    if any(baseline[key] != current[key] for key in ("recipe_digest", "policy_digest")):
        raise HTTPException(409, "真实两期须采用相同SOFA固定规则和原单位政策")
    return baseline


def _infection(db, user, req, now):
    from app import inpatient_support_common as common

    source = common.authorize_source(db, user, req.patient_id, req.admission_id, "infection_episode", req.infection_source_id)
    if source["content_hash"] != req.expected_infection_content_hash or source["governance_hash"] != req.expected_infection_governance_hash or explicit_utc(source["recorded_at"]) > now:
        raise HTTPException(409, "感染原声明完整正文、当前治理或实际可用时刻已变化")
    if req.infection_review.onset_review == "known" and source["payload"]["onset_at"] is None:
        raise HTTPException(409, "原未知感染发作时刻不能由新SOFA变化判读补造")
    return source


def candidates(db, user, values):
    from app import inpatient_support_common as common
    from app.ai.sofa_models import AISofaAssessment
    from app.inpatient_infection_models import InpatientInfectionEpisodeSource

    req = values if isinstance(values, ChangeCandidatesRequest) else ChangeCandidatesRequest.model_validate(values)
    actor = actor_current(db, user)
    current = _bound_current(db, actor, req)
    baselines = []
    for row in (
        db.query(AISofaAssessment)
        .filter(
            AISofaAssessment.patient_id == req.patient_id,
            AISofaAssessment.status == "active",
            AISofaAssessment.period_end <= explicit_utc(current["period_start"]),
            AISofaAssessment.as_of <= explicit_utc(current["as_of"]),
        )
        .populate_existing()
        .order_by(AISofaAssessment.period_end, AISofaAssessment.assessment_id)
        .all()
    ):
        try:
            item = daily.authorize_assessment(db, actor, req.patient_id, row.admission_id, row.assessment_id)
        except HTTPException as exc:
            if exc.status_code in (403, 404, 409):
                continue
            raise
        if any(item[key] != current[key] for key in ("recipe_digest", "policy_digest")):
            continue
        baselines.append({key: item[key] for key in (*daily.FROZEN_FIELDS, *daily.CLOCK_FIELDS, "source_id", "content_hash", "projection_hash", "governance_hash", "eligible", "exclusion_reasons")})
    infections = []
    for row in (
        db.query(InpatientInfectionEpisodeSource)
        .filter_by(patient_id=req.patient_id, admission_id=req.admission_id, status="active")
        .populate_existing()
        .order_by(InpatientInfectionEpisodeSource.support_source_id)
        .all()
    ):
        infections.append(common.authorize_source(db, actor, req.patient_id, req.admission_id, "infection_episode", row.support_source_id))
    result = {
        "current_assessment": current,
        "baseline_assessments": baselines,
        "infection_sources": infections,
        "can_sign": clinical_qualification(db, actor, req.patient_id, req.admission_id) is not None,
        "options": {"request_schema": ChangeCreate.model_json_schema()},
    }
    daily._bounded(result, MAX_PRIVATE_BYTES, "完整SOFA变化候选")
    return result


change_candidates = candidates


def _projection(row, snapshot):
    from app.ai.sofa_contract import SofaChangeSource

    req, current, prior, infection = snapshot["attestation"], snapshot["current_assessment"], snapshot["baseline_assessment"], snapshot["infection_source"]
    raw, decision = infection["payload"], req["infection_review"]
    baseline = req["baseline"]
    if baseline["mode"] == "observed":
        projected_baseline = {"mode": "observed", "source": prior["specialist_source"]}
    else:
        projected_baseline = {key: value for key, value in baseline.items() if key != "basis_note"} | {"basis_hash": hash_content(baseline["basis_note"])}
    projected_infection = {
        **daily._original_binding(infection),
        "schema_version": infection["schema_version"],
        "support_source_id": infection["support_source_id"],
        **{key: raw[key] for key in ("infection_status", "clinical_scope_start_at", "clinical_scope_end_at", "first_suspected_at", "onset_at", "onset_time_basis")},
        **{key: decision[key] for key in ("current_presence", "onset_review")},
        "current_presence_basis_hash": hash_content(decision["current_presence_basis_note"]),
        "onset_review_basis_hash": hash_content(decision["onset_review_basis_note"]),
        "late_original_available_after_current_as_of": infection["recorded_at"] > current["as_of"],
    }
    review = req["review"]
    projected_review = {key: review[key] for key in ("acute_change", "attribution", "temporal_relation")}
    projected_review.update({key + "_basis_hash": hash_content(review[key + "_basis_note"]) for key in ("acute_change", "attribution", "temporal_relation")})
    value = {
        "schema_version": "sofa1_change_source_v1",
        "change_assessment_id": row.change_assessment_id,
        "source_id": f"sofa_change_assessment:{row.change_assessment_id}:{row.content_hash[:12]}",
        "content_hash": row.content_hash,
        "assessment_governance_hash": hash_content({"status": "active", "revision": 1, "revoked_at": None, "revoked_by": None, "revoke_reason": ""}),
        "evaluation_at": utc_text(row.evaluation_at),
        "current": current["specialist_source"],
        "baseline": projected_baseline,
        "infection": projected_infection,
        "review": projected_review,
        "review_mode": "current_retrospective_review",
        "historical_prediction": False,
    }
    try:
        return SofaChangeSource.model_validate(value).model_dump(mode="json")
    except (ValueError, TypeError, KeyError, AttributeError, RecursionError) as exc:
        raise HTTPException(409, "完整SOFA变化来源、真实基线时序或公开原事实不满足严格契约") from exc


def create_change_assessment(db, user, values):
    req = values if isinstance(values, ChangeCreate) else ChangeCreate.model_validate(values)
    actor = actor_current(db, user)
    authorize_scope(db, actor, req.patient_id, req.admission_id)
    doctor = clinical_qualification(db, actor, req.patient_id, req.admission_id)
    if doctor is None:
        raise HTTPException(403, "真实SOFA变化及感染归因判读须实际医生与当前原住院照护权，管理权不能代签")
    current = _bound_current(db, actor, req)
    baseline = _baseline(db, actor, req, current)
    now = utcnow()
    infection = _infection(db, actor, req, now)
    if baseline is not None and infection["payload"]["onset_at"] is not None and baseline["period_end"] > infection["payload"]["onset_at"]:
        raise HTTPException(409, "实际基线整日须结束于原已知感染发作之前，不能挑选已发作后的低分作为基线")
    row = AISofaChangeAssessment(
        change_assessment_id=str(uuid.uuid4()),
        patient_id=req.patient_id,
        admission_id=req.admission_id,
        current_assessment_id=req.current_assessment_id,
        baseline_assessment_id=req.baseline.assessment_id if req.baseline.mode == "observed" else None,
        infection_source_id=req.infection_source_id,
        evaluation_at=now,
        created_at=now,
        created_by=actor.user_id,
        schema_version=SCHEMA_VERSION,
        status="active",
        revision=1,
        revoke_reason="",
    )
    snapshot = {
        **frozen_metadata(row),
        "attestation": req.model_dump(mode="json"),
        "current_assessment": current,
        "baseline_assessment": baseline,
        "infection_source": infection,
        "author_qualification": {
            "actor_id": actor.user_id,
            "role_at_creation": actor.user_role,
            "doctor_id": doctor.doctor_id,
            "doctor_user_id": doctor.user_id,
            "care_authorization": "authorized_original_admission_at_creation",
            "authorized_at": utc_text(now),
            "clinical_review_signed": True,
        },
        "review_mode": "current_retrospective_review",
        "historical_prediction": False,
        "clinical_statements_recorded_at": utc_text(now),
        "source_verification": "explicit_current_retrospective_human_review_not_independently_verified",
    }
    row.snapshot_json = daily._bounded(snapshot, MAX_PRIVATE_BYTES, "完整SOFA变化私有原件")
    row.content_hash = hash_content(snapshot)
    public = _projection(row, snapshot)
    row.projection_json = daily._bounded(public, MAX_PUBLIC_BYTES, "完整SOFA变化公开原事实")
    row.projection_hash = hash_content(public)
    authorize_scope(db, actor, req.patient_id, req.admission_id)
    db.add(row)
    return row


def _row(db, row_or_id, *, lock=False):
    from app.ai.risk_rule_profiles import canonical_id

    identifier = canonical_id(row_or_id.change_assessment_id if isinstance(row_or_id, AISofaChangeAssessment) else row_or_id)
    query = db.query(AISofaChangeAssessment).filter_by(change_assessment_id=identifier).populate_existing()
    row = (query.with_for_update() if lock else query).one_or_none()
    if row is None:
        raise HTTPException(404, "完整SOFA变化临床核实原件不存在")
    return row


def _frozen(db, row):
    from app.ai.qsofa_sources import AuthorQualification

    try:
        for raw, cap in ((row.snapshot_json, MAX_PRIVATE_BYTES), (row.projection_json, MAX_PUBLIC_BYTES)):
            if not isinstance(raw, str) or len(raw.encode("utf-8")) > cap:
                raise ValueError("完整原件容量不符")
        snapshot, public = json.loads(row.snapshot_json), json.loads(row.projection_json)
        if row.schema_version != SCHEMA_VERSION or row.snapshot_json != canonical_json(snapshot) or row.content_hash != hash_content(snapshot):
            raise ValueError("原完整私有正文或hash不符")
        if row.projection_json != canonical_json(public) or row.projection_hash != hash_content(public):
            raise ValueError("原完整公开正文或hash不符")
        if any(snapshot.get(key) != value for key, value in frozen_metadata(row).items()):
            raise ValueError("原元数据不符")
        req = ChangeCreate.model_validate(snapshot["attestation"])
        qualification = AuthorQualification.model_validate(snapshot["author_qualification"])
        if any(getattr(req, key) != getattr(row, key) for key in ("patient_id", "admission_id", "current_assessment_id", "infection_source_id")):
            raise ValueError("原范围或引用不符")
        baseline_id = req.baseline.assessment_id if req.baseline.mode == "observed" else None
        if baseline_id != row.baseline_assessment_id or not row.evaluation_at == row.created_at <= utcnow():
            raise ValueError("原基线或时刻不符")
        if qualification.actor_id != row.created_by or qualification.doctor_user_id != row.created_by or qualification.authorized_at != utc_text(row.created_at):
            raise ValueError("原临床签署身份不符")
        current, prior, infection = snapshot["current_assessment"], snapshot["baseline_assessment"], snapshot["infection_source"]
        if current["assessment_id"] != row.current_assessment_id or current["patient_id"] != row.patient_id or current["admission_id"] != row.admission_id:
            raise ValueError("完整当前原件范围不符")
        if current["content_hash"] != req.expected_current_content_hash or current["projection_hash"] != req.expected_current_projection_hash:
            raise ValueError("完整当前原件摘要不符")
        if infection["support_source_id"] != row.infection_source_id or infection["patient_id"] != row.patient_id or infection["admission_id"] != row.admission_id:
            raise ValueError("感染原件范围不符")
        if infection["content_hash"] != req.expected_infection_content_hash or infection["governance_hash"] != req.expected_infection_governance_hash:
            raise ValueError("感染原件摘要不符")
        if (
            baseline_id is None
            and prior is not None
            or baseline_id is not None
            and (
                prior is None
                or prior["assessment_id"] != baseline_id
                or prior["patient_id"] != row.patient_id
                or prior["content_hash"] != req.baseline.expected_content_hash
                or prior["projection_hash"] != req.baseline.expected_projection_hash
            )
        ):
            raise ValueError("真实基线原件范围或摘要不符")
        if (
            snapshot.get("review_mode") != "current_retrospective_review"
            or snapshot.get("historical_prediction") is not False
            or snapshot.get("clinical_statements_recorded_at") != utc_text(row.created_at)
            or snapshot.get("source_verification") != "explicit_current_retrospective_human_review_not_independently_verified"
        ):
            raise ValueError("当前回顾性声明语义不符")
        daily._validate_governance(row, row.created_at)
        if _projection(row, snapshot) != public:
            raise ValueError("完整私有原件与公开投影不符")
        return snapshot, public, qualification
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError, RecursionError, HTTPException) as exc:
        raise HTTPException(409, "完整SOFA变化原文、签署、基线、感染或公开投影完整性校验失败") from exc


def change_detail(db, row_or_id, audit_only=False):
    from app import inpatient_support_common as common
    from app.models import Doctor, User

    row = _row(db, row_or_id)
    snapshot, public, qualification = _frozen(db, row)
    reasons = ["assessment_revoked"] if row.status != "active" else []
    author = db.query(User).filter_by(user_id=row.created_by).populate_existing().one_or_none()
    if author is None:
        reasons.append("original_author_missing")
    if db.query(Doctor.doctor_id).filter_by(doctor_id=qualification.doctor_id, user_id=qualification.doctor_user_id).first() is None:
        reasons.append("clinical_signer_relationship_changed")
    try:
        if author is None:
            raise HTTPException(409, "原作者不存在")
        current = daily.authorize_assessment(db, author, row.patient_id, row.admission_id, row.current_assessment_id)
        if current != snapshot["current_assessment"]:
            reasons.append("current_assessment_changed")
        if row.baseline_assessment_id is not None:
            original = snapshot["baseline_assessment"]
            prior = daily.authorize_assessment(db, author, row.patient_id, original["admission_id"], row.baseline_assessment_id)
            if prior != original:
                reasons.append("baseline_assessment_changed")
        infection = common.authorize_source(db, author, row.patient_id, row.admission_id, "infection_episode", row.infection_source_id)
        if infection != snapshot["infection_source"]:
            reasons.append("infection_source_changed")
    except HTTPException:
        reasons.append("current_baseline_infection_or_care_not_current")
    reasons = sorted(set(reasons))
    if reasons and not audit_only:
        raise HTTPException(409, "SOFA变化的当前日、真实基线、感染原件、医生或原照护权不再一致，不能继续执行")
    return {
        **metadata(row),
        "snapshot": snapshot,
        "specialist_source": public,
        "eligible": not reasons,
        "exclusion_reasons": reasons,
        "freshness": {"state": "current" if not reasons else "revoked" if row.status == "revoked" else "stale"},
        "eligibility_basis": "source_and_rule_governance_not_clinical_applicability",
    }


change_current = change_detail


def authorize_change(db, user, pid, adm, identifier):
    actor = actor_current(db, user)
    authorize_scope(db, actor, pid, adm)
    row = _row(db, identifier)
    if row.patient_id != pid or row.admission_id != adm:
        raise HTTPException(409, "SOFA变化原核实不属于当前明确原患者及住院")
    # Ordinary execution must independently authorize both original admissions.
    snapshot, _, _ = _frozen(db, row)
    daily.authorize_assessment(db, actor, pid, adm, row.current_assessment_id)
    if row.baseline_assessment_id is not None:
        daily.authorize_assessment(db, actor, pid, snapshot["baseline_assessment"]["admission_id"], row.baseline_assessment_id)
    result = change_detail(db, row)
    authorize_scope(db, actor, pid, adm)
    return result


def revoke_change(db, user, row_or_id, expected_revision, reason):
    from sqlalchemy import update

    actor = actor_current(db, user)
    row = _row(db, row_or_id, lock=True)
    req = AssessmentRevoke.model_validate({"patient_id": row.patient_id, "admission_id": row.admission_id, "expected_revision": expected_revision, "reason": reason})
    if actor.user_role != "super_admin":
        authorize_scope(db, actor, row.patient_id, row.admission_id)
        if actor.user_id != row.created_by:
            raise HTTPException(403, "仅原作者仍具当前照护权或超级管理员可撤销SOFA变化原件")
    _frozen(db, row)
    changed = db.execute(
        update(AISofaChangeAssessment)
        .where(AISofaChangeAssessment.change_assessment_id == row.change_assessment_id, AISofaChangeAssessment.revision == req.expected_revision, AISofaChangeAssessment.status == "active")
        .values(status="revoked", revision=2, revoked_at=utcnow(), revoked_by=actor.user_id, revoke_reason=req.reason),
        execution_options={"synchronize_session": False},
    )
    if changed.rowcount != 1:
        raise HTTPException(409, "SOFA变化原件治理版本已变化，请刷新后核对")
    db.expire(row)
    return row
