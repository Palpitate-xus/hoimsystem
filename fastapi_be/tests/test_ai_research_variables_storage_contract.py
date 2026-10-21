"""Pure snapshot checks over an unmodified actual current SQL Context.

Provider/validation values below are synthetic shape-test inputs. No configured
Task, qualification, dispatch, model inference or clinical validation is claimed.
"""

import copy
import hashlib
import json
from pathlib import Path

import pytest

from app.ai import research_variables_storage_contract as s
from app.ai.research_variables_prompt import DEFAULT_TASK_PROMPT, SYSTEM_PROMPT
from app.ai.research_variables_task_contract import validate_frozen_source

FIXTURE = Path(__file__).parent / "fixtures/research_variables_task/actual-current-context.json"


def original():
    return json.loads(FIXTURE.read_text())


def snapshot():
    actual = original()
    return {
        "schema_version": "research_variable_task_snapshot_v1",
        "catalog_version": "pure-contract-not-executed",
        "system_prompt": SYSTEM_PROMPT,
        "task_prompt": DEFAULT_TASK_PROMPT,
        "prompt_origin": {"prompt_id": None, "prompt_version": 0},
        "payload": {"input": actual["selection"], "context": actual["context"], "tools": {}, "evidence": actual["evidence"]},
        "provider_snapshot": {
            "provider_id": 1,
            "revision": 1,
            "name": "synthetic-config-shape-only",
            "kind": "chat",
            "api_base": "https://synthetic.invalid/v1",
            "model": "synthetic-not-called",
            "timeout_seconds": 3,
            "max_output_tokens": 4096,
            "validation_report": "",
            "temperature": 0.0,
            "allows_patient_data": True,
            "effective_output_limit": 4096,
        },
        "feature_validation": {"status": "unreviewed", "note": "shape only, not clinical validation", "validated_by": None, "validated_at": None, "feature_revision": 1},
        "batch_publication": actual["batch_publication"],
        "actor_epoch": {"user_role": actual["binding"]["request_authorization"]["actor_role"], "token_invalid_before": actual["binding"]["request_authorization"]["actor_token_invalid_before"]},
        "run_clock_basis": "legacy_utc_second_storage",
    }


def test_exact_actual_context_publication_permission_and_short_ref_are_closed_without_claiming_a_provider_configuration():
    actual = original()
    proof = json.loads(FIXTURE.with_name("actual-current-context-provenance.json").read_text())
    assert hashlib.sha256(FIXTURE.read_bytes()).hexdigest() == proof["fixture_sha256"]
    assert "No Task Run" in proof["scope"]
    assert validate_frozen_source(actual["source"], actual["binding"]["source_projection_hash"]).external_model_use == "recorded_permitted"
    value = s.checked_snapshot(snapshot(), actual["binding"])
    assert value.payload.context.question == actual["selection"]["question"]
    assert len(actual["binding"]["request_authorization"]["patient_authorizations"]) == 2
    assert value.batch_publication.model_dump() == actual["batch_publication"]
    assert "source_json" not in value.payload.context.model_dump()


def test_prompt_hash_and_instructions_digest_use_distinct_exact_declared_conventions():
    value = snapshot()
    raw = json.dumps([value["system_prompt"], value["task_prompt"]], ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    assert s.prompt_hash(value) == hashlib.sha256(raw.encode()).hexdigest()
    assert s.instructions_digest(value) == hashlib.sha256((value["system_prompt"] + "\n\n" + value["task_prompt"]).encode()).hexdigest()
    assert s.prompt_hash(value) != s.instructions_digest(value)


@pytest.mark.parametrize(
    "origin,valid",
    [
        ({"prompt_id": None, "prompt_version": 0}, True),
        ({"prompt_id": "00000000-0000-0000-0000-000000000001", "prompt_version": 3}, True),
        ({"prompt_id": 1, "prompt_version": 3}, False),
        ({"prompt_id": None, "prompt_version": 3}, False),
        ({"prompt_id": "00000000-0000-0000-0000-000000000001", "prompt_version": 0}, False),
        ({"prompt_id": None, "prompt_version": False}, False),
    ],
)
def test_actual_custom_prompt_identity_is_uuid_and_independent_of_validation_status(origin, valid):
    raw = snapshot()
    raw["prompt_origin"] = origin
    if valid:
        assert s.VariableTaskSnapshot.model_validate(raw).feature_validation.status == "unreviewed"
    else:
        with pytest.raises(ValueError):
            s.VariableTaskSnapshot.model_validate(raw)


@pytest.mark.parametrize("damage", ["question_both", "evidence_both", "gov_note", "role", "source_digest"])
def test_two_mutable_copies_cannot_replace_the_independent_original_binding(damage):
    value, bound = snapshot(), original()["binding"]
    if damage == "question_both":
        value["payload"]["input"]["research_variable_batch_id"] = "00000000-0000-0000-0000-000000000001"
        value["payload"]["context"]["scope"]["selected_sources"]["research_variable_batch_id"] = value["payload"]["input"]["research_variable_batch_id"]
        value["payload"]["context"]["research_variable_binding"]["batch_id"] = value["payload"]["input"]["research_variable_batch_id"]
    elif damage == "evidence_both":
        value["payload"]["context"]["research_variable_binding"]["source_projection_hash"] = "a" * 64
        value["payload"]["evidence"][0]["source_digest"] = "a" * 64
    elif damage == "gov_note":
        value["batch_publication"]["review_basis_note"] += "changed"
    elif damage == "role":
        value["actor_epoch"]["user_role"] = "director"
    else:
        value["payload"]["evidence"][0]["documents_hash"] = "f" * 64
    with pytest.raises(ValueError):
        s.checked_snapshot(value, bound)


@pytest.mark.parametrize(
    "section,key,value",
    [
        ("provider_snapshot", "allows_patient_data", False),
        ("provider_snapshot", "allows_patient_data", 1),
        ("provider_snapshot", "api_key", "forbidden"),
        ("provider_snapshot", "temperature", float("nan")),
        ("provider_snapshot", "effective_output_limit", 4097),
        ("provider_snapshot", "provider_id", True),
        ("feature_validation", "validated_at", "2026-10-21T00:00:00Z"),
        ("actor_epoch", "token_invalid_before", "9999-12-31T00:00:00.000000Z"),
    ],
)
def test_missing_original_permission_invalid_clock_numeric_or_extra_credential_is_rejected(section, key, value):
    raw = snapshot()
    raw[section][key] = value
    with pytest.raises(ValueError):
        s.VariableTaskSnapshot.model_validate(raw)


def test_full_run_text_boundary_counts_system_prompt_and_entire_frozen_envelope_without_truncation():
    raw = snapshot()
    size = len(json.dumps(raw, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode())
    raw["task_prompt"] += "x" * (65535 - size)
    value = s.checked_snapshot(raw, original()["binding"])
    assert len(json.dumps(value.model_dump(mode="json"), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()) == 65535
    raw["task_prompt"] += "x"
    with pytest.raises(ValueError):
        s.VariableTaskSnapshot.model_validate(raw)


@pytest.mark.parametrize("counts,attempted", [((None, None), True), ((11, None), True), ((None, 13), True), ((11, 13), True), ((0, 0), False), ((None, None), None)])
def test_legally_missing_or_partial_usage_is_nullable_without_blocking_valid_content(counts, attempted):
    value = s.VariableUsageReceipt(input_tokens=counts[0], output_tokens=counts[1], complete=all(v is not None for v in counts), model_call_attempted=attempted)
    assert (value.input_tokens, value.output_tokens) == counts


@pytest.mark.parametrize(
    "change",
    [
        {"input_tokens": True},
        {"input_tokens": -1},
        {"output_tokens": 2000001},
        {"input_tokens": 0.0},
        {"complete": True},
        {"model_call_attempted": False},
        {"input_tokens": 11, "model_call_attempted": None},
    ],
)
def test_unknown_is_never_filled_with_zero_or_recovered_from_total_counts(change):
    with pytest.raises(ValueError):
        s.VariableUsageReceipt.model_validate({"input_tokens": None, "output_tokens": None, "complete": False, "model_call_attempted": True, **change})


def test_empty_tools_and_full_payload_closed_keys_prevent_generic_or_foreign_scope_fallback():
    for altered in (lambda v: v["payload"].update(tools={"rag": []}), lambda v: v["payload"]["context"]["scope"]["selected_sources"].update(patient_id=1)):
        value = copy.deepcopy(snapshot())
        altered(value)
        with pytest.raises(ValueError):
            s.VariableTaskSnapshot.model_validate(value)
