"""Complete single-SKU selections. Never fills unknowns or selects latest originals."""

import datetime
import secrets
from typing import Annotated, Literal
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from pydantic import AfterValidator, Field, model_validator

from app.ai import supply_contract as core
from app.ai.supply_source_input import ItemKind, Positive, Scope, check_basis

SCHEMA_VERSION = "supply_series_private_v1"
MAX_BYTES = core.MAX_BYTES
Basis = Annotated[str, Field(min_length=20, max_length=4000), AfterValidator(check_basis)]


def utcnow():
    return datetime.datetime.now(datetime.UTC).replace(tzinfo=None)


def utc_text(value):
    if value.tzinfo is not None:
        value = value.astimezone(datetime.UTC).replace(tzinfo=None)
    return core.utc(value.isoformat(timespec="microseconds") + "Z")


def instant(value):
    return datetime.datetime.fromisoformat(core.utc(value).replace("Z", "+00:00"))


def period_days(request):
    first, last = datetime.date.fromisoformat(request.date_from), datetime.date.fromisoformat(request.date_to)
    rows = []
    for i in range((last - first).days + 1):
        d = first + datetime.timedelta(days=i)
        start, end = core.day_bounds(d, request.timezone)
        rows.append({"date": d.isoformat(), "day_start_at": start, "day_end_at": end})
    return rows


class SeriesPeriodRequest(core.StrictModel):
    item_kind: ItemKind
    item_id: Positive
    scope: Scope
    timezone: str = Field(min_length=1, max_length=80)
    date_from: core.DateText
    date_to: core.DateText
    as_of: core.UtcText

    @model_validator(mode="after")
    def closed_period(self):
        try:
            first, last = datetime.date.fromisoformat(self.date_from), datetime.date.fromisoformat(self.date_to)
            if not 112 <= (last - first).days + 1 <= 366 or (instant(self.as_of).astimezone(ZoneInfo(self.timezone)).date() - datetime.timedelta(days=1)) != last:
                raise ValueError("112..366 closed days ending at frozen cutoff local date minus one required")
            period_days(self)
            for lead in range(1, 15):
                core.day_bounds(last + datetime.timedelta(days=lead), self.timezone)
        except (KeyError, OverflowError) as exc:
            raise ValueError("Invalid IANA timezone or Gregorian horizon") from exc
        return self


class TargetCoverageDeclaration(core.StrictModel):
    target: core.Target
    same_scope_confirmed: core.Review
    same_definition_confirmed: core.Review
    same_method_confirmed: core.Review
    basis_note: Basis


class TargetSelection(core.StrictModel):
    target: core.Target
    source_record_id: core.UUID | None
    absent_reason: Literal["missing_selected_original", "unresolved_conflict"] | None
    group_digest: core.SHA256
    basis_note: Basis

    @model_validator(mode="after")
    def selected_or_missing(self):
        if (self.source_record_id is None) != (self.absent_reason is not None):
            raise ValueError("Explicit whole original or absent reason required")
        return self


class DaySelection(core.StrictModel):
    date: core.DateText
    selections: list[TargetSelection] = Field(min_length=3, max_length=3)

    @model_validator(mode="after")
    def all_targets(self):
        if [r.target for r in self.selections] != list(core.TARGETS):
            raise ValueError("All three independent ordered targets required")
        return self


class MemberReview(core.StrictModel):
    source_record_id: core.UUID
    source_kind: Literal["unit_definition", "daily_quantity"]
    expected_content_hash: core.SHA256
    expected_governance_hash: core.SHA256
    selection: Literal["confirmed", "excluded", "unknown"]
    basis_note: Basis


class SeriesRequest(SeriesPeriodRequest):
    unit_definition_id: core.UUID
    expected_unit_content_hash: core.SHA256
    expected_unit_governance_hash: core.SHA256
    parameters: core.Parameters
    days: list[DaySelection] = Field(min_length=112, max_length=366)
    target_coverage: list[TargetCoverageDeclaration] = Field(min_length=3, max_length=3)
    member_reviews: list[MemberReview] = Field(max_length=core.MAX_MEMBERS)

    @model_validator(mode="after")
    def complete_declarations(self):
        if [r.date for r in self.days] != [r["date"] for r in period_days(self)] or [r.target for r in self.target_coverage] != list(core.TARGETS):
            raise ValueError("Whole chronological period and all target declarations required")
        keys = [(r.source_kind, r.source_record_id) for r in self.member_reviews]
        if len(set(keys)) != len(keys):
            raise ValueError("Each related original is reviewed exactly once")
        return self


def typed_period(value):
    try:
        if isinstance(value, (SeriesRequest, SeriesPeriodRequest)):
            value = value.model_dump(mode="json")
        if isinstance(value, dict) and set(value) == set(SeriesRequest.model_fields):
            value = {k: value[k] for k in SeriesPeriodRequest.model_fields}
        return SeriesPeriodRequest.model_validate(value)
    except (ValueError, TypeError, OverflowError) as exc:
        raise HTTPException(422, "须明确单SKU范围、IANA完整日及真实资料截止") from exc


def typed_request(value):
    try:
        return value if isinstance(value, SeriesRequest) else SeriesRequest.model_validate(value)
    except (ValueError, TypeError, OverflowError) as exc:
        raise HTTPException(422, "须逐日逐目标选择、完整成员用途及三个明确分数参数") from exc


def validate_series_period(request, *, now=None):
    request = typed_period(request)
    last = (instant(utc_text(utcnow() if now is None else now)).astimezone(ZoneInfo(request.timezone)).date() - datetime.timedelta(days=1)).isoformat()
    if request.date_to != last:
        raise HTTPException(409, "新预测须使用当前业务时区最近已闭合日，旧序列不冒充当前预测")
    return period_days(request)


def bounded_json(value):
    try:
        text = core.canonical_json(value)
        if not 0 < len(text.encode()) <= MAX_BYTES:
            raise ValueError("Whole value exceeds8MiB")
        return text
    except (ValueError, TypeError, OverflowError, RecursionError) as exc:
        raise HTTPException(409, "完整原件超容量或非规范JSON，未截断") from exc


def candidate_groups(collection, request):
    groups = []
    for day in period_days(request):
        for target in core.TARGETS:
            members = []
            for record in collection["source_records"]:
                loc, s = record["locator"], record["source"]
                if loc["target"] == target and (loc["date"] == day["date"] or loc["day_start_at"] < day["day_end_at"] and loc["day_end_at"] > day["day_start_at"]):
                    members.append({k: s[k] for k in ("source_record_id", "content_hash", "governance_hash", "status", "eligible")} | {"locator_hash": record["locator_hash"]})
            body = day | {"target": target, "members": sorted(members, key=lambda r: r["source_record_id"])}
            groups.append(body | {"group_digest": core.hash_content(body)})
    return groups


def validate_selections(collection, request):
    rows = collection["unit_definitions"] + collection["source_records"]
    originals = {(r["source"]["source_kind"], r["source"]["source_record_id"]): r["source"] for r in rows}
    reviews = {(r.source_kind, r.source_record_id): r for r in request.member_reviews}
    if len(originals) != len(rows) or originals.keys() != reviews.keys():
        raise HTTPException(409, "须对完整单位及日原件全集逐件声明，不得遗漏")
    for key, s in originals.items():
        r = reviews[key]
        if (r.expected_content_hash, r.expected_governance_hash) != (s["content_hash"], s["governance_hash"]):
            raise HTTPException(409, "原成员内容或治理变化，请重新完整捕获")
        if r.selection == "confirmed" and (s["status"] != "published" or not s["eligible"] or s["payload"] is None):
            raise HTTPException(409, "失效或未发布原件不能确认为观察")
    unit = originals.get(("unit_definition", request.unit_definition_id))
    if (
        unit is None
        or (unit["content_hash"], unit["governance_hash"]) != (request.expected_unit_content_hash, request.expected_unit_governance_hash)
        or reviews[("unit_definition", request.unit_definition_id)].selection != "confirmed"
        or unit["professional_status"] != "confirmed"
    ):
        raise HTTPException(409, "须选择当前已发布并由真实药师确认的完整单位原件")
    groups = {(r["date"], r["target"]): r for r in candidate_groups(collection, request)}
    chosen = set()
    for day in request.days:
        for selection in day.selections:
            group = groups[(day.date, selection.target)]
            if selection.group_digest != group["group_digest"]:
                raise HTTPException(409, "该日完整候选集合变化，不能保留旧赢家")
            eligible = [m for m in group["members"] if m["eligible"] and m["status"] == "published"]
            if len(eligible) > 1 and (selection.source_record_id is not None or selection.absent_reason != "unresolved_conflict"):
                raise HTTPException(409, "多个当前同日同目标原件必须保留冲突，不能排除不利成员制造赢家")
            if selection.source_record_id is None:
                continue
            s = originals.get(("daily_quantity", selection.source_record_id))
            if s is None or not any(m["source_record_id"] == selection.source_record_id for m in group["members"]) or reviews[("daily_quantity", selection.source_record_id)].selection != "confirmed":
                raise HTTPException(409, "逐日选择未绑定已确认完整原件")
            p = s["payload"]
            if (p["target"], p["date"], p["timezone"], p["day_start_at"], p["day_end_at"]) != (
                selection.target,
                day.date,
                request.timezone,
                *core.day_bounds(day.date, request.timezone),
            ) or selection.source_record_id in chosen:
                raise HTTPException(409, "原件与所选目标、日期或真实日界不符")
            chosen.add(selection.source_record_id)
    if chosen != {r.source_record_id for r in request.member_reviews if r.source_kind == "daily_quantity" and r.selection == "confirmed"}:
        raise HTTPException(409, "每件已确认日原件必须引用一次，不能隐去或重复原量")
    return unit


def current_collection(db, user, *, request, locking=False):
    from app.ai.supply_collection import capture_sources

    return capture_sources(db, user, typed_period(request), locking=locking)


def preview_input(db, user, request, *, locking=False):
    request = typed_period(request)
    collection = current_collection(db, user, request=request, locking=locking)
    value = {"schema_version": "supply_series_preview_v1", "collection": collection, "groups": candidate_groups(collection, request), "expected_capture_digest": collection["collection_digest"]}
    bounded_json(value)
    return value


def capture_input(db, user, request, series_id, *, expected_collection_digest=None, locking=False):
    from app.ai import supply_sources as facts
    from app.ai.supply_snapshot import verify_snapshot

    request = typed_request(request)
    actor = facts.current_actor(db, user, locking=locking)
    collection = current_collection(db, actor, request=request, locking=locking)
    if expected_collection_digest is not None and collection["collection_digest"] != expected_collection_digest:
        raise HTTPException(409, "当前全集变化，请重新核对全部候选")
    validate_selections(collection, request)
    profile = {"parameters": request.parameters.model_dump(mode="json"), "recipe_digest": core.recipe_digest(), "input_policy_digest": core.input_policy_digest()}
    snapshot = {
        "schema_version": SCHEMA_VERSION,
        "series_id": core.identity(series_id),
        "item_kind": request.item_kind,
        "item_id": request.item_id,
        "scope": request.scope,
        "created_by": actor.user_id,
        "as_of": request.as_of,
        "captured_at": collection["captured_at"],
        "identity_secret": secrets.token_hex(32),
        "request": request.model_dump(mode="json"),
        "collection": collection,
        "collection_digest": collection["collection_digest"],
        "recipe": core.RECIPE,
        "input_policy": core.INPUT_POLICY,
        "recipe_digest": core.recipe_digest(),
        "input_policy_digest": core.input_policy_digest(),
        "profile": profile,
    }
    verify_snapshot(snapshot)
    bounded_json(snapshot)
    return snapshot


def project_source(snapshot, governance_hash, *, validate_current_recipe=True):
    from app.ai.supply_projection import project_source as project

    return project(snapshot, governance_hash, validate_current_recipe=validate_current_recipe)


def verify_snapshot(snapshot):
    from app.ai.supply_snapshot import verify_snapshot as verify

    return verify(snapshot)
