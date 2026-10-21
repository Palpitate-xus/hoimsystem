"""Controlled complete originals. No business inventory/dispense/procurement writes."""

import datetime
import json
import uuid

from fastapi import HTTPException
from sqlalchemy import inspect

from app.ai import governance as audit_governance
from app.ai.supply_contract import canonical_json, hash_content
from app.ai.supply_source_input import SOURCE_ROLES, FrozenIdentity, Governance, SourceCreate, SourceReview, SourceRevoke, UnitCreate
from app.ai.supply_source_models import PARENT_BYTES, PAYLOAD_BYTES, AISupplyDailyQuantity, AISupplyUnitDefinition
from app.models import Consumable, ConsumableTrace, Pharmaceutical, PharmaceuticalBatch, PharmaceuticalStockLedger, User

MODELS = {"unit": (AISupplyUnitDefinition, "unit_definition_id"), "daily": (AISupplyDailyQuantity, "source_record_id")}
GOVERNANCE_FIELDS = ("status", "revision", "reviewed_by", "reviewed_at", "review_basis_note", "revoked_by", "revoked_at", "revoke_reason")
IDENTITY_FIELDS = (
    "record_kind",
    "source_kind",
    "source_record_id",
    "unit_definition_id",
    "schema_version",
    "item_kind",
    "item_id",
    "scope",
    "target",
    "date",
    "day_start_at",
    "day_end_at",
    "observed_at",
    "recorded_at",
    "created_by",
)
REASONS = frozenset({"source_not_published", "original_sku_changed", "original_sku_unavailable", "professional_signature_changed", "unit_definition_changed", "audit_original_changed"})


def utcnow():
    return datetime.datetime.now(datetime.UTC).replace(tzinfo=None)


def utc_text(value):
    if value is None:
        return None
    if value.tzinfo is not None:
        value = value.astimezone(datetime.UTC).replace(tzinfo=None)
    return value.isoformat(timespec="microseconds") + "Z"


def utc_datetime(value):
    return datetime.datetime.fromisoformat(value[:-1])


def current_query(query, *, locking=False):
    query = query.populate_existing()
    return query.with_for_update() if locking else query


def current_actor(db, user, *, locking=False):
    state = inspect(user, raiseerr=False)
    user_id = state.identity[0] if state is not None and state.identity is not None else getattr(user, "user_id", None)
    query = db.query(User).filter_by(user_id=user_id).populate_existing()
    # A normal SELECT may reuse the JWT-created MySQL RR snapshot.
    # Both read and write authorization require the actual current role.
    row = query.with_for_update(read=True).one_or_none()
    if row is None or row.user_role not in SOURCE_ROLES:
        raise HTTPException(403, "当前账户不具有医院库存原件范围权限")
    return row


def sku_binding(db, item_kind, item_id, *, locking=False, require_active=False):
    if item_kind not in {"pharmaceutical", "consumable"}:
        raise HTTPException(422, "库存品种类型无效")
    cls, primary = (Pharmaceutical, "pharmaceutical_id") if item_kind == "pharmaceutical" else (Consumable, "consumable_id")
    row = current_query(db.query(cls).filter(getattr(cls, primary) == item_id), locking=locking).one_or_none()
    if row is None:
        raise HTTPException(409, "实际库存品种已不存在")
    if require_active and row.status != 0:
        raise HTTPException(409, "实际库存品种当前未明确启用")
    # Stock, price, expiry and supplier do not define a past quantity observation.
    fields = {"name": row.name, "status": row.status}
    fields.update({"barcode": row.barcode} if item_kind == "pharmaceutical" else {"category": row.category, "catalog_unit": row.unit})
    return {"item_kind": item_kind, "item_id": item_id, "scope": "hospital_inventory", "identity": fields}


def lock_supply_scope(db, user, item_kind, item_id, *, require_active=False, allow_missing=False):
    """Shared actual identity, then one exclusive real SKU serialization row.

    All controlled source/series and final result writers use this order and
    retain it until their transaction commits. No business inventory is changed.
    """
    actor = current_actor(db, user, locking=True)
    try:
        sku = sku_binding(db, item_kind, item_id, locking=True, require_active=require_active)
    except HTTPException as exc:
        if not allow_missing or exc.status_code != 409:
            raise
        sku = None
    return actor, sku


def _signer(db, attestation, actor=None, *, locking=False):
    if attestation["status"] == "unknown":
        return None
    query = db.query(User).filter_by(user_id=attestation["signer_user_id"]).populate_existing()
    # Professional signing authority is also current in metadata/read paths.
    signer = query.with_for_update(read=True).one_or_none()
    if signer is None or signer.user_role != "pharmacist" or actor is not None and actor.user_id != signer.user_id:
        raise HTTPException(403, "专业确认必须由当前实际药师账户本人完成，技术角色不能代签")
    return {"user_id": signer.user_id, "user_role": "pharmacist"}


def bounded_json(value, maximum=PAYLOAD_BYTES):
    text = canonical_json(value)
    if len(text.encode()) > maximum:
        raise HTTPException(422, "完整原件超过安全字节上限，不能截断")
    return text


def _load(value, maximum):
    try:
        if not isinstance(value, str) or not value or len(value.encode()) > maximum:
            raise ValueError()
        result = json.loads(value, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
        if canonical_json(result) != value:
            raise ValueError()
        return result
    except (ValueError, TypeError, RecursionError) as exc:
        raise HTTPException(409, "受控原件存储不是完整规范JSON") from exc


def record(db, kind, record_id, *, locking=False):
    if kind not in MODELS:
        raise HTTPException(422, "库存原件类型无效")
    try:
        if str(uuid.UUID(record_id)) != record_id:
            raise ValueError()
    except (ValueError, TypeError, AttributeError) as exc:
        raise HTTPException(422, "原件标识必须是规范UUID") from exc
    cls, primary = MODELS[kind]
    row = current_query(db.query(cls).filter(getattr(cls, primary) == record_id), locking=locking).one_or_none()
    if row is None:
        raise HTTPException(404, "受控库存原件不存在")
    return row


def identity(kind, row):
    rid = getattr(row, MODELS[kind][1])
    return {
        "record_kind": kind,
        "source_kind": "unit_definition" if kind == "unit" else "daily_quantity",
        "source_record_id": rid,
        "unit_definition_id": row.unit_definition_id,
        "schema_version": row.schema_version,
        "item_kind": row.item_kind,
        "item_id": row.item_id,
        "scope": row.scope,
        "target": None if kind == "unit" else row.target,
        "date": None if kind == "unit" else row.business_date,
        "day_start_at": None if kind == "unit" else utc_text(row.day_start_at),
        "day_end_at": None if kind == "unit" else utc_text(row.day_end_at),
        "observed_at": None if kind == "unit" else utc_text(row.observed_at),
        "recorded_at": utc_text(row.recorded_at),
        "created_by": row.created_by,
    }


def governance(row):
    return {key: utc_text(getattr(row, key)) if key.endswith("_at") else getattr(row, key) for key in GOVERNANCE_FIELDS}


def _audit_original(db, reference, item_kind, item_id, *, locking=False):
    if reference["kind"] == "pharmaceutical_ledger":
        if item_kind != "pharmaceutical":
            raise HTTPException(422, "审计台账类型不属于所选品种")
        row = current_query(db.query(PharmaceuticalStockLedger).filter_by(ledger_id=reference["ledger_id"])).one_or_none()
        if row is None or row.pharmaceutical_id != item_id:
            raise HTTPException(409, "审计台账不属于明确原药品")
        batch = current_query(db.query(PharmaceuticalBatch).filter_by(batch_id=row.batch_id)).one_or_none()
        projection = {
            "kind": "pharmaceutical_ledger",
            "ledger_id": row.ledger_id,
            "pharmaceutical_id": row.pharmaceutical_id,
            "batch_id": row.batch_id,
            "batch_pharmaceutical_id": batch.pharmaceutical_id if batch else None,
            "transaction_type": row.transaction_type,
            "quantity": row.quantity,
            "before_stock": row.before_stock,
            "after_stock": row.after_stock,
            "create_time_legacy": row.create_time.isoformat() if row.create_time else None,
            "time_basis": "legacy_naive_unknown_not_utc_evidence",
        }
    else:
        if item_kind != "consumable":
            raise HTTPException(422, "审计追溯类型不属于所选品种")
        row = current_query(db.query(ConsumableTrace).filter_by(trace_id=reference["trace_id"])).one_or_none()
        if row is None or row.consumable_id != item_id:
            raise HTTPException(409, "审计追溯不属于明确原耗材")
        projection = {
            "kind": "consumable_trace",
            "trace_id": row.trace_id,
            "consumable_id": row.consumable_id,
            "action": row.action,
            "quantity": row.quantity,
            "action_time_legacy": row.action_time.isoformat() if row.action_time else None,
            "time_basis": "legacy_naive_unknown_not_utc_evidence",
        }
    # This is a closed safe audit projection, not the hash of undisclosed patient,
    # operator, prescription/reference or free-note columns.
    return {"reference": reference, "projection": projection, "projection_hash": hash_content(projection)}


def _source_id(kind, rid, digest):
    return f"{'supply_unit' if kind == 'unit' else 'supply_day'}:{rid}:{digest[:12]}"


def _state_valid(value, recorded, redacted=False):
    try:
        reviewed = value["reviewed_at"] is not None
        if reviewed and (value["reviewed_at"] < recorded or type(value["reviewed_by"]) is not int or value["reviewed_by"] < 1) or not reviewed and value["reviewed_by"] is not None:
            return False
        if value["status"] == "draft":
            valid = value["revision"] == 1 and not reviewed
        elif value["status"] in {"published", "rejected"}:
            valid = value["revision"] == 2 and reviewed
        elif value["status"] == "revoked":
            valid = (
                value["revision"] == (3 if reviewed else 2)
                and type(value["revoked_by"]) is int
                and value["revoked_by"] > 0
                and value["revoked_at"] is not None
                and value["revoked_at"] >= (value["reviewed_at"] or recorded)
            )
        else:
            return False
        if not valid or value["status"] != "revoked" and (value["revoked_by"] is not None or value["revoked_at"] is not None):
            return False
        if redacted:
            return value["review_basis_note"] is None and value["revoke_reason"] is None
        if reviewed:
            SourceReview.model_validate({"expected_revision": 1, "expected_content_hash": "a" * 64, "decision": "publish", "basis_note": value["review_basis_note"]})
        elif value["review_basis_note"] != "":
            return False
        if value["status"] == "revoked":
            SourceRevoke.model_validate({"expected_revision": 1, "expected_content_hash": "a" * 64, "basis_note": value["revoke_reason"]})
        elif value["revoke_reason"] != "":
            return False
        return True
    except (ValueError, TypeError, KeyError):
        return False


def _validate_parent(kind, parent, payload, immutable):
    expected = {"scope", "sku", "signer"} if kind == "unit" else {"scope", "sku", "signer", "unit_definition", "audit_originals"}
    if not isinstance(parent, dict) or set(parent) != expected or parent["scope"] != "hospital_inventory":
        return False
    sku = parent["sku"]
    fields = {"name", "status", "barcode"} if immutable["item_kind"] == "pharmaceutical" else {"name", "status", "category", "catalog_unit"}
    if (
        not isinstance(sku, dict)
        or set(sku) != {"item_kind", "item_id", "scope", "identity"}
        or any(sku[k] != immutable[k] for k in ("item_kind", "item_id", "scope"))
        or not isinstance(sku["identity"], dict)
        or set(sku["identity"]) != fields
    ):
        return False
    signer = parent["signer"]
    attestation = payload["professional_attestation"]
    if attestation["status"] == "confirmed":
        if signer != {"user_id": attestation["signer_user_id"], "user_role": "pharmacist"} or attestation["signer_user_id"] != immutable["created_by"]:
            return False
    elif signer is not None:
        return False
    if kind == "unit":
        return True
    unit = parent["unit_definition"]
    if immutable["unit_definition_id"] is None:
        if unit is not None:
            return False
    elif (
        not isinstance(unit, dict)
        or not verify_original_proof(unit)
        or unit["record_kind"] != "unit"
        or unit["status"] != "published"
        or any(unit[k] != immutable[k] for k in ("unit_definition_id", "item_kind", "item_id", "scope"))
    ):
        return False
    if payload["unit_review"] == "confirmed" and (
        unit is None or unit["payload"]["professional_attestation"]["status"] != "confirmed" or unit["payload"]["original_unit_text"] != payload["original_unit_text"]
    ):
        return False
    if not isinstance(parent["audit_originals"], list) or len(parent["audit_originals"]) != len(payload["audit_refs"]):
        return False
    for ref, original in zip(payload["audit_refs"], parent["audit_originals"], strict=True):
        if set(original) != {"reference", "projection", "projection_hash"} or original["reference"] != ref or hash_content(original["projection"]) != original["projection_hash"]:
            return False
        p = original["projection"]
        names = (
            {"kind", "ledger_id", "pharmaceutical_id", "batch_id", "batch_pharmaceutical_id", "transaction_type", "quantity", "before_stock", "after_stock", "create_time_legacy", "time_basis"}
            if ref["kind"] == "pharmaceutical_ledger"
            else {"kind", "trace_id", "consumable_id", "action", "quantity", "action_time_legacy", "time_basis"}
        )
        if (
            set(p) != names
            or p["kind"] != ref["kind"]
            or p["time_basis"] != "legacy_naive_unknown_not_utc_evidence"
            or p["pharmaceutical_id" if ref["kind"] == "pharmaceutical_ledger" else "consumable_id"] != immutable["item_id"]
            or p["ledger_id" if ref["kind"] == "pharmaceutical_ledger" else "trace_id"] != ref["ledger_id" if ref["kind"] == "pharmaceutical_ledger" else "trace_id"]
            or type(p["quantity"]) is not int
        ):
            return False
    return True


def verify_original_proof(value):
    """Pure whole original validator, including frozen unit/signature/audit closure."""
    try:
        names = set(IDENTITY_FIELDS) | set(GOVERNANCE_FIELDS) | {"content_hash", "source_id", "governance_hash", "payload", "parent_binding"}
        if not isinstance(value, dict) or set(value) != names or value["record_kind"] not in MODELS:
            return False
        Governance.model_validate({k: value[k] for k in GOVERNANCE_FIELDS})
        kind = value["record_kind"]
        body = {k: value[k] for k in IDENTITY_FIELDS}
        FrozenIdentity.model_validate(body)
        payload = value["payload"]
        parent = value["parent_binding"]
        if (
            value["schema_version"] != ("supply_unit_private_v1" if kind == "unit" else "supply_daily_private_v1")
            or value["source_kind"] != ("unit_definition" if kind == "unit" else "daily_quantity")
            or not _state_valid(value, value["recorded_at"])
        ):
            return False
        if kind == "unit":
            UnitCreate.model_validate({**{k: value[k] for k in ("item_kind", "item_id", "scope")}, "payload": payload})
            if value["source_record_id"] != value["unit_definition_id"] or any(value[k] is not None for k in ("target", "date", "day_start_at", "day_end_at", "observed_at")):
                return False
        else:
            unit = parent.get("unit_definition") if isinstance(parent, dict) else None
            SourceCreate.model_validate(
                {
                    **{k: value[k] for k in ("item_kind", "item_id", "scope", "unit_definition_id")},
                    "expected_unit_content_hash": unit["content_hash"] if unit else None,
                    "expected_unit_governance_hash": unit["governance_hash"] if unit else None,
                    "payload": payload,
                }
            )
            if any(value[k] != payload[k] for k in ("target", "date", "day_start_at", "day_end_at", "observed_at")) or value["observed_at"] > value["recorded_at"]:
                return False
        if not _validate_parent(kind, parent, payload, body):
            return False
        return (
            hash_content({**body, "payload": payload, "parent_binding": parent}) == value["content_hash"]
            and _source_id(kind, value["source_record_id"], value["content_hash"]) == value["source_id"]
            and hash_content({k: value[k] for k in GOVERNANCE_FIELDS}) == value["governance_hash"]
        )
    except (ValueError, TypeError, KeyError, RecursionError):
        return False


def source_proof(kind, row):
    result = {
        **identity(kind, row),
        **governance(row),
        "content_hash": row.content_hash,
        "source_id": _source_id(kind, getattr(row, MODELS[kind][1]), row.content_hash),
        "governance_hash": hash_content(governance(row)),
        "payload": _load(row.payload_json, PAYLOAD_BYTES),
        "parent_binding": _load(row.parent_binding_json, PARENT_BYTES),
    }
    if not verify_original_proof(result):
        raise HTTPException(409, "受控库存原件、签署、单位闭包或自身SHA无法核对")
    return result


def parent_status(db, proof, *, locking=False):
    parent = proof["parent_binding"]
    reasons = []
    current = {"sku": None, "signer": None, "unit": None, "audit": []}
    try:
        current["sku"] = sku_binding(db, proof["item_kind"], proof["item_id"], locking=locking)
        if current["sku"] != parent["sku"] or current["sku"]["identity"]["status"] != 0:
            reasons.append("original_sku_changed")
    except HTTPException:
        reasons.append("original_sku_unavailable")
    try:
        current["signer"] = _signer(db, proof["payload"]["professional_attestation"], locking=locking)
    except HTTPException:
        reasons.append("professional_signature_changed")
    if proof["record_kind"] == "daily":
        unit = parent["unit_definition"]
        if unit is not None:
            try:
                row = record(db, "unit", unit["unit_definition_id"], locking=locking)
                actual = source_proof("unit", row)
                unit_reasons, _ = parent_status(db, actual, locking=locking)
                current["unit"] = {"content_hash": actual["content_hash"], "governance_hash": actual["governance_hash"], "parent_current": not unit_reasons, "current_basis_hash": hash_content(_)}
                if actual["status"] != "published" or unit_reasons or actual["content_hash"] != unit["content_hash"] or actual["governance_hash"] != unit["governance_hash"]:
                    reasons.append("unit_definition_changed")
            except HTTPException:
                reasons.append("unit_definition_changed")
        for frozen in parent["audit_originals"]:
            try:
                actual = _audit_original(db, frozen["reference"], proof["item_kind"], proof["item_id"], locking=locking)
                current["audit"].append(actual["projection_hash"])
                if actual != frozen:
                    reasons.append("audit_original_changed")
            except HTTPException:
                reasons.append("audit_original_changed")
    return sorted(set(reasons)), current


def source_current(db, user, kind, record_id, *, audit_only=False, locking=False):
    actor = current_actor(db, user, locking=locking)
    if audit_only and actor.user_role != "super_admin":
        raise HTTPException(403, "完整失效原件审计仅限超级管理员")
    row = record(db, kind, record_id, locking=locking)
    proof = source_proof(kind, row)
    reasons, current = parent_status(db, proof, locking=locking)
    parent_current = not reasons
    if proof["status"] != "published":
        reasons.append("source_not_published")
    eligible = not reasons
    attestation = proof["payload"]["professional_attestation"]
    visible = audit_only or eligible or proof["status"] == "draft" and parent_current
    result = {
        **proof,
        "professional_status": attestation["status"],
        "signer_user_id": attestation["signer_user_id"],
        "signed_at": proof["recorded_at"] if attestation["status"] == "confirmed" else None,
        "parent_current": parent_current,
        "eligible": eligible,
        "exclusion_reasons": sorted(set(reasons)),
        "can_record": current.get("sku") is not None and current["sku"]["identity"]["status"] == 0,
        "can_review": actor.user_role == "super_admin" and proof["status"] == "draft" and parent_current,
        "can_revoke": proof["status"] in {"draft", "published"} and (actor.user_role == "super_admin" or actor.user_id == proof["created_by"]),
        "audit_only": audit_only,
        "eligibility_basis": {"schema_version": "supply_current_eligibility_v1", "current_parent_state_hash": hash_content(current), "not_professional_or_operational_validation": True},
    }
    if not visible:
        for key in ("payload", "parent_binding", "review_basis_note", "revoke_reason"):
            result[key] = None
    return result


def _create(db, user, kind, request):
    req = (UnitCreate if kind == "unit" else SourceCreate).model_validate(request.model_dump(mode="json") if hasattr(request, "model_dump") else request)
    actor, sku = lock_supply_scope(db, user, req.item_kind, req.item_id, require_active=True)
    values = req.model_dump(mode="json")
    payload = values["payload"]
    signer = _signer(db, payload["professional_attestation"], actor, locking=True)
    now = utcnow()
    rid = str(uuid.uuid4())
    parent = {"scope": "hospital_inventory", "sku": sku, "signer": signer}
    if kind == "daily":
        if utc_datetime(req.payload.observed_at) > now:
            raise HTTPException(422, "原观察时刻不能晚于实际服务器登记时刻")
        unit = None
        if req.unit_definition_id is not None:
            unit = source_proof("unit", record(db, "unit", req.unit_definition_id, locking=True))
            why, _ = parent_status(db, unit, locking=True)
            if (
                unit["status"] != "published"
                or why
                or unit["content_hash"] != req.expected_unit_content_hash
                or unit["governance_hash"] != req.expected_unit_governance_hash
                or any(unit[k] != values[k] for k in ("item_kind", "item_id", "scope"))
            ):
                raise HTTPException(409, "明确单位原件已变化或不属于所选SKU")
        parent.update(unit_definition=unit, audit_originals=[_audit_original(db, r, req.item_kind, req.item_id, locking=True) for r in payload["audit_refs"]])
        row = AISupplyDailyQuantity(
            source_record_id=rid,
            target=req.payload.target,
            business_date=req.payload.date,
            day_start_at=utc_datetime(req.payload.day_start_at),
            day_end_at=utc_datetime(req.payload.day_end_at),
            observed_at=utc_datetime(req.payload.observed_at),
            unit_definition_id=req.unit_definition_id,
        )
    else:
        row = AISupplyUnitDefinition(unit_definition_id=rid)
    row.item_kind = req.item_kind
    row.item_id = req.item_id
    row.scope = req.scope
    row.schema_version = "supply_unit_private_v1" if kind == "unit" else "supply_daily_private_v1"
    row.recorded_at = now
    row.created_by = actor.user_id
    row.status = "draft"
    row.revision = 1
    row.reviewed_by = row.reviewed_at = row.revoked_by = row.revoked_at = None
    row.review_basis_note = row.revoke_reason = ""
    row.payload_json = bounded_json(payload)
    row.parent_binding_json = bounded_json(parent, PARENT_BYTES)
    row.content_hash = hash_content({**identity(kind, row), "payload": payload, "parent_binding": parent})
    # Invalid claimed units or tampered closure never reach SQL.
    source_proof(kind, row)
    db.add(row)
    db.flush()
    audit_governance.audit(
        db,
        actor.user_id,
        "supply.source.create",
        rid,
        {"kind": kind, "item_kind": row.item_kind, "item_id": row.item_id, "content_hash": row.content_hash, "professional_status": payload["professional_attestation"]["status"]},
    )
    db.flush()
    current_actor(db, user, locking=True)
    if parent_status(db, source_proof(kind, row), locking=True)[0]:
        raise HTTPException(409, "登记期间实际SKU、单位或药师签署身份已变化")
    return row


def create_unit(db, user, request):
    return _create(db, user, "unit", request)


def create_source(db, user, request):
    return _create(db, user, "daily", request)


def review_source(db, user, kind, record_id, request, *, revoke=False):
    req = (SourceRevoke if revoke else SourceReview).model_validate(request.model_dump(mode="json") if hasattr(request, "model_dump") else request)
    actor = current_actor(db, user, locking=True)
    if not revoke and actor.user_role != "super_admin":
        raise HTTPException(403, "原件技术审核仅限超级管理员")
    initial = record(db, kind, record_id)
    actor, _ = lock_supply_scope(db, user, initial.item_kind, initial.item_id, allow_missing=revoke)
    row = record(db, kind, record_id, locking=True)
    proof = source_proof(kind, row)
    if revoke and actor.user_role != "super_admin" and row.created_by != actor.user_id:
        raise HTTPException(403, "普通账户只能撤销本人登记的原件")
    if row.revision != req.expected_revision or row.content_hash != req.expected_content_hash or row.status not in ({"draft", "published"} if revoke else {"draft"}):
        raise HTTPException(409, "原版本、状态或完整原件SHA已变化")
    if not revoke and parent_status(db, proof, locking=True)[0]:
        raise HTTPException(409, "当前SKU、单位或原药师签署已失效，不能技术发布")
    now = utcnow()
    values = {"status": "revoked" if revoke else "published" if req.decision == "publish" else "rejected", "revision": row.revision + 1}
    values.update(
        {"revoked_by": actor.user_id, "revoked_at": now, "revoke_reason": req.basis_note} if revoke else {"reviewed_by": actor.user_id, "reviewed_at": now, "review_basis_note": req.basis_note}
    )
    cls, primary = MODELS[kind]
    count = (
        db.query(cls)
        .filter(getattr(cls, primary) == record_id, cls.revision == req.expected_revision, cls.content_hash == req.expected_content_hash, cls.status == row.status)
        .update(values, synchronize_session=False)
    )
    if count != 1:
        raise HTTPException(409, "并发治理已变化，请重新读取")
    db.flush()
    db.refresh(row)
    source_proof(kind, row)
    audit_governance.audit(
        db,
        actor.user_id,
        "supply.source." + ("revoke" if revoke else req.decision),
        record_id,
        {"kind": kind, "expected_revision": req.expected_revision, "revision": row.revision, "content_hash": row.content_hash, "governance_hash": hash_content(governance(row))},
    )
    db.flush()
    final_actor = current_actor(db, user, locking=True)
    if not revoke and final_actor.user_role != "super_admin" or revoke and final_actor.user_role != "super_admin" and final_actor.user_id != row.created_by:
        raise HTTPException(403, "治理期间实际账户权限已变化")
    if not revoke and parent_status(db, source_proof(kind, row), locking=True)[0]:
        raise HTTPException(409, "审核期间原SKU、单位或药师签署已变化")
    return row


def source_metadata(value):
    """Metadata is a locator/hash, never a reconstruction of hidden originals."""
    return {key: item for key, item in value.items() if key not in {"payload", "parent_binding", "review_basis_note", "revoke_reason"}}


def verify_source_wrapper(value, *, capture=False):
    """Pure strict full proof or explicitly redacted frozen metadata validation."""
    from app.ai.supply_source_input import CaptureSourceWrapper, SourceWrapper

    try:
        model = CaptureSourceWrapper if capture else SourceWrapper
        parsed = model.model_validate(value).model_dump(mode="json")
        if parsed != value or len(bounded_json(value, PAYLOAD_BYTES + PARENT_BYTES + 16384).encode()) > PAYLOAD_BYTES + PARENT_BYTES + 16384:
            return False
        kind = value["record_kind"]
        if (
            value["source_kind"] != ("unit_definition" if kind == "unit" else "daily_quantity")
            or value["schema_version"] != ("supply_unit_private_v1" if kind == "unit" else "supply_daily_private_v1")
            or value["source_id"] != _source_id(kind, value["source_record_id"], value["content_hash"])
        ):
            return False
        if kind == "unit" and (value["unit_definition_id"] != value["source_record_id"] or any(value[k] is not None for k in ("target", "date", "day_start_at", "day_end_at", "observed_at"))):
            return False
        if kind == "daily" and (
            any(value[k] is None for k in ("target", "date", "day_start_at", "day_end_at", "observed_at"))
            or not value["day_start_at"] < value["day_end_at"] <= value["observed_at"] <= value["recorded_at"]
        ):
            return False
        reasons = value["exclusion_reasons"]
        if (
            len(set(reasons)) != len(reasons)
            or value["eligible"] != (not reasons)
            or (value["status"] != "published") != ("source_not_published" in reasons)
            or value["parent_current"] != (not (set(reasons) - {"source_not_published"}))
        ):
            return False
        if value["professional_status"] == "confirmed":
            if value["signer_user_id"] is None or value["signed_at"] != value["recorded_at"]:
                return False
        elif value["signer_user_id"] is not None or value["signed_at"] is not None:
            return False
        if value["can_review"] and (value["status"] != "draft" or not value["parent_current"]) or value["can_revoke"] and value["status"] not in {"draft", "published"}:
            return False
        if capture and (value["audit_only"] or any(value[k] for k in ("can_record", "can_review", "can_revoke"))):
            return False
        visible = value["eligible"] if capture else value["audit_only"] or value["eligible"] or value["status"] == "draft" and value["parent_current"]
        if not visible:
            return _state_valid(value, value["recorded_at"], redacted=True) and all(value[k] is None for k in ("payload", "parent_binding", "review_basis_note", "revoke_reason"))
        proof = {key: value[key] for key in (*IDENTITY_FIELDS, *GOVERNANCE_FIELDS, "payload", "parent_binding", "content_hash", "source_id", "governance_hash")}
        if not verify_original_proof(proof):
            return False
        att = value["payload"]["professional_attestation"]
        return att["status"] == value["professional_status"] and att["signer_user_id"] == value["signer_user_id"]
    except (ValueError, TypeError, KeyError, HTTPException, RecursionError):
        return False
