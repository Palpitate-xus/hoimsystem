"""Pure76 Task data; the real Source fixture still has no model permission.

No SQL/source authority, clinical effectiveness, model quality or new Source
recipe is asserted by these literal shape and resource-bound checks.
"""

import copy
import hashlib
import json
from pathlib import Path

import pytest

from app.ai import research_variables_task_contract as c

FIXTURES = Path(__file__).parent / "fixtures/research_variables_task"


def source():
    return json.loads((FIXTURES / "actual-public-source.json").read_text())


def access(count=2):
    return {
        "schema_version": "research_variable_task_access_v1",
        "requested_by": 1,
        "actor_role": "doctor",
        "actor_token_invalid_before": None,
        "scope_id": "00000000-0000-0000-0000-000000000001",
        "scope_content_hash": "a" * 64,
        "scope_governance_hash": "b" * 64,
        "acl_id": "00000000-0000-0000-0000-000000000002",
        "acl_content_hash": "c" * 64,
        "acl_governance_hash": "d" * 64,
        "patient_authorizations": [
            {"patient_id": index, "authorization_id": f"00000000-0000-0000-0000-{index + 10:012d}", "content_hash": "e" * 64, "governance_hash": "f" * 64} for index in range(1, count + 1)
        ],
    }


def test_actual_main_published_source_is_whole_and_unknown_model_permission_is_not_changed():
    value = source()
    manifest = json.loads((FIXTURES / "provenance.json").read_text())
    assert c.digest(value) == manifest["public_source_canonical_sha256"]
    assert c.validate_source(value).model_dump(mode="json") == value
    assert value["external_model_use"] == "unknown"
    assert len(value["documents"]) == 7 and len(value["limitations"]) == 5
    assert len({row["field_token"] for row in value["documents"]}) == 7
    assert "source_artifact_sha256" in manifest and "never authorizes a model task" in manifest["scope"]


@pytest.mark.parametrize("question", [None, "", "\u0085\ufeff\r\n　", "e\u0301🧪\r\n" * 200, "🧪" * 2000], ids=["none", "empty", "whitespace", "combining", "max_emoji"])
def test_optional_question_is_unchanged_unicode_codepoints_and_bytes(question):
    value = {"research_variable_batch_id": "00000000-0000-0000-0000-000000000001", "question": question}
    assert c.VariableTaskSelection.model_validate(value).model_dump() == value


@pytest.mark.parametrize("change", [{"patient_id": 1}, {"encounter_ref": "x"}, {"text": "caller source"}, {"research_variable_batch_id": None}, {"question": "x" * 2001}, {"question": "\ud800"}])
def test_task_selector_does_not_accept_patient_free_source_or_coerce_invalid_question(change):
    with pytest.raises(ValueError):
        c.VariableTaskSelection.model_validate({"research_variable_batch_id": "00000000-0000-0000-0000-000000000001", **change})


def test_actual_256_patient_anchor_manifest_fits_its_independent_binding_budget_without_run_text_promise():
    value = c.VariableTaskAccessManifest.model_validate(access(256))
    encoded = c.canonical(value, c.MAX_BINDING_BYTES).encode()
    assert 60000 < len(encoded) < c.MAX_BINDING_BYTES
    assert hashlib.sha256(encoded).hexdigest() == c.digest(value, c.MAX_BINDING_BYTES)
    assert len(value.patient_authorizations) == 256


def test_self_consistent_wholesale_omission_needs_the_independent_frozen_projection_anchor():
    original = source()
    expected = c.digest(original)
    assert c.validate_frozen_source(original, expected).model_dump(mode="json") == original
    altered = copy.deepcopy(original)
    record = altered["records"].pop()
    tokens = set(record["field_tokens"])
    altered["documents"] = [row for row in altered["documents"] if row["field_token"] not in tokens]
    altered["documents_hash"] = c.digest(altered["documents"])
    # A public opaque token set alone cannot prove SQL collection completeness.
    assert c.validate_source(altered).model_dump(mode="json") == altered
    with pytest.raises(ValueError):
        c.validate_frozen_source(altered, expected)


@pytest.mark.parametrize("axis", ["duplicate_patient", "order", "duplicate_permission", "bool_patient", "missing_acl", "role", "epoch", "extra"])
def test_authority_manifest_keeps_explicit_original_acl_patient_references_and_epoch(axis):
    value = access()
    if axis == "duplicate_patient":
        value["patient_authorizations"][1]["patient_id"] = 1
    elif axis == "order":
        value["patient_authorizations"].reverse()
    elif axis == "duplicate_permission":
        value["patient_authorizations"][1]["authorization_id"] = value["patient_authorizations"][0]["authorization_id"]
    elif axis == "bool_patient":
        value["patient_authorizations"][0]["patient_id"] = True
    elif axis == "missing_acl":
        value.pop("acl_id")
    elif axis == "role":
        value["actor_role"] = "patient"
    elif axis == "epoch":
        value["actor_token_invalid_before"] = "2026-10-21T12:00:00Z"
    else:
        value["approved"] = True
    with pytest.raises(ValueError):
        c.VariableTaskAccessManifest.model_validate(value)


@pytest.mark.parametrize(
    "axis",
    [
        "missing_document",
        "duplicate_record",
        "duplicate_document",
        "foreign_member",
        "field_record",
        "variable_kind",
        "window",
        "known_clock",
        "timezone",
        "lifecycle",
        "parent",
        "recipe",
        "source_id",
        "documents_hash",
        "limitation",
        "extra",
    ],
)
def test_whole_public_source_cannot_drop_or_mix_original_record_variable_or_clock_metadata(axis):
    value = copy.deepcopy(source())
    if axis == "missing_document":
        value["documents"].pop()
    elif axis == "duplicate_record":
        value["records"].append(value["records"][0])
    elif axis == "duplicate_document":
        value["documents"].append(value["documents"][0])
    elif axis == "foreign_member":
        value["member_tokens"] = ["rv_member:" + "a" * 64]
    elif axis == "field_record":
        value["documents"][0]["record_token"] = value["records"][1]["record_token"]
    elif axis == "variable_kind":
        value["documents"][0]["value_kind"] = "original_integer"
    elif axis == "window":
        value["records"][0]["recorded_clock"] = "2020-01-01T00:00:00.000000"
    elif axis == "known_clock":
        value["records"][0]["window_status"] = "unknown_record_clock"
    elif axis == "timezone":
        value["records"][0]["recorded_clock"] += "Z"
    elif axis == "lifecycle":
        value["records"][0]["lifecycle_original"]["status"] = False
    elif axis == "parent":
        value["records"][0]["parent_status"] = "current_encounter_confirmed"
    elif axis == "recipe":
        value["recipe"]["implementation_sha256"].pop("research_variables_snapshot.py")
    elif axis == "source_id":
        value["source_id"] = value["source_id"][:-1] + ("0" if value["source_id"][-1] != "0" else "1")
    elif axis == "documents_hash":
        value["documents_hash"] = "f" * 64
    elif axis == "limitation":
        value["limitations"].pop()
    else:
        value["auto_export"] = True
    with pytest.raises(ValueError):
        c.validate_source(value)


@pytest.mark.parametrize("raw", ['{"x":1,"x":2}', '{"x":NaN}', '{"x":Infinity}', '{"x":"\\ud800"}', "[" * 33 + "0" + "]" * 33])
def test_strict_json_rejects_duplicate_nonfinite_surrogate_or_excessive_depth(raw):
    with pytest.raises(ValueError):
        c.strict_json(raw)


def test_whole_utf8_escape_and_node_budgets_refuse_without_returning_a_partial_prefix():
    assert c.canonical({"x": "🧪"}, 12) == '{"x":"🧪"}'
    with pytest.raises(ValueError):
        c.canonical({"x": "🧪"}, 11)
    assert c.canonical({"x": "\n"}, 10) == '{"x":"\\n"}'
    with pytest.raises(ValueError):
        c.canonical({"x": "\n"}, 9)
    # An oversized child list is rejected before constructing a node-stack
    # tuple for every member. No huge Source or generated JSON is retained.
    with pytest.raises(ValueError):
        c.canonical([None] * c.MAX_JSON_NODES)
