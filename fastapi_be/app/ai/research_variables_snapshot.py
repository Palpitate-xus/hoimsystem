"""Complete76 private Batch and purpose-authorized literal model projection.

Identity minimization is not anonymity. Frozen hashes do not certify live
authority, SQL completeness, scientific validity or a missingness conclusion.
"""

import hashlib
import hmac
import json
from pathlib import Path

from fastapi import HTTPException
from pydantic import TypeAdapter

from app.ai.research_cohort_contract import SHA, UTC, UUID, Basis, Positive, canonical_json
from app.ai.research_cohort_sources import hash_content
from app.ai.research_variables_capture_proof import MAX_BYTES, verify_variable_capture
from app.ai.research_variables_draft import validate_draft
from app.ai.research_variables_fields import LIMITATIONS

RULE_ID = "research_variable_literal_projection_v1"
RECIPE_FILES = (
    "research_variables_fields.py",
    "research_variables_contract.py",
    "research_variables_collection.py",
    "research_variables_capture_proof.py",
    "research_variables_dictionary.py",
    "research_variables_snapshot.py",
    "research_cohort_contract.py",
    "research_cohort_collection.py",
    "research_cohort_registry.py",
    "research_cohort_sources.py",
)
SNAPSHOT_KEYS = {
    "schema_version",
    "batch_id",
    "scope_id",
    "dictionary_id",
    "created_by",
    "created_event_id",
    "created_at",
    "basis_note",
    "request",
    "capture",
    "collection_digest",
    "member_manifest_hash",
    "authorization_binding_hash",
    "identity_key_hash",
    "recipe",
}


def current_variable_recipe():
    root = Path(__file__).parent
    return {"rule_id": RULE_ID, "implementation_sha256": {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in RECIPE_FILES}}


def authorization_binding(capture):
    return hash_content({key: capture[key] for key in ("scope_original", "actor_acl", "patient_authorizations", "authorization_manifest", "dictionary_original")})


def _key(value):
    if type(value) is not bytes or len(value) != 32:
        raise HTTPException(409, "每批次私有身份键必须为完整32字节，未复用明文患者标识")
    return value


def make_variable_snapshot(batch_id, actor_id, captured, basis_note, *, identity_key, created_event_id, created_at):
    captured = verify_variable_capture(captured)
    request = captured["request"]
    result = {
        "schema_version": "research_variable_batch_original_v1",
        "batch_id": batch_id,
        "scope_id": request["scope_id"],
        "dictionary_id": request["variable_dictionary_id"],
        "created_by": actor_id,
        "created_event_id": created_event_id,
        "created_at": created_at,
        "basis_note": basis_note,
        "request": request,
        "capture": captured,
        "collection_digest": captured["collection_digest"],
        "member_manifest_hash": captured["member_manifest_hash"],
        "authorization_binding_hash": authorization_binding(captured),
        "identity_key_hash": hashlib.sha256(_key(identity_key)).hexdigest(),
        "recipe": current_variable_recipe(),
    }
    if len(canonical_json(result).encode("utf-8")) > MAX_BYTES:
        raise HTTPException(413, "完整变量批次快照超过8MiB，未裁剪原记录或授权")
    return verify_variable_snapshot(result, identity_key=identity_key)


def verify_variable_snapshot(value, *, identity_key, validate_current_recipe=True):
    try:
        if type(validate_current_recipe) is not bool or type(value) is not dict or set(value) != SNAPSHOT_KEYS or value["schema_version"] != "research_variable_batch_original_v1":
            raise ValueError("Closed whole Batch original required")
        if len(canonical_json(value).encode("utf-8")) > MAX_BYTES:
            raise ValueError("Whole private Batch budget required")
        for name in ("batch_id", "scope_id", "dictionary_id"):
            TypeAdapter(UUID).validate_python(value[name], strict=True)
        for name in ("created_by", "created_event_id"):
            TypeAdapter(Positive).validate_python(value[name], strict=True)
        TypeAdapter(UTC).validate_python(value["created_at"], strict=True)
        TypeAdapter(Basis).validate_python(value["basis_note"], strict=True)
        for name in ("collection_digest", "member_manifest_hash", "authorization_binding_hash", "identity_key_hash"):
            TypeAdapter(SHA).validate_python(value[name], strict=True)
        captured = verify_variable_capture(value["capture"])
        if (
            value["request"] != captured["request"]
            or value["created_by"] != captured["actor_id"]
            or value["created_at"] < captured["captured_at"]
            or value["scope_id"] != captured["request"]["scope_id"]
            or value["dictionary_id"] != captured["request"]["variable_dictionary_id"]
            or value["collection_digest"] != captured["collection_digest"]
            or value["member_manifest_hash"] != captured["member_manifest_hash"]
            or value["authorization_binding_hash"] != authorization_binding(captured)
            or value["identity_key_hash"] != hashlib.sha256(_key(identity_key)).hexdigest()
        ):
            raise ValueError("Exact private Batch creation, actor, key and all original anchors required")
        recipe = value["recipe"]
        if (
            type(recipe) is not dict
            or set(recipe) != {"rule_id", "implementation_sha256"}
            or recipe["rule_id"] != RULE_ID
            or type(recipe["implementation_sha256"]) is not dict
            or set(recipe["implementation_sha256"]) != set(RECIPE_FILES)
        ):
            raise ValueError("Whole explicit frozen implementation recipe required")
        for digest in recipe["implementation_sha256"].values():
            TypeAdapter(SHA).validate_python(digest, strict=True)
        if validate_current_recipe and recipe != current_variable_recipe():
            raise ValueError("Frozen Batch implementation differs from the current recipe")
        return json.loads(canonical_json(value))
    except (HTTPException, ValueError, TypeError, KeyError, AttributeError, UnicodeError) as exc:
        raise HTTPException(409, "变量批次快照原身份、创建审计、完整字段、私钥或实现摘要无法核对") from exc


def _opaque(key, namespace, raw):
    return namespace + ":" + hmac.new(key, canonical_json([namespace, raw]).encode("utf-8"), hashlib.sha256).hexdigest()


def project_variable_snapshot(snapshot, governance_hash, *, identity_key):
    key = _key(identity_key)
    snapshot = verify_variable_snapshot(snapshot, identity_key=key)
    TypeAdapter(SHA).validate_python(governance_hash, strict=True)
    captured = snapshot["capture"]
    documents, records = [], []
    for row in captured["records"]:
        member = _opaque(key, "rv_member", row["patient_id"])
        record = _opaque(key, "rv_record", [row["patient_id"], row["family"], row["record_id"]])
        field_tokens = []
        for field in row["variables"]:
            token = _opaque(key, "rv_field", [row["patient_id"], row["family"], row["record_id"], field["field"], field["variable_key"]])
            literal = field["literal"]
            document = {
                "member_token": member,
                "record_token": record,
                "field_token": token,
                "variable_key": field["variable_key"],
                "value_kind": field["value_kind"],
                "literal": str(literal) if type(literal) is int else literal,
            }
            if len(documents) >= 8192:
                raise HTTPException(413, "完整变量原字段超过8192份模型文档，未截断变量或原记录")
            documents.append(document)
            field_tokens.append(token)
        records.append(
            {
                "member_token": member,
                "record_token": record,
                "family": row["family"],
                "recorded_clock": row["recorded_clock"],
                "window_status": row["window_status"],
                "lifecycle_original": row["lifecycle_original"],
                "parent_status": row["parent_binding"]["status"],
                "field_tokens": field_tokens,
            }
        )
    # Reuse the independent closed literal-document validator, including NULL,
    # full scalar spelling, uniqueness and its own complete8MiB/8192 limits.
    validate_draft({"schema_version": "research_variable_draft_v1", "coverage": "partial_candidates_only", "candidates": []}, documents)
    result = {
        "schema_version": "research_variable_source_v1",
        "source_id": f"research_variables:{snapshot['batch_id']}:{hash_content(snapshot)[:12]}",
        "content_hash": hash_content(snapshot),
        "governance_hash": governance_hash,
        "captured_at": captured["captured_at"],
        "scope_token": _opaque(key, "rv_scope", snapshot["scope_id"]),
        "dictionary_token": _opaque(key, "rv_dictionary", snapshot["dictionary_id"]),
        "authorization_binding": _opaque(key, "rv_authority", snapshot["authorization_binding_hash"]),
        "collection_binding": _opaque(key, "rv_collection", snapshot["collection_digest"]),
        "member_tokens": [_opaque(key, "rv_member", patient_id) for patient_id in snapshot["request"]["patient_ids"]],
        "variables": captured["dictionary_original"]["payload"]["variables"],
        "records": records,
        "documents": documents,
        "documents_hash": hash_content(documents),
        "recipe": snapshot["recipe"],
        "limitations": list(LIMITATIONS),
        "coverage": "all_declared_recorded_candidates_no_inferred_absence_or_automatic_winner",
        "privacy_basis": "purpose_authorized_identifier_minimization_not_anonymity",
        "external_model_use": captured["scope_original"]["payload"]["external_model_use"],
    }
    if len(canonical_json(result).encode("utf-8")) > MAX_BYTES:
        raise HTTPException(413, "完整变量模型来源超过8MiB，未裁剪字段或文字")
    return result
