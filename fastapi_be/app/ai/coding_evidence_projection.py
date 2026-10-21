"""One minimal model-visible projection, with literal Unicode citation text."""

import hashlib
import hmac
from types import SimpleNamespace

TEXT_FIELDS = ("admission_diagnosis", "discharge_diagnosis", "other_diagnosis", "operation_summary", "complication")
POLICY = {
    "schema_version": "coding_projection_policy_v1",
    "scope": "one_actual_home_and_admission",
    "clinical_assessment": "awaits_human_clarification",
    "dictionary_release": "unknown",
    "historical_group_rule_basis": "unknown",
    "official_grouper": "not_provided",
    "minimization": "known_patient_identifiers_and_common_identity_phone_patterns_in_explicit_display_text_only_not_guaranteed_anonymous",
    "citation_basis": "exact_model_visible_projected_text_unicode_codepoints_not_private_original_fulltext",
}


def token(snapshot, kind, identifier):
    return "coding_" + kind + ":" + hmac.new(bytes.fromhex(snapshot["identity_secret"]), (kind + ":" + str(identifier)).encode(), hashlib.sha256).hexdigest()


def text_hash(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def display(snapshot, value):
    if value is None:
        return None
    from app.ai.context import minimize_identifiers

    patient = SimpleNamespace(**snapshot["collection"]["minimization_basis"])
    return minimize_identifiers(value, patient)


def project_snapshot(snapshot, metadata):
    """No arbitrary recursive rewrite of hashes, IDs, discriminators or keys."""
    c = snapshot["collection"]
    documents = []
    missing = []
    for key in TEXT_FIELDS:
        value = c["home"][key]
        if value is None:
            missing.append(key)
            continue
        text = display(snapshot, value)
        documents.append({"source_id": token(snapshot, "document", key), "field": key, "text": text, "text_hash": text_hash(text)})
    dictionary = {(r["kind"], r["code"]): r["entry"] for r in c["dictionary_entries"]}
    bindings = []
    for row in c["code_bindings"]:
        entry = dictionary.get((row["kind"], row["icd_code"]))
        state = (
            "entry_unavailable"
            if entry is None
            else "entry_status_unknown"
            if type(entry["status"]) is not int or entry["status"] not in (0, 1)
            else "entry_inactive"
            if entry["status"] == 0
            else "stored_name_differs"
            if row["icd_name"] != entry["name"]
            else "matches_current_dictionary"
        )
        bindings.append(
            {
                "binding_token": token(snapshot, "binding", row["binding_id"]),
                "code_token": token(snapshot, "code", str(row["kind"]) + ":" + str(row["icd_code"])),
                "kind": row["kind"] if row["kind"] in {"diagnosis", "operation"} else "unknown",
                "code_text": display(snapshot, row["icd_code"]),
                "stored_name": display(snapshot, row["icd_name"]),
                "is_primary": row["is_primary"],
                "current_dictionary_state": state,
                "current_dictionary_name": display(snapshot, entry["name"]) if entry else None,
            }
        )
    entries = [
        {
            "source_id": token(snapshot, "dictionary", str(r["kind"]) + ":" + str(r["code"])),
            "kind": r["kind"] if r["kind"] in {"diagnosis", "operation"} else "unknown",
            "code_text": display(snapshot, r["code"]),
            "entry": None
            if r["entry"] is None
            else {
                "code_text": display(snapshot, r["entry"]["code"]),
                "name": display(snapshot, r["entry"]["name"]),
                "category": display(snapshot, r["entry"]["category"]),
                "status": r["entry"]["status"],
                "release_version": "unknown",
            },
        }
        for r in c["dictionary_entries"]
    ]

    def rule_view(row):
        if row is None:
            return None
        return {
            "source_id": token(snapshot, "rule", row["rule_id"]),
            **{k: display(snapshot, row[k]) for k in ("payment_method", "group_code", "group_name", "diagnosis_prefix", "procedure_prefix", "version")},
            **{k: row[k] for k in ("priority", "status", "effective_from", "effective_to")},
            "rule_scope": "current_local_prefix_rule_not_official_grouper",
        }

    groups = [
        {
            "source_id": token(snapshot, "group", r["grouping_id"]),
            **{k: display(snapshot, r[k]) for k in ("group_code", "payment_method", "diagnosis", "diagnosis_codes", "procedure_codes", "grouping_method")},
            "linked_current_rule": None if r["rule_id"] is None else token(snapshot, "rule", r["rule_id"]),
            "original_rule_version": "unknown",
        }
        for r in c["recorded_groups"]
    ]
    primary = [r for r in c["code_bindings"] if r["kind"] == "diagnosis" and type(r["is_primary"]) is int and r["is_primary"] == 1]
    checks = {
        "primary_diagnosis_state": "one_recorded_primary" if len(primary) == 1 else "not_recorded" if not primary else "conflicting_multiple_primaries",
        "malformed_primary_flags": sum(type(r["is_primary"]) is not int or r["is_primary"] not in (0, 1) for r in c["code_bindings"]),
        "duplicate_codes": len(c["code_bindings"]) - len({(r["kind"], r["icd_code"]) for r in c["code_bindings"]}),
        "home_document_state": "submitted" if c["home"]["status"] == 1 else "archived" if c["home"]["status"] == 2 else "draft_or_unknown",
        "clinical_validity": "not_determined",
    }
    package = c["rule_package"]
    return {
        "schema_version": "coding_evidence_public_v1",
        "case_snapshot_id": metadata["case_snapshot_id"],
        "source_id": metadata["source_id"],
        "case_content_hash": metadata["content_hash"],
        "case_publication_governance_hash": metadata["governance_hash"],
        "policy": POLICY.copy(),
        "captured_at": c["captured_at"],
        "original_clock_basis": "legacy_naive_unknown_not_utc_or_historical_availability_evidence",
        "documents": documents,
        "missing_document_fields": missing,
        "code_bindings": bindings,
        "dictionary_entries": entries,
        "recorded_groups": groups,
        "linked_local_rules": [rule_view(r["entry"]) for r in c["linked_rules"]],
        "local_rule_package": None
        if package is None
        else {
            "source_id": token(snapshot, "package", package["package_id"]),
            "package_kind": "local_prefix_snapshot",
            "rules": [rule_view(r) for r in package["snapshot"]["rules"]],
            "official_release": "not_provided",
        },
        "structural_checks": checks,
    }
