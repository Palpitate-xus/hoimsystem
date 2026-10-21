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
