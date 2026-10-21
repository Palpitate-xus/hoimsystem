"""Reconstruct a frozen76 capture; hashes grant no live access/completeness.

Current SQL recapture and the stored Batch creation receipt remain separate
requirements. A self-consistent supplied document cannot certify its own origin.
"""

import datetime as dt
import json

from fastapi import HTTPException
from pydantic import TypeAdapter

from app.ai.research_cohort_collection import Budget, _verify_authorization_manifest
from app.ai.research_cohort_contract import SHA, UTC, UUID, Date, Positive, canonical_json
from app.ai.research_cohort_registry import verify_registry_proof
from app.ai.research_cohort_sources import hash_content, verify_scope_proof
from app.ai.research_variables_authority import validate_dictionary_scope
from app.ai.research_variables_collection import FAMILY_CLOCKS, LIFECYCLE, MAX_BYTES, MAX_ROOTS, _active
from app.ai.research_variables_contract import BatchCapture
from app.ai.research_variables_dictionary import verify_dictionary_proof
from app.ai.research_variables_fields import VARIABLE_USE

POLICIES = {
    "time_basis": "retained_legacy_naive_record_clock_not_historical_asof_availability",
    "missingness_basis": "no_record_null_or_no_model_candidate_does_not_establish_not_measured_not_applicable_or_absent",
    "privacy_basis": "purpose_authorized_literal_fields_may_contain_identifiers_not_anonymous",
}
CAPTURE_KEYS = {
    "schema_version",
    "purpose",
    "request",
    "actor_id",
    "scope_original",
    "actor_acl",
    "patient_authorizations",
    "authorization_manifest",
    "dictionary_original",
    "records",
    "member_manifest",
    "member_manifest_hash",
    "captured_at",
    "collection_digest",
    *POLICIES,
}
RECORD_KEYS = {"family", "patient_id", "record_id", "recorded_clock", "window_status", "lifecycle_original", "parent_binding", "variables"}


def _typed(annotation, value):
    return TypeAdapter(annotation).validate_python(value, strict=True)


def _literal(kind, value):
    if value is None:
        return None
    if kind == "original_integer":
        if type(value) is not int or not -(2**31) <= value < 2**31:
            raise ValueError("An exact recorded SQL Integer, including zero, is required")
    elif kind == "original_calendar_date":
        _typed(Date, value)
    elif kind == "original_naive_clock":
        if type(value) is not str:
            raise ValueError("An original naive clock must remain literal text")
        clock = dt.datetime.fromisoformat(value)
        if clock.tzinfo is not None or clock.isoformat(timespec="microseconds") != value:
            raise ValueError("Do not invent timezone or remove stored microseconds")
    elif kind == "verbatim_text":
        if type(value) is not str:
            raise ValueError("Literal original text required")
        value.encode("utf-8", errors="strict")
    else:
        raise ValueError("An exact declared original kind is required")
    return value


def _published_at(proof, captured_at, *, validity=True):
    identity, governance = proof["identity"], proof["governance"]
    if governance["status"] != "published" or governance["reviewed_at"] > captured_at or identity["created_at"] > captured_at:
        raise ValueError("Original publication must precede capture")
    if validity and (identity["valid_from"] is None or not identity["valid_from"] <= captured_at < identity["valid_until"]):
        raise ValueError("Original recorded period did not cover capture")


def _manifest_types(roots):
    for item in roots:
        meta = item["metadata"]
        if item["kind"] == "acl":
            _typed(Positive, meta["user_id"])
            if meta["permission"] not in {"read_only", "read_capture"}:
                raise ValueError("Unknown original ACL permission")
        else:
            _typed(Positive, meta["patient_id"])
            if meta["authorization_kind"] not in {"permission_recorded", "waiver_recorded", "unknown", "withdrawn", "denied"} or meta["access_basis"] not in {
                "explicit_project_acl",
                "current_care_or_grant",
            }:
                raise ValueError("Unknown original patient authority kind")
            if meta["authorization_review_status"] not in {"unknown", "recorded_reviewed", "not_confirmed"}:
                raise ValueError("Unknown independent review state")
            if meta["authorization_reviewed_by"] is not None:
                _typed(Positive, meta["authorization_reviewed_by"])


def _record(entry, request, by_family):
    if type(entry) is not dict or set(entry) != RECORD_KEYS:
        raise ValueError("Closed whole literal record required")
    family, patient_id = entry["family"], entry["patient_id"]
    _typed(Positive, patient_id)
    if family not in by_family or patient_id not in request.patient_ids:
        raise ValueError("A record cannot expand the explicit Batch or dictionary")
    _typed(Positive if family == "patient_demographics" else UUID, entry["record_id"])
    if family == "patient_demographics" and entry["record_id"] != patient_id:
        raise ValueError("Exact actual demographic subject identity required")
    clock = _literal("original_naive_clock", entry["recorded_clock"])
    clock_name = FAMILY_CLOCKS.get(family)
    if not clock_name and clock is not None:
        raise ValueError("Static demographics has no episode clock")
    status = "static_subject_without_event_clock" if not clock_name else "unknown_record_clock" if clock is None else "recorded_naive_calendar_in_variable_window"
    if entry["window_status"] != status:
        raise ValueError("Original unknown/static/recorded clock distinction differs")
    active = [v for v in by_family[family] if _active(v, dt.datetime.fromisoformat(clock) if clock is not None else None)]
    if not active or type(entry["variables"]) is not list or len(entry["variables"]) != len(active):
        raise ValueError("Every active explicitly windowed original field is required")
    lifecycle = entry["lifecycle_original"]
    if type(lifecycle) is not dict or set(lifecycle) != set(LIFECYCLE.get(family, ())):
        raise ValueError("Whole recorded lifecycle fields required")
    for name, value in lifecycle.items():
        _literal("original_integer" if name == "status" else "original_naive_clock", value)
    repeated = {}
    for literal, variable in zip(entry["variables"], active, strict=True):
        expected = {
            "variable_key": variable.variable_key,
            "field": variable.field,
            "value_kind": variable.value_kind,
            "record_window": variable.record_window.model_dump() if variable.record_window is not None else None,
        }
        if type(literal) is not dict or set(literal) != {*expected, "literal"} or any(literal[key] != value for key, value in expected.items()):
            raise ValueError("Exact ordered declared field/window/type binding required")
        value = _literal(variable.value_kind, literal["literal"])
        if variable.field == clock_name and value != clock or variable.field in lifecycle and value != lifecycle[variable.field]:
            raise ValueError("A field cannot contradict its own retained header/lifecycle")
        if variable.field in repeated and repeated[variable.field] != value:
            raise ValueError("Repeated definitions cannot change the same original column")
        repeated[variable.field] = value
    parent = entry["parent_binding"]
    kind = "registration_uuid" if family == "medical_records" else "admission_id" if family == "structured_medical_records" else "direct_patient_fk"
    if (
        type(parent) is not dict
        or set(parent) != {"kind", "status", "technical_hash"}
        or parent["kind"] != kind
        or parent["status"] not in {"patient_bound", "unknown_parent", "missing_parent", "patient_mismatch"}
    ):
        raise ValueError("Closed opaque original parent locator required")
    _typed(SHA, parent["technical_hash"])
    if kind == "direct_patient_fk" and parent != {"kind": kind, "status": "patient_bound", "technical_hash": hash_content({"patient_id": patient_id})}:
        raise ValueError("Exact direct subject parent required")
    if parent["status"] == "unknown_parent" and parent["technical_hash"] != hash_content({kind: None}):
        raise ValueError("Unknown original parent cannot invent an identity")
    return (patient_id, family, str(entry["record_id"]))


def verify_variable_capture(value):
    """Whole frozen reconstruction only; do not use as current SQL authority."""
    try:
        if type(value) is not dict or set(value) != CAPTURE_KEYS or value["schema_version"] != "research_variable_capture_v1" or value["purpose"] != VARIABLE_USE:
            raise ValueError("Closed complete variable capture required")
        if len(canonical_json(value).encode("utf-8")) > MAX_BYTES or any(value[key] != expected for key, expected in POLICIES.items()):
            raise ValueError("Whole bounded capture and exact limitations required")
        actor_id, captured_at = _typed(Positive, value["actor_id"]), _typed(UTC, value["captured_at"])
        request = BatchCapture.model_validate(value["request"])
        if request.model_dump() != value["request"]:
            raise ValueError("Exact literal typed Batch request required")
        scope = verify_scope_proof(value["scope_original"])
        definition = verify_dictionary_proof(value["dictionary_original"])
        dictionary = validate_dictionary_scope(definition["payload"], scope)
        if (request.scope_id, request.scope_content_hash, request.scope_governance_hash) != (scope["identity"]["scope_id"], scope["content_hash"], scope["governance_hash"]):
            raise ValueError("All explicit project anchors required")
        if not set(request.patient_ids).issubset(scope["payload"]["patient_ids"]) or definition["parent_binding"]["scope"] != scope:
            raise ValueError("Original finite project and dictionary parent differ")
        if (request.variable_dictionary_id, request.dictionary_content_hash, request.dictionary_governance_hash) != (
            definition["identity"]["dictionary_id"],
            definition["content_hash"],
            definition["governance_hash"],
        ):
            raise ValueError("All explicit dictionary anchors required")
        _published_at(definition, captured_at, validity=False)
        if definition["definition_review"]["definition_review_status"] != "recorded_reviewed" or definition["definition_review"]["definition_reviewed_at"] > captured_at:
            raise ValueError("Recorded independent definition review must precede capture")
        acl = verify_registry_proof("acl", value["actor_acl"])
        if acl["identity"]["user_id"] != actor_id or acl["identity"]["permission"] != "read_capture" or acl["parent_binding"]["scope"] != scope:
            raise ValueError("Exact capture actor ACL required")
        permissions = value["patient_authorizations"]
        if type(permissions) is not list or [p["identity"]["patient_id"] for p in permissions] != request.patient_ids:
            raise ValueError("Every explicitly selected patient authority required")
        for permission in permissions:
            checked = verify_registry_proof("authorization", permission)
            if (
                checked["parent_binding"]["scope"] != scope
                or checked["identity"]["authorization_kind"] not in {"permission_recorded", "waiver_recorded"}
                or checked["authorization_review"]["authorization_review_status"] != "recorded_reviewed"
            ):
                raise ValueError("Original independent positive patient permission required")
        for proof in (scope, acl, *permissions):
            _published_at(proof, captured_at)
        _verify_authorization_manifest(value, scope, acl, permissions)
        _manifest_types(value["authorization_manifest"])
        budget = Budget()
        for original in (scope, acl, definition, *permissions, *value["authorization_manifest"]):
            budget.add(original)
        by_family = {}
        for variable in dictionary.variables:
            by_family.setdefault(variable.family, []).append(variable)
        if type(value["records"]) is not list or len(value["records"]) > MAX_ROOTS:
            raise ValueError("Whole bounded original member set required")
        manifest, previous = [], None
        for record in value["records"]:
            locator = _record(record, request, by_family)
            if previous is not None and locator <= previous:
                raise ValueError("Sorted distinct whole original members required")
            previous = locator
            budget.add(record)
            manifest.append({"patient_id": record["patient_id"], "family": record["family"], "record_id": record["record_id"], "content_hash": hash_content(record)})
        if value["member_manifest"] != manifest or value["member_manifest_hash"] != hash_content(manifest):
            raise ValueError("Every retained field must match its full original member manifest")
        body = {key: item for key, item in value.items() if key not in {"captured_at", "collection_digest"}}
        if value["collection_digest"] != hash_content(body):
            raise ValueError("Whole collection SHA differs")
        return json.loads(canonical_json(value))
    except (HTTPException, ValueError, TypeError, KeyError, AttributeError, UnicodeError) as exc:
        raise HTTPException(409, "变量捕获闭集、原项目字典、逐患者授权、完整字段或SHA无法核对") from exc
