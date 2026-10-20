"""Explicit current retrospective clinical review of original qSOFA bedside evidence."""

import json
import uuid
from typing import Literal

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.ai.models import AIQsofaAssessment, utcnow
from app.ai.news2_sources import ASSESSMENT_ROLES as ASSESSMENT_ROLES
from app.ai.news2_sources import actor_current, authorize_scope, clinical_qualification
from app.ai.risk_rule_profiles import canonical_id, profile_current
from app.inpatient_laboratory import hash_content
from app.inpatient_observations import canonical_json, canonical_uuid, explicit_utc, utc_text

SCHEMA_VERSION = "qsofa_assessment_v1"
RULE_ID = "qsofa_sepsis3_2016"
MAX_SNAPSHOT_BYTES = 262144
MAX_GCS_MEMBERS = 1000
FROZEN_FIELDS = (
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
    "created_by",
    "schema_version",
)
GOVERNANCE_FIELDS = ("status", "revision", "revoked_at", "revoked_by", "revoke_reason")
MEASUREMENT_KEYS = {"respiratory_rate", "systolic_bp"}
SCOPE_NOTES = ("age_basis_note", "care_setting_basis_note", "infection_basis_note")


class StrictInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class GcsReference(StrictInput):
    gcs_observation_id: str
    expected_content_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    _id = field_validator("gcs_observation_id")(canonical_uuid)


class AssessmentCreate(StrictInput):
    patient_id: int = Field(ge=1, le=2147483647)
    admission_id: str
    window_id: str
    expected_window_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    point_id: str
    expected_point_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    rule_profile_id: str
    expected_rule_profile_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    age_at_observation_years: int | None = Field(ge=0, le=130)
    age_basis_note: str = Field(min_length=20, max_length=1000)
    care_setting: Literal["non_icu", "icu", "unknown"]
    care_setting_basis_note: str = Field(min_length=20, max_length=1000)
    infection_status: Literal["suspected", "documented", "not_suspected", "unknown"]
    infection_basis_note: str = Field(min_length=20, max_length=1000)
    gcs_observation: GcsReference | None
    gcs_interpretability: Literal["confirmed", "limited", "unknown"]
    gcs_review_note: str | None = Field(min_length=20, max_length=1000)
    _ids = field_validator("admission_id", "window_id", "point_id", "rule_profile_id")(canonical_uuid)

    @field_validator("age_basis_note", "care_setting_basis_note", "infection_basis_note", "gcs_review_note")
    @classmethod
    def meaningful(cls, value):
        if value is not None and len(value.strip()) < 20:
            raise ValueError("每项临床核实依据须有至少20字有效内容")
        return value

    @model_validator(mode="after")
    def explicit_gcs_review(self):
        if self.gcs_observation is None:
            if self.gcs_interpretability != "unknown" or self.gcs_review_note is not None:
                raise ValueError("未选择原GCS时须保留未知可判读性及null依据，不能推定GCS15")
        elif self.gcs_review_note is None:
            raise ValueError("所选原GCS须有明确可判读性核实依据，未知亦不省略")
        return self


class AssessmentRevoke(StrictInput):
    patient_id: int = Field(ge=1, le=2147483647)
    admission_id: str
    expected_revision: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=1000)
    _id = field_validator("admission_id")(canonical_uuid)

    @field_validator("reason")
    @classmethod
    def meaningful(cls, value):
        if not value.strip():
            raise ValueError("撤销依据不能为空")
        return value


class AuthorQualification(StrictInput):
    actor_id: int = Field(ge=1)
    role_at_creation: Literal["doctor", "director", "super_admin"]
    doctor_id: int = Field(ge=1)
    doctor_user_id: int = Field(ge=1)
    care_authorization: Literal["authorized_original_admission_at_creation"]
    authorized_at: str
    clinical_review_signed: Literal[True]

    @field_validator("clinical_review_signed", mode="before")
    @classmethod
    def exact_signature(cls, value):
        if value is not True:
            raise ValueError("临床核实须明确签署")
        return value


def frozen_metadata(row):
    return {**{key: getattr(row, key) for key in FROZEN_FIELDS}, "evaluation_at": utc_text(row.evaluation_at), "created_at": utc_text(row.created_at)}


def metadata(row):
    governance = {key: utc_text(row.revoked_at) if key == "revoked_at" and row.revoked_at is not None else getattr(row, key) for key in GOVERNANCE_FIELDS}
    return {
        **frozen_metadata(row),
        "source_id": f"qsofa_assessment:{row.assessment_id}:{row.content_hash[:12]}",
        "content_hash": row.content_hash,
        **governance,
        "governance_hash": hash_content(governance),
    }


def window_binding(window):
    return {key: window[key] for key in ("window_id", "source_id", "content_hash", "schema_version", "start_at", "end_at", "as_of", "created_at")}


def point_view(point):
    return {**point, "governance_hash": hash_content({key: point[key] for key in GOVERNANCE_FIELDS}), "assessment_projection": "qsofa_point_projection_v1"}


def point_conflicts(window, point):
    return sorted(
        {
            group["measurement_code"]
            for group in window["quality"]["same_time_groups"]
            if group["observed_at"] == point["observed_at"] and group["measurement_code"] in MEASUREMENT_KEYS and group["state"] == "conflicting_values_or_missing_state"
        }
    )


def gcs_group(db, point_id, cutoff):
    from app.inpatient_gcs import source_current
    from app.models import InpatientGcsObservation

    rows = (
        db.query(InpatientGcsObservation)
        .filter(InpatientGcsObservation.anchor_point_id == point_id, InpatientGcsObservation.recorded_at <= cutoff)
        .populate_existing()
        .order_by(InpatientGcsObservation.gcs_observation_id)
        .limit(MAX_GCS_MEMBERS + 1)
        .all()
    )
    if len(rows) > MAX_GCS_MEMBERS:
        raise HTTPException(422, "截止前同锚点原GCS超过1000条，不能截断冲突核对")
    return [source_current(db, row, allow_revoked=True) for row in rows]


def group_conflict(group):
    signatures = {canonical_json(item["payload"]["components"]) for item in group if item["status"] == "active"}
    return len(signatures) > 1


def selected_gcs(db, reference, point, window, group=None):
    from app.inpatient_gcs import source_current
    from app.models import InpatientGcsObservation

    if reference is None:
        return None
    row = db.query(InpatientGcsObservation).filter_by(gcs_observation_id=reference.gcs_observation_id).populate_existing().one_or_none()
    data = source_current(db, row)
    payload = data["payload"]
    if data["patient_id"] != point["patient_id"] or data["admission_id"] != point["admission_id"] or data["content_hash"] != reference.expected_content_hash:
        raise HTTPException(409, "原GCS须属于相同原患者及住院，完整摘要须一致")
    if (
        payload["anchor_point"] != {"observation_id": point["observation_id"], "expected_content_hash": point["content_hash"]}
        or payload["same_exam_confirmed"] is not True
        or not data["anchor_current"]
    ):
        raise HTTPException(409, "须选择明确关联本原点测的同次GCS，不按最近时刻或AVPU猜测")
    if not explicit_utc(window["start_at"]) <= explicit_utc(data["observed_at"]) <= explicit_utc(window["end_at"]) or explicit_utc(data["recorded_at"]) > explicit_utc(window["as_of"]):
        raise HTTPException(409, "原GCS实际时刻须在窗口内且登记不晚于截止，不能补入早窗")
    if group is not None and not any(item == data for item in group):
        raise HTTPException(409, "原GCS不在截止前明确同锚点来源集合内")
    return data


def _projection(row, snapshot, window, profile):
    from app.ai.qsofa_contract import QsofaSource

    request, point, gcs = snapshot["attestation"], snapshot["point"], snapshot["gcs_observation"]
    projected_gcs = None
    if gcs is not None:
        anchor = gcs["anchor_point_snapshot"]
        projected_gcs = {
            **{key: gcs[key] for key in ("gcs_observation_id", "source_id", "content_hash", "governance_hash", "schema_version", "observed_at", "recorded_at")},
            "components": gcs["payload"]["components"],
            "anchor_point_id": anchor["observation_id"],
            "anchor_point_source_id": anchor["source_id"],
            "anchor_point_content_hash": anchor["content_hash"],
            "same_exam_confirmed": True,
            "same_exam_evidence_hash": hash_content(gcs["payload"]["same_exam_basis_note"]),
            "conflict": group_conflict(snapshot["gcs_group"]),
        }
    data = {
        "assessment_id": row.assessment_id,
        "source_id": metadata(row)["source_id"],
        "content_hash": row.content_hash,
        "source_governance_hash": metadata(row)["governance_hash"],
        "window_id": row.window_id,
        "window_source_id": window["source_id"],
        "window_content_hash": row.window_content_hash,
        **{key: window[key] for key in ("start_at", "end_at", "as_of")},
        "point_id": row.point_id,
        "point_source_id": point["source_id"],
        "point_content_hash": row.point_content_hash,
        "point_governance_hash": point["governance_hash"],
        "observed_at": point["observed_at"],
        "recorded_at": point["recorded_at"],
        "rule_profile_id": row.rule_profile_id,
        "rule_profile_source_id": profile["source_id"],
        "rule_profile_content_hash": row.rule_profile_content_hash,
        "rule_profile_governance_hash": profile["governance_hash"],
        "rule_id": RULE_ID,
        "recipe_digest": row.recipe_digest,
        "evaluation_at": utc_text(row.evaluation_at),
        "clinical_statements_recorded_at": utc_text(row.created_at),
        "clinical_scope_applies_to": point["observed_at"],
        "review_mode": "current_retrospective_review",
        "historical_prediction": False,
        **{key: request[key] for key in ("age_at_observation_years", "care_setting", "infection_status")},
        "scope_evidence_hash": hash_content({key: request[key] for key in SCOPE_NOTES}),
        "measurements": {key: value for key, value in point["payload"]["measurements"].items() if key in MEASUREMENT_KEYS},
        "point_conflicts": snapshot["point_conflicts"],
        "gcs": projected_gcs,
        "gcs_interpretability": request["gcs_interpretability"],
        "gcs_review_evidence_hash": hash_content(request["gcs_review_note"]) if request["gcs_review_note"] is not None else None,
    }
    return QsofaSource.model_validate(data).model_dump(mode="json")


def create_assessment(db, user, values):
    from app.ai import observation_windows
    from app.inpatient_observations import source_current
    from app.models import InpatientObservation

    req = values if isinstance(values, AssessmentCreate) else AssessmentCreate.model_validate(values)
    actor = actor_current(db, user)
    authorize_scope(db, actor, req.patient_id, req.admission_id)
    doctor = clinical_qualification(db, actor, req.patient_id, req.admission_id)
    if doctor is None:
        raise HTTPException(403, "qSOFA当前临床核实须有真实Doctor身份及原住院临床照护，管理权限不能代签")
    window = observation_windows.snapshot_current(db, actor, req.window_id)
    if window["patient_id"] != req.patient_id or window["admission_id"] != req.admission_id or window["content_hash"] != req.expected_window_hash:
        raise HTTPException(409, "原窗口患者、住院或完整摘要不一致")
    members = [item for item in window["points"] if item["observation_id"] == req.point_id]
    if len(members) != 1 or members[0]["status"] != "active" or members[0]["content_hash"] != req.expected_point_hash:
        raise HTTPException(409, "须明确选择活动原窗口成员点测，不拼接最近RR与血压")
    point_row = db.query(InpatientObservation).filter_by(observation_id=req.point_id).populate_existing().one_or_none()
    point = source_current(db, point_row)
    if point["content_hash"] != req.expected_point_hash or point["patient_id"] != req.patient_id or point["admission_id"] != req.admission_id:
        raise HTTPException(409, "原点测内容、时刻或归属变化")
    point = point_view(point)
    profile = profile_current(db, req.rule_profile_id)
    now = utcnow()
    if profile["rule_id"] != RULE_ID or profile["content_hash"] != req.expected_rule_profile_hash or explicit_utc(profile["published_at"]) > now or explicit_utc(window["created_at"]) > now:
        raise HTTPException(409, "qSOFA须绑定当前已发布专用规则和原窗口，不混用NEWS2或AKI规则")
    group = gcs_group(db, req.point_id, explicit_utc(window["as_of"]))
    gcs = selected_gcs(db, req.gcs_observation, point, window, group)
    row = AIQsofaAssessment(
        assessment_id=str(uuid.uuid4()),
        patient_id=req.patient_id,
        admission_id=req.admission_id,
        window_id=req.window_id,
        window_content_hash=req.expected_window_hash,
        point_id=req.point_id,
        point_content_hash=req.expected_point_hash,
        rule_profile_id=req.rule_profile_id,
        rule_profile_content_hash=req.expected_rule_profile_hash,
        recipe_digest=profile["recipe_digest"],
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
        "window_binding": window_binding(window),
        "point": point,
        "gcs_observation": gcs,
        "gcs_group": group,
        "point_conflicts": point_conflicts(window, point),
        "rule_profile": profile,
        "attestation": req.model_dump(mode="json"),
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
        "clinical_scope_applies_to": point["observed_at"],
        "source_verification": "explicit_current_retrospective_human_review_not_independently_verified",
    }
    row.snapshot_json = canonical_json(snapshot)
    if len(row.snapshot_json.encode("utf-8")) > MAX_SNAPSHOT_BYTES:
        raise HTTPException(422, "完整qSOFA原资料核实超过262144个UTF-8字节，不登记、不截断")
    row.content_hash = hash_content(snapshot)
    _projection(row, snapshot, window, profile)
    authorize_scope(db, actor, req.patient_id, req.admission_id)
    db.add(row)
    return row


def assessment_current(db, row_or_id, allow_revoked=False, *, user=None):
    from app.ai import observation_windows
    from app.inpatient_observations import source_current
    from app.models import Doctor, InpatientObservation, User

    identifier = canonical_id(row_or_id.assessment_id if isinstance(row_or_id, AIQsofaAssessment) else row_or_id)
    row = db.query(AIQsofaAssessment).filter_by(assessment_id=identifier).populate_existing().one_or_none()
    if row is None:
        raise HTTPException(409, "原qSOFA临床核实不存在")
    if user is None:
        raise HTTPException(422, "须以当前请求者原住院照护权复验qSOFA来源")
    actor = actor_current(db, user)
    authorize_scope(db, actor, row.patient_id, row.admission_id)
    try:
        if not isinstance(row.snapshot_json, str) or len(row.snapshot_json.encode("utf-8")) > MAX_SNAPSHOT_BYTES:
            raise ValueError("原正文超过上限")
        snapshot = json.loads(row.snapshot_json)
        if (
            row.schema_version != SCHEMA_VERSION
            or row.snapshot_json != canonical_json(snapshot)
            or row.content_hash != hash_content(snapshot)
            or canonical_json({key: snapshot.get(key) for key in frozen_metadata(row)}) != canonical_json(frozen_metadata(row))
        ):
            raise ValueError("冻结原文、归属、版本或摘要改变")
        req = AssessmentCreate.model_validate(snapshot["attestation"])
        qualification = AuthorQualification.model_validate(snapshot["author_qualification"])
        expected = {
            "patient_id": row.patient_id,
            "admission_id": row.admission_id,
            "window_id": row.window_id,
            "expected_window_hash": row.window_content_hash,
            "point_id": row.point_id,
            "expected_point_hash": row.point_content_hash,
            "rule_profile_id": row.rule_profile_id,
            "expected_rule_profile_hash": row.rule_profile_content_hash,
        }
        if any(getattr(req, key) != value for key, value in expected.items()) or not row.evaluation_at == row.created_at <= utcnow():
            raise ValueError("原引用或当前临床核实钟点不一致")
        if (
            snapshot.get("source_verification") != "explicit_current_retrospective_human_review_not_independently_verified"
            or snapshot.get("review_mode") != "current_retrospective_review"
            or snapshot.get("historical_prediction") is not False
        ):
            raise ValueError("当前回顾性人工核实语义不一致")
        if snapshot.get("clinical_statements_recorded_at") != utc_text(row.created_at) or snapshot.get("clinical_scope_applies_to") != snapshot["point"]["observed_at"]:
            raise ValueError("当前声明被冒充成历史可用资料")
        if qualification.actor_id != row.created_by or qualification.doctor_user_id != row.created_by or qualification.authorized_at != utc_text(row.created_at):
            raise ValueError("原临床签署身份不一致")
        active = row.status == "active" and row.revision == 1 and row.revoked_at is None and row.revoked_by is None and row.revoke_reason == ""
        revoked = (
            row.status == "revoked"
            and row.revision == 2
            and row.revoked_at is not None
            and row.created_at <= row.revoked_at <= utcnow()
            and type(row.revoked_by) is int
            and row.revoked_by > 0
            and 0 < len(row.revoke_reason.strip()) <= 1000
        )
        if not active and not revoked:
            raise ValueError("原治理状态不一致")
    except (ValueError, TypeError, AttributeError, KeyError, OverflowError, RecursionError) as exc:
        raise HTTPException(409, "qSOFA原文、临床声明、签署或治理完整性校验失败") from exc
    excluded = ["assessment_revoked"] if row.status == "revoked" else []
    if db.query(User.user_id).filter_by(user_id=row.created_by).first() is None:
        excluded.append("original_author_missing")
    if db.query(Doctor.doctor_id).filter_by(doctor_id=qualification.doctor_id, user_id=qualification.doctor_user_id).first() is None:
        excluded.append("clinical_signer_relationship_changed")
    window = profile = None
    try:
        window = observation_windows.snapshot_current(db, actor, row.window_id)
        if window_binding(window) != snapshot["window_binding"] or window["content_hash"] != row.window_content_hash:
            excluded.append("window_binding_changed")
    except HTTPException:
        excluded.append("window_not_current")
    try:
        point = point_view(source_current(db, db.query(InpatientObservation).filter_by(observation_id=row.point_id).populate_existing().one_or_none()))
        if (
            canonical_json(point) != canonical_json(snapshot["point"])
            or point["content_hash"] != row.point_content_hash
            or window is not None
            and point_conflicts(window, point) != snapshot["point_conflicts"]
        ):
            excluded.append("point_not_current")
    except HTTPException:
        excluded.append("point_not_current")
    try:
        current_group = gcs_group(db, row.point_id, explicit_utc(snapshot["window_binding"]["as_of"]))
        if canonical_json(current_group) != canonical_json(snapshot["gcs_group"]):
            excluded.append("same_anchor_gcs_membership_changed")
        if req.gcs_observation is not None:
            gcs = selected_gcs(db, req.gcs_observation, snapshot["point"], snapshot["window_binding"], current_group)
            if canonical_json(gcs) != canonical_json(snapshot["gcs_observation"]):
                excluded.append("selected_gcs_changed")
        elif snapshot["gcs_observation"] is not None:
            excluded.append("unexpected_gcs_source")
    except HTTPException:
        excluded.append("gcs_sources_not_current")
    try:
        profile = profile_current(db, row.rule_profile_id, allow_revoked=True)
        if (
            profile["rule_id"] != RULE_ID
            or canonical_json(profile) != canonical_json(snapshot["rule_profile"])
            or profile["content_hash"] != row.rule_profile_content_hash
            or profile["recipe_digest"] != row.recipe_digest
            or explicit_utc(profile["published_at"]) > row.created_at
        ):
            excluded.append("rule_profile_changed")
        if not profile["eligible"]:
            excluded.extend(profile["exclusion_reasons"])
    except HTTPException:
        excluded.append("rule_profile_not_current")
    excluded = sorted(set(excluded))
    if excluded and not allow_revoked:
        raise HTTPException(409, "qSOFA原窗口、点测、GCS集合、临床签署或规则不再一致，不能执行")
    projected = _projection(row, snapshot, window, profile) if not excluded else None
    authorize_scope(db, actor, row.patient_id, row.admission_id)
    return {
        **metadata(row),
        "snapshot": snapshot,
        "specialist_source": projected,
        "eligible": not excluded,
        "exclusion_reasons": excluded,
        "freshness": {"state": "current" if not excluded else "revoked" if row.status == "revoked" else "stale"},
        "eligibility_basis": "source_and_rule_governance_not_clinical_applicability",
    }


def authorize_assessment(db, user, patient_id, admission_id, assessment_id, window_id=None):
    actor = actor_current(db, user)
    authorize_scope(db, actor, patient_id, admission_id)
    row = db.query(AIQsofaAssessment).filter_by(assessment_id=canonical_id(assessment_id)).populate_existing().one_or_none()
    if row is None:
        raise HTTPException(404, "原qSOFA核实不存在")
    if row.patient_id != patient_id or row.admission_id != admission_id or window_id is not None and row.window_id != window_id:
        raise HTTPException(409, "qSOFA核实不属于当前原患者、住院或明确窗口")
    return assessment_current(db, row, user=actor)
