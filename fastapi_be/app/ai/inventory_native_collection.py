"""Complete, bounded, current inventory capsules; never reconstructs past stock.

Opaque original-row hashes include withheld business references. The complete
safe projection and its own digest can be rebuilt; undisclosed raw columns
cannot be reconstructed by a client from these capsules.
"""

from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from fastapi import HTTPException
from sqlalchemy import or_

from app.ai.inventory_contract import canonical_json, hash_content, utc
from app.ai.inventory_write_guard import current_inventory_rows, lock_inventory_gate
from app.ai.supply_sources import utc_text, utcnow
from app.models import Consumable, Pharmaceutical, PharmaceuticalBatch, PharmaceuticalStockLedger, PurchaseOrder, PurchaseOrderItem

MAX_LEGACY_ROWS = 4096
MAX_LEGACY_BYTES = 4194304
BATCH_SIZE = 32
TIME_BASIS = "legacy_naive_unknown_not_utc_evidence"
SCOPE = "hospital_inventory"


def original_scalar(value):
    if value is None or type(value) in (str, int, bool):
        return value
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise HTTPException(409, "原库存记录包含非有限数值，不能生成完整受控快照")
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat(timespec="microseconds")
    if isinstance(value, date):
        return value.isoformat()
    raise HTTPException(409, "原库存列类型无法完整保留，不能截断或补值")


def original_row(row):
    return {column.name: original_scalar(getattr(row, column.name)) for column in row.__table__.columns}


def capsule(kind, identifier, item_kind, item_id, projection, raw):
    digest = hash_content(raw)
    return {
        "schema_version": "inventory_legacy_capsule_v1",
        "record_kind": kind,
        "record_id": identifier,
        "item_kind": item_kind,
        "item_id": item_id,
        "scope": SCOPE,
        "projection": projection,
        "projection_hash": hash_content(projection),
        "original_row_hash": digest,
        "source_id": f"inventory_legacy:{kind}:{identifier}:{digest[:12]}",
    }


class CaptureBudget:
    def __init__(self):
        self.rows = 0
        self.bytes = 0

    def keep(self, value):
        self.rows += 1
        self.bytes += len(canonical_json(value).encode())
        if self.rows > MAX_LEGACY_ROWS or self.bytes > MAX_LEGACY_BYTES:
            raise HTTPException(409, "实际库存完整集合超出受控容量，未截断为完整资料")
        return value


def read_all(query, primary, build, budget, identifier):
    result, cursor = [], 0
    while True:
        # IDs alone are batched. Full originals are read one at a time, so32
        # potentially large rows cannot be materialised before byte accounting.
        ids = current_inventory_rows(query.with_entities(primary).filter(primary > cursor).order_by(primary).limit(BATCH_SIZE)).all()
        if not ids:
            break
        for (pk,) in ids:
            row = current_inventory_rows(query.filter(primary == pk)).one_or_none()
            if row is None or identifier(row) != pk:
                raise HTTPException(409, "完整库存成员读取期间发生变化，请重新捕获")
            result.append(budget.keep(build(row)))
            cursor = pk
    return result


def legacy_content(value):
    return {key: value[key] for key in ("item_kind", "item_id", "scope", "sku", "batches", "ledger_entries", "open_purchase_items")}


def capture_legacy_inventory(db, item_kind, item_id):
    """Caller checks actor permission; this helper ensures the actual SQL gate.

    All clocks are current server capture clocks. Legacy naive row clocks stay
    explicitly unverified, even when their literal text resembles UTC.
    """
    if item_kind not in {"pharmaceutical", "consumable"} or type(item_id) is not int or not 1 <= item_id <= 2147483647:
        raise HTTPException(422, "须明确一个实际医院库存品种")
    with db.no_autoflush:
        lock_inventory_gate(db)
        model, primary = (Pharmaceutical, Pharmaceutical.pharmaceutical_id) if item_kind == "pharmaceutical" else (Consumable, Consumable.consumable_id)
        row = current_inventory_rows(db.query(model).filter(primary == item_id)).one_or_none()
        if row is None:
            raise HTTPException(409, "实际库存品种已不存在")
        raw = original_row(row)
        projection = {
            "name": row.name,
            "status": row.status,
            "stock": row.stock,
            "price": original_scalar(row.price),
            "unit": row.unit if item_kind == "consumable" else None,
            "barcode": row.barcode if item_kind == "pharmaceutical" else None,
            "category": row.category if item_kind == "consumable" else None,
            "expiry_date": original_scalar(row.expireddate) if item_kind == "pharmaceutical" else None,
            "purchasing_time_legacy": original_scalar(row.purchasing_time) if item_kind == "pharmaceutical" else None,
            "time_basis": TIME_BASIS,
        }
        budget = CaptureBudget()
        sku = budget.keep(capsule("sku", item_id, item_kind, item_id, projection, raw))
        batches, ledger = [], []
        if item_kind == "pharmaceutical":
            batch_query = db.query(PharmaceuticalBatch).filter(PharmaceuticalBatch.pharmaceutical_id == item_id)

            def batch(row):
                values = {key: original_scalar(getattr(row, key)) for key in ("batch_id", "pharmaceutical_id", "stock", "status", "expiry_date")}
                values.update(create_time_legacy=original_scalar(row.create_time), update_time_legacy=original_scalar(row.update_time), time_basis=TIME_BASIS)
                return capsule("batch", row.batch_id, item_kind, item_id, values, original_row(row))

            batches = read_all(batch_query, PharmaceuticalBatch.batch_id, batch, budget, lambda row: row.batch_id)
            ledger_query = db.query(PharmaceuticalStockLedger).filter(PharmaceuticalStockLedger.pharmaceutical_id == item_id)

            def movement(row):
                values = {key: original_scalar(getattr(row, key)) for key in ("ledger_id", "batch_id", "pharmaceutical_id", "transaction_type", "quantity", "before_stock", "after_stock")}
                values.update(create_time_legacy=original_scalar(row.create_time), time_basis=TIME_BASIS)
                return capsule("ledger", row.ledger_id, item_kind, item_id, values, original_row(row))

            ledger = read_all(ledger_query, PharmaceuticalStockLedger.ledger_id, movement, budget, lambda row: row.ledger_id)
        purchase_query = (
            db.query(PurchaseOrderItem, PurchaseOrder)
            .join(PurchaseOrder, PurchaseOrder.purchase_id == PurchaseOrderItem.purchase_id)
            .filter(
                PurchaseOrderItem.item_type == ("drug" if item_kind == "pharmaceutical" else "consumable"),
                PurchaseOrderItem.item_id_ref == item_id,
                or_(PurchaseOrder.status.is_(None), PurchaseOrder.status.notin_((2, 3))),
            )
        )

        def purchase(pair):
            line, order = pair
            values = {
                key: original_scalar(getattr(line, key)) for key in ("item_id", "purchase_id", "item_type", "item_id_ref", "quantity", "unit_price", "total_price", "expiry_date", "received_quantity")
            }
            values.update(order_status=order.status, order_create_time_legacy=original_scalar(order.create_time), order_approve_time_legacy=original_scalar(order.approve_time), time_basis=TIME_BASIS)
            return capsule("open_purchase_item", line.item_id, item_kind, item_id, values, {"item": original_row(line), "order": original_row(order)})

        purchases = read_all(purchase_query, PurchaseOrderItem.item_id, purchase, budget, lambda pair: pair[0].item_id)
        result = {
            "schema_version": "inventory_legacy_capture_v1",
            "item_kind": item_kind,
            "item_id": item_id,
            "scope": SCOPE,
            "captured_at": utc_text(utcnow()),
            "sku": sku,
            "batches": batches,
            "ledger_entries": ledger,
            "open_purchase_items": purchases,
            "row_count": budget.rows,
        }
        result["collection_digest"] = hash_content(legacy_content(result))
        if len(canonical_json(result).encode()) > MAX_LEGACY_BYTES or not verify_legacy_capture(result):
            raise HTTPException(409, "完整库存胶囊或当前数量无法核对，未形成快照")
        return result


PROJECTION_KEYS = {
    "sku": {"name", "status", "stock", "price", "unit", "barcode", "category", "expiry_date", "purchasing_time_legacy", "time_basis"},
    "batch": {"batch_id", "pharmaceutical_id", "stock", "status", "expiry_date", "create_time_legacy", "update_time_legacy", "time_basis"},
    "ledger": {"ledger_id", "batch_id", "pharmaceutical_id", "transaction_type", "quantity", "before_stock", "after_stock", "create_time_legacy", "time_basis"},
    "open_purchase_item": {
        "item_id",
        "purchase_id",
        "item_type",
        "item_id_ref",
        "quantity",
        "unit_price",
        "total_price",
        "expiry_date",
        "received_quantity",
        "order_status",
        "order_create_time_legacy",
        "order_approve_time_legacy",
        "time_basis",
    },
}


def valid_projection(kind, value):
    if not isinstance(value, dict) or set(value) != PROJECTION_KEYS[kind] or value["time_basis"] != TIME_BASIS:
        return False
    integers = {
        "status",
        "stock",
        "batch_id",
        "pharmaceutical_id",
        "ledger_id",
        "quantity",
        "before_stock",
        "after_stock",
        "item_id",
        "purchase_id",
        "item_id_ref",
        "received_quantity",
        "order_status",
    }
    decimals = {"price", "unit_price", "total_price"}
    for key, raw in value.items():
        if key in integers:
            if raw is not None and type(raw) is not int:
                return False
        elif key in decimals:
            if raw is not None and (not isinstance(raw, str) or len(raw) > 64 or not Decimal(raw).is_finite()):
                return False
        elif key.endswith("_legacy"):
            if raw is not None:
                if not isinstance(raw, str):
                    return False
                parsed = datetime.fromisoformat(raw)
                if parsed.tzinfo is not None or parsed.isoformat(timespec="microseconds") != raw:
                    return False
        elif key == "expiry_date":
            if raw is not None and (not isinstance(raw, str) or date.fromisoformat(raw).isoformat() != raw):
                return False
        elif raw is not None and (not isinstance(raw, str) or len(raw.encode()) > 4000):
            return False
    return True


def verify_legacy_capture(value):
    """Rebuild safe capsules only; raw original_row_hash remains an opaque anchor."""
    try:
        from pydantic import TypeAdapter

        from app.ai.supply_contract import SHA256

        hash_type = TypeAdapter(SHA256)
        if not isinstance(value, dict) or set(value) != {
            "schema_version",
            "item_kind",
            "item_id",
            "scope",
            "captured_at",
            "sku",
            "batches",
            "ledger_entries",
            "open_purchase_items",
            "row_count",
            "collection_digest",
        }:
            return False
        if (
            value["schema_version"] != "inventory_legacy_capture_v1"
            or value["scope"] != SCOPE
            or value["item_kind"] not in {"pharmaceutical", "consumable"}
            or type(value["item_id"]) is not int
            or not 1 <= value["item_id"] <= 2147483647
        ):
            return False
        utc(value["captured_at"])
        total = 1
        for kind, rows in (("sku", [value["sku"]]), ("batch", value["batches"]), ("ledger", value["ledger_entries"]), ("open_purchase_item", value["open_purchase_items"])):
            if not isinstance(rows, list) or len(rows) > MAX_LEGACY_ROWS or kind != "sku" and value["item_kind"] == "consumable" and kind in {"batch", "ledger"} and rows:
                return False
            if kind != "sku":
                total += len(rows)
            ids = []
            for row in rows:
                if not isinstance(row, dict) or set(row) != {
                    "schema_version",
                    "record_kind",
                    "record_id",
                    "item_kind",
                    "item_id",
                    "scope",
                    "projection",
                    "projection_hash",
                    "original_row_hash",
                    "source_id",
                }:
                    return False
                if (
                    row["schema_version"] != "inventory_legacy_capsule_v1"
                    or row["record_kind"] != kind
                    or any(row[key] != value[key] for key in ("item_kind", "item_id", "scope"))
                    or type(row["record_id"]) is not int
                    or not 1 <= row["record_id"] <= 2147483647
                ):
                    return False
                p = row["projection"]
                if not valid_projection(kind, p) or hash_content(p) != row["projection_hash"]:
                    return False
                hash_type.validate_python(row["original_row_hash"], strict=True)
                if row["source_id"] != f"inventory_legacy:{kind}:{row['record_id']}:{row['original_row_hash'][:12]}":
                    return False
                if kind == "sku" and (
                    row["record_id"] != value["item_id"]
                    or value["item_kind"] == "pharmaceutical"
                    and (p["unit"] is not None or p["category"] is not None)
                    or value["item_kind"] == "consumable"
                    and (p["barcode"] is not None or p["expiry_date"] is not None or p["purchasing_time_legacy"] is not None)
                ):
                    return False
                if kind in {"batch", "ledger"} and (p["pharmaceutical_id"] != value["item_id"] or p["batch_id" if kind == "batch" else "ledger_id"] != row["record_id"]):
                    return False
                if kind == "open_purchase_item" and (
                    p["item_id_ref"] != value["item_id"]
                    or p["item_id"] != row["record_id"]
                    or p["item_type"] != ("drug" if value["item_kind"] == "pharmaceutical" else "consumable")
                    or p["order_status"] in (2, 3)
                ):
                    return False
                ids.append(row["record_id"])
            if ids != sorted(set(ids)):
                return False
        return (
            total <= MAX_LEGACY_ROWS
            and type(value["row_count"]) is int
            and total == value["row_count"]
            and hash_content(legacy_content(value)) == value["collection_digest"]
            and len(canonical_json(value).encode()) <= MAX_LEGACY_BYTES
        )
    except (ValueError, TypeError, KeyError, OverflowError, InvalidOperation):
        return False


# Conservatively binds every governed root for this actual SKU, including other
# periods. This deliberately broader closure prevents a corrupt/unknown period
# header or an unselected adverse plan from disappearing from current review.
MAX_MEMBERS = 4096
MAX_CAPTURE_BYTES = 8388608
COLLECTION_KEYS = frozenset(
    {
        "schema_version",
        "request",
        "as_of",
        "captured_at",
        "sku_binding",
        "unit_definitions",
        "source_records",
        "legacy_snapshot",
        "historical_collection_digest",
        "current_membership_digest",
        "collection_digest",
    }
)


def capture_view(value, *, unit=False):
    from copy import deepcopy

    from app.ai import inventory_native_sources as sources
    from app.ai import supply_sources as units

    result = deepcopy(value)
    result.update(capture_view=True, audit_only=False, can_record=False, can_review=False, can_revoke=False)
    if not result["eligible"]:
        for key in ("payload", "parent_binding", "review_basis_note", "revoke_reason"):
            result[key] = None
    if unit:
        if not units.verify_source_wrapper(result, capture=True):
            raise HTTPException(409, "完整单位原件捕获闭包无法核对")
    elif not sources.verify_source_wrapper(result, capture=True):
        raise HTTPException(409, "库存原件完整/隐去捕获声明不一致")
    return result


def source_locator(source):
    result = {key: source[key] for key in ("source_kind", "source_record_id", "item_kind", "item_id", "scope")}
    if source["source_kind"] != "unit_definition":
        result.update({key: source[key] for key in ("date_from", "date_to", "timezone")})
    return result


def _member_state(source):
    keys = (
        "source_kind",
        "source_record_id",
        "item_kind",
        "item_id",
        "scope",
        "content_hash",
        "governance_hash",
        "status",
        "revision",
        "recorded_at",
        "reviewed_at",
        "revoked_at",
        "eligible",
        "parent_current",
        "professional_status",
        "eligibility_basis",
    )
    return {key: source[key] for key in keys}


def _historical(value):
    return {**{key: value[key] for key in ("request", "sku_binding", "unit_definitions", "source_records")}, "legacy_content": legacy_content(value["legacy_snapshot"])}


def _membership(value):
    return {
        "sku_binding": value["sku_binding"],
        "legacy_content_digest": value["legacy_snapshot"]["collection_digest"],
        "members": [_member_state(entry["source"]) for group in ("unit_definitions", "source_records") for entry in value[group]],
    }


def _finish(value):
    value["historical_collection_digest"] = hash_content(_historical(value))
    value["current_membership_digest"] = hash_content(_membership(value))
    value["collection_digest"] = hash_content({key: value[key] for key in ("request", "sku_binding", "historical_collection_digest", "current_membership_digest")})
    if len(canonical_json(value).encode()) > MAX_CAPTURE_BYTES:
        raise HTTPException(409, "库存原件完整集合超过安全字节上限，不能截断")
    return value


def capture_sources(db, user, period, *, locking=False):
    """Current all-SKU closure, never an old-cutoff historical replay.

    Every query is a current lock read behind the same inventory Gate. `locking`
    is retained for callers; neither False nor read-only preview permits stale
    RR authority, membership or stock to escape serialization.
    """
    from app.ai import inventory_native_sources as sources
    from app.ai import supply_sources as units
    from app.ai.inventory_native_source_input import SOURCE_ROLES, CapturePeriod
    from app.ai.inventory_native_source_models import AIInventoryNativeSource
    from app.ai.inventory_write_guard import lock_inventory_write
    from app.ai.supply_source_models import AISupplyUnitDefinition

    req = CapturePeriod.model_validate(period.model_dump(mode="json") if hasattr(period, "model_dump") else period)
    actor = lock_inventory_write(db, user, allowed_roles=SOURCE_ROLES, skus=[(req.item_kind, req.item_id)], require_active=True)
    now = utcnow()
    cutoff = units.utc_datetime(req.as_of)
    if cutoff > now:
        raise HTTPException(422, "资料截止不能晚于真实服务器捕获时刻")
    result = {
        "schema_version": "inventory_capture_all_sku_v1",
        "request": req.model_dump(mode="json"),
        "as_of": req.as_of,
        "captured_at": None,
        "sku_binding": units.sku_binding(db, req.item_kind, req.item_id, locking=True, require_active=True),
        "unit_definitions": [],
        "source_records": [],
        "legacy_snapshot": capture_legacy_inventory(db, req.item_kind, req.item_id),
    }
    budget = len(canonical_json(result["legacy_snapshot"]).encode())
    members = 0
    models = ((True, AISupplyUnitDefinition, AISupplyUnitDefinition.unit_definition_id), (False, AIInventoryNativeSource, AIInventoryNativeSource.source_record_id))
    # Preflight every kind before loading any governed original. A late source
    # cannot cause even an earlier unit body to be read during a rejected view.
    for _, model, primary in models:
        query = db.query(model).filter(model.item_kind == req.item_kind, model.item_id == req.item_id, model.scope == req.scope)
        if (
            current_inventory_rows(query.with_entities(primary).filter(or_(model.recorded_at > cutoff, model.reviewed_at > cutoff, model.revoked_at > cutoff)), shared=True).limit(1).first()
            is not None
        ):
            raise HTTPException(409, "当前完整来源集合已有变化，请刷新真实截止后重新捕获")
    for unit, model, primary in models:
        query = db.query(model).filter(model.item_kind == req.item_kind, model.item_id == req.item_id, model.scope == req.scope)
        late = current_inventory_rows(query.with_entities(primary).filter(or_(model.recorded_at > cutoff, model.reviewed_at > cutoff, model.revoked_at > cutoff)), shared=True).limit(1).first()
        if late is not None:
            raise HTTPException(409, "当前完整来源集合已有变化，请刷新真实截止后重新捕获")
        cursor = None
        while True:
            page = query if cursor is None else query.filter(primary > cursor)
            # Fetch only bounded PKs; load and charge each original separately.
            identifiers = current_inventory_rows(page.with_entities(primary).order_by(primary).limit(BATCH_SIZE), shared=True).all()
            if not identifiers:
                break
            for (identifier,) in identifiers:
                members += 1
                if members > MAX_MEMBERS:
                    raise HTTPException(409, "同SKU完整来源根超过受控上限，不能取前N件冒充完整")
                current = units.source_current(db, actor, "unit", identifier, audit_only=False, locking=True) if unit else sources.source_current(db, actor, identifier, audit_only=False, locking=True)
                if any(current[key] is not None and current[key] > req.as_of for key in ("recorded_at", "reviewed_at", "revoked_at")):
                    raise HTTPException(409, "当前完整来源集合已有变化，请刷新真实截止后重新捕获")
                view = capture_view(current, unit=unit)
                where = source_locator(view)
                entry = {"source": view, "locator": where, "locator_hash": hash_content(where)}
                budget += len(canonical_json(entry).encode())
                if budget > MAX_CAPTURE_BYTES:
                    raise HTTPException(409, "同SKU完整来源集合超过安全字节上限，未截断")
                result["unit_definitions" if unit else "source_records"].append(entry)
            cursor = identifiers[-1][0]
    result["captured_at"] = utc_text(utcnow())
    result = _finish(result)
    if not verify_capture(result):
        raise HTTPException(409, "库存完整来源捕获原件闭包无法核对")
    return result


def verify_capture(value):
    """Pure disclosed proof. Hidden bodies/opaque raw-row hashes remain opaque."""
    from app.ai import inventory_native_sources as sources
    from app.ai import supply_sources as units
    from app.ai.inventory_native_source_input import CapturePeriod

    try:
        if not isinstance(value, dict) or set(value) != COLLECTION_KEYS or value["schema_version"] != "inventory_capture_all_sku_v1" or len(canonical_json(value).encode()) > MAX_CAPTURE_BYTES:
            return False
        req = CapturePeriod.model_validate(value["request"])
        utc(value["captured_at"])
        legacy = value["legacy_snapshot"]
        if value["as_of"] != req.as_of or value["captured_at"] < req.as_of or not verify_legacy_capture(legacy) or legacy["captured_at"] > value["captured_at"]:
            return False
        if any(value["sku_binding"][key] != getattr(req, key) or legacy[key] != getattr(req, key) for key in ("item_kind", "item_id", "scope")):
            return False
        raw = legacy["sku"]["projection"]
        expected_identity = {"name": raw["name"], "status": raw["status"]}
        expected_identity.update({"barcode": raw["barcode"]} if req.item_kind == "pharmaceutical" else {"category": raw["category"], "catalog_unit": raw["unit"]})
        if value["sku_binding"] != {"item_kind": req.item_kind, "item_id": req.item_id, "scope": req.scope, "identity": expected_identity} or raw["status"] != 0:
            return False
        if not all(isinstance(value[key], list) for key in ("unit_definitions", "source_records")) or len(value["unit_definitions"]) + len(value["source_records"]) > MAX_MEMBERS:
            return False
        seen = set()
        for unit, group in ((True, "unit_definitions"), (False, "source_records")):
            order = []
            for entry in value[group]:
                if not isinstance(entry, dict) or set(entry) != {"source", "locator", "locator_hash"}:
                    return False
                source = entry["source"]
                if unit:
                    if source.get("source_kind") != "unit_definition":
                        return False
                    if not units.verify_source_wrapper(source, capture=True):
                        return False
                    if any(source[key] for key in ("audit_only", "can_record", "can_review", "can_revoke")):
                        return False
                elif not sources.verify_source_wrapper(source, capture=True):
                    return False
                if any(source[key] != getattr(req, key) for key in ("item_kind", "item_id", "scope")) or source["source_record_id"] in seen:
                    return False
                if any(source[key] is not None and source[key] > req.as_of for key in ("recorded_at", "reviewed_at", "revoked_at")):
                    return False
                if source["payload"] is not None and source["parent_binding"]["sku"] != value["sku_binding"]:
                    return False
                if entry["locator"] != source_locator(source) or entry["locator_hash"] != hash_content(entry["locator"]):
                    return False
                seen.add(source["source_record_id"])
                order.append(source["source_record_id"])
            if order != sorted(order):
                return False
        return (
            value["historical_collection_digest"] == hash_content(_historical(value))
            and value["current_membership_digest"] == hash_content(_membership(value))
            and value["collection_digest"] == hash_content({key: value[key] for key in ("request", "sku_binding", "historical_collection_digest", "current_membership_digest")})
        )
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError, RecursionError):
        return False
