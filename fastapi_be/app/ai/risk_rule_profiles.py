"""Publish immutable fixed rule manifests without configuring thresholds or validating clinical outcomes."""

import datetime
import json
import uuid
from typing import Literal

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.ai.models import AIRiskRuleProfile, utcnow
from app.inpatient_laboratory import hash_content
from app.inpatient_observations import canonical_json, canonical_uuid, utc_text

PROFILE_ROLES = {"super_admin"}
SCHEMA_VERSION = "risk_rule_profile_v1"
MAX_PROFILE_BYTES = 262144
INPUT_POLICY = {
    "point_selection": "single_explicit_point",
    "temporal_fusion": "no_merge",
    "pulse_metric": "pulse_rate_only",
    "same_time_conflicts": "reject_same_time_relevant_conflict",
    "integer_chart_metrics": ["respiratory_rate", "spo2", "systolic_bp", "pulse_rate"],
    "temperature_step": "0.1",
    "rounding": "never",
    "imputation": "none",
    "unit_conversion": "none",
}


class ProfileCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    name: str = Field(min_length=1, max_length=120)
    rule_id: Literal["news2_2017"]
    expected_recipe_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    evidence_reference: str = Field(min_length=5, max_length=1000)
    rationale: str = Field(min_length=20, max_length=2000)

    @field_validator("name", "evidence_reference", "rationale")
    @classmethod
    def meaningful(cls, value, info):
        if len(value.strip()) < {"name": 1, "evidence_reference": 5, "rationale": 20}[info.field_name]:
            raise ValueError("须明确填写规则名称及实施审核依据，不用空白补足长度")
        return value


def canonical_id(value):
    try:
        return canonical_uuid(value)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


def fixed_options():
    from app.ai.news2_contract import RECIPE, recipe_digest

    return [{"rule_id": "news2_2017", "recipe_digest": recipe_digest(), "recipe": json.loads(canonical_json(RECIPE)), "input_policy": json.loads(canonical_json(INPUT_POLICY))}]


def actual_super(db, user):
    from app.models import User

    actor = db.query(User).filter_by(user_id=user.user_id).with_for_update().populate_existing().one_or_none()
    if actor is None or actor.user_role not in PROFILE_ROLES:
        raise HTTPException(403, "只有当前超级管理员可管理固定风险规则实施版本")
    return actor


def create_profile(db, user, values):
    user = actual_super(db, user)
    req = values if isinstance(values, ProfileCreate) else ProfileCreate.model_validate(values)
    option = fixed_options()[0]
    if req.expected_recipe_digest != option["recipe_digest"]:
        raise HTTPException(409, "规则实现已变化，请重新核对固定版本")
    now, identifier = utcnow(), str(uuid.uuid4())
    payload = {
        "rule_profile_id": identifier,
        "schema_version": SCHEMA_VERSION,
        "created_by": user.user_id,
        "created_at": utc_text(now),
        **req.model_dump(exclude={"expected_recipe_digest"}),
        **option,
        "clinical_validation": "not_provided",
        "review_basis": "human_implementation_review_not_clinical_validation",
    }
    raw = canonical_json(payload)
    if len(raw.encode("utf-8")) > MAX_PROFILE_BYTES:
        raise HTTPException(422, "规则实施正文超过UTF-8字节上限，不截断")
    row = AIRiskRuleProfile(
        rule_profile_id=identifier,
        schema_version=SCHEMA_VERSION,
        rule_id=req.rule_id,
        recipe_digest=option["recipe_digest"],
        policy_digest=hash_content(option["input_policy"]),
        identity_hash=hash_content({"rule_id": req.rule_id}),
        payload_json=raw,
        content_hash=hash_content(payload),
        created_by=user.user_id,
        created_at=now,
        status="draft",
        revision=1,
        implementation_terms_confirmed=0,
        review_note="",
        review_evidence_reference="",
        revoke_reason="",
    )
    db.add(row)
    return row


def profile_detail(db, row_or_id):
    identifier = canonical_id(row_or_id.rule_profile_id if isinstance(row_or_id, AIRiskRuleProfile) else row_or_id)
    row = db.query(AIRiskRuleProfile).filter_by(rule_profile_id=identifier).populate_existing().one_or_none()
    if row is None:
        raise HTTPException(404, "风险规则实施版本不存在")
    try:
        if not isinstance(row.payload_json, str) or len(row.payload_json.encode("utf-8")) > MAX_PROFILE_BYTES:
            raise ValueError("正文超过上限")
        raw = json.loads(row.payload_json)
        if not isinstance(raw, dict) or not isinstance(raw.get("recipe"), dict) or not isinstance(raw.get("input_policy"), dict):
            raise ValueError("正文结构无效")
        ProfileCreate.model_validate({key: raw[key] for key in ("name", "rule_id", "evidence_reference", "rationale")} | {"expected_recipe_digest": raw["recipe_digest"]})
        expected = {
            "rule_profile_id": row.rule_profile_id,
            "schema_version": row.schema_version,
            "rule_id": row.rule_id,
            "recipe_digest": row.recipe_digest,
            "created_by": row.created_by,
            "created_at": utc_text(row.created_at),
        }
        if row.schema_version != SCHEMA_VERSION or any(raw.get(key) != value for key, value in expected.items()) or canonical_json(raw) != row.payload_json or hash_content(raw) != row.content_hash:
            raise ValueError("冻结正文或身份索引不一致")
        if row.recipe_digest != hash_content(raw["recipe"]) or row.policy_digest != hash_content(raw["input_policy"]) or row.identity_hash != hash_content({"rule_id": row.rule_id}):
            raise ValueError("规则摘要或策略身份不一致")
        if type(row.created_by) is not int or row.created_by <= 0 or not row.created_at <= utcnow():
            raise ValueError("创建身份或时钟无效")
        never_published = row.published_at is None and row.published_by is None and row.review_note == "" and row.review_evidence_reference == "" and row.implementation_terms_confirmed == 0
        published = (
            isinstance(row.published_at, datetime.datetime)
            and row.published_at.tzinfo is None
            and row.created_at <= row.published_at <= utcnow()
            and type(row.published_by) is int
            and row.published_by > 0
            and row.implementation_terms_confirmed == 1
            and 20 <= len(row.review_note.strip()) <= 2000
            and 5 <= len(row.review_evidence_reference.strip()) <= 2000
        )
        never_revoked = row.revoked_at is None and row.revoked_by is None and row.revoke_reason == ""
        revoked = (
            isinstance(row.revoked_at, datetime.datetime)
            and row.revoked_at.tzinfo is None
            and (row.published_at or row.created_at) <= row.revoked_at <= utcnow()
            and type(row.revoked_by) is int
            and row.revoked_by > 0
            and 5 <= len(row.revoke_reason.strip()) <= 1000
        )
        valid = row.status == "draft" and row.revision == 1 and row.published_key is None and never_published and never_revoked
        valid = valid or row.status == "published" and row.revision == 2 and row.published_key == row.identity_hash and published and never_revoked
        valid = valid or row.status == "revoked" and row.published_key is None and revoked and (row.revision == 2 and never_published or row.revision == 3 and published)
        if not valid:
            raise ValueError("发布或撤销治理不一致")
        if raw.get("clinical_validation") != "not_provided" or raw.get("review_basis") != "human_implementation_review_not_clinical_validation":
            raise ValueError("实施审核语义改变")
        governance = {
            "status": row.status,
            "revision": row.revision,
            "published_at": utc_text(row.published_at) if row.published_at else None,
            "published_by": row.published_by,
            "implementation_terms_confirmed": row.implementation_terms_confirmed == 1,
            "review_note": row.review_note,
            "review_evidence_reference": row.review_evidence_reference,
            "revoked_at": utc_text(row.revoked_at) if row.revoked_at else None,
            "revoked_by": row.revoked_by,
            "revoke_reason": row.revoke_reason,
        }
        current = fixed_options()[0]
        implementation_current = raw["recipe"] == current["recipe"] and row.recipe_digest == current["recipe_digest"] and raw["input_policy"] == current["input_policy"]
        reasons = ([] if row.status == "published" else ["profile_not_published"]) + ([] if implementation_current else ["recipe_or_input_policy_changed"])
        return {
            **raw,
            "content_hash": row.content_hash,
            "source_id": f"risk_rule_profile:{identifier}:{row.content_hash[:12]}",
            **governance,
            "governance_hash": hash_content(governance),
            "implementation_current": implementation_current,
            "eligible": not reasons,
            "exclusion_reasons": reasons,
        }
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError, RecursionError) as exc:
        raise HTTPException(409, "固定规则正文、原发布身份或治理完整性校验失败") from exc


def profile_current(db, identifier, allow_revoked=False):
    data = profile_detail(db, identifier)
    if not allow_revoked and not data["eligible"]:
        raise HTTPException(409, "规则未发布、已撤销或当前实现已改变，不能执行旧版本")
    if allow_revoked and data["published_at"] is None:
        raise HTTPException(409, "从未发布的规则不能作为评估来源")
    return data
