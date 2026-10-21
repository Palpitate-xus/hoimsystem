"""Frozen reconstruction is tested independently from current SQL authority."""

import copy

import pytest
from fastapi import HTTPException
from sqlalchemy import event

from app.ai.research_cohort_registry import review_registry_original
from app.ai.research_cohort_sources import hash_content
from app.ai.research_variables_capture_proof import _literal, verify_variable_capture
from app.ai.research_variables_collection import capture_variable_sources
from tests.test_ai_research_cohort_contract import BASIS
from tests.test_ai_research_cohort_sources import research_case as research_case  # noqa: F401
from tests.test_ai_research_variables_collection import variable_capture_case as variable_capture_case  # noqa: F401
from tests.test_ai_research_variables_dictionary import variable_dictionary_case as variable_dictionary_case  # noqa: F401


def _rehash(value):
    value["member_manifest"] = [{"patient_id": row["patient_id"], "family": row["family"], "record_id": row["record_id"], "content_hash": hash_content(row)} for row in value["records"]]
    value["member_manifest_hash"] = hash_content(value["member_manifest"])
    value["collection_digest"] = hash_content({key: item for key, item in value.items() if key not in {"captured_at", "collection_digest"}})


def test_actual_complete_capture_frozen_reconstruction_reads_no_sql_and_preserves_bom_crlf_emoji_null_zero(db_session, variable_capture_case):
    case, permission, request, _, _ = variable_capture_case
    captured = capture_variable_sources(db_session, case["admin_user"], request)
    statements = []

    def record(conn, cursor, statement, params, context, many):
        statements.append(statement)

    event.listen(db_session.bind, "before_cursor_execute", record)
    try:
        assert verify_variable_capture(captured) == captured
    finally:
        event.remove(db_session.bind, "before_cursor_execute", record)
    assert not statements
    literals = [v["literal"] for row in captured["records"] for v in row["variables"]]
    assert "\ufeff否认既往原症状\r\n🧪e\u0301逐字" in literals and None in literals
    assert any(row["lifecycle_original"]["status"] == 0 for row in captured["records"])
    review_registry_original(db_session, case["super_admin_user"], "authorization", permission["source_record_id"], dict(expected_revision=2, basis_note=BASIS), revoke=True)
    # Historical structural integrity survives withdrawal; current clinical
    # recapture separately denies. Neither this hash nor Super role grants it.
    assert verify_variable_capture(captured) == captured
    with pytest.raises(HTTPException) as error:
        capture_variable_sources(db_session, case["super_admin_user"], request)
    assert error.value.status_code == 403


@pytest.mark.parametrize(
    "mutation",
    [
        "extra",
        "purpose",
        "actor",
        "patient_bool",
        "record_identity",
        "duplicate",
        "order",
        "literal_bool",
        "literal_integer",
        "type",
        "field",
        "window",
        "clock_zone",
        "clock_precision",
        "clock_status",
        "missing_variable",
        "lifecycle_bool",
        "parent_kind",
        "parent_hash",
        "member_sha",
        "missing_member",
        "digest",
        "future_capture",
        "policy",
        "acl_bool",
    ],
)
def test_actual_capture_rejects_structural_and_semantic_tampering_even_with_recomputed_outer_hashes(db_session, variable_capture_case, mutation):
    case, _, request, _, _ = variable_capture_case
    value = copy.deepcopy(capture_variable_sources(db_session, case["admin_user"], request))
    row = next(row for row in value["records"] if row["recorded_clock"] is not None)
    field = row["variables"][0]
    if mutation == "extra":
        value["automatic_diagnosis"] = "forbidden"
    elif mutation == "purpose":
        value["purpose"] = "cohort_criteria_review"
    elif mutation == "actor":
        value["actor_id"] += 100000
    elif mutation == "patient_bool":
        row["patient_id"] = True
    elif mutation == "record_identity":
        row["record_id"] = 1
    elif mutation == "duplicate":
        value["records"].append(copy.deepcopy(row))
    elif mutation == "order":
        value["records"].reverse()
    elif mutation == "literal_bool":
        field["literal"] = False
    elif mutation == "literal_integer":
        field["literal"] = 0
    elif mutation == "type":
        field["value_kind"] = "original_integer"
    elif mutation == "field":
        field["field"] = "doctor_id"
    elif mutation == "window":
        field["record_window"]["date_from"] = "2026-01-01"
    elif mutation == "clock_zone":
        row["recorded_clock"] += "Z"
    elif mutation == "clock_precision":
        row["recorded_clock"] = row["recorded_clock"][:19]
    elif mutation == "clock_status":
        row["window_status"] = "unknown_record_clock"
    elif mutation == "missing_variable":
        row["variables"].pop()
    elif mutation == "lifecycle_bool":
        row["lifecycle_original"]["status"] = False
    elif mutation == "parent_kind":
        row["parent_binding"]["kind"] = "direct_patient_fk"
    elif mutation == "parent_hash":
        row["parent_binding"].update(status="unknown_parent", technical_hash="f" * 64)
    elif mutation == "future_capture":
        value["captured_at"] = "2099-01-01T00:00:00.000000Z"
    elif mutation == "policy":
        value["privacy_basis"] = "anonymous"
    elif mutation == "acl_bool":
        next(item for item in value["authorization_manifest"] if item["kind"] == "acl")["metadata"]["user_id"] = True
    _rehash(value)
    if mutation == "member_sha":
        value["member_manifest"][0]["content_hash"] = "f" * 64
    elif mutation == "missing_member":
        value["member_manifest"].pop()
    elif mutation == "digest":
        value["collection_digest"] = "f" * 64
    with pytest.raises(HTTPException) as error:
        verify_variable_capture(value)
    assert error.value.status_code == 409


@pytest.mark.parametrize(
    "kind,value",
    [
        ("original_integer", False),
        ("original_integer", 2**31),
        ("original_integer", -(2**31) - 1),
        ("original_integer", "0"),
        ("original_calendar_date", "2026-02-30"),
        ("original_naive_clock", "2026-10-01T00:00:00.000000Z"),
        ("original_naive_clock", "2026-10-01T00:00:00"),
        ("verbatim_text", "\ud800"),
    ],
)
def test_exact_sql_literal_types_refuse_boolean_conversion_timezone_or_invalid_unicode(kind, value):
    with pytest.raises((ValueError, UnicodeError)):
        _literal(kind, value)


@pytest.mark.parametrize(
    "kind,value",
    [
        ("original_integer", 0),
        ("original_integer", -(2**31)),
        ("original_integer", 2**31 - 1),
        ("original_calendar_date", "2024-02-29"),
        ("original_naive_clock", "2026-10-01T00:00:00.123456"),
        ("verbatim_text", "\ufeff原值\r\n🧪e\u0301"),
        ("verbatim_text", ""),
        ("verbatim_text", None),
    ],
)
def test_literal_originals_preserve_their_exact_sql_type_and_value(kind, value):
    assert _literal(kind, value) == value
