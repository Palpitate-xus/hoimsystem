"""Whole current SKU collection. Late related originals invalidate, never leak."""

import copy
import datetime
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from pydantic import Field, model_validator
from sqlalchemy import and_, or_

from app.ai import supply_sources as sources
from app.ai.supply_contract import DateText, StrictModel, UtcText, canonical_json, day_bounds, hash_content
from app.ai.supply_source_input import ItemKind, Positive, Scope

MAX_MEMBERS = 4096
MAX_BYTES = 8 * 1024 * 1024
READ_BATCH = 32
COLLECTION_KEYS = frozenset(
    {
        "schema_version",
        "request",
        "captured_at",
        "as_of",
        "sku_binding",
        "scope_binding",
        "unit_definitions",
        "source_records",
        "member_manifest",
        "historical_collection_digest",
        "current_membership_digest",
        "collection_digest",
        "max_available_at",
    }
)


class CapturePeriodRequest(StrictModel):
    item_kind: ItemKind
    item_id: Positive
    scope: Scope
    timezone: str = Field(min_length=1, max_length=80)
    date_from: DateText
    date_to: DateText
    as_of: UtcText

    @model_validator(mode="after")
    def closed(self):
        try:
            first, last = datetime.date.fromisoformat(self.date_from), datetime.date.fromisoformat(self.date_to)
            current = datetime.datetime.fromisoformat(self.as_of.replace("Z", "+00:00")).astimezone(ZoneInfo(self.timezone)).date()
            if not 112 <= (last - first).days + 1 <= 366 or last != current - datetime.timedelta(days=1):
                raise ValueError("History must end at actual last closed business day,112..366 days")
            for offset in range((last - first).days + 1):
                day_bounds(first + datetime.timedelta(days=offset), self.timezone)
        except (ValueError, OverflowError, KeyError) as exc:
            raise ValueError("Explicit complete IANA closed history required") from exc
        return self


def scope_binding(sku):
    return {"item_kind": sku["item_kind"], "item_id": sku["item_id"], "scope": "hospital_inventory", "sku_identity_hash": hash_content(sku)}


def capture_view(value):
    result = copy.deepcopy(value)
    result.update(capture_view=True, audit_only=False, can_record=False, can_review=False, can_revoke=False)
    if not result["eligible"]:
        for key in ("payload", "parent_binding", "review_basis_note", "revoke_reason"):
            result[key] = None
    if not sources.verify_source_wrapper(result, capture=True):
        raise HTTPException(409, "捕获原件与闭集完整/隐去声明不一致")
    return result


def locator(kind, proof):
    base = {key: proof[key] for key in ("record_kind", "source_record_id", "item_kind", "item_id", "scope")}
    if kind == "daily":
        base.update({key: proof[key] for key in ("target", "date", "day_start_at", "day_end_at", "observed_at")}, timezone=proof["payload"]["timezone"])
    return base


def _historical(value):
    return {key: value[key] for key in ("request", "scope_binding", "unit_definitions", "source_records", "member_manifest")}


def _membership(value):
    return {"scope_binding": value["scope_binding"], "current_sku_state_hash": hash_content(value["sku_binding"]), "members": value["member_manifest"]}


def _finish(value):
    value["historical_collection_digest"] = hash_content(_historical(value))
    value["current_membership_digest"] = hash_content(_membership(value))
    value["collection_digest"] = hash_content({key: item for key, item in value.items() if key not in {"captured_at", "collection_digest"}})
    if len(canonical_json(value).encode()) > MAX_BYTES:
        raise HTTPException(422, "完整库存来源集合超过安全字节上限，不能截断")
    return value


def history_bounds(request):
    return day_bounds(request.date_from, request.timezone)[0], day_bounds(request.date_to, request.timezone)[1]


def daily_related(request, source):
    start, end = history_bounds(request)
    return request.date_from <= source["date"] <= request.date_to or source["day_start_at"] < end and source["day_end_at"] > start


def capture_sources(db, user, period, *, locking=False):
    request = CapturePeriodRequest.model_validate(period.model_dump(mode="json") if hasattr(period, "model_dump") else period)
    values = request.model_dump(mode="json")
    now = sources.utcnow()
    cutoff = sources.utc_datetime(request.as_of)
    if cutoff > now:
        raise HTTPException(422, "资料截止不能晚于实际服务器捕获时刻")
    if locking:
        actor, sku = sources.lock_supply_scope(db, user, request.item_kind, request.item_id, require_active=True)
    else:
        actor = sources.current_actor(db, user)
        sku = sources.sku_binding(db, request.item_kind, request.item_id, require_active=True)
    result = {
        "schema_version": "supply_capture_v1",
        "request": values,
        "captured_at": sources.utc_text(now),
        "as_of": request.as_of,
        "sku_binding": sku,
        "scope_binding": scope_binding(sku),
        "unit_definitions": [],
        "source_records": [],
        "member_manifest": [],
        "max_available_at": None,
    }
    clocks = []
    budget = 0
    history_start, history_end = (sources.utc_datetime(clock) for clock in history_bounds(request))
    for kind, (model, primary) in sources.MODELS.items():
        query = db.query(model).filter(model.item_kind == request.item_kind, model.item_id == request.item_id, model.scope == "hospital_inventory")
        if kind == "daily":
            query = query.filter(or_(and_(model.business_date >= request.date_from, model.business_date <= request.date_to), and_(model.day_start_at < history_end, model.day_end_at > history_start)))
        # No late ID, count, time, quantity or text is returned. A later related
        # original cannot be hidden to preserve a once-current winning series.
        if (
            sources.current_query(query.with_entities(getattr(model, primary)).filter(or_(model.recorded_at > cutoff, model.reviewed_at > cutoff, model.revoked_at > cutoff)), locking=locking)
            .limit(1)
            .first()
            is not None
        ):
            raise HTTPException(409, "完整当前来源集合已变化，请刷新真实资料截止后重新捕获")
        cursor = None
        while True:
            page = query if cursor is None else query.filter(getattr(model, primary) > cursor)
            rows = sources.current_query(page.order_by(getattr(model, primary)).limit(READ_BATCH), locking=locking).all()
            if not rows:
                break
            for row in rows:
                if len(result["member_manifest"]) >= MAX_MEMBERS:
                    raise HTTPException(422, "完整库存来源根超过4096，不能截断")
                rid = getattr(row, primary)
                proof = sources.source_proof(kind, row)
                if any(proof[key] is not None and proof[key] > request.as_of for key in ("recorded_at", "reviewed_at", "revoked_at")):
                    raise HTTPException(409, "完整当前来源集合已变化，请刷新真实资料截止后重新捕获")
                current = sources.source_current(db, actor, kind, rid, audit_only=False, locking=locking)
                view = capture_view(current)
                where = locator(kind, proof)
                entry = {"source": view, "locator": where, "locator_hash": hash_content(where)}
                metadata = sources.source_metadata(view)
                budget += len(canonical_json(entry).encode()) + len(canonical_json(metadata).encode())
                if budget > MAX_BYTES:
                    raise HTTPException(422, "完整库存来源集合超过安全字节上限，不能截断")
                result["unit_definitions" if kind == "unit" else "source_records"].append(entry)
                result["member_manifest"].append(metadata)
                clocks.extend(proof[key] for key in ("recorded_at", "reviewed_at", "revoked_at") if proof[key] is not None)
            cursor = getattr(rows[-1], primary)
    result["member_manifest"].sort(key=lambda r: (r["record_kind"], r["source_record_id"]))
    result["max_available_at"] = max(clocks) if clocks else None
    return _finish(result)


def verify_capture(value):
    """Pure proof; hidden noneligible bodies remain opaque SHA locators.

    This validates all disclosed complete originals, exact hidden metadata,
    locators, closure and canonical digests. It does not claim to reconstruct
    a hidden draft/revoked original or historical pharmacist identity from SHA.
    """
    try:
        if not isinstance(value, dict) or set(value) != COLLECTION_KEYS or value["schema_version"] != "supply_capture_v1" or len(canonical_json(value).encode()) > MAX_BYTES:
            raise ValueError()
        request = CapturePeriodRequest.model_validate(value["request"])
        values = request.model_dump(mode="json")
        from app.ai.supply_contract import utc

        utc(value["captured_at"])
        if (
            value["as_of"] != request.as_of
            or value["captured_at"] < request.as_of
            or value["scope_binding"] != scope_binding(value["sku_binding"])
            or any(value["sku_binding"][key] != values[key] for key in ("item_kind", "item_id", "scope"))
        ):
            raise ValueError()
        entries = value["unit_definitions"] + value["source_records"]
        if len(entries) > MAX_MEMBERS or not all(isinstance(value[key], list) for key in ("unit_definitions", "source_records", "member_manifest")):
            raise ValueError()
        manifest = []
        clocks = []
        seen = set()
        for group, kind in (("unit_definitions", "unit"), ("source_records", "daily")):
            order = []
            for entry in value[group]:
                if not isinstance(entry, dict) or set(entry) != {"source", "locator", "locator_hash"}:
                    raise ValueError()
                source = entry["source"]
                where = entry["locator"]
                if (
                    not sources.verify_source_wrapper(source, capture=True)
                    or source["record_kind"] != kind
                    or any(source[k] != values[k] for k in ("item_kind", "item_id", "scope"))
                    or source["payload"] is not None
                    and source["parent_binding"]["sku"] != value["sku_binding"]
                ):
                    raise ValueError()
                if source["source_record_id"] in seen:
                    raise ValueError()
                seen.add(source["source_record_id"])
                order.append(source["source_record_id"])
                if kind == "unit":
                    expected = {key: source[key] for key in ("record_kind", "source_record_id", "item_kind", "item_id", "scope")}
                else:
                    if (
                        not daily_related(request, source)
                        or not isinstance(where, dict)
                        or set(where) != {"record_kind", "source_record_id", "item_kind", "item_id", "scope", "target", "date", "day_start_at", "day_end_at", "observed_at", "timezone"}
                    ):
                        raise ValueError()
                    expected = {key: source[key] for key in ("record_kind", "source_record_id", "item_kind", "item_id", "scope", "target", "date", "day_start_at", "day_end_at", "observed_at")}
                    expected["timezone"] = where["timezone"]
                    start, end = day_bounds(source["date"], where["timezone"])
                    if (start, end) != (source["day_start_at"], source["day_end_at"]) or source["payload"] is not None and where["timezone"] != source["payload"]["timezone"]:
                        raise ValueError()
                if where != expected or entry["locator_hash"] != hash_content(where):
                    raise ValueError()
                for key in ("recorded_at", "reviewed_at", "revoked_at"):
                    if source[key] is not None:
                        if source[key] > request.as_of:
                            raise ValueError()
                        clocks.append(source[key])
                manifest.append(sources.source_metadata(source))
            if order != sorted(order):
                raise ValueError()
        manifest.sort(key=lambda r: (r["record_kind"], r["source_record_id"]))
        if (
            value["member_manifest"] != manifest
            or value["max_available_at"] != (max(clocks) if clocks else None)
            or value["historical_collection_digest"] != hash_content(_historical(value))
            or value["current_membership_digest"] != hash_content(_membership(value))
            or value["collection_digest"] != hash_content({key: item for key, item in value.items() if key not in {"captured_at", "collection_digest"}})
        ):
            raise ValueError()
        return copy.deepcopy(value)
    except (ValueError, TypeError, KeyError, RecursionError) as exc:
        raise HTTPException(409, "完整捕获原件、隐去边界、逐根定位或集合摘要无法核对") from exc
