"""Immutable inventory originals and independent technical governance."""

import datetime
import functools
import uuid
from zoneinfo import ZoneInfo

from fastapi import HTTPException

from app.ai import governance as audit
from app.ai import supply_sources as units
from app.ai.inventory_contract import canonical_json, hash_content
from app.ai.inventory_contract import identity as check_uuid
from app.ai.inventory_native_collection import capture_legacy_inventory, verify_legacy_capture
from app.ai.inventory_native_source_input import SOURCE_ROLES, CaptureSourceWrapper, FrozenIdentity, SourceCreate, SourceMetadata, SourceReview, SourceRevoke, SourceWrapper
from app.ai.inventory_native_source_models import PARENT_BYTES, PAYLOAD_BYTES, SOURCE_BYTES, AIInventoryNativeSource
from app.ai.inventory_write_guard import current_inventory_rows, lock_inventory_write

utcnow, utc_text, utc_datetime = units.utcnow, units.utc_text, units.utc_datetime
GOVERNANCE_FIELDS = units.GOVERNANCE_FIELDS
IDENTITY_FIELDS = tuple(FrozenIdentity.model_fields)
REASONS = {"source_not_published", "original_sku_changed", "original_sku_unavailable", "professional_signature_changed", "unit_definition_changed", "legacy_inventory_changed"}


def atomic(fn):
    @functools.wraps(fn)
    def run(db, *args, **kwargs):
        try:
            return fn(db, *args, **kwargs)
        except Exception:
            db.rollback()
            raise

    return run


def source_identity(row):
    return {key: utc_text(getattr(row, key)) if key == "recorded_at" else getattr(row, key) for key in IDENTITY_FIELDS}


def governance(row):
    return units.governance(row)


def record(db, record_id, *, locking=False):
    try:
        check_uuid(record_id)
    except (ValueError, TypeError, AttributeError) as exc:
        raise HTTPException(422, "原库存资料标识须为规范UUID") from exc
    query = db.query(AIInventoryNativeSource).filter_by(source_record_id=record_id).populate_existing()
    row = (current_inventory_rows(query) if locking else query).one_or_none()
    if row is None:
        raise HTTPException(404, "原库存资料不存在")
    return row


def _scope(db, user, record_id):
    actor = lock_inventory_write(db, user, allowed_roles=SOURCE_ROLES)
    try:
        check_uuid(record_id)
    except (ValueError, TypeError, AttributeError) as exc:
        raise HTTPException(422, "原库存资料标识须为规范UUID") from exc
    # A technical immutable locator is resolved under the global gate. Business
    # SKU/state locks follow the exact same order as create and final acceptance.
    locator = current_inventory_rows(db.query(AIInventoryNativeSource.item_kind, AIInventoryNativeSource.item_id).filter_by(source_record_id=record_id), shared=True).one_or_none()
    if locator is None:
        raise HTTPException(404, "原库存资料不存在")
    actor = lock_inventory_write(db, actor, allowed_roles=SOURCE_ROLES, skus=[tuple(locator)], allow_missing=True)
    return actor, record(db, record_id, locking=True)


def _all_quantities(value):
    if isinstance(value, dict):
        if set(value) == {"value", "absent_reason", "original_unit_text", "unit_review"}:
            yield value
        for child in value.values():
            yield from _all_quantities(child)
    elif isinstance(value, list):
        for child in value:
            yield from _all_quantities(child)


def verify_original_proof(proof):
    try:
        names = set(IDENTITY_FIELDS) | set(GOVERNANCE_FIELDS) | {"source_id", "content_hash", "governance_hash", "payload", "parent_binding"}
        if not isinstance(proof, dict) or set(proof) != names:
            return False
        immutable = FrozenIdentity.model_validate({key: proof[key] for key in IDENTITY_FIELDS}).model_dump(mode="json")
        if not units._state_valid(proof, proof["recorded_at"]) or hash_content({key: proof[key] for key in GOVERNANCE_FIELDS}) != proof["governance_hash"]:
            return False
        parent = proof["parent_binding"]
        if not isinstance(parent, dict) or set(parent) != {"scope", "sku", "signer", "unit_definition", "legacy_snapshot"} or parent["scope"] != "hospital_inventory":
            return False
        unit = parent["unit_definition"]
        req = SourceCreate.model_validate(
            {
                "item_kind": proof["item_kind"],
                "item_id": proof["item_id"],
                "scope": proof["scope"],
                "unit_definition_id": proof["unit_definition_id"],
                "expected_unit_content_hash": None if unit is None else unit["content_hash"],
                "expected_unit_governance_hash": None if unit is None else unit["governance_hash"],
                "payload": proof["payload"],
            }
        )
        p = req.payload.model_dump(mode="json")
        if p["kind"] != proof["source_kind"] or any(proof[key] != p.get(key) for key in ("date_from", "date_to", "timezone")):
            return False
        if p["kind"] == "inventory_observation" and p["observed_at"] is not None and p["observed_at"] > proof["recorded_at"]:
            return False
        if p.get("date_from") is not None and p["date_from"] <= utc_datetime(proof["recorded_at"]).replace(tzinfo=datetime.UTC).astimezone(ZoneInfo(p["timezone"])).date().isoformat():
            return False
        sku = parent["sku"]
        fields = {"name", "status", "barcode"} if proof["item_kind"] == "pharmaceutical" else {"name", "status", "category", "catalog_unit"}
        if (
            not isinstance(sku, dict)
            or set(sku) != {"item_kind", "item_id", "scope", "identity"}
            or any(sku[key] != proof[key] for key in ("item_kind", "item_id", "scope"))
            or not isinstance(sku["identity"], dict)
            or set(sku["identity"]) != fields
        ):
            return False
        attestation = p["professional_attestation"]
        expected_signer = {"user_id": proof["created_by"], "user_role": "pharmacist"} if attestation["status"] == "confirmed" else None
        if parent["signer"] != expected_signer or attestation["status"] == "confirmed" and attestation["signer_user_id"] != proof["created_by"]:
            return False
        if proof["unit_definition_id"] is None:
            if unit is not None:
                return False
        elif (
            unit is None
            or not units.verify_original_proof(unit)
            or unit["record_kind"] != "unit"
            or unit["status"] != "published"
            or any(unit[key] != proof[key] for key in ("unit_definition_id", "item_kind", "item_id", "scope"))
        ):
            return False
        confirmed_quantities = any(q["unit_review"] == "confirmed" for q in _all_quantities(p))
        if confirmed_quantities or p.get("legacy_quantity_unit_review") == "confirmed":
            if unit is None or unit["payload"]["professional_attestation"]["status"] != "confirmed":
                return False
            if any(q["unit_review"] == "confirmed" and q["original_unit_text"] != unit["payload"]["original_unit_text"] for q in _all_quantities(p)):
                return False
        legacy = parent["legacy_snapshot"]
        if p["kind"] == "inventory_observation":
            if not verify_legacy_capture(legacy) or any(legacy[key] != proof[key] for key in ("item_kind", "item_id", "scope")) or legacy["captured_at"] > proof["recorded_at"]:
                return False
            raw = legacy["sku"]["projection"]
            expected_sku = {"name": raw["name"], "status": raw["status"]}
            expected_sku.update({"barcode": raw["barcode"]} if proof["item_kind"] == "pharmaceutical" else {"category": raw["category"], "catalog_unit": raw["unit"]})
            if expected_sku != sku["identity"]:
                return False
            if p["legacy_quantity_unit_review"] == "confirmed" and raw["unit"] is not None and raw["unit"] != unit["payload"]["original_unit_text"]:
                return False
        elif legacy is not None:
            return False
        if proof["source_id"] != f"inventory_fact:{proof['source_record_id']}:{proof['content_hash'][:12]}":
            return False
        return hash_content({**immutable, "payload": p, "parent_binding": parent}) == proof["content_hash"] and len(canonical_json(proof).encode()) <= SOURCE_BYTES
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError):
        return False


def source_proof(row):
    values = {
        **source_identity(row),
        **governance(row),
        "payload": units._load(row.payload_json, PAYLOAD_BYTES),
        "parent_binding": units._load(row.parent_binding_json, PARENT_BYTES),
        "content_hash": row.content_hash,
    }
    values["governance_hash"] = hash_content(governance(row))
    values["source_id"] = f"inventory_fact:{row.source_record_id}:{row.content_hash[:12]}"
    if not verify_original_proof(values):
        raise HTTPException(409, "完整库存原件自身类型、单位、时间或SHA无法核对")
    return values


def parent_status(db, proof):
    parent, reasons = proof["parent_binding"], []
    current = {"sku": None, "signer": None, "unit": None, "legacy_content_digest": None}
    try:
        current["sku"] = units.sku_binding(db, proof["item_kind"], proof["item_id"], locking=True)
        if current["sku"] != parent["sku"] or current["sku"]["identity"]["status"] != 0:
            reasons.append("original_sku_changed")
    except HTTPException:
        reasons.append("original_sku_unavailable")
    try:
        current["signer"] = units._signer(db, proof["payload"]["professional_attestation"], locking=True)
        if current["signer"] != parent["signer"]:
            reasons.append("professional_signature_changed")
    except HTTPException:
        reasons.append("professional_signature_changed")
    unit = parent["unit_definition"]
    if unit is not None:
        try:
            now = units.source_proof("unit", units.record(db, "unit", unit["unit_definition_id"], locking=True))
            why, state = units.parent_status(db, now, locking=True)
            current["unit"] = {"content_hash": now["content_hash"], "governance_hash": now["governance_hash"], "parent_current": not why, "current_basis_hash": hash_content(state)}
            if why or now["status"] != "published" or any(now[key] != unit[key] for key in ("content_hash", "governance_hash")):
                reasons.append("unit_definition_changed")
        except HTTPException:
            reasons.append("unit_definition_changed")
    if parent["legacy_snapshot"] is not None:
        try:
            now = capture_legacy_inventory(db, proof["item_kind"], proof["item_id"])
            current["legacy_content_digest"] = now["collection_digest"]
            if now["collection_digest"] != parent["legacy_snapshot"]["collection_digest"]:
                reasons.append("legacy_inventory_changed")
        except HTTPException:
            reasons.append("legacy_inventory_changed")
    return sorted(set(reasons)), current


def source_current(db, user, record_id, *, audit_only=False, locking=False):
    actor, row = _scope(db, user, record_id)
    if audit_only and actor.user_role != "super_admin":
        raise HTTPException(403, "失效库存原件完整审计仅限超级管理员")
    proof = source_proof(row)
    reasons, current = parent_status(db, proof)
    parent_current = not reasons
    if proof["status"] != "published":
        reasons.append("source_not_published")
    attestation = proof["payload"]["professional_attestation"]
    result = {
        **proof,
        "professional_status": attestation["status"],
        "signer_user_id": attestation["signer_user_id"],
        "signed_at": proof["recorded_at"] if attestation["status"] == "confirmed" else None,
        "parent_current": parent_current,
        "eligible": not reasons,
        "exclusion_reasons": sorted(set(reasons)),
        "can_record": current["sku"] is not None and current["sku"]["identity"]["status"] == 0,
        "can_review": actor.user_role == "super_admin" and row.status == "draft" and parent_current,
        "can_revoke": row.status in {"draft", "published"} and (actor.user_role == "super_admin" or actor.user_id == row.created_by),
        "audit_only": audit_only,
        "eligibility_basis": {"schema_version": "inventory_current_eligibility_v1", "current_parent_state_hash": hash_content(current), "not_professional_or_operational_validation": True},
    }
    if not (audit_only or result["eligible"] or row.status == "draft" and parent_current):
        for key in ("payload", "parent_binding", "review_basis_note", "revoke_reason"):
            result[key] = None
    if not verify_source_wrapper(result):
        raise HTTPException(409, "库存原件回执闭包无法核对")
    return result


@atomic
def create_source(db, user, request):
    req = SourceCreate.model_validate(request.model_dump(mode="json") if hasattr(request, "model_dump") else request)
    actor = lock_inventory_write(db, user, allowed_roles=SOURCE_ROLES, skus=[(req.item_kind, req.item_id)], require_active=True)
    p = req.payload.model_dump(mode="json")
    signer = units._signer(db, p["professional_attestation"], actor, locking=True)
    unit = None
    if req.unit_definition_id is not None:
        unit = units.source_proof("unit", units.record(db, "unit", req.unit_definition_id, locking=True))
        why, _ = units.parent_status(db, unit, locking=True)
        if (
            why
            or unit["status"] != "published"
            or unit["content_hash"] != req.expected_unit_content_hash
            or unit["governance_hash"] != req.expected_unit_governance_hash
            or any(unit[key] != getattr(req, key) for key in ("item_kind", "item_id", "scope"))
        ):
            raise HTTPException(409, "所选原单位、实际SKU或药师签署已变化")
    parent = {
        "scope": req.scope,
        "sku": units.sku_binding(db, req.item_kind, req.item_id, locking=True),
        "signer": signer,
        "unit_definition": unit,
        "legacy_snapshot": capture_legacy_inventory(db, req.item_kind, req.item_id) if p["kind"] == "inventory_observation" else None,
    }
    now = utcnow()
    recorded = utc_text(now)
    if p.get("observed_at") is not None and p["observed_at"] > recorded:
        raise HTTPException(422, "独立盘点原观察时刻不能晚于真实服务器登记")
    if p.get("date_from") is not None and p["date_from"] <= now.replace(tzinfo=datetime.UTC).astimezone(ZoneInfo(p["timezone"])).date().isoformat():
        raise HTTPException(422, "未来情景和候选须从明确的未来完整业务日开始")
    row = AIInventoryNativeSource(
        source_record_id=str(uuid.uuid4()),
        source_kind=p["kind"],
        item_kind=req.item_kind,
        item_id=req.item_id,
        scope=req.scope,
        unit_definition_id=req.unit_definition_id,
        date_from=p.get("date_from"),
        date_to=p.get("date_to"),
        timezone=p.get("timezone"),
        schema_version="inventory_native_source_v1",
        recorded_at=now,
        created_by=actor.user_id,
        payload_json=units.bounded_json(p, PAYLOAD_BYTES),
        parent_binding_json=units.bounded_json(parent, PARENT_BYTES),
        status="draft",
        revision=1,
        reviewed_by=None,
        reviewed_at=None,
        review_basis_note="",
        revoked_by=None,
        revoked_at=None,
        revoke_reason="",
    )
    row.content_hash = hash_content({**source_identity(row), "payload": p, "parent_binding": parent})
    source_proof(row)
    db.add(row)
    db.flush()
    audit.audit(
        db, actor.user_id, "inventory.source.create", row.source_record_id, {"source_kind": row.source_kind, "content_hash": row.content_hash, "item_kind": row.item_kind, "item_id": row.item_id}
    )
    db.flush()
    lock_inventory_write(db, user, allowed_roles=SOURCE_ROLES, skus=[(req.item_kind, req.item_id)], require_active=True)
    if parent_status(db, source_proof(row))[0]:
        raise HTTPException(409, "登记期间真实SKU、单位、药师或库存原集合已变化")
    return row


@atomic
def review_source(db, user, record_id, request, *, revoke=False):
    req = (SourceRevoke if revoke else SourceReview).model_validate(request.model_dump(mode="json") if hasattr(request, "model_dump") else request)
    actor, row = _scope(db, user, record_id)
    proof = source_proof(row)
    if not revoke and actor.user_role != "super_admin" or revoke and actor.user_role != "super_admin" and actor.user_id != row.created_by:
        raise HTTPException(403, "技术发布仅限超级管理员；普通账户仅可撤销本人原件")
    if row.revision != req.expected_revision or row.content_hash != req.expected_content_hash or row.status not in ({"draft", "published"} if revoke else {"draft"}):
        raise HTTPException(409, "原库存资料版本、SHA或治理状态已变化")
    if not revoke and parent_status(db, proof)[0]:
        raise HTTPException(409, "原SKU、单位、药师或完整库存集合已失效")
    now = utcnow()
    changes = {"status": "revoked" if revoke else "published" if req.decision == "publish" else "rejected", "revision": row.revision + 1}
    changes.update(
        {"revoked_by": actor.user_id, "revoked_at": now, "revoke_reason": req.basis_note} if revoke else {"reviewed_by": actor.user_id, "reviewed_at": now, "review_basis_note": req.basis_note}
    )
    count = (
        db.query(AIInventoryNativeSource)
        .filter_by(source_record_id=record_id, revision=req.expected_revision, content_hash=req.expected_content_hash, status=row.status)
        .update(changes, synchronize_session=False)
    )
    if count != 1:
        raise HTTPException(409, "并发库存原件治理已变化")
    db.flush()
    db.refresh(row)
    source_proof(row)
    audit.audit(
        db,
        actor.user_id,
        "inventory.source." + ("revoke" if revoke else req.decision),
        record_id,
        {"revision": row.revision, "content_hash": row.content_hash, "governance_hash": hash_content(governance(row))},
    )
    db.flush()
    final = lock_inventory_write(db, user, allowed_roles=SOURCE_ROLES)
    if not revoke and final.user_role != "super_admin" or revoke and final.user_role != "super_admin" and final.user_id != row.created_by:
        raise HTTPException(403, "治理期间当前账户权限已变化")
    if not revoke and parent_status(db, source_proof(row))[0]:
        raise HTTPException(409, "治理期间原库存完整集合或专业原件已变化")
    return row


def source_metadata(value):
    return SourceMetadata.model_validate({key: value[key] for key in SourceMetadata.model_fields}).model_dump(mode="json")


def verify_source_wrapper(value, *, capture=False):
    try:
        expected = CaptureSourceWrapper if capture else SourceWrapper
        parsed = expected.model_validate(value).model_dump(mode="json")
        if parsed != value or len(canonical_json(value).encode()) > SOURCE_BYTES or value["source_id"] != f"inventory_fact:{value['source_record_id']}:{value['content_hash'][:12]}":
            return False
        reasons = value["exclusion_reasons"]
        if (
            len(set(reasons)) != len(reasons)
            or set(reasons) - REASONS
            or value["parent_current"] != (not bool(set(reasons) - {"source_not_published"}))
            or value["eligible"] != (value["status"] == "published" and value["parent_current"])
        ):
            return False
        if (value["status"] != "published") != ("source_not_published" in reasons):
            return False
        if capture and (value["audit_only"] or any(value[key] for key in ("can_record", "can_review", "can_revoke"))):
            return False
        absent = value["payload"] is None
        if not units._state_valid(value, value["recorded_at"], redacted=absent):
            return False
        if absent:
            return value["parent_binding"] is None and not value["eligible"] and not value["audit_only"] and bool(reasons)
        proof = {key: value[key] for key in (*IDENTITY_FIELDS, *GOVERNANCE_FIELDS, "source_id", "content_hash", "governance_hash", "payload", "parent_binding")}
        if not verify_original_proof(proof):
            return False
        a = value["payload"]["professional_attestation"]
        if [value["professional_status"], value["signer_user_id"], value["signed_at"]] != [a["status"], a["signer_user_id"], value["recorded_at"] if a["status"] == "confirmed" else None]:
            return False
        if capture:
            return value["eligible"] and value["status"] == "published" and not value["audit_only"] and not any(value[key] for key in ("can_record", "can_review", "can_revoke"))
        return value["audit_only"] or value["eligible"] or value["status"] == "draft" and value["parent_current"]
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError):
        return False


def current_actor(db, user):
    """All ordinary/audit decisions are actual current SHARE reads."""
    return units.current_actor(db, user, locking=True)


def row_metadata(row):
    """Metadata only; full original validation is explicitly deferred to detail."""
    value = {
        **source_identity(row),
        **governance(row),
        "content_hash": row.content_hash,
        "source_id": f"inventory_fact:{row.source_record_id}:{row.content_hash[:12]}",
        "governance_hash": hash_content(governance(row)),
    }
    if not units._state_valid(value, value["recorded_at"]):
        raise HTTPException(409, "原件治理元数据无法核对，不能伪装完整原件")
    return source_metadata(value)
