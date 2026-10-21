"""Explicit whole-source choices and common constraints for a finite inventory scene."""

import datetime
import secrets
from fractions import Fraction
from typing import Annotated, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import HTTPException
from pydantic import AfterValidator, Field, model_validator

from app.ai import inventory_contract as core
from app.ai.inventory_native_source_input import Cost, ItemKind, Positive, Quantity
from app.ai.supply_source_input import check_basis

SCHEMA_VERSION = "inventory_scenario_private_v1"
Basis = Annotated[str, Field(min_length=20, max_length=4000), AfterValidator(check_basis)]


def utcnow():
    return datetime.datetime.now(datetime.UTC).replace(tzinfo=None)


def utc_text(value):
    if value.tzinfo is not None:
        value = value.astimezone(datetime.UTC).replace(tzinfo=None)
    return core.utc(value.isoformat(timespec="microseconds") + "Z")


def instant(value):
    return datetime.datetime.fromisoformat(core.utc(value).replace("Z", "+00:00"))


def bounded_json(value):
    try:
        text = core.canonical_json(value)
        if not 0 < len(text.encode()) <= core.MAX_BYTES:
            raise ValueError("Complete scene exceeds8MiB")
        return text
    except (ValueError, TypeError, RecursionError, OverflowError) as exc:
        raise HTTPException(409, "完整库存场景超容量或不是规范JSON，未截断") from exc


class ScenarioPeriodRequest(core.StrictModel):
    item_kind: ItemKind
    item_id: Positive
    scope: Literal["hospital_inventory"]
    timezone: str = Field(min_length=1, max_length=100)
    date_from: core.DateText
    date_to: core.DateText
    as_of: core.UtcText

    @model_validator(mode="after")
    def future_period(self):
        try:
            local_today = instant(self.as_of).astimezone(ZoneInfo(self.timezone)).date()
            first, last = datetime.date.fromisoformat(self.date_from), datetime.date.fromisoformat(self.date_to)
            if not 1 <= (last - first).days + 1 <= 31 or first <= local_today:
                raise ValueError("One to31 consecutive business dates strictly after the declared cutoff local date required")
            for offset in range((last - first).days + 1):
                core.day_bounds(first + datetime.timedelta(days=offset), self.timezone)
        except (ZoneInfoNotFoundError, OverflowError) as exc:
            raise ValueError("Actual IANA zone and unambiguous Gregorian midnights required") from exc
        return self


class OriginalRef(core.StrictModel):
    source_record_id: core.UUID
    expected_content_hash: core.SHA256
    expected_governance_hash: core.SHA256


class MemberReview(OriginalRef):
    source_kind: Literal["unit_definition", "inventory_observation", "future_quantity_scenario", "purchase_candidate_plan"]
    use: Literal["confirmed", "excluded", "unknown"]
    basis_note: Basis


class QuantityConstraint(core.StrictModel):
    mode: Literal["known", "unknown", "not_applicable"]
    amount: Quantity | None

    @model_validator(mode="after")
    def explicit_amount(self):
        if (self.mode == "known") != (self.amount is not None) or self.amount is not None and self.amount.value is None:
            raise ValueError("Known constraint requires one actual nonnegative amount; unknown and not-applicable contain none")
        return self


class CostConstraint(core.StrictModel):
    mode: Literal["known", "unknown", "not_applicable"]
    amount: Cost | None

    @model_validator(mode="after")
    def explicit_amount(self):
        if (self.mode == "known") != (self.amount is not None) or self.amount is not None and self.amount.value is None:
            raise ValueError("Shared known budget requires one actual monetary amount; unknown is not unlimited")
        return self


class DayConstraints(core.StrictModel):
    date: core.DateText
    minimum_end_usable: QuantityConstraint
    maximum_end_total: QuantityConstraint


class CostUnit(core.StrictModel):
    currency_text: str = Field(min_length=1, max_length=32)
    original_cost_unit_text: str = Field(min_length=1, max_length=120)
    review: core.Review
    basis_note: Basis

    @model_validator(mode="after")
    def explicit_cost_unit(self):
        if not self.currency_text.strip() or not self.original_cost_unit_text.strip():
            raise ValueError("Actual currency and cost-unit text are explicit, never inferred from a catalog price")
        return self


class Assumptions(core.StrictModel):
    opening_carry_forward: core.Review
    no_other_inventory_changes: core.Review
    frozen_quantities_unchanged: core.Review
    basis_note: Basis


class ScenarioRequest(ScenarioPeriodRequest):
    unit_definition_id: core.UUID
    expected_unit_content_hash: core.SHA256
    expected_unit_governance_hash: core.SHA256
    observation: OriginalRef
    future_quantity_scenario: OriginalRef
    candidates: list[OriginalRef] = Field(min_length=1, max_length=core.MAX_CANDIDATES)
    member_reviews: list[MemberReview] = Field(max_length=4096)
    daily_constraints: list[DayConstraints] = Field(min_length=1, max_length=31)
    shared_budget: CostConstraint
    cost_unit: CostUnit
    policy_review: core.Review
    policy_basis_note: Basis
    assumptions: Assumptions
    candidate_set_review: core.Review
    candidate_set_basis_note: Basis

    @model_validator(mode="before")
    @classmethod
    def complete_request_bytes(cls, value):
        if isinstance(value, dict) and len(core.canonical_json(value).encode()) > core.MAX_BYTES:
            raise ValueError("Whole scene request exceeds8MiB; no truncation")
        return value

    @model_validator(mode="after")
    def complete_choices(self):
        first, last = datetime.date.fromisoformat(self.date_from), datetime.date.fromisoformat(self.date_to)
        if [day.date for day in self.daily_constraints] != [(first + datetime.timedelta(days=i)).isoformat() for i in range((last - first).days + 1)]:
            raise ValueError("All common daily min/max constraints appear exactly once in chronological order")
        ids = [self.observation.source_record_id, self.future_quantity_scenario.source_record_id, *(row.source_record_id for row in self.candidates)]
        if len(set(ids)) != len(ids):
            raise ValueError("Whole original roles and candidate membership cannot repeat")
        reviews = [(row.source_kind, row.source_record_id) for row in self.member_reviews]
        if len(set(reviews)) != len(reviews):
            raise ValueError("Every original member has exactly one explicit use declaration")
        return self


def typed_period(value):
    try:
        if isinstance(value, (ScenarioRequest, ScenarioPeriodRequest)):
            value = value.model_dump(mode="json")
        if isinstance(value, dict) and set(value) == set(ScenarioRequest.model_fields):
            value = {key: value[key] for key in ScenarioPeriodRequest.model_fields}
        return ScenarioPeriodRequest.model_validate(value)
    except (ValueError, TypeError, OverflowError) as exc:
        raise HTTPException(422, "须明确单SKU、未来完整日、IANA时区与真实资料截止") from exc


def typed_request(value):
    try:
        return value if isinstance(value, ScenarioRequest) else ScenarioRequest.model_validate(value)
    except (ValueError, TypeError, OverflowError) as exc:
        raise HTTPException(422, "须完整声明原件、全体候选及共同约束和依据") from exc


def validate_planning_period(request, *, now=None):
    request = typed_period(request)
    now = utcnow() if now is None else now
    cutoff = instant(request.as_of)
    clock = instant(utc_text(now))
    if cutoff > clock or datetime.date.fromisoformat(request.date_from) <= clock.astimezone(ZoneInfo(request.timezone)).date():
        raise HTTPException(409, "新方案须规划当下业务日期之后的完整未来日，旧截止不冒充历史库存回放")
    return request


def source_rows(collection):
    rows = collection["unit_definitions"] + collection["source_records"]
    result = {(r["source"]["source_kind"], r["source"]["source_record_id"]): r["source"] for r in rows}
    if len(result) != len(rows):
        raise HTTPException(409, "完整来源集合成员身份重复")
    return result


def validate_selections(collection, values):
    req = typed_request(values)
    originals = source_rows(collection)
    reviews = {(r.source_kind, r.source_record_id): r for r in req.member_reviews}
    if originals.keys() != reviews.keys():
        raise HTTPException(409, "须逐件处置完整单位和原始来源全集，不能只审核赢家")
    for key, original in originals.items():
        declaration = reviews[key]
        if (declaration.expected_content_hash, declaration.expected_governance_hash) != (original["content_hash"], original["governance_hash"]):
            raise HTTPException(409, "原成员内容或治理已改变，请完整重新捕获")
        if declaration.use == "confirmed" and (original["status"] != "published" or original["payload"] is None):
            raise HTTPException(409, "未发布或失效原件不能确认为来源")

    unit = originals.get(("unit_definition", req.unit_definition_id))
    if unit is None or unit["status"] != "published" or not unit["eligible"] or unit["payload"] is None or unit["professional_status"] != "confirmed":
        raise HTTPException(409, "须使用当前真实药师专业签署并独立审核的完整原计量定义")
    if (unit["content_hash"], unit["governance_hash"]) != (req.expected_unit_content_hash, req.expected_unit_governance_hash):
        raise HTTPException(409, "原计量内容或治理已变化")

    selected = []
    for kind, ref in [("inventory_observation", req.observation), ("future_quantity_scenario", req.future_quantity_scenario), *(("purchase_candidate_plan", row) for row in req.candidates)]:
        original = originals.get((kind, ref.source_record_id))
        if original is None or original["status"] != "published" or original["payload"] is None:
            raise HTTPException(409, "须选择已发布且完整可鉴真的原件，不自动选最新值")
        if (original["content_hash"], original["governance_hash"]) != (ref.expected_content_hash, ref.expected_governance_hash):
            raise HTTPException(409, "选择的完整原件内容或治理已变化")
        if (original["item_kind"], original["item_id"], original["scope"]) != (req.item_kind, req.item_id, req.scope):
            raise HTTPException(409, "各完整原件必须属于同一真实SKU和物理范围；各自原计量未知或错配原样保留")
        if kind != "inventory_observation" and any(original["payload"][key] != getattr(req, key) for key in ("timezone", "date_from", "date_to")):
            raise HTTPException(409, "未来原量和完整候选必须明确适用于本次同一日域")
        selected.append(original)
    candidates = selected[2:]
    actual = {
        original["source_record_id"]
        for (kind, _), original in originals.items()
        if kind == "purchase_candidate_plan"
        and original["status"] == "published"
        and original["payload"] is not None
        and all(original["payload"][key] == getattr(req, key) for key in ("timezone", "date_from", "date_to"))
    }
    if actual != {r.source_record_id for r in req.candidates}:
        raise HTTPException(409, "须纳入同范围同日域的全部已发布候选，未知或不利方案不能被排除")
    if not any(not row["payload"]["orders"] and row["payload"]["plan_fixed_fee"]["value"] is not None and Fraction(row["payload"]["plan_fixed_fee"]["value"]) == 0 for row in candidates):
        raise HTTPException(409, "须有真实已受审的零订单且明确零固定费用基线原件，不自动补零方案")
    return unit, selected, reviews


def observation_conflicts(collection, values, selected):
    """Current independent counts cannot be hidden by a carry-forward checkbox.

    Original observations remain unmodified. Exact numeric equality tolerates
    original lexical decimal formatting; lot identity, units, frozen amounts
    and original expiry still distinguish actual physical-count claims.
    """
    req = typed_request(values)
    payload = selected["payload"]
    if payload["method"] != "independent_count":
        return []

    def numeric(quantity):
        return {**quantity, "value": None if quantity["value"] is None else core.rational(Fraction(quantity["value"]))}

    def signature(original):
        return {
            "total": numeric(original["declared_total_quantity"]),
            "lots": sorted(
                [
                    {
                        key: (numeric(row[key]) if key in {"quantity", "frozen_quantity"} else row[key])
                        for key in ("lot_id", "quantity", "frozen_quantity", "valid_through", "expiry_review", "frozen_review")
                    }
                    for row in original["lots"]
                ],
                key=lambda row: row["lot_id"],
            ),
        }

    selected_signature = signature(payload)
    result = []
    for record in collection["source_records"]:
        source = record["source"]
        p = source["payload"]
        if (
            source["source_record_id"] != selected["source_record_id"]
            and source["source_kind"] == "inventory_observation"
            and source["status"] == "published"
            and source["unit_definition_id"] == selected["unit_definition_id"]
            and p is not None
            and p["method"] == "independent_count"
            and payload["observed_at"] <= p["observed_at"] <= req.as_of
            and signature(p) != selected_signature
        ):
            result.append({"source_record_id": source["source_record_id"], "content_hash": source["content_hash"], "observed_at": p["observed_at"]})
    return sorted(result, key=lambda row: row["source_record_id"])


def profile_for(request, recipe_digest, input_policy_digest):
    req = typed_request(request)
    return {
        "schema_version": "inventory_profile_private_v1",
        "recipe_digest": recipe_digest,
        "input_policy_digest": input_policy_digest,
        **{
            key: req.model_dump(mode="json")[key]
            for key in ("daily_constraints", "shared_budget", "cost_unit", "policy_review", "policy_basis_note", "assumptions", "candidate_set_review", "candidate_set_basis_note")
        },
    }


def current_collection(db, user, *, request, locking=False):
    from app.ai.inventory_native_collection import capture_sources

    return capture_sources(db, user, typed_period(request), locking=locking)


def preview_input(db, user, request):
    req = typed_period(request)
    validate_planning_period(req)
    return current_collection(db, user, request=req)


def capture_input(db, user, request, scenario_id, *, expected_collection_digest=None, locking=False):
    req = typed_request(request)
    validate_planning_period(req)
    core.identity(scenario_id)
    collection = current_collection(db, user, request=req, locking=locking)
    if expected_collection_digest is not None and collection["collection_digest"] != expected_collection_digest:
        raise HTTPException(409, "完整原来源或库存集合已变化，请重新捕获")
    validate_selections(collection, req)
    snapshot = {
        "schema_version": SCHEMA_VERSION,
        "scenario_id": scenario_id,
        "item_kind": req.item_kind,
        "item_id": req.item_id,
        "scope": req.scope,
        "created_by": user.user_id,
        "as_of": req.as_of,
        "captured_at": collection["captured_at"],
        "identity_secret": secrets.token_hex(32),
        "request": req.model_dump(mode="json"),
        "collection": collection,
        "collection_digest": collection["collection_digest"],
        "recipe": core.RECIPE,
        "input_policy": core.INPUT_POLICY,
        "recipe_digest": core.recipe_digest(),
        "input_policy_digest": core.input_policy_digest(),
        "profile": profile_for(req, core.recipe_digest(), core.input_policy_digest()),
    }
    bounded_json(snapshot)
    return snapshot


def legacy_frozen_conflict(selected):
    """Only compare already reviewed, same-unit whole physical frozen totals.

    A legacy frozen flag never fills a physical-count field. The explicit new
    continuation declaration loses certainty when its own disclosed originals
    already contain a known contradiction.
    """
    p = selected["payload"]
    parent = selected["parent_binding"]
    legacy, unit = parent["legacy_snapshot"], parent["unit_definition"]
    if (
        selected["item_kind"] != "pharmaceutical"
        or selected["professional_status"] != "confirmed"
        or p["method"] != "independent_count"
        or p["coverage"] != "attested_complete"
        or p["scope_review"] != "confirmed"
        or p["legacy_quantity_unit_review"] != "confirmed"
        or unit is None
    ):
        return None
    original_unit = unit["payload"]["original_unit_text"]
    raw_unit = legacy["sku"]["projection"]["unit"]
    if raw_unit is not None and raw_unit != original_unit:
        return None
    actual = 0
    for row in legacy["batches"]:
        stock, status = row["projection"]["stock"], row["projection"]["status"]
        if type(stock) is not int or stock < 0 or type(status) is not int or status not in (0, 1):
            return None
        if status == 1:
            actual += stock
    claimed = Fraction(0)
    for row in p["lots"]:
        q = row["frozen_quantity"]
        if q["value"] is None or q["unit_review"] != "confirmed" or q["original_unit_text"] != original_unit or row["frozen_review"] != "confirmed":
            return None
        claimed += Fraction(q["value"])
    if claimed == actual:
        return None
    return {"legacy_frozen_quantity": core.rational(actual), "physical_frozen_quantity": core.rational(claimed), "legacy_collection_digest": legacy["collection_digest"]}
