"""Explicit original-admission NEWS2 sources with frozen human applicability and clinical sign-off."""

import json
import uuid
from types import SimpleNamespace
from typing import Literal

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.ai.models import AINews2Assessment, utcnow
from app.ai.risk_rule_profiles import canonical_id, profile_current
from app.inpatient_laboratory import hash_content
from app.inpatient_observations import authorize_observation_admission, canonical_json, canonical_uuid, explicit_utc, utc_text

ASSESSMENT_ROLES = {"nurse", "doctor", "director", "admin", "super_admin"}
SCHEMA_VERSION = "news2_assessment_v1"
MAX_SNAPSHOT_BYTES = 262144
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
MEASUREMENT_KEYS = {"respiratory_rate", "spo2", "systolic_bp", "pulse_rate", "temperature"}
RELEVANT_KEYS = MEASUREMENT_KEYS | {"supplemental_oxygen", "consciousness"}


class Scale2Review(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    hypercapnic_respiratory_failure_confirmed: Literal[True]
    clinical_decision_confirmed: Literal[True]
    target_range: Literal["88-92"]
    blood_gas_reference: str = Field(min_length=20, max_length=1000)
    clinical_decision_reference: str = Field(min_length=20, max_length=1000)

    @field_validator("hypercapnic_respiratory_failure_confirmed", "clinical_decision_confirmed", mode="before")
    @classmethod
    def explicit_true(cls, value):
        if value is not True:
            raise ValueError("Scale2临床决定须由具资格医生逐项明确确认")
        return value

    @field_validator("blood_gas_reference", "clinical_decision_reference")
    @classmethod
    def meaningful(cls, value):
        if len(value.strip()) < 20:
            raise ValueError("Scale2血气依据及独立临床决定各须至少20字有效内容")
        return value


class AssessmentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    patient_id: int = Field(ge=1, le=2147483647)
    admission_id: str
    window_id: str
    expected_window_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    point_id: str
    expected_point_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    rule_profile_id: str
    expected_rule_profile_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    age_at_observation_years: int = Field(ge=0, le=130)
    age_basis_note: str = Field(min_length=20, max_length=1000)
    pregnancy_status: Literal["pregnant", "not_pregnant", "not_applicable", "unknown"]
    pregnancy_basis_note: str = Field(min_length=20, max_length=1000)
    spo2_scale: int = Field(ge=1, le=2)
    scale2_review: Scale2Review | None

    _ids = field_validator("admission_id", "window_id", "point_id", "rule_profile_id")(canonical_uuid)

    @field_validator("age_basis_note", "pregnancy_basis_note")
    @classmethod
    def meaningful(cls, value):
        if len(value.strip()) < 20:
            raise ValueError("年龄与妊娠适用性依据各须至少20字有效内容")
        return value


class AssessmentRevoke(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    patient_id: int = Field(ge=1, le=2147483647)
    admission_id: str
    expected_revision: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=1000)
    _id = field_validator("admission_id")(canonical_uuid)

    @field_validator("reason")
    @classmethod
    def meaningful(cls, value):
        if not value.strip():
            raise ValueError("请明确记录撤销依据")
        return value


class AuthorQualification(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    actor_id: int = Field(ge=1)
    role_at_creation: Literal["nurse", "doctor", "director", "admin", "super_admin"]
    doctor_id: int | None = Field(ge=1)
    doctor_user_id: int | None = Field(ge=1)
    care_authorization: Literal["authorized_original_admission_at_creation"]
    authorized_at: str
    scale2_decision_signed: bool


def authorize_scope(db, user, patient_id, admission_id):
    return authorize_observation_admission(db, user, patient_id, admission_id)


def actor_current(db, user):
    from app.models import User

    actor = db.query(User).filter_by(user_id=user.user_id).populate_existing().one_or_none()
    if actor is None or actor.user_role not in ASSESSMENT_ROLES:
        raise HTTPException(403, "当前用户没有NEWS2原住院评估资料权限")
    return actor


def clinical_qualification(db, user, patient_id, admission_id):
    """Super management rights never substitute for the doctor's actual care relationship."""
    from app.ai.context import authorize_patient
    from app.models import Doctor

    actor = actor_current(db, user)
    if actor.user_role not in {"doctor", "director", "super_admin"}:
        return None
    doctors = db.query(Doctor).filter_by(user_id=actor.user_id).order_by(Doctor.doctor_id).populate_existing().all()
    if not doctors:
        return None
    clinical_actor = SimpleNamespace(user_id=actor.user_id, username=actor.username, user_role="director" if actor.user_role == "director" else "doctor")
    try:
        authorize_patient(db, clinical_actor, patient_id, "inpatient", admission_id)
    except HTTPException:
        return None
    return doctors[0]


def frozen_metadata(row):
    return {**{key: getattr(row, key) for key in FROZEN_FIELDS}, "observed_at": utc_text(row.observed_at), "created_at": utc_text(row.created_at)}


def metadata(row):
    governance = {"status": row.status, "revision": row.revision, "revoked_at": utc_text(row.revoked_at) if row.revoked_at else None, "revoked_by": row.revoked_by, "revoke_reason": row.revoke_reason}
    return {
        **frozen_metadata(row),
        "source_id": f"news2_assessment:{row.assessment_id}:{row.content_hash[:12]}",
        "content_hash": row.content_hash,
        **governance,
        "governance_hash": hash_content(governance),
    }


def _window_binding(window):
    return {key: window[key] for key in ("window_id", "source_id", "content_hash", "schema_version", "start_at", "end_at", "as_of", "created_at")}


def _conflicts(window, point):
    return sorted(
        {
            group["measurement_code"]
            for group in window["quality"]["same_time_groups"]
            if group["observed_at"] == point["observed_at"] and group["measurement_code"] in RELEVANT_KEYS and group["state"] == "conflicting_values_or_missing_state"
        }
    )


def _projection(row, snapshot, window, profile):
    from app.ai.news2_contract import News2Source

    request = snapshot["attestation"]
    point = snapshot["point"]
    review = request["scale2_review"]
    if review is not None:
        review = {key: review[key] for key in ("hypercapnic_respiratory_failure_confirmed", "clinical_decision_confirmed", "target_range")} | {
            "blood_gas_reference_hash": hash_content(request["scale2_review"]["blood_gas_reference"]),
            "clinical_decision_reference_hash": hash_content(request["scale2_review"]["clinical_decision_reference"]),
        }
    data = {
        "assessment_id": row.assessment_id,
        "source_id": metadata(row)["source_id"],
        "content_hash": row.content_hash,
        "source_governance_hash": metadata(row)["governance_hash"],
        "window_id": row.window_id,
        "window_source_id": window["source_id"],
        "window_content_hash": row.window_content_hash,
        "as_of": window["as_of"],
        "point_id": row.point_id,
        "point_source_id": point["source_id"],
        "observed_at": point["observed_at"],
        "recorded_at": point["recorded_at"],
        "rule_profile_id": row.rule_profile_id,
        "rule_profile_source_id": profile["source_id"],
        "rule_profile_content_hash": row.rule_profile_content_hash,
        "rule_profile_governance_hash": profile["governance_hash"],
        "rule_id": "news2_2017",
        "recipe_digest": row.recipe_digest,
        **{key: request[key] for key in ("age_at_observation_years", "pregnancy_status", "spo2_scale")},
        "scale2_review": review,
        "measurements": {key: value for key, value in point["payload"]["measurements"].items() if key in MEASUREMENT_KEYS},
        "supplemental_oxygen": point["payload"]["supplemental_oxygen"],
        "consciousness": point["payload"]["consciousness"],
        "conflict_codes": _conflicts(window, point),
    }
    return News2Source.model_validate(data).model_dump(mode="json")


def create_assessment(db, user, values):
    from app.ai import observation_windows
    from app.inpatient_observations import source_current
    from app.models import InpatientObservation

    req = values if isinstance(values, AssessmentCreate) else AssessmentCreate.model_validate(values)
    actor = actor_current(db, user)
    authorize_scope(db, actor, req.patient_id, req.admission_id)
    if req.spo2_scale == 1 and req.scale2_review is not None or req.spo2_scale == 2 and req.scale2_review is None:
        raise HTTPException(422, "Scale1须无Scale2声明；Scale2须由医生完整记录独立临床决定")
    doctor = clinical_qualification(db, actor, req.patient_id, req.admission_id) if req.spo2_scale == 2 else None
    if req.spo2_scale == 2 and doctor is None:
        raise HTTPException(403, "Scale2须有真实Doctor身份及本次住院临床照护关系；管理权限不等于临床签署资格")
    window = observation_windows.snapshot_current(db, actor, req.window_id)
    if window["patient_id"] != req.patient_id or window["admission_id"] != req.admission_id or window["content_hash"] != req.expected_window_hash:
        raise HTTPException(409, "所选窗口不属于原患者/住院或摘要已变化")
    selected = [item for item in window["points"] if item["observation_id"] == req.point_id]
    if len(selected) != 1 or selected[0]["status"] != "active" or selected[0]["content_hash"] != req.expected_point_hash:
        raise HTTPException(409, "须明确选择当前原窗口内活动点测及其原摘要，不按最近记录推定")
    point_row = db.query(InpatientObservation).filter_by(observation_id=req.point_id).populate_existing().one_or_none()
    point = source_current(db, point_row)
    if point["content_hash"] != req.expected_point_hash or point["patient_id"] != req.patient_id or point["admission_id"] != req.admission_id:
        raise HTTPException(409, "原点测归属或临床内容已变化")
    profile = profile_current(db, req.rule_profile_id)
    if profile["rule_id"] != "news2_2017":
        raise HTTPException(409, "NEWS2评估只能绑定已发布的NEWS2固定规则，不能使用其他风险规则")
    now = utcnow()
    if profile["content_hash"] != req.expected_rule_profile_hash or explicit_utc(profile["published_at"]) > now or explicit_utc(window["created_at"]) > now:
        raise HTTPException(409, "规则原文或发布/窗口时钟已改变")
    row = AINews2Assessment(
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
        observed_at=explicit_utc(point["observed_at"]),
        created_at=now,
        created_by=actor.user_id,
        schema_version=SCHEMA_VERSION,
        status="active",
        revision=1,
        revoke_reason="",
    )
    snapshot = {
        **frozen_metadata(row),
        "window_binding": _window_binding(window),
        "point": point,
        "rule_profile": profile,
        "attestation": req.model_dump(mode="json"),
        "author_qualification": {
            "actor_id": actor.user_id,
            "role_at_creation": actor.user_role,
            "doctor_id": doctor.doctor_id if doctor else None,
            "doctor_user_id": doctor.user_id if doctor else None,
            "care_authorization": "authorized_original_admission_at_creation",
            "authorized_at": utc_text(now),
            "scale2_decision_signed": req.spo2_scale == 2,
        },
        "source_verification": "explicit_user_attestation_not_independently_verified",
    }
    row.snapshot_json = canonical_json(snapshot)
    if len(row.snapshot_json.encode("utf-8")) > MAX_SNAPSHOT_BYTES:
        raise HTTPException(422, "NEWS2来源正文超过262144个UTF-8字节，不登记、不截断")
    row.content_hash = hash_content(snapshot)
    _projection(row, snapshot, window, profile)
    db.add(row)
    return row


def assessment_current(db, row_or_id, allow_revoked=False, *, user=None):
    from app.ai import observation_windows
    from app.inpatient_observations import source_current
    from app.models import Doctor, InpatientObservation, User

    identifier = canonical_id(row_or_id.assessment_id if isinstance(row_or_id, AINews2Assessment) else row_or_id)
    row = db.query(AINews2Assessment).filter_by(assessment_id=identifier).populate_existing().one_or_none()
    if row is None:
        raise HTTPException(409, "原NEWS2评估来源不存在")
    if user is None:
        raise HTTPException(422, "须通过当前已授权请求者复验NEWS2来源；请使用authorize_assessment")
    actor = actor_current(db, user)
    authorize_scope(db, actor, row.patient_id, row.admission_id)
    try:
        if not isinstance(row.snapshot_json, str) or len(row.snapshot_json.encode("utf-8")) > MAX_SNAPSHOT_BYTES:
            raise ValueError("来源正文超过上限")
        snapshot = json.loads(row.snapshot_json)
        if (
            row.schema_version != SCHEMA_VERSION
            or snapshot["rule_profile"]["rule_id"] != "news2_2017"
            or row.snapshot_json != canonical_json(snapshot)
            or row.content_hash != hash_content(snapshot)
            or any(snapshot.get(key) != value for key, value in frozen_metadata(row).items())
        ):
            raise ValueError("来源冻结正文或归属哈希改变")
        req = AssessmentCreate.model_validate(snapshot["attestation"])
        qualification = AuthorQualification.model_validate(snapshot["author_qualification"])
        if (
            snapshot.get("source_verification") != "explicit_user_attestation_not_independently_verified"
            or qualification.actor_id != row.created_by
            or qualification.authorized_at != utc_text(row.created_at)
        ):
            raise ValueError("原作者或声明语义改变")
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
        if any(getattr(req, key) != value for key, value in expected.items()) or not row.observed_at <= row.created_at <= utcnow():
            raise ValueError("原选择绑定或评估时钟无效")
        if req.spo2_scale == 1 and (req.scale2_review is not None or qualification.scale2_decision_signed or qualification.doctor_id is not None or qualification.doctor_user_id is not None):
            raise ValueError("Scale1夹带临床声明")
        if req.spo2_scale == 2 and (
            req.scale2_review is None
            or not qualification.scale2_decision_signed
            or qualification.role_at_creation not in {"doctor", "director", "super_admin"}
            or qualification.doctor_id is None
            or qualification.doctor_user_id != row.created_by
        ):
            raise ValueError("原Scale2临床签署资格缺失")
        active = row.status == "active" and row.revision == 1 and row.revoked_at is None and row.revoked_by is None and row.revoke_reason == ""
        revoked = (
            row.status == "revoked"
            and row.revision == 2
            and row.revoked_at is not None
            and row.created_at <= row.revoked_at <= utcnow()
            and type(row.revoked_by) is int
            and row.revoked_by > 0
            and bool(row.revoke_reason.strip())
        )
        if not active and not revoked:
            raise ValueError("来源治理状态不一致")
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError, RecursionError) as exc:
        raise HTTPException(409, "NEWS2冻结原文、人工声明或治理完整性校验失败") from exc
    excluded = ["assessment_revoked"] if row.status == "revoked" else []
    if db.query(User.user_id).filter_by(user_id=row.created_by).first() is None:
        excluded.append("original_author_missing")
    # An original signed role is frozen. Later role changes do not retroactively
    # remove that signature; reassigning its actual Doctor identity does.
    if qualification.doctor_id is not None and db.query(Doctor.doctor_id).filter_by(doctor_id=qualification.doctor_id, user_id=qualification.doctor_user_id).first() is None:
        excluded.append("clinical_signer_relationship_changed")
    window = profile = None
    try:
        window = observation_windows.snapshot_current(db, actor, row.window_id)
        if window["content_hash"] != row.window_content_hash or _window_binding(window) != snapshot["window_binding"]:
            excluded.append("window_binding_changed")
    except HTTPException:
        excluded.append("window_not_current")
    try:
        point_row = db.query(InpatientObservation).filter_by(observation_id=row.point_id).populate_existing().one_or_none()
        point = source_current(db, point_row, allow_revoked=True)
        if point != snapshot["point"] or point["content_hash"] != row.point_content_hash:
            excluded.append("point_not_current")
    except HTTPException:
        excluded.append("point_not_current")
    try:
        profile = profile_current(db, row.rule_profile_id, allow_revoked=True)
        if profile["rule_id"] != "news2_2017":
            excluded.append("profile_rule_mismatch")
        mutable = {"status", "revision", "revoked_at", "revoked_by", "revoke_reason", "governance_hash", "implementation_current", "eligible", "exclusion_reasons"}
        if (
            {key: value for key, value in profile.items() if key not in mutable} != {key: value for key, value in snapshot["rule_profile"].items() if key not in mutable}
            or profile["content_hash"] != row.rule_profile_content_hash
            or profile["recipe_digest"] != row.recipe_digest
        ):
            excluded.append("profile_publication_changed")
        if not profile["eligible"]:
            excluded.extend(profile["exclusion_reasons"])
        if explicit_utc(profile["published_at"]) > row.created_at:
            excluded.append("profile_published_after_assessment")
    except HTTPException:
        excluded.append("profile_not_current")
    excluded = sorted(set(excluded))
    if excluded and not allow_revoked:
        raise HTTPException(409, "NEWS2原评估、窗口、点测、签署身份或规则不再一致，不能继续执行")
    projected = _projection(row, snapshot, window, profile) if not excluded else None
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
    identifier = canonical_id(assessment_id)
    row = db.query(AINews2Assessment).filter_by(assessment_id=identifier).populate_existing().one_or_none()
    if row is None:
        raise HTTPException(404, "NEWS2原评估不存在")
    if row.patient_id != patient_id or row.admission_id != admission_id or window_id is not None and row.window_id != window_id:
        raise HTTPException(409, "NEWS2评估不属于本次原患者、住院或明确窗口")
    return assessment_current(db, row, user=actor)
