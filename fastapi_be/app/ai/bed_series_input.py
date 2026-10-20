"""Closed physical-bed collections and lossless, privacy limited series projection."""

import copy
import datetime
import re
from types import SimpleNamespace
from typing import Annotated, Literal
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from pydantic import Field, ValidationError, field_validator, model_validator

from app.ai import bed_contract as core
from app.ai import bed_facts as facts
from app.ai.bed_models import AIBedSource
from app.models import Bed, Ward

SCHEMA_VERSION = "bed_series_private_v1"
MAX_BYTES = 8 * 1024 * 1024
MAX_MEMBERS = 4096
MAX_SCANNED = 200000
SOURCE_BATCH_SIZE = 128
MAX_BEDS = 200000
Basis = Annotated[str, Field(min_length=20, max_length=4000)]


def utcnow():
    return datetime.datetime.now(datetime.UTC).replace(tzinfo=None)


def meaningful_basis(value):
    if len("".join(value.split())) < 20:
        raise ValueError("An explicit review requires twenty non-whitespace characters")
    return value


class SeriesPeriodRequest(facts.StrictInput):
    ward_id: facts.PositiveInteger
    business_timezone: facts.Timezone
    date_from: facts.LocalDate
    date_to: facts.LocalDate

    @model_validator(mode="after")
    def consecutive_period(self):
        n = (datetime.date.fromisoformat(self.date_to) - datetime.date.fromisoformat(self.date_from)).days + 1
        if not 112 <= n <= 366:
            raise ValueError("A series requires 112 to 366 contiguous complete business days")
        period_bounds(self)
        return self


class TargetCoverageDeclaration(facts.StrictInput):
    target: core.Target
    definition: Literal["occupied_physical_beds_at_boundary_v1", "ward_physical_day_events_v1"]
    same_scope_confirmed: facts.Review
    same_definition_confirmed: facts.Review
    same_method_confirmed: facts.Review
    basis_note: Basis
    _basis = field_validator("basis_note")(meaningful_basis)

    @model_validator(mode="after")
    def target_definition(self):
        expected = "occupied_physical_beds_at_boundary_v1" if self.target == core.TARGETS[0] else "ward_physical_day_events_v1"
        if self.definition != expected:
            raise ValueError("Each independent target requires its actual physical definition")
        return self


class DaySelection(facts.StrictInput):
    business_date: facts.LocalDate
    census_source_record_id: facts.CanonicalId | None
    census_selection_reason: Literal["confirmed", "missing", "unresolved_conflict"]
    census_group_digest: facts.HashText
    flow_source_record_id: facts.CanonicalId | None
    flow_selection_reason: Literal["confirmed", "missing", "unresolved_conflict"]
    flow_group_digest: facts.HashText
    selection_basis_note: Basis
    _basis = field_validator("selection_basis_note")(meaningful_basis)

    @model_validator(mode="after")
    def selected_or_missing(self):
        for kind in ("census", "flow"):
            if (getattr(self, kind + "_source_record_id") is not None) != (getattr(self, kind + "_selection_reason") == "confirmed"):
                raise ValueError("A selected whole original must have an explicit confirmed selection")
        return self


class MemberReviewBase(facts.StrictInput):
    source_record_id: facts.CanonicalId
    expected_content_hash: facts.HashText
    expected_governance_hash: facts.HashText
    basis_note: Basis
    _basis = field_validator("basis_note")(meaningful_basis)


class DailyMemberReview(MemberReviewBase):
    kind: Literal["census", "flow_day"]
    selection: Literal["confirmed", "excluded", "unknown"]


class CapacityMemberReview(MemberReviewBase):
    kind: Literal["capacity_interval"]
    selection: Literal["confirmed", "excluded"]


MemberReview = Annotated[DailyMemberReview | CapacityMemberReview, Field(discriminator="kind")]


class SeriesRequest(SeriesPeriodRequest):
    days: list[DaySelection] = Field(min_length=112, max_length=366)
    target_coverage: list[TargetCoverageDeclaration] = Field(min_length=5, max_length=5)
    member_reviews: list[MemberReview] = Field(max_length=MAX_MEMBERS)

    @model_validator(mode="after")
    def full_day_and_member_declarations(self):
        if [day.business_date for day in self.days] != period_bounds(self)["business_dates"]:
            raise ValueError("Day declarations must cover the whole chronological history exactly once")
        if [item.target for item in self.target_coverage] != list(core.TARGETS):
            raise ValueError("All five targets require their own ordered declarations")
        ids = [item.source_record_id for item in self.member_reviews]
        if len(ids) != len(set(ids)):
            raise ValueError("Each complete related original must be reviewed exactly once")
        return self


class BedBinding(facts.StrictInput):
    bed_id: facts.PositiveInteger
    ward_id: facts.PositiveInteger


class WardEvidence(facts.StrictInput):
    status: int | None
    configured_bed_count: int | None


class CensusLocator(facts.StrictInput):
    kind: Literal["census"]
    business_date: facts.LocalDate
    business_timezone: facts.Timezone
    census_at: facts.UtcText
    observed_at: facts.UtcText


class FlowLocator(facts.StrictInput):
    kind: Literal["flow_day"]
    business_date: facts.LocalDate
    business_timezone: facts.Timezone
    day_start_at: facts.UtcText
    day_end_at: facts.UtcText
    observed_at: facts.UtcText


class CapacityLocator(facts.StrictInput):
    kind: Literal["capacity_interval"]
    start_at: facts.UtcText
    end_at: facts.UtcText
    basis_kind: Literal["observed_operational_capacity", "reviewed_future_scenario"]
    observed_at: facts.UtcText | None


LOCATORS = {"census": CensusLocator, "flow_day": FlowLocator, "capacity_interval": CapacityLocator}


def period_bounds(request):
    first, last = datetime.date.fromisoformat(request.date_from), datetime.date.fromisoformat(request.date_to)
    dates = [(first + datetime.timedelta(days=index)).isoformat() for index in range((last - first).days + 1)]
    bounds = [facts.day_bounds(day, request.business_timezone) for day in dates]
    future = []
    for lead in range(1, 15):
        try:
            day = (last + datetime.timedelta(days=lead)).isoformat()
        except OverflowError as exc:
            raise ValueError("Forecast date exceeds supported Gregorian range") from exc
        start, end = facts.day_bounds(day, request.business_timezone)
        future.append({"business_date": day, "start_at": start, "end_at": end})
    return {
        "business_dates": dates,
        "history_start_at": bounds[0][0],
        "history_end_at": bounds[-1][1],
        "future_start_at": future[0]["start_at"],
        "future_end_at": future[-1]["end_at"],
        "future_days": future,
    }


def typed_period(value, *, stored=False):
    try:
        if isinstance(value, SeriesRequest):
            return SeriesPeriodRequest.model_validate({key: getattr(value, key) for key in SeriesPeriodRequest.model_fields})
        if isinstance(value, SeriesPeriodRequest):
            return value
        if isinstance(value, dict) and set(value) == set(SeriesRequest.model_fields):
            value = {key: value[key] for key in SeriesPeriodRequest.model_fields}
        return SeriesPeriodRequest.model_validate(value)
    except (ValueError, TypeError, ValidationError) as exc:
        raise HTTPException(409 if stored else 422, "病区序列须提供真实IANA日界及连续112至366个完整自然日") from exc


def typed_request(value, *, stored=False):
    try:
        return value if isinstance(value, SeriesRequest) else SeriesRequest.model_validate(value)
    except (ValueError, TypeError, ValidationError) as exc:
        raise HTTPException(409 if stored else 422, "病区序列须逐日整件选择、完整成员审核及五个独立目标声明") from exc


def validate_series_period(request, *, now=None):
    request = typed_period(request)
    now = utcnow() if now is None else now
    clock = facts.instant(facts.utc_text(now))
    last = (clock.astimezone(ZoneInfo(request.business_timezone)).date() - datetime.timedelta(days=1)).isoformat()
    if request.date_to != last:
        raise HTTPException(409, "新捕获或新执行的历史须截止服务器当前业务时区最后完整日，不能把当前部分日当完整观察")
    return period_bounds(request)


def _locator(kind, payload):
    return LOCATORS[kind].model_validate({"kind": kind, **{key: payload[key] for key in LOCATORS[kind].model_fields if key != "kind"}}).model_dump(mode="json")


def _overlap(start, end, left, right):
    return start < right and end > left


def _relevant(locator, request, period):
    kind = locator["kind"]
    if kind == "census":
        return request.date_from <= locator["business_date"] <= request.date_to or period["history_start_at"] < locator["census_at"] <= period["history_end_at"]
    if kind == "flow_day":
        return request.date_from <= locator["business_date"] <= request.date_to or _overlap(locator["day_start_at"], locator["day_end_at"], period["history_start_at"], period["history_end_at"])
    left, right = (period["history_start_at"], period["history_end_at"]) if locator["basis_kind"] == "observed_operational_capacity" else (period["future_start_at"], period["future_end_at"])
    # Historical capacity serves only day integrals. The future scenario also
    # needs a source containing the final forecast census instant, not ending there.
    return _overlap(locator["start_at"], locator["end_at"], left, right) or (locator["basis_kind"] == "reviewed_future_scenario" and locator["start_at"] <= right < locator["end_at"])


def _capture_source(db, actor, row, payload, parent, *, locking=False):
    reasons = facts.parent_exclusion_reasons(db, row, parent, locking=locking)
    eligible = row.status == "published" and not reasons
    exclusions = [*reasons, *([] if row.status == "published" else ["source_" + row.status])]
    value = {
        **facts.metadata(row),
        "payload": payload if eligible else None,
        "parent_binding": parent if eligible else None,
        "parent_current": not reasons,
        "eligible": eligible,
        "exclusion_reasons": exclusions,
        "can_record": not reasons,
        "can_review": actor.user_role == "super_admin" and row.status == "draft" and not reasons,
        "can_revoke": row.status in {"draft", "published"} and (actor.user_role == "super_admin" or row.created_by == actor.user_id and not reasons),
        "audit_only": False,
        "eligibility_basis": "published_governance_and_current_ward_department_not_census_coverage_capacity_readiness_or_forecast_validation",
    }
    if not eligible:
        for key in ("review_basis_note", "revoke_reason"):
            value[key] = None
    return value


def _manifest_item(record):
    source = record["source"]
    return {
        "kind": source["source_kind"],
        **{
            key: source[key]
            for key in (
                "source_record_id",
                "source_id",
                "content_hash",
                "governance_hash",
                "department_id",
                "ward_id",
                "status",
                "revision",
                "recorded_at",
                "reviewed_at",
                "revoked_at",
                "parent_current",
                "eligible",
                "exclusion_reasons",
            )
        },
        "locator_hash": record["locator_hash"],
    }


def _group_candidates(records, day, timezone, start, end, kind):
    candidates = []
    for record in records:
        loc, source = record["locator"], record["source"]
        if loc["kind"] != kind:
            continue
        related = loc["business_date"] == day or (start < loc["census_at"] <= end if kind == "census" else _overlap(loc["day_start_at"], loc["day_end_at"], start, end))
        if not related:
            continue
        incompatible = []
        if loc["business_timezone"] != timezone:
            incompatible.append("different_original_business_timezone")
        if loc["business_date"] != day:
            incompatible.append("different_original_business_date")
        if loc["census_at"] != end if kind == "census" else (loc["day_start_at"], loc["day_end_at"]) != (start, end):
            incompatible.append("different_original_physical_boundary")
        candidates.append(
            {
                "source_record_id": source["source_record_id"],
                "content_hash": source["content_hash"],
                "governance_hash": source["governance_hash"],
                "eligible": source["eligible"],
                "compatible": not incompatible,
                "exclusion_reasons": [*source["exclusion_reasons"], *incompatible],
            }
        )
    return candidates


def _day_groups(records, request):
    groups = []
    for day in period_bounds(request)["business_dates"]:
        start, end = facts.day_bounds(day, request.business_timezone)
        item = {"business_date": day, "day_start_at": start, "day_end_at": end}
        for key, kind in (("census", "census"), ("flow", "flow_day")):
            candidates = _group_candidates(records, day, request.business_timezone, start, end, kind)
            item[key + "_candidates"] = candidates
            item[key + "_group_digest"] = facts.hash_content({"business_date": day, "kind": kind, "candidates": candidates})
        groups.append(item)
    return groups


def _digests(ward_binding, cohort, records, period):
    historical, future = [], []
    for record in records:
        target = future if record["locator"]["kind"] == "capacity_interval" and record["locator"]["basis_kind"] == "reviewed_future_scenario" else historical
        target.append(_manifest_item(record))
    membership = facts.hash_content({"ward_binding": ward_binding, "bed_cohort": cohort})
    history = facts.hash_content({"start_at": period["history_start_at"], "end_at": period["history_end_at"], "manifest": historical})
    scenario = facts.hash_content({"start_at": period["future_start_at"], "end_at": period["future_end_at"], "manifest": future})
    return {
        "historical_collection_digest": history,
        "current_membership_digest": membership,
        "future_scenario_collection_digest": scenario,
        "collection_digest": facts.hash_content(
            {"ward_binding": ward_binding, "historical_collection_digest": history, "current_membership_digest": membership, "future_scenario_collection_digest": scenario}
        ),
    }


def current_collection(db, user, ward_id, *, request, locking=False):
    """Current relevant roots, not a historical replay; does not impose today's date."""
    request = typed_period(request)
    if type(ward_id) is not int or ward_id != request.ward_id:
        raise HTTPException(422, "病区标识与完整序列请求不一致")
    period = period_bounds(request)
    first = facts.current_query(db.query(Ward).filter_by(ward_id=ward_id)).one_or_none()
    if first is None or first.department_id is None:
        raise HTTPException(422, "病区不存在或尚无可核实科室")
    department_id = first.department_id
    actor = facts.bed_scope(db, user, department_id, locking=locking)
    ward = facts.current_query(db.query(Ward).filter_by(ward_id=ward_id), locking=locking).one_or_none()
    if ward is None or ward.department_id != department_id:
        raise HTTPException(409, "读取期间病区科室已变化，请重新捕获")
    ward_binding = {"ward_id": ward_id, "department_id": department_id}
    beds = facts.current_query(db.query(Bed.bed_id, Bed.ward_id).filter_by(ward_id=ward_id).order_by(Bed.bed_id).limit(MAX_BEDS + 1), locking=locking).all()
    if len(beds) > MAX_BEDS:
        raise HTTPException(422, "完整床位身份集合超过明确容量，不得截断为部分床位")
    cohort = [{"bed_id": row.bed_id, "ward_id": row.ward_id} for row in beds]
    records = []
    scanned = byte_count = 0
    last_id = None
    while True:
        query = db.query(AIBedSource).filter_by(ward_id=ward_id)
        if last_id is not None:
            query = query.filter(AIBedSource.source_record_id > last_id)
        query = query.order_by(AIBedSource.source_record_id).limit(min(SOURCE_BATCH_SIZE, MAX_SCANNED + 1 - scanned))
        rows = facts.current_query(query, locking=locking).all()
        if not rows:
            break
        for row in rows:
            scanned += 1
            if scanned > MAX_SCANNED:
                raise HTTPException(422, "病区原来源扫描超过200000记录，不能截断或假称集合完整")
            # Authenticate every bounded batch before using clocks to skip a body.
            # Locking capture holds the Ward FK parent and all visited source rows.
            payload, parent = facts.source_proof(row)
            locator = _locator(row.source_kind, payload)
            if not _relevant(locator, request, period):
                continue
            if len(records) >= MAX_MEMBERS:
                raise HTTPException(422, "完整相关原来源超过4096根，不得挑少量候选或截断")
            record = {"source": _capture_source(db, actor, row, payload, parent, locking=locking), "locator": locator, "locator_hash": facts.hash_content(locator)}
            byte_count += len(facts.canonical_json(record).encode("utf-8"))
            if byte_count > MAX_BYTES:
                raise HTTPException(422, "相关完整原件累计超过8MiB，不得先构建超大集合后截断")
            records.append(record)
        last_id = rows[-1].source_record_id
    manifest = [_manifest_item(record) for record in records]
    value = {
        "ward_binding": ward_binding,
        "ward_capture_evidence": {"status": ward.status, "configured_bed_count": ward.bed_count},
        "bed_cohort": cohort,
        "facts": records,
        "fact_manifest": manifest,
        "day_groups": _day_groups(records, request),
        "period": period,
        **_digests(ward_binding, cohort, records, period),
    }
    if len(facts.canonical_json(value).encode("utf-8")) > MAX_BYTES:
        raise HTTPException(422, "完整相关来源及成员超过8MiB，不得截断原件或清单")
    return value


def preview_input(db, user, request):
    request = typed_period(request)
    validate_series_period(request)
    value = current_collection(db, user, request.ward_id, request=request)
    return {
        key: item
        for key, item in {
            **value,
            "capture_mode": "current_capture",
            "capacity_basis": "physical_historical_census_flows_separate_total_capacity_and_reviewed_future_scenarios_not_bookable_slots",
        }.items()
        if key != "facts"
    }


def _check_selections(request, collection):
    records = {record["source"]["source_record_id"]: record for record in collection["facts"]}
    reviews = {review.source_record_id: review for review in request.member_reviews}
    if set(reviews) != set(records):
        raise ValueError("Every related original must have exactly one explicit review")
    for key, record in records.items():
        review, source = reviews[key], record["source"]
        if review.kind != source["source_kind"] or review.expected_content_hash != source["content_hash"] or review.expected_governance_hash != source["governance_hash"]:
            raise ValueError("Review original kind, full content or governance hash differs")
        if review.selection == "confirmed" and not source["eligible"]:
            raise ValueError("An unpublished or stale original cannot be selected")
    selected = set()
    for day, group in zip(request.days, collection["day_groups"], strict=True):
        for prefix in ("census", "flow"):
            if getattr(day, prefix + "_group_digest") != group[prefix + "_group_digest"]:
                raise ValueError("The complete daily candidate group has changed")
            source_id = getattr(day, prefix + "_source_record_id")
            if source_id is None:
                continue
            candidate = next((item for item in group[prefix + "_candidates"] if item["source_record_id"] == source_id), None)
            if candidate is None or not candidate["eligible"] or not candidate["compatible"] or reviews[source_id].selection != "confirmed" or source_id in selected:
                raise ValueError("Daily selection must be one compatible eligible whole original, used exactly once")
            selected.add(source_id)
    daily_confirmed = {key for key, review in reviews.items() if review.kind != "capacity_interval" and review.selection == "confirmed"}
    if selected != daily_confirmed:
        raise ValueError("An explicitly confirmed daily original is unreferenced or replaced")
    # A conflicting local timezone/boundary must be explicitly excluded, not
    # silently marked unknown while another logical calendar is selected.
    compatible = {item["source_record_id"] for group in collection["day_groups"] for prefix in ("census", "flow") for item in group[prefix + "_candidates"] if item["compatible"]}
    for key, record in records.items():
        if record["locator"]["kind"] in {"census", "flow_day"} and key not in compatible and reviews[key].selection != "excluded":
            raise ValueError("Incompatible original business timezones or logical boundaries require explicit exclusion")


def capture_input(db, user, request, series_id, *, expected_collection_digest=None):
    request = typed_request(request)
    try:
        series_id = facts.canonical_id(series_id)
    except (ValueError, TypeError, AttributeError) as exc:
        raise HTTPException(422, "序列标识须为规范UUID") from exc
    now = utcnow()
    period = validate_series_period(request, now=now)
    collection = current_collection(db, user, request.ward_id, request=request)
    if expected_collection_digest is not None and expected_collection_digest != collection["collection_digest"]:
        raise HTTPException(409, "完整相关来源、治理或床位身份已变化，请重新预览并逐件审核")
    try:
        _check_selections(request, collection)
    except ValueError as exc:
        raise HTTPException(409, "逐日整件选择、完整候选组或逐源审核与当前原件不一致") from exc
    final = current_collection(db, user, request.ward_id, request=request, locking=True)
    if final["collection_digest"] != collection["collection_digest"]:
        raise HTTPException(409, "捕获保存前病区归属、床位成员或相关来源已变化，本次未冻结")
    actor = facts.bed_scope(db, user, final["ward_binding"]["department_id"], locking=True)
    clock = facts.utc_text(now)
    snapshot = {
        "schema_version": SCHEMA_VERSION,
        "series_id": series_id,
        "ward_id": request.ward_id,
        "department_id": final["ward_binding"]["department_id"],
        "created_by": actor.user_id,
        "as_of": clock,
        "captured_at": facts.utc_text(utcnow()),
        "capture_mode": "current_capture",
        "request": request.model_dump(mode="json"),
        **{
            key: final[key]
            for key in (
                "collection_digest",
                "historical_collection_digest",
                "current_membership_digest",
                "future_scenario_collection_digest",
                "ward_binding",
                "bed_cohort",
                "ward_capture_evidence",
                "facts",
                "fact_manifest",
                "day_groups",
            )
        },
        "period": period,
        "manifest_digest": facts.hash_content(final["fact_manifest"]),
        "scope_binding_hash": facts.hash_content(final["ward_binding"]),
        "algorithm": {
            "rule_id": core.RULE_ID,
            "recipe": copy.deepcopy(core.RECIPE),
            "recipe_digest": core.recipe_digest(),
            "input_policy": copy.deepcopy(core.INPUT_POLICY),
            "input_policy_digest": core.input_policy_digest(),
        },
    }
    verify_snapshot(snapshot)
    return snapshot


def _validate_locator(locator):
    value = LOCATORS[locator["kind"]].model_validate(locator).model_dump(mode="json")
    kind = value["kind"]
    if kind in {"census", "flow_day"}:
        start, end = facts.day_bounds(value["business_date"], value["business_timezone"])
        if kind == "census":
            if value["census_at"] != end or value["observed_at"] < end:
                raise ValueError("Redacted census locator differs from original logical boundary")
        elif (value["day_start_at"], value["day_end_at"]) != (start, end) or value["observed_at"] < end:
            raise ValueError("Redacted physical-flow locator is not the original closed day")
    elif (
        value["start_at"] >= value["end_at"]
        or (value["basis_kind"] == "reviewed_future_scenario" and value["observed_at"] is not None)
        or (value["basis_kind"] == "observed_operational_capacity" and (value["observed_at"] is None or value["observed_at"] < value["end_at"]))
    ):
        raise ValueError("Redacted capacity locator differs from its observed/scenario state")
    return value


def _validate_frozen_record(record):
    if not isinstance(record, dict) or set(record) != {"source", "locator", "locator_hash"}:
        raise ValueError("Unexpected frozen member shape")
    source = record["source"]
    expected = (
        set(facts.IDENTITY_FIELDS)
        | set(facts.GOVERNANCE_FIELDS)
        | {
            "source_id",
            "content_hash",
            "governance_hash",
            "payload",
            "parent_binding",
            "parent_current",
            "eligible",
            "exclusion_reasons",
            "can_record",
            "can_review",
            "can_revoke",
            "audit_only",
            "eligibility_basis",
        }
    )
    if not isinstance(source, dict) or set(source) != expected:
        raise ValueError("Unexpected frozen original wrapper")
    facts.FrozenIdentity.model_validate({key: source[key] for key in facts.IDENTITY_FIELDS})
    core.MemberRef.model_validate(_member_ref(source))
    locator = _validate_locator(record["locator"])
    if locator["kind"] != source["source_kind"] or record["locator_hash"] != facts.hash_content(locator):
        raise ValueError("Original technical locator differs")
    if locator["observed_at"] is not None and locator["observed_at"] > source["recorded_at"]:
        raise ValueError("Original observation follows its registration")
    if any(type(source[key]) is not bool for key in ("parent_current", "eligible", "can_record", "can_review", "can_revoke", "audit_only")) or source["audit_only"] is not False:
        raise ValueError("A new series cannot capture privileged frozen audit as current")
    status, revision = source["status"], source["revision"]
    reviewed = source["reviewed_by"] is not None and source["reviewed_at"] is not None
    if reviewed:
        if type(source["reviewed_by"]) is not int or source["reviewed_by"] < 1 or facts.canonical_utc(source["reviewed_at"]) < source["recorded_at"]:
            raise ValueError("Frozen review identity/clock differs")
    elif source["reviewed_by"] is not None or source["reviewed_at"] is not None:
        raise ValueError("Partial review metadata")
    if type(revision) is not int or status not in {"draft", "published", "rejected", "revoked"}:
        raise ValueError("Invalid frozen governance")
    if status == "draft" and (revision != 1 or reviewed) or status in {"published", "rejected"} and (revision != 2 or not reviewed):
        raise ValueError("Invalid governance transition metadata")
    if status == "revoked":
        if (
            revision != (3 if reviewed else 2)
            or type(source["revoked_by"]) is not int
            or source["revoked_by"] < 1
            or source["revoked_at"] is None
            or facts.canonical_utc(source["revoked_at"]) < (source["reviewed_at"] if reviewed else source["recorded_at"])
        ):
            raise ValueError("Invalid revocation metadata")
    elif source["revoked_by"] is not None or source["revoked_at"] is not None:
        raise ValueError("Unexpected revocation metadata")
    parent_reasons = {"original_department_missing", "original_ward_missing", "ward_department_binding_changed"}
    reasons = source["exclusion_reasons"]
    if not isinstance(reasons, list) or len(reasons) != len(set(reasons)) or any(item not in parent_reasons | {"source_draft", "source_rejected", "source_revoked"} for item in reasons):
        raise ValueError("Unexpected exclusion metadata")
    expected_reasons = [item for item in reasons if item in parent_reasons] + ([] if status == "published" else ["source_" + status])
    if reasons != expected_reasons or source["parent_current"] != (not any(item in parent_reasons for item in reasons)) or source["eligible"] != (status == "published" and source["parent_current"]):
        raise ValueError("Eligibility differs from captured original parent/governance state")
    if (
        source["can_record"] != source["parent_current"]
        or source["can_review"]
        and (status != "draft" or not source["parent_current"])
        or source["can_revoke"]
        and status not in {"draft", "published"}
    ):
        raise ValueError("Frozen action flags differ from source state")
    if source["eligible"]:
        fields = {key: source[key] for key in (*facts.IDENTITY_FIELDS, "content_hash", *facts.GOVERNANCE_FIELDS)}
        for key in ("recorded_at", "reviewed_at", "revoked_at"):
            fields[key] = facts.instant(fields[key]).replace(tzinfo=None) if fields[key] is not None else None
        fields.update(payload_json=facts.canonical_json(source["payload"]), parent_binding_json=facts.canonical_json(source["parent_binding"]))
        payload, _ = facts.source_proof(SimpleNamespace(**fields))
        if _locator(source["source_kind"], payload) != locator or facts.hash_content({key: source[key] for key in facts.GOVERNANCE_FIELDS}) != source["governance_hash"]:
            raise ValueError("Complete current source locator/governance differs from its own bytes")
    elif any(source[key] is not None for key in ("payload", "parent_binding", "review_basis_note", "revoke_reason")):
        raise ValueError("Unpublished or stale original notes must remain redacted even inside capture")


def verify_snapshot(snapshot, *, validate_current_recipe=False):
    """Own frozen proof, independent of today's freshness, permissions and states."""
    try:
        expected = {
            "schema_version",
            "series_id",
            "ward_id",
            "department_id",
            "created_by",
            "as_of",
            "captured_at",
            "capture_mode",
            "request",
            "collection_digest",
            "historical_collection_digest",
            "current_membership_digest",
            "future_scenario_collection_digest",
            "ward_binding",
            "bed_cohort",
            "ward_capture_evidence",
            "facts",
            "fact_manifest",
            "day_groups",
            "period",
            "manifest_digest",
            "scope_binding_hash",
            "algorithm",
        }
        if not isinstance(snapshot, dict) or set(snapshot) != expected or snapshot["schema_version"] != SCHEMA_VERSION or snapshot["capture_mode"] != "current_capture":
            raise ValueError("Unexpected complete series shape/version")
        if len(facts.canonical_json(snapshot).encode("utf-8")) > MAX_BYTES:
            raise ValueError("Complete private series exceeds UTF8 capacity")
        facts.canonical_id(snapshot["series_id"])
        request = typed_request(snapshot["request"], stored=True)
        binding = facts.WardBinding.model_validate(snapshot["ward_binding"]).model_dump(mode="json")
        if (
            binding != {"ward_id": snapshot["ward_id"], "department_id": snapshot["department_id"]}
            or request.ward_id != snapshot["ward_id"]
            or type(snapshot["created_by"]) is not int
            or snapshot["created_by"] < 1
        ):
            raise ValueError("Series author or original ward/department differs")
        facts.canonical_utc(snapshot["as_of"])
        facts.canonical_utc(snapshot["captured_at"])
        if snapshot["as_of"] > snapshot["captured_at"]:
            raise ValueError("Frozen availability cutoff follows capture")
        # Use only the frozen server clock. Historical reads never roll dates.
        period = validate_series_period(request, now=facts.instant(snapshot["as_of"]))
        if snapshot["period"] != period:
            raise ValueError("Frozen business calendar/domain differs")
        cohort = snapshot["bed_cohort"]
        if not isinstance(cohort, list) or len(cohort) > MAX_BEDS:
            raise ValueError("Invalid complete stable bed cohort")
        for item in cohort:
            BedBinding.model_validate(item)
            if item["ward_id"] != request.ward_id:
                raise ValueError("A bed identity belongs to another ward")
        if cohort != sorted(cohort, key=lambda item: item["bed_id"]) or len(cohort) != len({item["bed_id"] for item in cohort}):
            raise ValueError("Stable bed membership is duplicated or unordered")
        WardEvidence.model_validate(snapshot["ward_capture_evidence"])
        records = snapshot["facts"]
        if not isinstance(records, list) or len(records) > MAX_MEMBERS:
            raise ValueError("Invalid full relevant root collection")
        ids = []
        for record in records:
            _validate_frozen_record(record)
            source = record["source"]
            ids.append(source["source_record_id"])
            if source["ward_id"] != request.ward_id or not _relevant(record["locator"], request, period):
                raise ValueError("Frozen original is outside this actual ward/date domain")
            if source["eligible"] and (source["department_id"] != snapshot["department_id"] or source["parent_binding"]["ward"] != binding):
                raise ValueError("Eligible original belongs to a different captured population")
            if any(source[key] is not None and source[key] > snapshot["as_of"] for key in ("recorded_at", "reviewed_at", "revoked_at")):
                raise ValueError("Captured governance/original was not yet available at the frozen cutoff")
        if ids != sorted(ids) or len(ids) != len(set(ids)):
            raise ValueError("Relevant root identities are duplicated or unordered")
        manifest = [_manifest_item(record) for record in records]
        if snapshot["fact_manifest"] != manifest or snapshot["manifest_digest"] != facts.hash_content(manifest) or snapshot["scope_binding_hash"] != facts.hash_content(binding):
            raise ValueError("Complete original manifest or scope hash differs")
        digests = _digests(binding, cohort, records, period)
        if any(snapshot[key] != value for key, value in digests.items()) or snapshot["day_groups"] != _day_groups(records, request):
            raise ValueError("Historical, current membership, future scenario or daily group binding differs")
        _check_selections(request, snapshot)
        algorithm = snapshot["algorithm"]
        if not isinstance(algorithm, dict) or set(algorithm) != {"rule_id", "recipe", "recipe_digest", "input_policy", "input_policy_digest"} or algorithm["rule_id"] != core.RULE_ID:
            raise ValueError("Unexpected frozen algorithm identity")
        if (
            facts.hash_content(algorithm["recipe"]) != algorithm["recipe_digest"]
            or facts.hash_content(algorithm["input_policy"]) != algorithm["input_policy_digest"]
            or algorithm["recipe"].get("input_policy") != algorithm["input_policy"]
        ):
            raise ValueError("Frozen algorithm/policy differs from its own contents")
        if validate_current_recipe and (algorithm["recipe_digest"] != core.recipe_digest() or algorithm["input_policy_digest"] != core.input_policy_digest()):
            raise ValueError("New use requires the current fixed algorithm/policy")
        return snapshot
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError, RecursionError, UnicodeError, ValidationError, HTTPException) as exc:
        raise HTTPException(409, "床位序列的完整冻结原件、成员清单、整日选择、日界或算法绑定不一致") from exc


def _member_ref(source):
    return {"kind": source["source_kind"], **{key: source[key] for key in ("source_record_id", "source_id", "content_hash", "governance_hash")}}


def _public_original(source):
    payload = source["payload"]
    result = {
        "ref": _member_ref(source),
        "recorded_at": source["recorded_at"],
        "published_at": source["reviewed_at"],
        "observed_at": payload["observed_at"],
        "original_scope_hash": facts.hash_content(source["parent_binding"]),
        "coverage": payload["coverage"],
    }
    if source["source_kind"] == "capacity_interval":
        result.update(
            {
                key: copy.deepcopy(payload[key])
                for key in ("start_at", "end_at", "basis_kind", "operational_total_beds", "staff_readiness", "equipment_readiness", "isolation_applicability", "capacity_definition")
            }
        )
        result["capacity_basis_hash"] = facts.hash_content(payload["capacity_basis_note"])
    else:
        result.update(
            business_date=payload["business_date"],
            method=payload["method"],
            coverage_basis_hash=facts.hash_content(payload["coverage_basis_note"]),
            external_record_key_hash=None if payload["external_record_key"] is None else facts.hash_content(payload["external_record_key"]),
            definition=payload["definition"],
        )
        keys = (
            ("census_at", "boundary_state_confirmed", "occupied_beds")
            if source["source_kind"] == "census"
            else ("day_start_at", "day_end_at", "admission_events", "discharge_events", "transfer_in_events", "transfer_out_events")
        )
        result.update({key: copy.deepcopy(payload[key]) for key in keys})
    return result


def project_source(snapshot, governance_hash, *, validate_current_recipe=True):
    verify_snapshot(snapshot, validate_current_recipe=validate_current_recipe)
    try:
        if not isinstance(governance_hash, str) or not re.fullmatch(r"[a-f0-9]{64}", governance_hash):
            raise ValueError("Complete published series governance hash required")
        request = typed_request(snapshot["request"], stored=True)
        reviews = {item.source_record_id: item for item in request.member_reviews}
        originals = {record["source"]["source_record_id"]: record["source"] for record in snapshot["facts"]}
        manifest = []
        for record in snapshot["facts"]:
            source = record["source"]
            review = reviews[source["source_record_id"]]
            manifest.append(
                {**_member_ref(source), "status": source["status"], "eligible": source["eligible"], "selection": review.selection, "selection_basis_hash": facts.hash_content(review.basis_note)}
            )
        selected = [source for key, source in originals.items() if reviews[key].selection == "confirmed"]
        coverage = [
            {
                "target": item.target,
                "definition": item.definition,
                "same_scope_confirmed": item.same_scope_confirmed,
                "same_definition_confirmed": item.same_definition_confirmed,
                "same_method_confirmed": item.same_method_confirmed,
                "basis_hash": facts.hash_content(item.basis_note),
            }
            for item in request.target_coverage
        ]
        days = []
        for item, group in zip(request.days, snapshot["day_groups"], strict=True):
            days.append(
                {
                    "date": item.business_date,
                    "day_start_at": group["day_start_at"],
                    "day_end_at": group["day_end_at"],
                    "census_at": group["day_end_at"],
                    "census_source_id": None if item.census_source_record_id is None else originals[item.census_source_record_id]["source_id"],
                    "census_selection_reason": item.census_selection_reason,
                    "flow_source_id": None if item.flow_source_record_id is None else originals[item.flow_source_record_id]["source_id"],
                    "flow_selection_reason": item.flow_selection_reason,
                    "selection_basis_hash": facts.hash_content(item.selection_basis_note),
                }
            )
        digest = facts.hash_content(snapshot)
        value = {
            "schema_version": "bed_source_v1",
            "series_id": snapshot["series_id"],
            "source_id": f"bed_series:{snapshot['series_id']}:{digest[:12]}",
            "content_hash": digest,
            "governance_hash": governance_hash,
            "rule_id": snapshot["algorithm"]["rule_id"],
            "recipe_digest": snapshot["algorithm"]["recipe_digest"],
            "input_policy_digest": snapshot["algorithm"]["input_policy_digest"],
            "scope": "single_ward",
            "scope_token": snapshot["scope_binding_hash"],
            "timezone": request.business_timezone,
            "target_definitions_digest": facts.hash_content([{"target": item["target"], "definition": item["definition"]} for item in coverage]),
            "date_from": request.date_from,
            "date_to": request.date_to,
            "as_of": snapshot["as_of"],
            "captured_at": snapshot["captured_at"],
            **{key: snapshot[key] for key in ("historical_collection_digest", "current_membership_digest", "future_scenario_collection_digest")},
            "member_manifest_hash": facts.hash_content(manifest),
            "target_coverage": coverage,
            "days": days,
            "member_manifest": manifest,
            "census_observations": [_public_original(source) for source in selected if source["source_kind"] == "census"],
            "flow_observations": [_public_original(source) for source in selected if source["source_kind"] == "flow_day"],
            "capacity_intervals": [_public_original(source) for source in selected if source["source_kind"] == "capacity_interval"],
        }
        if len(facts.canonical_json(value).encode("utf-8")) > MAX_BYTES:
            raise ValueError("Complete public source exceeds UTF8 cap")
        return core.BedSource.model_validate(value).model_dump(mode="json") if validate_current_recipe else value
    except (ValueError, TypeError, KeyError, AttributeError, ValidationError, RecursionError, UnicodeError) as exc:
        raise HTTPException(409, "不能从完整冻结床位原量构建固定算法公开投影") from exc
