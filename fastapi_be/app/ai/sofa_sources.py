"""Complete, governed 24-hour SOFA evidence; original facts are never imputed."""

import datetime
import json
import uuid
from collections import defaultdict
from fractions import Fraction
from typing import Annotated, Literal

from fastapi import HTTPException
from pydantic import AfterValidator, Field, field_validator, model_validator

from app.ai.news2_sources import ASSESSMENT_ROLES as ASSESSMENT_ROLES
from app.ai.news2_sources import actor_current, authorize_scope, clinical_qualification
from app.inpatient_laboratory import hash_content
from app.inpatient_observations import canonical_json, canonical_uuid, explicit_utc, utc_text
from app.inpatient_support_common import StrictInput

FROZEN_FIELDS = ("assessment_id", "patient_id", "admission_id", "rule_profile_id", "rule_profile_content_hash", "recipe_digest", "policy_digest", "manifest_digest", "created_by", "schema_version")
CLOCK_FIELDS = ("period_start", "period_end", "as_of", "evaluation_at", "created_at")

RULE_ID = "sofa1_native_observed_v1"
SCHEMA_VERSION = "sofa1_assessment_v1"
MANIFEST_SCHEMA_VERSION = "sofa1_period_manifest_v1"
MAX_MEMBERS = 4096
MAX_PRIVATE_BYTES = 8 * 1024 * 1024
MAX_PUBLIC_BYTES = 2 * 1024 * 1024
AXES = ("respiratory", "coagulation", "liver", "cardiovascular", "cns", "renal")
MEMBER_KINDS = ("laboratory", "map", "respiratory_support", "arterial_pair", "vasoactive", "gcs", "urine")
GOVERNANCE_FIELDS = ("status", "revision", "revoked_at", "revoked_by", "revoke_reason")
ANALYTES = {"platelet_count": "coagulation", "total_bilirubin": "liver", "creatinine": "renal", "arterial_oxygen_partial_pressure": "respiratory"}
HashText = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
CanonicalId = Annotated[str, AfterValidator(canonical_uuid)]
Kind = Literal["laboratory", "map", "respiratory_support", "arterial_pair", "vasoactive", "gcs", "urine"]
DrugKey = Literal["dopamine", "dobutamine", "epinephrine", "norepinephrine", "other"]
ExclusionReason = Literal["not_patient_measurement", "wrong_sample_or_analyte", "duplicate_record", "measurement_error", "not_applicable", "conflicting_alternative", "other_clinician_reason"]


def utcnow():
    return datetime.datetime.now(datetime.UTC).replace(tzinfo=None)


def canonical_time(value):
    instant = explicit_utc(value)
    if instant.year < 1000 or value != utc_text(instant):
        raise ValueError("须提交1000至9999年范围、含六位微秒和Z的规范UTC原时刻")
    return value


UtcText = Annotated[str, AfterValidator(canonical_time)]


def meaningful(value):
    if sum(not char.isspace() for char in value) < 20:
        raise ValueError("每项人工核实依据须至少20个非空白字符")
    return value


BasisNote = Annotated[str, Field(min_length=20, max_length=1000), AfterValidator(meaningful)]


class PeriodRequest(StrictInput):
    patient_id: int = Field(ge=1, le=2147483647)
    admission_id: CanonicalId
    period_start: UtcText
    period_end: UtcText
    as_of: UtcText

    @model_validator(mode="after")
    def fixed_day(self):
        start, end, cutoff = (explicit_utc(getattr(self, name)) for name in ("period_start", "period_end", "as_of"))
        if end - start != datetime.timedelta(days=1) or not end <= cutoff:
            raise ValueError("须为连续完整24小时且结束不晚于原资料可用截止")
        return self


class MemberReview(StrictInput):
    member_key: str = Field(min_length=1, max_length=200)
    expected_content_hash: HashText
    status: Literal["confirmed", "excluded", "unknown"]
    basis_note: BasisNote
    exclusion_reason: ExclusionReason | None

    @model_validator(mode="after")
    def explicit_exclusion(self):
        if (self.status == "excluded") != (self.exclusion_reason is not None):
            raise ValueError("仅明确排除的原件须填写固定排除原因")
        return self


class LaboratoryReview(MemberReview):
    kind: Literal["laboratory"]


class MapReview(MemberReview):
    kind: Literal["map"]


class RespiratorySupportReview(MemberReview):
    kind: Literal["respiratory_support"]


class ArterialPairReview(MemberReview):
    kind: Literal["arterial_pair"]
    qualifying_respiratory_support: Literal["yes", "no", "unknown"]
    support_qualification_basis_note: BasisNote


class VasoactiveReview(MemberReview):
    kind: Literal["vasoactive"]
    continuous_iv: Literal["confirmed", "not_confirmed", "unknown"]
    rate_scope: Literal["stream_rate", "agent_total", "unknown"]
    weight_use_confirmed: bool
    weight_basis_note: BasisNote
    mass_basis_compatible_confirmed: bool
    mass_basis_note: BasisNote


class GcsReview(MemberReview):
    kind: Literal["gcs"]
    interpretable: Literal["confirmed", "limited", "unknown"]
    sedation_confounding_status: Literal["excluded", "present", "unknown"]
    other_confounding_status: Literal["excluded", "present", "unknown"]
    confounding_basis_note: BasisNote


class UrineReview(MemberReview):
    kind: Literal["urine"]


AnyMemberReview = Annotated[LaboratoryReview | MapReview | RespiratorySupportReview | ArterialPairReview | VasoactiveReview | GcsReview | UrineReview, Field(discriminator="kind")]


class Coverage(StrictInput):
    source_inventory: Literal["complete", "incomplete", "unknown"]
    clinical_protocol: Literal["adequate", "incomplete", "unknown"]
    basis_note: BasisNote


class CardiovascularCoverage(Coverage):
    drug_exposure: Literal["none", "reviewed_intervals", "unknown"]
    no_other_unrepresented_exposure_confirmed: bool


class SixAxisCoverage(StrictInput):
    respiratory: Coverage
    coagulation: Coverage
    liver: Coverage
    cardiovascular: CardiovascularCoverage
    cns: Coverage
    renal: Coverage


class VasoactiveGroupReview(StrictInput):
    drug_key: DrugKey
    relation: Literal["single_stream", "distinct_parallel_streams", "agent_total", "unresolved"]
    relation_confirmed: bool
    dose_basis_consistency_confirmed: bool
    basis_note: BasisNote


class ConflictReview(StrictInput):
    group_id: str = Field(min_length=1, max_length=200)
    expected_group_digest: HashText
    status: Literal["resolved", "unresolved"]
    accepted_source_ids: list[Annotated[str, Field(min_length=1, max_length=200)]] = Field(max_length=MAX_MEMBERS)
    excluded_source_ids: list[Annotated[str, Field(min_length=1, max_length=200)]] = Field(max_length=MAX_MEMBERS)
    basis_note: BasisNote

    @model_validator(mode="after")
    def no_implicit_winner(self):
        accepted, excluded = set(self.accepted_source_ids), set(self.excluded_source_ids)
        if len(accepted) != len(self.accepted_source_ids) or len(excluded) != len(self.excluded_source_ids) or accepted & excluded:
            raise ValueError("冲突取舍集合不得重复或相交")
        if self.status == "unresolved" and (accepted or excluded):
            raise ValueError("未解决冲突不能偷偷指定赢家")
        return self


class AssessmentCreate(PeriodRequest):
    rule_profile_id: CanonicalId
    expected_rule_profile_hash: HashText
    expected_manifest_hash: HashText
    age_at_period_years: int | None = Field(ge=0, le=130)
    age_basis_note: BasisNote
    care_setting: Literal["icu", "other", "unknown"]
    care_setting_basis_note: BasisNote
    applicability_confirmed: bool
    member_reviews: list[AnyMemberReview] = Field(max_length=MAX_MEMBERS)
    coverage: SixAxisCoverage
    conflict_reviews: list[ConflictReview] = Field(max_length=MAX_MEMBERS)
    vasoactive_group_reviews: list[VasoactiveGroupReview] = Field(max_length=5)
    note: str = Field(max_length=1000)

    @model_validator(mode="after")
    def no_duplicate_reviews(self):
        for values in ([item.member_key for item in self.member_reviews], [item.group_id for item in self.conflict_reviews], [item.drug_key for item in self.vasoactive_group_reviews]):
            if len(values) != len(set(values)):
                raise ValueError("逐源、冲突或药物流组人工判读不得重复")
        return self


class AssessmentRevoke(StrictInput):
    patient_id: int = Field(ge=1, le=2147483647)
    admission_id: CanonicalId
    expected_revision: int = Field(ge=1, le=2)
    reason: str = Field(min_length=1, max_length=1000)

    @field_validator("reason")
    @classmethod
    def reason_present(cls, value):
        if not value.strip():
            raise ValueError("撤销依据不能为空")
        return value


def _governance(source):
    return source.get("governance_hash") or hash_content({key: source[key] for key in GOVERNANCE_FIELDS})


def _source_cutoff(source, cutoff, patient_id, admission_id):
    """Check actual reliable clocks only; legacy naive dates are never promoted to UTC."""
    if source.get("patient_id") != patient_id or source.get("admission_id") != admission_id:
        raise HTTPException(409, "完整原始依赖不属于同一原患者及住院")
    for key in ("recorded_at", "registered_at", "available_at"):
        if source.get(key) is not None and explicit_utc(source[key]) > cutoff:
            raise HTTPException(409, "完整原始依赖实际登记或可用晚于截止，不能回填历史资料")
    if source.get("mapping_current", {}).get("published_at") is not None and explicit_utc(source["mapping_current"]["published_at"]) > cutoff:
        raise HTTPException(409, "原检验映射实际发布晚于截止")
    if source.get("payload", {}).get("anchor_point") is not None and not source.get("anchor_current"):
        raise HTTPException(409, "原GCS明确锚点已失效，不能伪造可用原件")
    for nested in (source.get("anchor_point_snapshot"), *source.get("reference_snapshots", {}).values()):
        if nested is None:
            continue
        if "patient_id" in nested:
            _source_cutoff(nested, cutoff, patient_id, admission_id)
        elif nested.get("published_at") is not None and explicit_utc(nested["published_at"]) > cutoff:
            raise HTTPException(409, "原药物映射实际发布晚于截止")


def _member(kind, identifier, source, role="period"):
    excluded = sorted(set(source.get("exclusion_reasons", []) + (["source_revoked"] if source["status"] != "active" else [])))
    return {
        "member_key": f"{kind}:{identifier}",
        "kind": kind,
        "identifier": identifier,
        "source_id": source["source_id"],
        "content_hash": source["content_hash"],
        "governance_hash": _governance(source),
        "full_source": source,
        "temporal_role": role,
        "eligible": not excluded,
        "exclusion_reasons": excluded,
    }


def stream_key(source):
    identity = source["payload"]["stream_identity"]
    return hash_content({key: identity[key] for key in ("source_namespace", "external_stream_id")})


def _interval_body(row, kind):
    """Authenticate the closed original before filtering; unrelated old parents are not loaded."""
    from app import inpatient_support_common as common

    try:
        spec = common.definition(kind)
        for name in ("support_source_id", "admission_id"):
            canonical_uuid(getattr(row, name))
        if row.schema_version != spec.schema_version or type(row.patient_id) is not int or row.patient_id <= 0 or type(row.created_by) is not int or row.created_by <= 0:
            raise ValueError("原元数据不符")
        for name, cap in (("payload_json", common.MAX_PAYLOAD_BYTES), ("reference_snapshot_json", common.MAX_SOURCE_BYTES), ("author_qualification_json", common.MAX_PAYLOAD_BYTES)):
            if not isinstance(getattr(row, name), str) or len(getattr(row, name).encode("utf-8")) > cap:
                raise ValueError("原正文容量不符")
        payload = spec.payload_model.model_validate(json.loads(row.payload_json)).model_dump(mode="json")
        references, qualification = json.loads(row.reference_snapshot_json), json.loads(row.author_qualification_json)
        if not isinstance(references, dict) or any(
            getattr(row, name) != canonical_json(value) for name, value in (("payload_json", payload), ("reference_snapshot_json", references), ("author_qualification_json", qualification))
        ):
            raise ValueError("原正文不规范")
        common._validate_qualification(row, spec, qualification)
        body = common.frozen_content(row, spec, payload, references, qualification)
        if row.content_hash != hash_content(body) or len(canonical_json(body).encode("utf-8")) > common.MAX_SOURCE_BYTES:
            raise ValueError("原本体hash不符")
        start, end = explicit_utc(payload["start_at"]), explicit_utc(payload["verified_until_at"])
        if row.event_at != start or row.recorded_at.tzinfo is not None or not start < end <= row.recorded_at <= utcnow():
            raise ValueError("原明确连续区段时刻不符")
        _validate_governance(row, row.recorded_at)
        return payload
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError, RecursionError) as exc:
        raise HTTPException(409, "原持续来源本体、时刻或治理完整性不符，不能按未验结束时刻跳过") from exc


def _validate_governance(row, created):
    active = row.status == "active" and row.revision == 1 and row.revoked_at is None and row.revoked_by is None and row.revoke_reason == ""
    revoked = (
        row.status == "revoked"
        and row.revision == 2
        and isinstance(row.revoked_at, datetime.datetime)
        and row.revoked_at.tzinfo is None
        and created <= row.revoked_at <= utcnow()
        and type(row.revoked_by) is int
        and row.revoked_by > 0
        and isinstance(row.revoke_reason, str)
        and 0 < len(row.revoke_reason.strip()) <= 1000
    )
    if not active and not revoked:
        raise ValueError("原治理状态不符")


def _laboratory_analyte(row):
    """Use authenticated frozen semantics before loading parents of relevant axes only."""
    from app import inpatient_laboratory as labs
    from app.ai.lab_mappings import ANALYTES as MAPPED_ANALYTES

    try:
        for key in ("lab_source_id", "admission_id", "mapping_id"):
            canonical_uuid(getattr(row, key))
        labs.opaque_id(row.observation_id)
        if not isinstance(row.snapshot_json, str) or len(row.snapshot_json.encode("utf-8")) > labs.MAX_SNAPSHOT_BYTES:
            raise ValueError("原正文容量不符")
        snapshot = json.loads(row.snapshot_json)
        if row.schema_version != labs.SCHEMA_VERSION or row.snapshot_json != canonical_json(snapshot) or row.content_hash != hash_content(snapshot):
            raise ValueError("原全文或摘要不符")
        if any(snapshot.get(key) != value for key, value in labs.frozen_metadata(row).items()):
            raise ValueError("冻结原元数据不符")
        mapping = snapshot["mapping"]
        if mapping["mapping_id"] != row.mapping_id or mapping["content_hash"] != row.mapping_content_hash or mapping["analyte_key"] not in MAPPED_ANALYTES:
            raise ValueError("原冻结映射身份不符")
        if not row.collected_at_utc <= row.registered_at == row.available_at <= utcnow() or explicit_utc(mapping["published_at"]) > row.registered_at:
            raise ValueError("原可靠时刻不符")
        _validate_governance(row, row.registered_at)
        if row.active_observation_id != (row.observation_id if row.status == "active" else None):
            raise ValueError("原活动索引不符")
        return mapping["analyte_key"]
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError, RecursionError) as exc:
        raise HTTPException(409, "原检验本体、冻结映射身份或可靠UTC时刻不符，不能按未验正文过滤") from exc


def _conflict_groups(members):
    groups = defaultdict(list)
    for member in members:
        source, kind = member["full_source"], member["kind"]
        if kind == "laboratory":
            axis = ANALYTES[source["snapshot"]["mapping"]["analyte_key"]]
            groups[(axis, "laboratory_original", source["observation_id"])].append(member)
        elif kind == "arterial_pair":
            original = source["reference_snapshots"]["pao2"]["observation_id"]
            groups[("respiratory", "arterial_original", original)].append(member)
        elif kind == "gcs" and source["anchor_point_snapshot"] is not None:
            groups[("cns", "explicit_gcs_anchor", source["anchor_point_snapshot"]["observation_id"])].append(member)
    # Actual positive-overlap components, not mere equal timestamps or nearby samples.
    for kind, axis in (("urine", "renal"), ("vasoactive", "cardiovascular")):
        candidates = [member for member in members if member["kind"] == kind]
        buckets = defaultdict(list)
        for member in candidates:
            source = member["full_source"]
            buckets[stream_key(source) if kind == "vasoactive" else "patient_total"].append(member)
        for identity, bucket in sorted(buckets.items()):
            intervals = sorted(bucket, key=lambda member: (member["full_source"].get("start_at") or member["full_source"]["payload"]["start_at"], member["member_key"]))
            component, component_end = [], None
            for member in intervals:
                source = member["full_source"]
                start = source.get("start_at") or source["payload"]["start_at"]
                end = source.get("end_at") or source["payload"]["verified_until_at"]
                if component_end is not None and start >= component_end:
                    if len(component) > 1:
                        groups[(axis, f"overlapping_{kind}", identity + ":" + component[0]["member_key"])].extend(component)
                    component, component_end = [], None
                component.append(member)
                component_end = max(component_end or end, end)
            if len(component) > 1:
                groups[(axis, f"overlapping_{kind}", identity + ":" + component[0]["member_key"])].extend(component)
    result = []
    for (axis, relation, identity), items in sorted(groups.items()):
        if len(items) < 2:
            continue
        ordered = sorted(items, key=lambda item: item["member_key"])
        identity_hash = hash_content({"axis": axis, "relation": relation, "identity": identity})
        membership = [{key: member[key] for key in ("member_key", "source_id", "content_hash", "governance_hash")} for member in ordered]
        result.append(
            {
                "group_id": f"sofa_conflict:{identity_hash}",
                "axis": axis,
                "relation": relation,
                "group_digest": hash_content(membership),
                "member_keys": [member["member_key"] for member in ordered],
                "member_source_ids": [member["source_id"] for member in ordered],
            }
        )
    return sorted(result, key=lambda group: group["group_id"])


def period_manifest(db, user, pid, adm, start, end, asof):
    """Enumerate every cutoff-visible original and validate its complete current parent chain."""
    from app import inpatient_gcs, inpatient_laboratory, inpatient_observations, inpatient_support_common
    from app.inpatient_respiratory_models import InpatientArterialPairSource, InpatientMapSource, InpatientRespiratorySource
    from app.inpatient_vasoactive_models import InpatientVasoactiveSource
    from app.models import InpatientGcsObservation, InpatientLabSource, InpatientUrineInterval

    values = PeriodRequest.model_validate({"patient_id": pid, "admission_id": adm, "period_start": start, "period_end": end, "as_of": asof})
    actor = actor_current(db, user)
    authorize_scope(db, actor, pid, adm)
    lower, upper, cutoff = (explicit_utc(getattr(values, field)) for field in ("period_start", "period_end", "as_of"))
    if cutoff > utcnow():
        raise HTTPException(422, "原资料截止不得晚于服务器当前UTC时刻")
    prefix = lower - datetime.timedelta(hours=1)
    members = []

    def append(kind, identifier, source, role="period"):
        _source_cutoff(source, cutoff, pid, adm)
        members.append(_member(kind, identifier, source, role))
        if len(members) > MAX_MEMBERS:
            raise HTTPException(422, "完整24小时原始成员超过4096条，不能截断或静默选择")

    for row in (
        db.query(InpatientLabSource)
        .filter(
            InpatientLabSource.patient_id == pid,
            InpatientLabSource.admission_id == adm,
            InpatientLabSource.collected_at_utc >= lower,
            InpatientLabSource.collected_at_utc < upper,
            InpatientLabSource.registered_at <= cutoff,
            InpatientLabSource.available_at <= cutoff,
        )
        .populate_existing()
        .order_by(InpatientLabSource.lab_source_id)
        .all()
    ):
        if _laboratory_analyte(row) in ANALYTES:
            source = inpatient_laboratory.source_current(db, row, allow_revoked=True)
            append("laboratory", row.lab_source_id, source)
    for kind, model, clock in (
        ("gcs", InpatientGcsObservation, InpatientGcsObservation.observed_at),
        ("map", InpatientMapSource, InpatientMapSource.event_at),
        ("arterial_pair", InpatientArterialPairSource, InpatientArterialPairSource.event_at),
    ):
        for row in (
            db.query(model)
            .filter(model.patient_id == pid, model.admission_id == adm, model.recorded_at <= cutoff, clock >= lower, clock < upper)
            .populate_existing()
            .order_by(model.__table__.primary_key.columns.values()[0])
            .all()
        ):
            source = inpatient_gcs.source_current(db, row, allow_revoked=True) if kind == "gcs" else inpatient_support_common.source_current(db, row, kind, allow_revoked=True)
            append(kind, row.gcs_observation_id if kind == "gcs" else row.support_source_id, source)
    for kind, model in (("respiratory_support", InpatientRespiratorySource), ("vasoactive", InpatientVasoactiveSource)):
        interval_start = prefix if kind == "vasoactive" else lower
        for row in (
            db.query(model).filter(model.patient_id == pid, model.admission_id == adm, model.recorded_at <= cutoff, model.event_at < upper).populate_existing().order_by(model.support_source_id).all()
        ):
            payload = _interval_body(row, kind)
            actual_end = explicit_utc(payload["verified_until_at"])
            if actual_end > interval_start:
                source = inpatient_support_common.source_current(db, row, kind, allow_revoked=True)
                append(kind, row.support_source_id, source, "prefix" if kind == "vasoactive" and actual_end <= lower else "period")
    for row in (
        db.query(InpatientUrineInterval)
        .filter(
            InpatientUrineInterval.patient_id == pid,
            InpatientUrineInterval.admission_id == adm,
            InpatientUrineInterval.recorded_at <= cutoff,
            InpatientUrineInterval.start_at < upper,
            InpatientUrineInterval.end_at > lower,
        )
        .populate_existing()
        .order_by(InpatientUrineInterval.interval_id)
        .all()
    ):
        append("urine", row.interval_id, inpatient_observations.source_current(db, row, allow_revoked=True))
    members.sort(key=lambda member: (member["kind"], member["identifier"]))
    result = {"schema_version": MANIFEST_SCHEMA_VERSION, **values.model_dump(mode="json"), "members": members, "conflict_groups": _conflict_groups(members)}
    return {**result, "content_hash": hash_content(result)}


def candidates(db, user, values):
    from app.ai.models import AIRiskRuleProfile
    from app.ai.risk_rule_profiles import profile_current

    req = values if isinstance(values, PeriodRequest) else PeriodRequest.model_validate(values)
    manifest = period_manifest(db, user, req.patient_id, req.admission_id, req.period_start, req.period_end, req.as_of)
    profiles = []
    for row in db.query(AIRiskRuleProfile).filter_by(rule_id=RULE_ID, status="published").order_by(AIRiskRuleProfile.rule_profile_id).all():
        profile = profile_current(db, row.rule_profile_id, allow_revoked=True)
        if profile["eligible"]:
            profiles.append(profile)
    return {
        "manifest": manifest,
        "can_sign": clinical_qualification(db, user, req.patient_id, req.admission_id) is not None,
        "profiles": profiles,
        "options": {"member_kinds": list(MEMBER_KINDS), "axes": list(AXES), "request_schema": AssessmentCreate.model_json_schema()},
    }


def frozen_metadata(row):
    return {**{name: getattr(row, name) for name in FROZEN_FIELDS}, **{name: utc_text(getattr(row, name)) for name in CLOCK_FIELDS}}


def metadata(row):
    governance = {name: utc_text(row.revoked_at) if name == "revoked_at" and row.revoked_at is not None else getattr(row, name) for name in GOVERNANCE_FIELDS}
    return {
        **frozen_metadata(row),
        "source_id": f"sofa_assessment:{row.assessment_id}:{row.content_hash[:12]}",
        "content_hash": row.content_hash,
        **governance,
        "governance_hash": hash_content(governance),
        "projection_hash": row.projection_hash,
    }


def _bounded(value, cap, description):
    try:
        encoded = canonical_json(value)
        count = len(encoded.encode("utf-8"))
    except (ValueError, TypeError, RecursionError) as exc:
        raise HTTPException(422, f"{description}须为完整有限且可编码的UTF-8 JSON，未保存") from exc
    if count > cap:
        raise HTTPException(422, f"{description}超过{cap}个UTF-8字节，不写入、不截断")
    return encoded


def _dependency_review_origins(manifest):
    roots = {member["source_id"] for member in manifest["members"] if member["kind"] == "respiratory_support"}
    return {
        member["member_key"]: {"support": "root_member" if member["full_source"]["reference_snapshots"]["support"]["source_id"] in roots else "pair_dependency"}
        for member in manifest["members"]
        if member["kind"] == "arterial_pair"
    }


def _validate_reviews(req, manifest):
    expected = {member["member_key"]: member for member in manifest["members"]}
    reviews = {review.member_key: review for review in req.member_reviews}
    if set(expected) != set(reviews):
        raise HTTPException(409, "须逐项明确判读完整原始成员，含撤销及排除原件，不得漏选或增加")
    for key, member in expected.items():
        review = reviews[key]
        if review.kind != member["kind"] or review.expected_content_hash != member["content_hash"]:
            raise HTTPException(409, "逐源核实类型或完整原文摘要不一致")
        if not member["eligible"] and review.status != "excluded":
            raise HTTPException(409, "撤销或不合当前治理的完整原件须明确排除，不得人工覆写原治理")
        if member["kind"] == "arterial_pair" and review.qualifying_respiratory_support == "yes" and member["full_source"]["reference_snapshots"]["support"]["payload"]["delivery_mode"] == "none":
            raise HTTPException(409, "原明确无呼吸支持不能由当前资格声明覆写为有支持，须保留并核对实际原件")
        if (
            member["kind"] == "vasoactive"
            and member["full_source"]["payload"]["start_at"] < req.period_end
            and member["full_source"]["payload"]["verified_until_at"] > req.period_start
            and review.status == "confirmed"
            and req.coverage.cardiovascular.drug_exposure == "none"
            and _known_positive_exposure(member["full_source"]["payload"]["dose_input"])
        ):
            raise HTTPException(409, "同日明确接受的原持续给药存在已知正剂量，不能同时声明无给药暴露")
    conflicts = {review.group_id: review for review in req.conflict_reviews}
    if set(conflicts) != {group["group_id"] for group in manifest["conflict_groups"]}:
        raise HTTPException(409, "须逐一核实全部实际冲突组，不得漏选或添加")
    by_source = {member["source_id"]: reviews[member["member_key"]] for member in manifest["members"]}
    for group in manifest["conflict_groups"]:
        review = conflicts[group["group_id"]]
        accepted, excluded = set(review.accepted_source_ids), set(review.excluded_source_ids)
        if review.expected_group_digest != group["group_digest"]:
            raise HTTPException(409, "冲突组完整成员摘要已变化")
        if review.status == "resolved":
            if accepted | excluded != set(group["member_source_ids"]) or any(by_source[key].status != "confirmed" for key in accepted) or any(by_source[key].status != "excluded" for key in excluded):
                raise HTTPException(409, "已解决冲突须完整分割原成员并与每件明确接受或排除判读一致")
    actual_drugs = {member["full_source"]["reference_snapshots"]["drug_mapping"]["drug_key"] for member in manifest["members"] if member["kind"] == "vasoactive"}
    if actual_drugs != {review.drug_key for review in req.vasoactive_group_reviews}:
        raise HTTPException(409, "须对实际全部原药物给出完整流关系核实，不得虚构或漏掉药物流组")


def _known_positive_exposure(dose):
    def positive(quantity):
        return quantity["value"] is not None and Fraction(quantity["value"]) > 0

    if dose["mode"] == "pump":
        return positive(dose["concentration"]) and positive(dose["pump_rate"])
    return positive(dose["rate"])


def _binding(source):
    return {"source_id": source["source_id"], "content_hash": source["content_hash"], "governance_hash": _governance(source)}


def _original_binding(source):
    return {**_binding(source), "recorded_at": source.get("recorded_at") or source["registered_at"]}


def _review(review):
    return {"status": review["status"], "basis_hash": hash_content(review["basis_note"]), "exclusion_reason": review["exclusion_reason"]}


def _lab_projection(source, review):
    from app.ai.sofa_contract import LIS_NATIVE_UNITS

    original, mapping = source["snapshot"]["original"]["observation"], source["snapshot"]["mapping"]
    value = original["value_num"]
    raw_unit = original["unit"]
    return {
        **_original_binding(source),
        **{key: source[key] for key in ("lab_source_id", "collected_at_utc", "registered_at", "available_at", "mapping_id")},
        "mapping_content_hash": mapping["content_hash"],
        "mapping_governance_hash": source["mapping_current"]["governance_hash"],
        "identity_hash": hash_content({"observation_id": source["observation_id"]}),
        "analyte": mapping["analyte_key"],
        "quantity": {
            "value": value,
            "unit": raw_unit if raw_unit in LIS_NATIVE_UNITS else "unknown" if raw_unit is None else "unsupported",
            "original_unit_hash": hash_content(raw_unit),
            "absent_reason": "unknown" if value is None else None,
            "value_kind": "qualitative" if value is None else "numeric",
        },
        "review": _review(review),
    }


def _support_projection(source, review):
    payload = source["payload"]
    return {
        **_original_binding(source),
        "support_source_id": source["support_source_id"],
        **{key: payload[key] for key in ("start_at", "verified_until_at", "ended_at", "delivery_mode", "continuity_confirmed")},
        "review": _review(review),
    }


def _projection(row, snapshot):
    from app.ai.sofa_contract import SofaSource

    attestation, manifest, profile = snapshot["attestation"], snapshot["manifest"], snapshot["rule_profile"]
    reviews = {review["member_key"]: review for review in attestation["member_reviews"]}
    members = manifest["members"]
    roots = {(member["kind"], member["identifier"]): member for member in members}
    by_source = {member["source_id"]: reviews[member["member_key"]] for member in members}
    labs, maps, gcs, urine, supports, respiratory, vaso = [], [], [], [], [], [], defaultdict(list)
    pair_labs = set()
    for member in members:
        kind, source, review = member["kind"], member["full_source"], reviews[member["member_key"]]
        if kind == "laboratory" and source["snapshot"]["mapping"]["analyte_key"] != "arterial_oxygen_partial_pressure":
            labs.append(_lab_projection(source, review))
        elif kind == "map":
            maps.append(
                {
                    **_original_binding(source),
                    "support_source_id": source["support_source_id"],
                    "observed_at": source["payload"]["observed_at"],
                    "quantity": source["payload"]["map"],
                    "measurement_method": source["payload"]["measurement_method"],
                    "review": _review(review),
                }
            )
        elif kind == "gcs":
            anchor = source["anchor_point_snapshot"]
            gcs.append(
                {
                    **_original_binding(source),
                    "gcs_observation_id": source["gcs_observation_id"],
                    "observed_at": source["observed_at"],
                    "components": source["payload"]["components"],
                    "interpretable": review["interpretable"],
                    "sedation_confounding_status": review["sedation_confounding_status"],
                    "other_confounding_status": review["other_confounding_status"],
                    "confounding_basis_hash": hash_content(review["confounding_basis_note"]),
                    "anchor": _original_binding(anchor) if anchor is not None else None,
                    "anchor_current": source["anchor_current"] if anchor is not None else True,
                    "review": _review(review),
                }
            )
        elif kind == "urine":
            urine.append(
                {
                    **_original_binding(source),
                    **{key: source[key] for key in ("interval_id", "start_at", "end_at")},
                    **{key: source["payload"][key] for key in ("volume_ml", "absent_reason", "collection_completeness", "patient_total")},
                    "review": _review(review),
                }
            )
        elif kind == "respiratory_support":
            supports.append(_support_projection(source, review))
        elif kind == "arterial_pair":
            refs, payload = source["reference_snapshots"], source["payload"]
            pao2, fio2, support = refs["pao2"], refs["fio2"], refs["support"]
            lab_member = roots[("laboratory", pao2["lab_source_id"])]
            lab_review = reviews[lab_member["member_key"]]
            pair_labs.add(pao2["lab_source_id"])
            support_review = by_source.get(support["source_id"], review)
            respiratory.append(
                {
                    "candidate_id": source["source_id"],
                    "pao2": _lab_projection(pao2, lab_review),
                    "pair": {**_original_binding(source), "support_source_id": source["support_source_id"]},
                    "fio2": {**_original_binding(fio2), "observation_id": fio2["observation_id"], "observed_at": fio2["observed_at"], "quantity": fio2["payload"]["measurements"]["fio2"]},
                    "support": _support_projection(support, support_review),
                    **{key: payload[key] for key in ("arterial_sample_confirmed", "same_sampling_state_confirmed", "fio2_applicability_confirmed")},
                    "qualifying_respiratory_support": review["qualifying_respiratory_support"],
                    "support_qualification_basis_hash": hash_content(review["support_qualification_basis_note"]),
                    "review": _review(review),
                }
            )
        elif kind == "vasoactive":
            refs, payload = source["reference_snapshots"], source["payload"]
            mapping, weight, dose = refs["drug_mapping"], refs["weight"], payload["dose_input"]
            projected_weight = None
            if weight is not None:
                projected_weight = {
                    **_original_binding(weight),
                    "observation_id": weight["observation_id"],
                    "observed_at": weight["observed_at"],
                    "quantity": weight["payload"]["measurements"]["body_weight"],
                    "review": {"status": "confirmed" if review["weight_use_confirmed"] else "unknown", "basis_hash": hash_content(review["weight_basis_note"]), "exclusion_reason": None},
                }
            native_dose = {key: value for key, value in dose.items() if key in ("mode", "rate", "concentration", "pump_rate")}
            vaso[mapping["drug_key"]].append(
                {
                    **_original_binding(source),
                    "support_source_id": source["support_source_id"],
                    **{key: payload[key] for key in ("start_at", "verified_until_at", "ended_at", "continuity_confirmed")},
                    "stream_key": stream_key(source),
                    "mapping": {**_binding(mapping), **{key: mapping[key] for key in ("mapping_id", "drug_key", "active_moiety_basis")}},
                    "continuous_iv": review["continuous_iv"],
                    "rate_scope": review["rate_scope"],
                    "dose_input": native_dose,
                    "weight": projected_weight,
                    "weight_applicability_confirmed": dose["weight_applicability_confirmed"],
                    "weight_use_confirmed": review["weight_use_confirmed"],
                    "mass_basis_compatible_confirmed": review["mass_basis_compatible_confirmed"],
                    "review": _review(review),
                }
            )
    for member in members:
        source, review = member["full_source"], reviews[member["member_key"]]
        if member["kind"] == "laboratory" and source["snapshot"]["mapping"]["analyte_key"] == "arterial_oxygen_partial_pressure" and member["identifier"] not in pair_labs:
            respiratory.append(
                {
                    "candidate_id": source["source_id"],
                    "pao2": _lab_projection(source, review),
                    "pair": None,
                    "fio2": None,
                    "support": None,
                    "arterial_sample_confirmed": False,
                    "same_sampling_state_confirmed": False,
                    "fio2_applicability_confirmed": False,
                    "qualifying_respiratory_support": "unknown",
                    "support_qualification_basis_hash": hash_content(review["basis_note"]),
                    "review": _review(review),
                }
            )
    groups = {review["drug_key"]: review for review in attestation["vasoactive_group_reviews"]}
    vaso_groups = [
        {
            "drug_key": key,
            **{field: groups[key][field] for field in ("relation", "relation_confirmed", "dose_basis_consistency_confirmed")},
            "basis_hash": hash_content(groups[key]["basis_note"]),
            "intervals": sorted(intervals, key=lambda item: item["source_id"]),
        }
        for key, intervals in sorted(vaso.items())
    ]
    conflict_reviews = {review["group_id"]: review for review in attestation["conflict_reviews"]}
    conflicts = [
        {
            **{key: group[key] for key in ("group_id", "axis", "group_digest", "member_source_ids")},
            **{key: conflict_reviews[group["group_id"]][key] for key in ("status", "accepted_source_ids", "excluded_source_ids")},
            "basis_hash": hash_content(conflict_reviews[group["group_id"]]["basis_note"]),
        }
        for group in manifest["conflict_groups"]
    ]
    active_governance = {"status": "active", "revision": 1, "revoked_at": None, "revoked_by": None, "revoke_reason": ""}
    coverage = {
        axis: {
            "source_inventory": attestation["coverage"][axis]["source_inventory"],
            "clinical_protocol": attestation["coverage"][axis]["clinical_protocol"],
            "basis_hash": hash_content(attestation["coverage"][axis]["basis_note"]),
        }
        for axis in AXES
    }
    cardio = attestation["coverage"]["cardiovascular"]
    age = attestation["age_at_period_years"]
    value = {
        "schema_version": "sofa1_source_v1",
        "assessment_id": row.assessment_id,
        "source_id": f"sofa_assessment:{row.assessment_id}:{row.content_hash[:12]}",
        "content_hash": row.content_hash,
        "assessment_governance_hash": hash_content(active_governance),
        "start_at": utc_text(row.period_start),
        "end_at": utc_text(row.period_end),
        "as_of": utc_text(row.as_of),
        "evaluation_at": utc_text(row.evaluation_at),
        "rule_profile_id": row.rule_profile_id,
        "rule_profile_source_id": profile["source_id"],
        "rule_profile_content_hash": row.rule_profile_content_hash,
        "rule_profile_governance_hash": profile["governance_hash"],
        "rule_id": RULE_ID,
        "recipe_digest": row.recipe_digest,
        "policy_digest": row.policy_digest,
        "source_set_digest": row.manifest_digest,
        "population": {
            "age_at_period_years": age,
            "adult": "unknown" if age is None else "yes" if age >= 18 else "no",
            "care_setting": attestation["care_setting"],
            "applicability_confirmed": attestation["applicability_confirmed"],
            "basis_hash": hash_content({key: attestation[key] for key in ("age_basis_note", "care_setting_basis_note")}),
        },
        "coverage": coverage,
        "lab_observations": labs,
        "respiratory_observations": sorted(respiratory, key=lambda item: item["candidate_id"]),
        "respiratory_support_observations": supports,
        "map_observations": maps,
        "gcs_observations": gcs,
        "vasoactive_groups": vaso_groups,
        "urine_intervals": urine,
        "circulation_review": {**{key: cardio[key] for key in ("drug_exposure", "no_other_unrepresented_exposure_confirmed")}, "basis_hash": hash_content(cardio["basis_note"])},
        "conflict_groups": conflicts,
        "member_issues": [],
    }
    try:
        return SofaSource.model_validate(value).model_dump(mode="json")
    except (ValueError, TypeError, KeyError, AttributeError, RecursionError) as exc:
        raise HTTPException(409, "完整SOFA公共原事实不满足严格原量与绑定契约，未登记或截断") from exc


def create_assessment(db, user, values):
    from app.ai.risk_rule_profiles import profile_current
    from app.ai.sofa_models import AISofaAssessment

    req = values if isinstance(values, AssessmentCreate) else AssessmentCreate.model_validate(values)
    actor = actor_current(db, user)
    authorize_scope(db, actor, req.patient_id, req.admission_id)
    doctor = clinical_qualification(db, actor, req.patient_id, req.admission_id)
    if doctor is None:
        raise HTTPException(403, "完整SOFA原资料临床判读须实际具资格医生及原住院照护权，管理权不能代签")
    manifest = period_manifest(db, actor, req.patient_id, req.admission_id, req.period_start, req.period_end, req.as_of)
    if req.expected_manifest_hash != manifest["content_hash"]:
        raise HTTPException(409, "完整24小时原始成员、依赖、治理或时刻已变化，请重核全部原件")
    _validate_reviews(req, manifest)
    profile = profile_current(db, req.rule_profile_id)
    now = utcnow()
    if profile["rule_id"] != RULE_ID or profile["content_hash"] != req.expected_rule_profile_hash or explicit_utc(profile["published_at"]) > now:
        raise HTTPException(409, "须选择已发布且摘要一致的本地SOFA固定实施版本")
    row = AISofaAssessment(
        assessment_id=str(uuid.uuid4()),
        patient_id=req.patient_id,
        admission_id=req.admission_id,
        rule_profile_id=req.rule_profile_id,
        rule_profile_content_hash=req.expected_rule_profile_hash,
        recipe_digest=profile["recipe_digest"],
        policy_digest=hash_content(profile["input_policy"]),
        manifest_digest=manifest["content_hash"],
        period_start=explicit_utc(req.period_start),
        period_end=explicit_utc(req.period_end),
        as_of=explicit_utc(req.as_of),
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
        "manifest": manifest,
        "rule_profile": profile,
        "dependency_review_origins": _dependency_review_origins(manifest),
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
        "clinical_scope_applies_to": {"period_start": req.period_start, "period_end": req.period_end},
        "source_verification": "explicit_current_retrospective_human_review_not_independently_verified",
    }
    row.snapshot_json = _bounded(snapshot, MAX_PRIVATE_BYTES, "完整SOFA私有原件")
    row.content_hash = hash_content(snapshot)
    public = _projection(row, snapshot)
    row.projection_json = _bounded(public, MAX_PUBLIC_BYTES, "完整SOFA公共原事实")
    row.projection_hash = hash_content(public)
    authorize_scope(db, actor, req.patient_id, req.admission_id)
    db.add(row)
    return row


def _row(db, row_or_id, *, lock=False):
    from app.ai.risk_rule_profiles import canonical_id
    from app.ai.sofa_models import AISofaAssessment

    identifier = canonical_id(row_or_id.assessment_id if isinstance(row_or_id, AISofaAssessment) else row_or_id)
    query = db.query(AISofaAssessment).filter_by(assessment_id=identifier).populate_existing()
    row = (query.with_for_update() if lock else query).one_or_none()
    if row is None:
        raise HTTPException(404, "完整SOFA原始临床核实不存在")
    return row


def _frozen(db, row):
    from app.ai.qsofa_sources import AuthorQualification

    try:
        for raw, cap in ((row.snapshot_json, MAX_PRIVATE_BYTES), (row.projection_json, MAX_PUBLIC_BYTES)):
            if not isinstance(raw, str) or len(raw.encode("utf-8")) > cap:
                raise ValueError("原正文容量不符")
        snapshot, public = json.loads(row.snapshot_json), json.loads(row.projection_json)
        if row.schema_version != SCHEMA_VERSION or row.snapshot_json != canonical_json(snapshot) or row.content_hash != hash_content(snapshot):
            raise ValueError("原文或私有hash不符")
        if row.projection_json != canonical_json(public) or row.projection_hash != hash_content(public):
            raise ValueError("公开原文或摘要不符")
        if any(snapshot.get(key) != value for key, value in frozen_metadata(row).items()):
            raise ValueError("原元数据不符")
        req = AssessmentCreate.model_validate(snapshot["attestation"])
        qualification = AuthorQualification.model_validate(snapshot["author_qualification"])
        expected = {
            "patient_id": row.patient_id,
            "admission_id": row.admission_id,
            "rule_profile_id": row.rule_profile_id,
            "expected_rule_profile_hash": row.rule_profile_content_hash,
            "expected_manifest_hash": row.manifest_digest,
            **{name: utc_text(getattr(row, name)) for name in ("period_start", "period_end", "as_of")},
        }
        if any(getattr(req, key) != value for key, value in expected.items()) or not row.as_of <= row.evaluation_at == row.created_at <= utcnow():
            raise ValueError("原引用或时钟不符")
        manifest, profile = snapshot["manifest"], snapshot["rule_profile"]
        if snapshot.get("dependency_review_origins") != _dependency_review_origins(manifest):
            raise ValueError("原显式配对的父件判读来源不符")
        if (
            manifest["schema_version"] != MANIFEST_SCHEMA_VERSION
            or manifest["content_hash"] != row.manifest_digest
            or hash_content({key: value for key, value in manifest.items() if key != "content_hash"}) != row.manifest_digest
        ):
            raise ValueError("完整成员原件摘要不符")
        if any(manifest[key] != getattr(req, key) for key in PeriodRequest.model_fields):
            raise ValueError("完整成员原范围不符")
        if (
            profile["rule_profile_id"] != row.rule_profile_id
            or profile["content_hash"] != row.rule_profile_content_hash
            or profile["recipe_digest"] != row.recipe_digest
            or hash_content(profile["input_policy"]) != row.policy_digest
        ):
            raise ValueError("原规则绑定不符")
        if qualification.actor_id != row.created_by or qualification.doctor_user_id != row.created_by or qualification.authorized_at != utc_text(row.created_at):
            raise ValueError("原签署身份不符")
        if (
            snapshot.get("review_mode") != "current_retrospective_review"
            or snapshot.get("historical_prediction") is not False
            or snapshot.get("clinical_statements_recorded_at") != utc_text(row.created_at)
            or snapshot.get("clinical_scope_applies_to") != {"period_start": req.period_start, "period_end": req.period_end}
            or snapshot.get("source_verification") != "explicit_current_retrospective_human_review_not_independently_verified"
        ):
            raise ValueError("当前回顾性核实语义不符")
        _validate_governance(row, row.created_at)
        _validate_reviews(req, manifest)
        if _projection(row, snapshot) != public:
            raise ValueError("完整公开原件与私有原事实严格投影不符")
        return snapshot, public, qualification
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError, RecursionError, HTTPException) as exc:
        raise HTTPException(409, "完整SOFA冻结原文、临床声明、来源集合、公开投影或治理完整性校验失败") from exc


def assessment_detail(db, row_or_id, audit_only=False):
    from app.ai.risk_rule_profiles import profile_current
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
        current = period_manifest(db, author, row.patient_id, row.admission_id, utc_text(row.period_start), utc_text(row.period_end), utc_text(row.as_of))
        if current != snapshot["manifest"]:
            reasons.append("complete_original_manifest_changed")
    except HTTPException:
        reasons.append("original_sources_or_care_not_current")
    try:
        profile = profile_current(db, row.rule_profile_id, allow_revoked=True)
        if not profile["eligible"] or profile != snapshot["rule_profile"]:
            reasons.append("rule_profile_not_current")
    except HTTPException:
        reasons.append("rule_profile_not_current")
    reasons = sorted(set(reasons))
    if reasons and not audit_only:
        raise HTTPException(409, "完整SOFA原来源集合、父件、医生、照护权或规则不再一致，不能继续执行")
    return {
        **metadata(row),
        "snapshot": snapshot,
        "specialist_source": public,
        "eligible": not reasons,
        "exclusion_reasons": reasons,
        "freshness": {"state": "current" if not reasons else "revoked" if row.status == "revoked" else "stale"},
        "eligibility_basis": "source_and_rule_governance_not_clinical_applicability",
    }


assessment_current = assessment_detail


def authorize_assessment(db, user, pid, adm, identifier):
    actor = actor_current(db, user)
    authorize_scope(db, actor, pid, adm)
    row = _row(db, identifier)
    if row.patient_id != pid or row.admission_id != adm:
        raise HTTPException(409, "完整SOFA核实不属于当前原患者及住院")
    result = assessment_detail(db, row)
    authorize_scope(db, actor, pid, adm)
    return result


def revoke_assessment(db, user, row_or_id, expected_revision, reason):
    from sqlalchemy import update

    from app.ai.sofa_models import AISofaAssessment

    actor = actor_current(db, user)
    row = _row(db, row_or_id, lock=True)
    req = AssessmentRevoke.model_validate({"patient_id": row.patient_id, "admission_id": row.admission_id, "expected_revision": expected_revision, "reason": reason})
    if actor.user_role != "super_admin":
        authorize_scope(db, actor, row.patient_id, row.admission_id)
        if actor.user_id != row.created_by:
            raise HTTPException(403, "仅原作者仍具当前照护权或超级管理员可撤销完整SOFA原件")
    _frozen(db, row)
    changed = db.execute(
        update(AISofaAssessment)
        .where(AISofaAssessment.assessment_id == row.assessment_id, AISofaAssessment.revision == req.expected_revision, AISofaAssessment.status == "active")
        .values(status="revoked", revision=2, revoked_at=utcnow(), revoked_by=actor.user_id, revoke_reason=req.reason),
        execution_options={"synchronize_session": False},
    )
    if changed.rowcount != 1:
        raise HTTPException(409, "完整SOFA治理版本已变化，请刷新后核对")
    db.expire(row)
    return row
