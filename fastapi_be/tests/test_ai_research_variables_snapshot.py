"""Private construction/projection helpers; no persisted Batch/audit authority."""

import copy
import json
import uuid

import pytest
from fastapi import HTTPException

from app.ai import research_variables_snapshot as snapshot
from app.ai.research_cohort_sources import utc_text, utcnow
from app.ai.research_variables_collection import capture_variable_sources
from tests.test_ai_research_cohort_contract import BASIS
from tests.test_ai_research_cohort_sources import research_case as research_case  # noqa: F401
from tests.test_ai_research_variables_collection import variable_capture_case as variable_capture_case  # noqa: F401
from tests.test_ai_research_variables_dictionary import variable_dictionary_case as variable_dictionary_case  # noqa: F401


def make(db, fixture, *, key=b"a" * 32, batch_id=None):
    case, _, request, _, _ = fixture
    captured = capture_variable_sources(db, case["admin_user"], request)
    # A deliberately synthetic prospective receipt, validated here for shape
    # only. The later SQL Batch lifecycle must bind its own actual Audit row.
    return snapshot.make_variable_snapshot(batch_id or str(uuid.uuid4()), captured["actor_id"], captured, BASIS, identity_key=key, created_event_id=10001, created_at=utc_text(utcnow()))


def test_whole_private_capture_projects_every_literal_once_without_raw_subject_record_ids_or_private_key(db_session, variable_capture_case):
    private = make(db_session, variable_capture_case)
    source = snapshot.project_variable_snapshot(private, "c" * 64, identity_key=b"a" * 32)
    captured = private["capture"]
    expected = [v["literal"] for row in captured["records"] for v in row["variables"]]
    assert [doc["literal"] for doc in source["documents"]] == expected
    assert len({doc["field_token"] for doc in source["documents"]}) == len(expected)
    assert source["privacy_basis"].endswith("not_anonymity") and source["coverage"].endswith("no_inferred_absence_or_automatic_winner")
    encoded = json.dumps(source, ensure_ascii=False)
    assert b"a".hex() * 32 not in encoded and private["identity_key_hash"] not in encoded
    assert private["scope_id"] not in encoded and private["dictionary_id"] not in encoded
    assert all(row["record_id"] not in encoded for row in captured["records"])
    assert source["variables"] == captured["dictionary_original"]["payload"]["variables"]
    assert len(source["records"]) == len(captured["records"])
    assert any(row["window_status"] == "unknown_record_clock" for row in source["records"])
    assert any(row["lifecycle_original"]["status"] == 0 for row in source["records"])
    assert snapshot.project_variable_snapshot(private, "c" * 64, identity_key=b"a" * 32) == source
    other = make(db_session, variable_capture_case, key=b"b" * 32)
    second = snapshot.project_variable_snapshot(other, "c" * 64, identity_key=b"b" * 32)
    assert set(source["member_tokens"]).isdisjoint(second["member_tokens"])
    assert {doc["field_token"] for doc in source["documents"]}.isdisjoint(doc["field_token"] for doc in second["documents"])


@pytest.mark.parametrize(
    "mutation",
    ["extra", "scope", "dictionary", "actor_bool", "event_bool", "creation_clock", "basis", "key_hash", "manifest", "authority", "collection", "request", "recipe_missing", "recipe_digest", "key"],
)
def test_private_batch_reconstruction_requires_exact_creation_identity_receipt_shape_parent_capture_and_recipe(db_session, variable_capture_case, mutation):
    value = copy.deepcopy(make(db_session, variable_capture_case))
    key = b"a" * 32
    if mutation == "extra":
        value["normalized_values"] = {}
    elif mutation in {"scope", "dictionary"}:
        value[mutation + "_id"] = str(uuid.uuid4())
    elif mutation == "actor_bool":
        value["created_by"] = True
    elif mutation == "event_bool":
        value["created_event_id"] = True
    elif mutation == "creation_clock":
        value["created_at"] = "2020-01-01T00:00:00.000000Z"
    elif mutation == "basis":
        value["basis_note"] = " " * 30
    elif mutation == "key_hash":
        value["identity_key_hash"] = "f" * 64
    elif mutation == "manifest":
        value["member_manifest_hash"] = "f" * 64
    elif mutation == "authority":
        value["authorization_binding_hash"] = "f" * 64
    elif mutation == "collection":
        value["collection_digest"] = "f" * 64
    elif mutation == "request":
        value["request"]["patient_ids"] = [2147483647]
    elif mutation == "recipe_missing":
        value["recipe"]["implementation_sha256"].pop(next(iter(value["recipe"]["implementation_sha256"])))
    elif mutation == "recipe_digest":
        value["recipe"]["implementation_sha256"]["research_variables_snapshot.py"] = "f" * 64
    else:
        key = b"b" * 32
    with pytest.raises(HTTPException) as error:
        snapshot.verify_variable_snapshot(value, identity_key=key)
    assert error.value.status_code == 409


def test_old_recipe_can_only_reconstruct_frozen_integrity_and_cannot_generate_new_model_projection(db_session, variable_capture_case):
    value = make(db_session, variable_capture_case)
    value["recipe"]["implementation_sha256"]["research_variables_snapshot.py"] = "f" * 64
    assert snapshot.verify_variable_snapshot(value, identity_key=b"a" * 32, validate_current_recipe=False) == value
    with pytest.raises(HTTPException):
        snapshot.project_variable_snapshot(value, "c" * 64, identity_key=b"a" * 32)


@pytest.mark.parametrize("key", [b"", b"a" * 31, b"a" * 33, "a" * 32, bytearray(b"a" * 32), None])
def test_private_identity_key_is_exact_bytes_and_never_an_inferred_subject_identifier(key):
    with pytest.raises(HTTPException):
        snapshot._key(key)
