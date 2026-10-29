"""Admission-bound immutable AKI inputs, explicit source roles and clinical attestations."""

import copy
import json
import uuid
from typing import Literal

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.ai.models import AIAKIAssessment, utcnow
from app.ai.news2_sources import ASSESSMENT_ROLES as ASSESSMENT_ROLES
from app.ai.news2_sources import actor_current, authorize_scope, clinical_qualification
from app.ai.risk_rule_profiles import canonical_id, profile_current
from app.inpatient_laboratory import hash_content
from app.inpatient_observations import canonical_json, canonical_uuid, explicit_utc, utc_text

SCHEMA_VERSION = "aki_assessment_v1"
MAX_SNAPSHOT_BYTES = 262144
RULE_ID = "kdigo_aki_2012"
LAB_ROLES = ("index_creatinine", "comparison_48h", "baseline_creatinine")
SELECTED_FIELDS = (*LAB_ROLES, "weight_point", "urine_intervals", "urine_coverage_issues")
FROZEN_FIELDS = ("assessment_id", "patient_id", "admission_id", "window_id", "window_content_hash", "rule_profile_id", "rule_profile_content_hash", "recipe_digest", "created_by", "schema_version")
GOVERNANCE_FIELDS = ("status", "revision", "revoked_at", "revoked_by", "revoke_reason")


class StrictInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class LabReference(StrictInput):
    lab_source_id: str
    expected_content_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    _id = field_validator("lab_source_id")(canonical_uuid)


class WeightReference(StrictInput):
    observation_id: str
    expected_content_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    _id = field_validator("observation_id")(canonical_uuid)


class UrineReference(StrictInput):
    interval_id: str
    expected_content_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    _id = field_validator("interval_id")(canonical_uuid)


def request_clock(value):
    return utc_text(explicit_utc(value))


class AssessmentCreate(StrictInput):
    patient_id: int = Field(ge=1, le=2147483647)
    admission_id: str
    window_id: str
    expected_window_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    rule_profile_id: str
    expected_rule_profile_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    evaluation_at: str
    age_at_evaluation_years: int = Field(ge=0, le=130)
    age_basis_note: str = Field(min_length=20, max_length=1000)
    index_creatinine: LabReference | None
    comparison_48h: LabReference | None
    baseline_creatinine: LabReference | None
    baseline_mode: Literal["unknown", "observed_within_7d", "presumed_within_7d"]
    serum_creatinine_confirmed: bool
    creatinine_review_note: str | None = Field(min_length=20, max_length=1000)
    baseline_rise_within_7d_confirmed: bool | None
    baseline_review_note: str | None = Field(min_length=20, max_length=1000)
    weight_point: WeightReference | None
    weight_applicability_confirmed: bool
    weight_basis_note: str | None = Field(min_length=20, max_length=1000)
    urine_intervals: list[UrineReference] = Field(max_length=64)
    rrt_status: Literal["unknown", "not_initiated", "acute_initiated_for_aki", "maintenance"]
    rrt_started_at: str | None
    rrt_acute_aki_confirmed: bool | None
    rrt_basis_note: str | None = Field(min_length=20, max_length=1000)

    _ids = field_validator("admission_id", "window_id", "rule_profile_id")(canonical_uuid)
    _evaluation_clock = field_validator("evaluation_at")(request_clock)

    @field_validator("rrt_started_at")
    @classmethod
    def explicit_rrt_clock(cls, value):
        return request_clock(value) if value is not None else None

    @field_validator("age_basis_note", "creatinine_review_note", "baseline_review_note", "weight_basis_note", "rrt_basis_note")
    @classmethod
    def meaningful(cls, value):
        if value is not None and len(value.strip()) < 20:
            raise ValueError("临床及适用性依据须有至少20字有效内容")
        return value

    @model_validator(mode="after")
    def coherent_declarations(self):
        if len({item.interval_id for item in self.urine_intervals}) != len(self.urine_intervals):
            raise ValueError("原尿量区间不可重复选择")
        if self.serum_creatinine_confirmed and self.creatinine_review_note is None:
            raise ValueError("血清/血浆肌酐用途确认须有独立临床依据")
        if self.baseline_mode == "presumed_within_7d" and (self.baseline_creatinine is None or self.baseline_rise_within_7d_confirmed is None or self.baseline_review_note is None):
            raise ValueError("推定近7天急升须选择真实旧来源并明确临床确认及依据")
        if self.weight_applicability_confirmed and (self.weight_point is None or self.weight_basis_note is None):
            raise ValueError("体重适用于完整尿量期间的声明须绑定原点测及依据")
        if self.rrt_status == "unknown" and any(value is not None for value in (self.rrt_started_at, self.rrt_acute_aki_confirmed, self.rrt_basis_note)):
            raise ValueError("RRT未知时不能夹带启动或临床结论")
        if self.rrt_status != "unknown" and self.rrt_basis_note is None:
            raise ValueError("RRT临床状态须有独立签署依据")
        if self.rrt_status == "acute_initiated_for_aki" and (self.rrt_started_at is None or self.rrt_acute_aki_confirmed is not True):
            raise ValueError("急性AKI透析启动须明确原UTC时刻及急性适应证确认")
        if self.rrt_status == "not_initiated" and self.rrt_started_at is not None or self.rrt_status in {"not_initiated", "maintenance"} and self.rrt_acute_aki_confirmed is True:
            raise ValueError("未启动或维持透析不能同时声称新急性AKI启动")
        if self.rrt_started_at is not None and explicit_utc(self.rrt_started_at) > explicit_utc(self.evaluation_at):
            raise ValueError("RRT启动不能晚于明确评估时刻")
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
    role_at_creation: Literal["nurse", "doctor", "director", "admin", "super_admin"]
    doctor_id: int | None = Field(ge=1)
    doctor_user_id: int | None = Field(ge=1)
    care_authorization: Literal["authorized_original_admission_at_creation"]
    authorized_at: str
    clinical_review_signed: bool


def requires_clinical_review(req):
    return req.serum_creatinine_confirmed or req.baseline_mode == "presumed_within_7d" or req.baseline_rise_within_7d_confirmed is not None or req.rrt_status != "unknown"


def frozen_metadata(row):
    return {**{key: getattr(row, key) for key in FROZEN_FIELDS}, "evaluation_at": utc_text(row.evaluation_at), "created_at": utc_text(row.created_at)}


def metadata(row):
    governance = {"status": row.status, "revision": row.revision, "revoked_at": utc_text(row.revoked_at) if row.revoked_at else None, "revoked_by": row.revoked_by, "revoke_reason": row.revoke_reason}
    return {
        **frozen_metadata(row),
        "source_id": f"aki_assessment:{row.assessment_id}:{row.content_hash[:12]}",
        "content_hash": row.content_hash,
        **governance,
        "governance_hash": hash_content(governance),
    }


def window_binding(window):
    return {key: window[key] for key in ("window_id", "source_id", "content_hash", "schema_version", "start_at", "end_at", "as_of", "created_at")}


def original_governance(data, laboratory=False):
    keys = (*GOVERNANCE_FIELDS, "mapping_current", "eligible", "exclusion_reasons") if laboratory else GOVERNANCE_FIELDS
    return hash_content({key: data[key] for key in keys})


def lab_identity(data):
    mapping = data["snapshot"]["mapping"]
    return hash_content({"source_namespace": mapping["source_namespace"], **mapping["signature"]})


def compact_lab(data):
    """A marked clinical projection; complete original parent prose stays in its source."""
    projected = copy.deepcopy(data)
    projected["governance_hash"] = original_governance(data, True)
    projected["identity_hash"] = lab_identity(data)
    projected["snapshot"]["original"]["report"].pop("result", None)
    for key in ("check_type", "check_items"):
        projected["snapshot"]["original"]["order"].pop(key, None)
    projected["assessment_projection"] = "aki_lab_projection_v1"
    return projected


def lab_conflict(db, data, cutoff):
    from app.ai.observation_windows import MAX_ROWS, _laboratory_quality
    from app.inpatient_laboratory import source_current
    from app.models import InpatientLabSource

    rows = (
        db.query(InpatientLabSource)
        .filter(
            InpatientLabSource.patient_id == data["patient_id"],
            InpatientLabSource.admission_id == data["admission_id"],
            InpatientLabSource.collected_at_utc == explicit_utc(data["collected_at_utc"]),
            InpatientLabSource.registered_at <= cutoff,
            InpatientLabSource.available_at <= cutoff,
        )
        .populate_existing()
        .order_by(InpatientLabSource.lab_source_id)
        .limit(MAX_ROWS + 1)
        .all()
    )
    if len(rows) > MAX_ROWS:
        raise HTTPException(422, "同刻原检验超过工程上限，不能截断冲突核查")
    quality = _laboratory_quality([source_current(db, row, allow_revoked=True) for row in rows])
    return any(group["identity_hash"] == lab_identity(data) and group["state"] == "conflicting_values_or_reference" for group in quality["same_time_groups"])


def load_lab(db, actor, ref, patient_id, cutoff):
    from app.inpatient_laboratory import source_current
    from app.models import InpatientLabSource

    row = db.query(InpatientLabSource).filter_by(lab_source_id=ref.lab_source_id).populate_existing().one_or_none()
    if row is None or row.patient_id != patient_id:
        raise HTTPException(409, "所选原检验来源不存在或不属于当前患者")
    authorize_scope(db, actor, patient_id, row.admission_id)
    data = source_current(db, row)
    if data["content_hash"] != ref.expected_content_hash or data["snapshot"]["mapping"]["analyte_key"] != "creatinine":
        raise HTTPException(409, "所选肌酐原摘要或已审核项目分类不一致")
    if explicit_utc(data["registered_at"]) > cutoff or explicit_utc(data["available_at"]) > cutoff:
        raise HTTPException(409, "原肌酐在所选窗口截止后才登记可用，不能反推历史可用")
    result = compact_lab(data)
    result["conflict"] = lab_conflict(db, data, cutoff)
    return result


def urine_issues(window, selected):
    from app.ai.aki_contract import COVERAGE_ISSUES

    if not selected:
        return []
    begin = min(item["start_at"] for item in selected)
    end = max(item["end_at"] for item in selected)
    active = [item for item in window["urine_intervals"] if item["status"] == "active" and item["start_at"] < end and item["end_at"] > begin]
    selected_ids = {item["interval_id"] for item in selected}
    issues = {"unselected_active_interval"} if any(item["interval_id"] not in selected_ids for item in active) else set()
    maximum = None
    for item in sorted(active, key=lambda value: (value["start_at"], value["end_at"], value["interval_id"])):
        if maximum is not None and item["start_at"] < maximum:
            issues.add("overlap")
        maximum = max(maximum, item["end_at"]) if maximum else item["end_at"]
        payload = item["payload"]
        if payload["collection_completeness"] != "complete":
            issues.add("partial_collection")
        if payload["volume_ml"] is None:
            issues.add("unknown_volume")
        if payload["patient_total"] is not True:
            issues.add("not_patient_total")
    cursor = begin
    for item in sorted(selected, key=lambda value: (value["start_at"], value["end_at"], value["interval_id"])):
        if item["start_at"] > cursor:
            issues.add("gap")
        cursor = max(cursor, item["end_at"])
    return [code for code in COVERAGE_ISSUES if code in issues]


def resolve_selected(db, actor, req, window):
    from app.inpatient_observations import source_current
    from app.models import InpatientObservation, InpatientUrineInterval

    cutoff = explicit_utc(window["as_of"])
    lab_members = {item["lab_source_id"]: item for item in window["lab_observations"]}
    result = {}
    for role in LAB_ROLES:
        ref = getattr(req, role)
        result[role] = None
        if ref is None:
            continue
        data = load_lab(db, actor, ref, req.patient_id, cutoff)
        outside_allowed = role == "baseline_creatinine" and req.baseline_mode == "presumed_within_7d"
        if not outside_allowed:
            member = lab_members.get(ref.lab_source_id)
            if member is None or member["status"] != "active" or member["eligible"] is not True or member["content_hash"] != data["content_hash"] or data["admission_id"] != req.admission_id:
                raise HTTPException(409, "当前肌酐、48小时比较和观察基线须明确选择原窗口内可用来源")
        if explicit_utc(data["collected_at_utc"]) > explicit_utc(req.evaluation_at):
            raise HTTPException(422, "原肌酐采样晚于明确评估时刻")
        result[role] = data
    result["weight_point"] = None
    if req.weight_point is not None:
        row = db.query(InpatientObservation).filter_by(observation_id=req.weight_point.observation_id).populate_existing().one_or_none()
        data = source_current(db, row)
        member = next((item for item in window["points"] if item["observation_id"] == req.weight_point.observation_id), None)
        if (
            member is None
            or data["patient_id"] != req.patient_id
            or data["admission_id"] != req.admission_id
            or data["content_hash"] != req.weight_point.expected_content_hash
            or "body_weight" not in data["payload"]["measurements"]
        ):
            raise HTTPException(409, "体重须明确选择同原住院窗口内有真实kg测量或未测原因的原点测")
        if explicit_utc(data["observed_at"]) > explicit_utc(req.evaluation_at):
            raise HTTPException(422, "体重点测不能晚于评估时刻")
        data["governance_hash"] = original_governance(data)
        data["conflict"] = any(
            group["observed_at"] == data["observed_at"] and group["measurement_code"] == "body_weight" and group["state"] == "conflicting_values_or_missing_state"
            for group in window["quality"]["same_time_groups"]
        )
        result["weight_point"] = data
    members = {item["interval_id"]: item for item in window["urine_intervals"]}
    selected = []
    for ref in req.urine_intervals:
        row = db.query(InpatientUrineInterval).filter_by(interval_id=ref.interval_id).populate_existing().one_or_none()
        data = source_current(db, row)
        if ref.interval_id not in members or data["content_hash"] != ref.expected_content_hash or data["patient_id"] != req.patient_id or data["admission_id"] != req.admission_id:
            raise HTTPException(409, "尿量须明确选择同原住院窗口内的原区间及摘要")
        if not explicit_utc(window["start_at"]) <= explicit_utc(data["start_at"]) < explicit_utc(data["end_at"]) <= explicit_utc(req.evaluation_at):
            raise HTTPException(422, "尿量原区间须完整落在原窗与评估时刻之前，不裁剪或分摊")
        data["governance_hash"] = original_governance(data)
        selected.append(data)
    result["urine_intervals"] = sorted(selected, key=lambda item: (item["start_at"], item["end_at"], item["interval_id"]))
    result["urine_coverage_issues"] = urine_issues(window, selected)
    return result


def project_source(row, snapshot, window, profile):
    from app.ai.aki_contract import AkiSource

    req = snapshot["attestation"]

    def evidence(value):
        return hash_content(value) if value is not None else None

    def creatinine(item):
        if item is None:
            return None
        original = item["snapshot"]["original"]["observation"]
        return {
            **{
                key: item[key]
                for key in ("lab_source_id", "source_id", "content_hash", "governance_hash", "collected_at_utc", "registered_at", "available_at", "mapping_id", "mapping_content_hash", "conflict")
            },
            "mapping_governance_hash": item["mapping_current"]["governance_hash"],
            "identity_hash": lab_identity(item),
            "value": original["value_num"],
            "unit": original["unit"],
        }

    weight = snapshot["weight_point"]
    weight_projection = (
        None
        if weight is None
        else {
            "point_id": weight["observation_id"],
            **{key: weight[key] for key in ("source_id", "content_hash", "governance_hash", "observed_at", "recorded_at", "conflict")},
            **weight["payload"]["measurements"]["body_weight"],
        }
    )
    data = {
        "assessment_id": row.assessment_id,
        "source_id": metadata(row)["source_id"],
        "content_hash": row.content_hash,
        "source_governance_hash": metadata(row)["governance_hash"],
        "window_id": row.window_id,
        "window_source_id": window["source_id"],
        "window_content_hash": row.window_content_hash,
        **{key: window[key] for key in ("start_at", "end_at", "as_of")},
        "evaluation_at": utc_text(row.evaluation_at),
        "rule_profile_id": row.rule_profile_id,
        "rule_profile_source_id": profile["source_id"],
        "rule_profile_content_hash": row.rule_profile_content_hash,
        "rule_profile_governance_hash": profile["governance_hash"],
        "rule_id": RULE_ID,
        "recipe_digest": row.recipe_digest,
        "age_at_evaluation_years": req["age_at_evaluation_years"],
        "creatinine_review": {"serum_creatinine_confirmed": req["serum_creatinine_confirmed"], "evidence_hash": evidence(req["creatinine_review_note"])},
        **{role: creatinine(snapshot[role]) for role in LAB_ROLES},
        "baseline_mode": req["baseline_mode"],
        "baseline_review": None
        if req["baseline_rise_within_7d_confirmed"] is None or req["baseline_review_note"] is None
        else {"rise_within_7d_confirmed": req["baseline_rise_within_7d_confirmed"], "evidence_hash": evidence(req["baseline_review_note"])},
        "weight": weight_projection,
        "weight_applicability_confirmed": req["weight_applicability_confirmed"],
        "weight_evidence_hash": evidence(req["weight_basis_note"]),
        "urine_intervals": [
            {
                **{key: item[key] for key in ("interval_id", "source_id", "content_hash", "governance_hash", "start_at", "end_at", "recorded_at")},
                **{key: item["payload"][key] for key in ("volume_ml", "absent_reason", "collection_completeness", "patient_total")},
            }
            for item in snapshot["urine_intervals"]
        ],
        "urine_coverage_issues": snapshot["urine_coverage_issues"],
        "rrt": {"status": req["rrt_status"], "started_at": req["rrt_started_at"], "acute_aki_confirmed": req["rrt_acute_aki_confirmed"], "evidence_hash": evidence(req["rrt_basis_note"])},
    }
    return AkiSource.model_validate(data).model_dump(mode="json")


def create_assessment(db, user, values):
    from app.ai.observation_windows import snapshot_current

    req = values if isinstance(values, AssessmentCreate) else AssessmentCreate.model_validate(values)
    actor = actor_current(db, user)
    authorize_scope(db, actor, req.patient_id, req.admission_id)
    clinical = requires_clinical_review(req)
    doctor = clinical_qualification(db, actor, req.patient_id, req.admission_id) if clinical else None
    if clinical and doctor is None:
        raise HTTPException(403, "请由本次住院的照护医生确认肌酐用途、基线和RRT情况。")
    window = snapshot_current(db, actor, req.window_id)
    if window["schema_version"] != "inpatient_window_v2" or window["patient_id"] != req.patient_id or window["admission_id"] != req.admission_id or window["content_hash"] != req.expected_window_hash:
        raise HTTPException(409, "AKI须明确绑定当前原患者/住院的v2受控观测窗及摘要")
    evaluation = explicit_utc(req.evaluation_at)
    if not explicit_utc(window["start_at"]) <= evaluation <= explicit_utc(window["end_at"]):
        raise HTTPException(422, "明确评估时刻须在原窗口内")
    selected = resolve_selected(db, actor, req, window)
    profile = profile_current(db, req.rule_profile_id)
    now = utcnow()
    if profile["rule_id"] != RULE_ID or profile["content_hash"] != req.expected_rule_profile_hash or explicit_utc(profile["published_at"]) > now or explicit_utc(window["created_at"]) > now:
        raise HTTPException(409, "须选择已发布的当前KDIGO固定规则实施版本及其原摘要")
    row = AIAKIAssessment(
        assessment_id=str(uuid.uuid4()),
        patient_id=req.patient_id,
        admission_id=req.admission_id,
        window_id=req.window_id,
        window_content_hash=req.expected_window_hash,
        rule_profile_id=req.rule_profile_id,
        rule_profile_content_hash=req.expected_rule_profile_hash,
        recipe_digest=profile["recipe_digest"],
        evaluation_at=evaluation,
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
        "rule_profile": profile,
        "attestation": req.model_dump(mode="json"),
        "author_qualification": {
            "actor_id": actor.user_id,
            "role_at_creation": actor.user_role,
            "doctor_id": doctor.doctor_id if doctor else None,
            "doctor_user_id": doctor.user_id if doctor else None,
            "care_authorization": "authorized_original_admission_at_creation",
            "authorized_at": utc_text(now),
            "clinical_review_signed": clinical,
        },
        **selected,
        "source_verification": "explicit_user_attestation_not_independently_verified",
    }
    row.snapshot_json = canonical_json(snapshot)
    if len(row.snapshot_json.encode("utf-8")) > MAX_SNAPSHOT_BYTES:
        raise HTTPException(422, "AKI来源正文超过262144个UTF-8字节工程上限；未登记或截断")
    row.content_hash = hash_content(snapshot)
    project_source(row, snapshot, window, profile)
    db.add(row)
    return row


def assessment_current(db, row_or_id, allow_revoked=False, *, user=None):
    from app.ai.observation_windows import snapshot_current
    from app.models import Doctor, User

    identifier = canonical_id(row_or_id.assessment_id if isinstance(row_or_id, AIAKIAssessment) else row_or_id)
    row = db.query(AIAKIAssessment).filter_by(assessment_id=identifier).populate_existing().one_or_none()
    if row is None:
        raise HTTPException(409, "原AKI评估来源不存在")
    if user is None:
        raise HTTPException(422, "复验AKI来源须有实际当前请求者，请使用authorize_assessment")
    actor = actor_current(db, user)
    authorize_scope(db, actor, row.patient_id, row.admission_id)
    try:
        if not isinstance(row.snapshot_json, str) or len(row.snapshot_json.encode("utf-8")) > MAX_SNAPSHOT_BYTES:
            raise ValueError("正文超过工程上限")
        snapshot = json.loads(row.snapshot_json)
        if (
            row.schema_version != SCHEMA_VERSION
            or snapshot["rule_profile"]["rule_id"] != RULE_ID
            or row.snapshot_json != canonical_json(snapshot)
            or hash_content(snapshot) != row.content_hash
            or any(snapshot.get(key) != value for key, value in frozen_metadata(row).items())
        ):
            raise ValueError("冻结正文或绑定已改变")
        req = AssessmentCreate.model_validate(snapshot["attestation"])
        qualification = AuthorQualification.model_validate(snapshot["author_qualification"])
        expected = {
            "patient_id": row.patient_id,
            "admission_id": row.admission_id,
            "window_id": row.window_id,
            "expected_window_hash": row.window_content_hash,
            "rule_profile_id": row.rule_profile_id,
            "expected_rule_profile_hash": row.rule_profile_content_hash,
            "evaluation_at": utc_text(row.evaluation_at),
        }
        if (
            any(getattr(req, key) != value for key, value in expected.items())
            or snapshot.get("source_verification") != "explicit_user_attestation_not_independently_verified"
            or not row.evaluation_at <= row.created_at <= utcnow()
        ):
            raise ValueError("原选择、时钟或声明语义无效")
        clinical = requires_clinical_review(req)
        if qualification.actor_id != row.created_by or qualification.authorized_at != utc_text(row.created_at) or qualification.clinical_review_signed != clinical:
            raise ValueError("原签署身份或临床权限记录无效")
        if clinical and (qualification.role_at_creation not in {"doctor", "director", "super_admin"} or qualification.doctor_id is None or qualification.doctor_user_id != row.created_by):
            raise ValueError("原临床签署资格缺失")
        if not clinical and (qualification.doctor_id is not None or qualification.doctor_user_id is not None):
            raise ValueError("无临床声明却夹带医生签署")
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
            raise ValueError("原治理状态无效")
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError, RecursionError) as exc:
        raise HTTPException(409, "AKI冻结正文、身份、人工声明或治理完整性校验失败") from exc
    excluded = ["assessment_revoked"] if row.status == "revoked" else []
    if db.query(User.user_id).filter_by(user_id=row.created_by).first() is None:
        excluded.append("original_author_missing")
    if qualification.doctor_id is not None and db.query(Doctor.doctor_id).filter_by(doctor_id=qualification.doctor_id, user_id=qualification.doctor_user_id).first() is None:
        excluded.append("clinical_signer_relationship_changed")
    window = profile = None
    try:
        window = snapshot_current(db, actor, row.window_id)
        if window["schema_version"] != "inpatient_window_v2" or window["content_hash"] != row.window_content_hash or window_binding(window) != snapshot["window_binding"]:
            excluded.append("window_binding_changed")
        else:
            selected = resolve_selected(db, actor, req, window)
            if any(selected[key] != snapshot[key] for key in SELECTED_FIELDS):
                excluded.append("selected_sources_changed")
    except HTTPException:
        excluded.append("window_or_selected_source_not_current")
    try:
        profile = profile_current(db, row.rule_profile_id, allow_revoked=True)
        mutable = {"status", "revision", "revoked_at", "revoked_by", "revoke_reason", "governance_hash", "implementation_current", "eligible", "exclusion_reasons"}
        if (
            profile["rule_id"] != RULE_ID
            or profile["content_hash"] != row.rule_profile_content_hash
            or profile["recipe_digest"] != row.recipe_digest
            or {key: value for key, value in profile.items() if key not in mutable} != {key: value for key, value in snapshot["rule_profile"].items() if key not in mutable}
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
        raise HTTPException(409, "AKI原评估、规则、窗口、所选来源或签署身份已变化，不能继续执行")
    projection = project_source(row, snapshot, window, profile) if not excluded else None
    return {
        **metadata(row),
        "snapshot": snapshot,
        "specialist_source": projection,
        "eligible": not excluded,
        "exclusion_reasons": excluded,
        "freshness": {"state": "current" if not excluded else "revoked" if row.status == "revoked" else "stale"},
        "eligibility_basis": "source_and_rule_governance_not_clinical_applicability",
    }


def authorize_assessment(db, user, patient_id, admission_id, assessment_id, window_id=None):
    actor = actor_current(db, user)
    authorize_scope(db, actor, patient_id, admission_id)
    row = db.query(AIAKIAssessment).filter_by(assessment_id=canonical_id(assessment_id)).populate_existing().one_or_none()
    if row is None:
        raise HTTPException(404, "原AKI评估来源不存在")
    if row.patient_id != patient_id or row.admission_id != admission_id or window_id is not None and row.window_id != window_id:
        raise HTTPException(409, "AKI来源不属于当前原患者、住院或所选窗口")
    return assessment_current(db, row, user=actor)
