"""Immutable admission-bound GCS originals with explicit, optional same-exam anchors."""

import datetime
import json
import uuid
from typing import Literal

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.inpatient_laboratory import hash_content
from app.inpatient_observations import OBSERVATION_ROLES, PointPayload, authorize_observation_admission, canonical_json, canonical_uuid, explicit_utc, utc_text

SCHEMA_VERSION = "inpatient_gcs_v1"
READ_ROLES = OBSERVATION_ROLES
MAX_SOURCE_BYTES = 32768
GOVERNANCE_FIELDS = ("status", "revision", "revoked_at", "revoked_by", "revoke_reason")


def utcnow():
    return datetime.datetime.now(datetime.UTC).replace(tzinfo=None)


class StrictInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Component(StrictInput):
    score: int | None = Field(ge=1, le=6)
    absent_reason: Literal["not_testable", "not_recorded"] | None

    @model_validator(mode="after")
    def measured_or_absent(self):
        if (self.score is None) == (self.absent_reason is None):
            raise ValueError("GCS各分项须且只能记录实际整数得分或未测原因，NT不能替为1")
        return self


class Components(StrictInput):
    eye: Component
    verbal: Component
    motor: Component

    @model_validator(mode="after")
    def original_ranges(self):
        for name, maximum in (("eye", 4), ("verbal", 5), ("motor", 6)):
            value = getattr(self, name).score
            if value is not None and value > maximum:
                raise ValueError(f"{name}原分项范围为1至{maximum}")
        return self


class AnchorReference(StrictInput):
    observation_id: str
    expected_content_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    _id = field_validator("observation_id")(canonical_uuid)


class GcsPayload(StrictInput):
    components: Components
    anchor_point: AnchorReference | None
    same_exam_confirmed: bool
    same_exam_basis_note: str | None = Field(min_length=20, max_length=1000)
    note: str = Field(default="", max_length=1000)

    @field_validator("same_exam_basis_note")
    @classmethod
    def meaningful(cls, value):
        if value is not None and len(value.strip()) < 20:
            raise ValueError("同次检查依据须至少20字有效内容")
        return value

    @model_validator(mode="after")
    def explicit_anchor(self):
        if self.anchor_point is None:
            if self.same_exam_confirmed or self.same_exam_basis_note is not None:
                raise ValueError("未关联原点测时须保留未确认同次检查及null依据")
        elif self.same_exam_confirmed is not True or self.same_exam_basis_note is None:
            raise ValueError("关联原点测须明确确认同次检查并保留独立依据")
        return self


class GcsCreate(StrictInput):
    patient_id: int = Field(ge=1, le=2147483647)
    admission_id: str
    observed_at: datetime.datetime
    payload: GcsPayload
    _id = field_validator("admission_id")(canonical_uuid)
    _clock = field_validator("observed_at", mode="before")(explicit_utc)

    @model_validator(mode="after")
    def no_future_clock(self):
        if self.observed_at > utcnow():
            raise ValueError("原GCS实际测量不能在未来，不按录入钟点替代实际时刻")
        return self


class GcsRevoke(StrictInput):
    patient_id: int = Field(ge=1, le=2147483647)
    admission_id: str
    expected_revision: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=1000)
    _id = field_validator("admission_id")(canonical_uuid)

    @field_validator("reason")
    @classmethod
    def meaningful(cls, value):
        if not value.strip():
            raise ValueError("撤销依据不能为空白")
        return value


def current_actor(db, user):
    from app.models import User

    actor = db.query(User).filter_by(user_id=user.user_id).populate_existing().one_or_none()
    if actor is None or actor.user_role not in READ_ROLES:
        raise HTTPException(403, "当前用户没有GCS原资料权限")
    return actor


def authorize_scope(db, user, patient_id, admission_id, *, creating=False):
    actor = current_actor(db, user)
    admission = authorize_observation_admission(db, actor, patient_id, admission_id)
    if creating:
        if admission.status != 1:
            raise HTTPException(409, "仅在院患者可新增GCS；出院后补录须另走明确补录流程")
        if actor.user_role not in {"nurse", "doctor", "director"}:
            from app.ai.news2_sources import clinical_qualification

            if actor.user_role != "super_admin" or clinical_qualification(db, actor, patient_id, admission_id) is None:
                raise HTTPException(403, "GCS原观测须由有原住院照护权的临床人员记录；管理权限不替代临床身份")
    return actor


def frozen_metadata(row):
    return {
        "gcs_observation_id": row.gcs_observation_id,
        "patient_id": row.patient_id,
        "admission_id": row.admission_id,
        "observed_at": utc_text(row.observed_at),
        "recorded_at": utc_text(row.recorded_at),
        "created_by": row.created_by,
        "schema_version": row.schema_version,
    }


def frozen_content(row, payload, anchor):
    return {**frozen_metadata(row), "payload": payload, "anchor_point_snapshot": anchor}


def derived_total(payload):
    scores = [payload["components"][name]["score"] for name in ("eye", "verbal", "motor")]
    return sum(scores) if all(type(score) is int for score in scores) else None


def _original_anchor(snapshot, ref, patient_id, admission_id):
    if ref is None:
        if snapshot is not None:
            raise ValueError("未选择锚点却存在冻结原点测")
        return
    if not isinstance(snapshot, dict) or snapshot.get("observation_id") != ref["observation_id"] or snapshot.get("content_hash") != ref["expected_content_hash"]:
        raise ValueError("冻结锚点标识或摘要不一致")
    if snapshot.get("patient_id") != patient_id or snapshot.get("admission_id") != admission_id or snapshot.get("schema_version") != "inpatient_observation_v1":
        raise ValueError("冻结原点测归属或版本不一致")
    payload = PointPayload.model_validate(snapshot["payload"]).model_dump(mode="json")
    frozen = {key: snapshot[key] for key in ("observation_id", "patient_id", "admission_id", "recorded_at", "created_by", "schema_version", "observed_at")}
    frozen["payload"] = payload
    if hash_content(frozen) != ref["expected_content_hash"] or snapshot.get("source_id") != f"inpatient_observation:{ref['observation_id']}:{ref['expected_content_hash'][:12]}":
        raise ValueError("冻结原点测完整性无效")
    if explicit_utc(snapshot["observed_at"]) > explicit_utc(snapshot["recorded_at"]) or snapshot.get("status") != "active":
        raise ValueError("冻结锚点原时钟或原状态无效")


def anchor_current(db, row, payload, anchor):
    from app.inpatient_observations import source_current as point_current
    from app.models import InpatientObservation

    ref = payload["anchor_point"]
    if ref is None:
        return False, ["no_explicit_original_point_anchor"]
    try:
        point_row = db.query(InpatientObservation).filter_by(observation_id=ref["observation_id"]).populate_existing().one_or_none()
        point = point_current(db, point_row)
        if point["patient_id"] != row.patient_id or point["admission_id"] != row.admission_id or point != anchor:
            return False, ["original_point_anchor_changed"]
    except HTTPException:
        return False, ["original_point_anchor_not_current"]
    return True, []


def source_current(db, row, *, allow_revoked=False):
    from app.models import Admission, InpatientGcsObservation

    if not isinstance(row, InpatientGcsObservation):
        raise HTTPException(409, "GCS来源类型无效")
    current = db.query(InpatientGcsObservation).filter_by(gcs_observation_id=row.gcs_observation_id).populate_existing().one_or_none()
    if current is None:
        raise HTTPException(409, "GCS原资料已不存在")
    try:
        canonical_uuid(current.gcs_observation_id)
        canonical_uuid(current.admission_id)
        if type(current.patient_id) is not int or current.patient_id < 1 or type(current.created_by) is not int or current.created_by < 1 or current.schema_version != SCHEMA_VERSION:
            raise ValueError("归属、作者或版本无效")
        if not isinstance(current.payload_json, str) or len(current.payload_json.encode("utf-8")) > MAX_SOURCE_BYTES:
            raise ValueError("原正文超过上限")
        payload = GcsPayload.model_validate(json.loads(current.payload_json)).model_dump(mode="json")
        anchor = json.loads(current.anchor_snapshot_json) if current.anchor_snapshot_json is not None else None
        _original_anchor(anchor, payload["anchor_point"], current.patient_id, current.admission_id)
        expected_anchor = payload["anchor_point"]["observation_id"] if payload["anchor_point"] else None
        if current.anchor_point_id != expected_anchor or current.payload_json != canonical_json(payload) or (anchor is not None and current.anchor_snapshot_json != canonical_json(anchor)):
            raise ValueError("原正文或锚点索引不一致")
        if current.content_hash != hash_content(frozen_content(current, payload, anchor)) or not current.observed_at <= current.recorded_at <= utcnow():
            raise ValueError("原摘要或时钟无效")
        if anchor is not None and explicit_utc(anchor["recorded_at"]) > current.recorded_at:
            raise ValueError("原锚点晚于本次GCS登记")
        if current.status == "active":
            if current.revision != 1 or current.revoked_at is not None or current.revoked_by is not None or current.revoke_reason != "":
                raise ValueError("活动来源治理无效")
        elif current.status == "revoked":
            if (
                current.revision != 2
                or current.revoked_at is None
                or type(current.revoked_by) is not int
                or current.revoked_by < 1
                or not 0 < len(current.revoke_reason.strip()) <= 1000
                or not current.recorded_at <= current.revoked_at <= utcnow()
            ):
                raise ValueError("撤销来源治理无效")
        else:
            raise ValueError("原状态无效")
    except (ValueError, TypeError, AttributeError, KeyError, OverflowError, RecursionError) as exc:
        raise HTTPException(409, "GCS原资料完整性校验失败") from exc
    if db.query(Admission).filter_by(admission_id=current.admission_id, patient_id=current.patient_id).populate_existing().one_or_none() is None:
        raise HTTPException(409, "GCS原住院不存在或归属变化")
    if current.status == "revoked" and not allow_revoked:
        raise HTTPException(409, "GCS原资料已撤销")
    governance = {key: utc_text(getattr(current, key)) if key == "revoked_at" and current.revoked_at is not None else getattr(current, key) for key in GOVERNANCE_FIELDS}
    valid_anchor, anchor_reasons = anchor_current(db, current, payload, anchor)
    return {
        **frozen_content(current, payload, anchor),
        "content_hash": current.content_hash,
        "source_id": f"gcs_observation:{current.gcs_observation_id}:{current.content_hash[:12]}",
        **governance,
        "governance_hash": hash_content(governance),
        "derived_total": derived_total(payload),
        "anchor_current": valid_anchor,
        "anchor_exclusion_reasons": anchor_reasons,
    }


def create_source(db, user, values):
    from app.inpatient_observations import source_current as point_current
    from app.models import InpatientGcsObservation, InpatientObservation

    req = values if isinstance(values, GcsCreate) else GcsCreate.model_validate(values)
    actor = authorize_scope(db, user, req.patient_id, req.admission_id, creating=True)
    payload = req.payload.model_dump(mode="json")
    anchor = None
    if req.payload.anchor_point is not None:
        ref = req.payload.anchor_point
        point_row = db.query(InpatientObservation).filter_by(observation_id=ref.observation_id).populate_existing().one_or_none()
        anchor = point_current(db, point_row)
        if anchor["patient_id"] != req.patient_id or anchor["admission_id"] != req.admission_id or anchor["content_hash"] != ref.expected_content_hash:
            raise HTTPException(409, "GCS须明确关联同患者、同原住院、原摘要完全一致的活动点测")
    now = utcnow()
    if req.observed_at > now or anchor is not None and explicit_utc(anchor["recorded_at"]) > now:
        raise HTTPException(409, "GCS实际观测或原锚点登记不能晚于本次登记")
    row = InpatientGcsObservation(
        gcs_observation_id=str(uuid.uuid4()),
        patient_id=req.patient_id,
        admission_id=req.admission_id,
        observed_at=req.observed_at,
        recorded_at=now,
        created_by=actor.user_id,
        schema_version=SCHEMA_VERSION,
        anchor_point_id=req.payload.anchor_point.observation_id if req.payload.anchor_point else None,
        payload_json=canonical_json(payload),
        anchor_snapshot_json=canonical_json(anchor) if anchor is not None else None,
        status="active",
        revision=1,
        revoke_reason="",
    )
    if len(row.payload_json.encode("utf-8")) > MAX_SOURCE_BYTES or row.anchor_snapshot_json is not None and len(row.anchor_snapshot_json.encode("utf-8")) > 65535:
        raise HTTPException(422, "完整GCS及原锚点超过UTF-8存储上限，不登记、不截断")
    row.content_hash = hash_content(frozen_content(row, payload, anchor))
    authorize_scope(db, actor, req.patient_id, req.admission_id, creating=True)
    db.add(row)
    return row
