"""Actual typed public sources; no hospital data, SQL or native model invocation."""

import copy
import json

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.ai.surgery_context import SurgeryContextBinding, binding_for, public_payload, selection, surgery_evidence
from tests.test_ai_surgery_contract import source_dict, uid


def packet():
    source = source_dict()
    return {
        "input": {"surgery_scenario_id": source["scenario_id"], "question": "SYNTH_PRIVATE_CASE_QUESTION"},
        "context": {
            "surgery_source": source,
            "surgery_binding": binding_for(source, pool_id=uid(500), department_id=7),
            "surgery_scenario": {"private_note": "SYNTH_PRIVATE_CASE_NAME", "patient_id": 999},
        },
        "evidence": [{"content": "SYNTH_PRIVATE_EVIDENCE"}],
    }


def test_only_complete_typed_projection_is_outbound_and_local_citation_is_reconstructible():
    data = packet()
    result = public_payload(data)
    assert result == {"context": {"surgery_source": data["context"]["surgery_source"]}}
    text = json.dumps(result)
    assert "SYNTH_PRIVATE" not in text

    def keys(value):
        if isinstance(value, dict):
            return set(value) | set().union(*(keys(item) for item in value.values()))
        if isinstance(value, list):
            return set().union(*(keys(item) for item in value))
        return set()

    assert not {"patient_id", "department_id", "pool_id", "question", "surgery_binding"} & keys(result)
    bound = data["context"]["surgery_binding"]
    evidence = surgery_evidence(bound)
    assert json.loads(evidence["content"]) == {"surgery_binding": bound}
    assert evidence["source_id"] == bound["source_id"]
    assert len(evidence["content"].encode()) < 65535


@pytest.mark.parametrize("key", [name for name in SurgeryContextBinding.model_fields if name not in {"pool_id", "department_id"}])
def test_each_original_public_binding_field_is_checked_before_transport(key):
    data = packet()
    bound = data["context"]["surgery_binding"]
    if key == "revision":
        bound[key] = 1
    elif key == "schema_version":
        bound[key] = "other_v1"
    elif key == "rule_version":
        bound[key] = "2"
    elif key in {"scenario_id", "scope_token", "profile_token"}:
        bound[key] = uid(999)
    else:
        bound[key] = "b" * 64
    with pytest.raises((ValidationError, ValueError)):
        public_payload(data)


@pytest.mark.parametrize("field,value", [("pool_id", True), ("pool_id", "not-a-uuid"), ("department_id", True), ("department_id", 0), ("department_id", 1.5)])
def test_private_scope_identifiers_remain_strict_typed_local_bindings(field, value):
    data = packet()
    data["context"]["surgery_binding"][field] = value
    with pytest.raises(ValidationError):
        public_payload(data)


@pytest.mark.parametrize(
    "values",
    [
        None,
        [],
        {},
        {"surgery_application_id": 1},
        {"surgery_scenario_id": True},
        {"surgery_scenario_id": 1},
        {"surgery_scenario_id": "invalid"},
        {"surgery_scenario_id": uid(100), "objective_mode": "all_required_then_min_declared_cost"},
        {"surgery_scenario_id": uid(100), "department_id": 7},
        {"surgery_scenario_id": uid(100), "case_requirements": []},
        {"surgery_scenario_id": uid(100), "question": True},
        {"surgery_scenario_id": uid(100), "question": "中" * 12001},
    ],
)
def test_local_selection_rejects_legacy_references_scope_or_model_overrides(values):
    with pytest.raises(HTTPException) as failed:
        selection(values)
    assert failed.value.status_code == 422


def test_legal_local_question_never_changes_the_reviewed_objective_or_native_source():
    data = packet()
    before = copy.deepcopy(public_payload(data))
    data["input"]["question"] = "中" * 12000
    assert selection(data["input"]) == uid(100)
    assert public_payload(data) == before
