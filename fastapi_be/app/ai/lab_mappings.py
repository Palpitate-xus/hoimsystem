"""Explicit local laboratory identities; no inferred terminology or unit conversion."""

import datetime
import hashlib
import json
import uuid
from typing import Literal

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy.exc import IntegrityError

from app.ai.models import AILabMapping, utcnow

MAPPING_ROLES = {"super_admin"}
SCHEMA_VERSION = "lab_mapping_v1"
# These labels are management categories, not mappings of any local code or unit.
ANALYTES = {
    "creatinine": "肌酐",
    "lactate": "乳酸",
    "white_blood_cell_count": "白细胞计数",
    "platelet_count": "血小板计数",
    "total_bilirubin": "总胆红素",
    "c_reactive_protein": "C反应蛋白",
    "procalcitonin": "降钙素原",
    "arterial_oxygen_partial_pressure": "动脉氧分压",
    "culture_result": "培养结果",
}


def canonical_json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def iso(value):
    if not isinstance(value, datetime.datetime) or value.tzinfo is not None:
        raise ValueError("时刻必须是明确UTC语义的无时区datetime")
    return value.isoformat(timespec="microseconds") + "Z"


def canonical_id(value):
    try:
        if not isinstance(value, str) or str(uuid.UUID(value)) != value:
            raise ValueError()
    except (ValueError, AttributeError) as exc:
        raise HTTPException(422, "映射标识须为规范小写UUID") from exc
    return value


class SourceSignature(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    code_system: str = Field(min_length=1, max_length=80)
    code: str = Field(min_length=1, max_length=80)
    unit: str | None = Field(max_length=40)
    method: str = Field(min_length=1, max_length=100)
    specimen_type: str = Field(min_length=1, max_length=80)
    value_kind: Literal["numeric", "qualitative"]

    @field_validator("code_system", "code", "unit", "method", "specimen_type")
    @classmethod
    def exact_nonblank(cls, value):
        if value is not None and (not value.strip() or value != value.strip()):
            raise ValueError("原身份字段须明确填写，不接受空白或隐式清理/大小写转换")
        return value

    @model_validator(mode="after")
    def numeric_unit(self):
        if self.value_kind == "numeric" and self.unit is None:
            raise ValueError("数值映射必须提供精确原单位")
        return self


class MappingCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    source_namespace: str = Field(min_length=2, max_length=120)
    signature: SourceSignature
    analyte_key: str = Field(min_length=1, max_length=64)
    evidence_reference: str = Field(min_length=5, max_length=1000)
    rationale: str = Field(min_length=20, max_length=2000)

    @field_validator("source_namespace", "evidence_reference", "rationale")
    @classmethod
    def meaningful(cls, value, info):
        minimum = {"source_namespace": 2, "evidence_reference": 5, "rationale": 20}[info.field_name]
        if value != value.strip() or len(value.strip()) < minimum:
            raise ValueError("须提供有效原来源及审核依据，不能用空白补足长度")
        return value

    @field_validator("analyte_key")
    @classmethod
    def known_category(cls, value):
        if value not in ANALYTES:
            raise ValueError("请选择后端支持的项目分类；分类不预置临床映射")
        return value


def identity_hash(namespace, signature):
    return digest({"source_namespace": namespace, "signature": signature})


def create_mapping(db, user, values):
    from app.models import User

    user = db.query(User).filter_by(user_id=user.user_id).with_for_update().populate_existing().one_or_none()
    if user is None or user.user_role != "super_admin":
        raise HTTPException(403, "当前身份不能创建AI检验项目映射")
    values = MappingCreate.model_validate(values).model_dump(mode="json")
    identifier, now = str(uuid.uuid4()), utcnow()
    payload = {"mapping_id": identifier, "schema_version": SCHEMA_VERSION, **values, "analyte_label": ANALYTES[values["analyte_key"]], "created_by": user.user_id, "created_at": iso(now)}
    row = AILabMapping(
        mapping_id=identifier,
        schema_version=SCHEMA_VERSION,
        source_namespace=values["source_namespace"],
        **values["signature"],
        analyte_key=values["analyte_key"],
        identity_hash=identity_hash(values["source_namespace"], values["signature"]),
        published_key=None,
        payload_json=canonical_json(payload),
        content_hash=digest(payload),
        created_by=user.user_id,
        created_at=now,
        status="draft",
        revision=1,
        review_note="",
        revoke_reason="",
    )
    db.add(row)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "映射登记与当前原资料发生竞争，请刷新核对") from exc
    return row


def mapping_detail(db, mapping_or_id):
    identifier = canonical_id(mapping_or_id.mapping_id if isinstance(mapping_or_id, AILabMapping) else mapping_or_id)
    row = db.query(AILabMapping).filter_by(mapping_id=identifier).populate_existing().one_or_none()
    if row is None:
        raise HTTPException(404, "项目映射不存在")
    try:
        raw = json.loads(row.payload_json)
        values = MappingCreate.model_validate({key: raw[key] for key in MappingCreate.model_fields}).model_dump(mode="json")
        expected = {
            "mapping_id": identifier,
            "schema_version": SCHEMA_VERSION,
            **values,
            "analyte_label": ANALYTES[values["analyte_key"]],
            "created_by": row.created_by,
            "created_at": iso(row.created_at),
        }
        if row.schema_version != SCHEMA_VERSION or canonical_json(expected) != row.payload_json or digest(expected) != row.content_hash:
            raise ValueError("正文或摘要不一致")
        signature = values["signature"]
        if values["source_namespace"] != row.source_namespace or values["analyte_key"] != row.analyte_key or any(getattr(row, key) != value for key, value in signature.items()):
            raise ValueError("身份索引与原正文不一致")
        if row.identity_hash != identity_hash(row.source_namespace, signature) or type(row.created_by) is not int or row.created_by <= 0 or row.created_at > utcnow():
            raise ValueError("原登记或身份摘要无效")
        never_published = row.published_at is None and row.published_by is None and row.review_note == ""
        valid_publication = (
            isinstance(row.published_at, datetime.datetime)
            and row.published_at.tzinfo is None
            and row.created_at <= row.published_at <= utcnow()
            and type(row.published_by) is int
            and row.published_by > 0
            and isinstance(row.review_note, str)
            and 20 <= len(row.review_note.strip()) <= 2000
        )
        never_revoked = row.revoked_at is None and row.revoked_by is None and row.revoke_reason == ""
        valid_revocation = (
            isinstance(row.revoked_at, datetime.datetime)
            and row.revoked_at.tzinfo is None
            and (row.published_at or row.created_at) <= row.revoked_at <= utcnow()
            and type(row.revoked_by) is int
            and row.revoked_by > 0
            and isinstance(row.revoke_reason, str)
            and 5 <= len(row.revoke_reason.strip()) <= 1000
        )
        valid_state = (
            (row.status == "draft" and row.revision == 1 and row.published_key is None and never_published and never_revoked)
            or (row.status == "published" and row.revision == 2 and row.published_key == row.identity_hash and valid_publication and never_revoked)
            or (row.status == "revoked" and row.published_key is None and valid_revocation and ((row.revision == 2 and never_published) or (row.revision == 3 and valid_publication)))
        )
        if not valid_state:
            raise ValueError("治理状态无效")
        governance = {
            "status": row.status,
            "revision": row.revision,
            "published_at": iso(row.published_at) if row.published_at else None,
            "published_by": row.published_by,
            "review_note": row.review_note,
            "revoked_at": iso(row.revoked_at) if row.revoked_at else None,
            "revoked_by": row.revoked_by,
            "revoke_reason": row.revoke_reason,
        }
        return {**expected, "content_hash": row.content_hash, "source_id": f"lab_mapping:{identifier}:{row.content_hash[:12]}", **governance, "governance_hash": digest(governance)}
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        raise HTTPException(409, "映射原文、身份或治理状态已不符合不可变契约") from exc


def mapping_current(db, mapping_id, allow_revoked=False):
    data = mapping_detail(db, mapping_id)
    if data["status"] != "published" and not (allow_revoked and data["status"] == "revoked" and data["published_at"] is not None):
        raise HTTPException(409, "映射尚未审核发布或已撤销，不能作为当前项目身份")
    return data


def observation_signature(observation):
    numeric, qualitative = observation.value_num is not None, observation.value_text is not None
    if numeric == qualitative:
        raise HTTPException(409, "原指标数值/定性结果不符合来源契约")
    return {**{key: getattr(observation, key) for key in ("code_system", "code", "unit", "method", "specimen_type")}, "value_kind": "numeric" if numeric else "qualitative"}


def mapping_matches(mapping, observation):
    return mapping["signature"] == observation_signature(observation)


def matching_mappings(db, observation, source_namespace=None):
    signature = observation_signature(observation)
    query = db.query(AILabMapping).filter_by(status="published")
    if source_namespace is not None:
        query = query.filter_by(identity_hash=identity_hash(source_namespace, signature))
    else:
        for key, value in signature.items():
            query = query.filter(getattr(AILabMapping, key) == value)
    rows = query.order_by(AILabMapping.created_at, AILabMapping.mapping_id).limit(101).populate_existing().all()
    if len(rows) > 100:
        raise HTTPException(422, "候选映射过多，请明确来源命名空间，不能截断后自动选取")
    # Database collations may be case-insensitive; clinical identity is exact.
    result = [mapping_current(db, row.mapping_id) for row in rows]
    return [item for item in result if item["signature"] == signature and (source_namespace is None or item["source_namespace"] == source_namespace)]
