"""Synthetic declared-stage facts; these times/costs are not clinical defaults."""

import copy
import json
import subprocess
import sys
import uuid

import pytest
from pydantic import ValidationError

from app.ai.surgery_contract import Accounting, Amount, FactRef, Offset, Period, SurgerySource, hash_content, input_policy_digest, recipe_digest


def uid(number):
    return str(uuid.UUID(int=number))


H = hash_content("synthetic-contract-only")
START = "2026-10-21T00:00:00.000000Z"
END = "2026-10-22T00:00:00.000000Z"
RECORDED = "2026-10-20T00:00:00.000000Z"
REF = uid(1)
KINDS = [
    "case_requirements",
    "duration_observation",
    "case_duration_estimate",
    "operating_room_identity_capability",
    "person_identity_qualification",
    "resource_availability_busy",
    "resource_occupation_policy",
    "equipment_identity_capability",
]
ROOM, PERSON, EQUIPMENT, DUTY, CASE = [uid(x) for x in range(10, 15)]


def amount(value="0"):
    return {"value": value, "absent_reason": None if value is not None else "unknown"}


def coverage():
    return {"start_at": "2026-10-01T00:00:00.000000Z", "end_at": "2026-11-01T00:00:00.000000Z", "status": "attested_complete", "basis_hash": H}


def accounting():
    return {"counted_as_work": True, "absent_reason": None, "breaks": [], "breaks_complete": True, "time_accounting_status": "verified"}


def occupation():
    return {
        "segment_ids": ["operation"],
        "occupation_mode": "segments",
        "transition_class_hash": None,
        "transition_class_absent_reason": "not_applicable",
        "accounting": {"counted_as_work": True, "absent_reason": None},
        "basis_hash": H,
    }


def resource(resource_id, kind):
    return {
        "resource_id": resource_id,
        "kind": kind,
        "identity_hash": H,
        "identity_status": "verified",
        "ref_ids": [{"room": uid(4), "person": uid(5), "equipment": uid(8)}[kind]],
        "capability_facts": [
            {
                "ref_ids": [uid(5) if kind == "person" else uid(8)],
                "capability_hashes": [H],
                "status": "verified",
                "valid_from_at": "2026-10-01T00:00:00.000000Z",
                "valid_until": {"kind": "not_applicable", "basis_hash": H},
                "basis_hash": H,
            }
        ]
        if kind in {"person", "equipment"}
        else [],
        "availability": [{"ref_ids": [uid(6)], "start_at": START, "end_at": END, "state": "available", "basis_hash": H}],
        "availability_coverage": coverage(),
        "all_locations_busy_coverage": coverage(),
        "transition_class_coverage": {"status": "attested_complete", "basis_hash": H},
        "transition_policy_review": {"status": "attested_not_required", "basis_hash": H},
        "work_policy_review": {"status": "attested_not_required", "basis_hash": H} if kind == "person" else None,
        "all_locations_duty_coverage": coverage() if kind == "person" else None,
    }


def demand(slot_id, resource_id, person=False):
    return {
        "slot_id": slot_id,
        "capability_hashes": [H] if person else [],
        "occupation": occupation(),
        "domain_status": "attested_complete",
        "choices": [{"resource_id": resource_id, "penalty": amount(), "duty_binding": {"duty_id": DUTY, "status": "verified", "basis_hash": H} if person else None}],
        "basis_hash": H,
    }


def source_dict():
    manifest = [
        {
            "fact_id": uid(index + 1),
            "kind": kind,
            "content_hash": H,
            "governance_hash": H,
            "recorded_at": RECORDED,
            "published_at": RECORDED,
            "status": "published",
            "revision": 1,
            "review": "confirmed",
            "review_basis_hash": H,
        }
        for index, kind in enumerate(KINDS)
    ]
    case = {
        "case_id": CASE,
        "patient_conflict_token": uid(21),
        "patient_identity_status": "verified",
        "procedure_group_hash": H,
        "ref_ids": [REF],
        "required": True,
        "release": {"kind": "known", "at": START},
        "deadline": {"kind": "known", "at": END},
        "start_domain_status": "attested_complete",
        "starts": [{"start_at": "2026-10-21T08:00:00.000001Z", "penalty": amount()}],
        "timing": {
            "method": "reviewed_case_estimate",
            "semantics": "declared_upper_bounds",
            "segments": [{"segment_id": "operation", "start_offset_us": amount(), "end_offset_us": amount("3600000000"), "ref_ids": [uid(3)]}],
            "basis_hash": H,
        },
        "patient_presence": {"segment_ids": ["operation"], "occupation_mode": "segments", "basis_hash": H},
        "room": demand("room", ROOM),
        "roles": [{**demand("surgeon", PERSON, True), "role_kind": "surgeon", "other_role_hash": None}],
        "equipment": [demand("asset_1", EQUIPMENT)],
        "penalty_if_scheduled": amount(),
        "penalty_if_deferred": None,
        "other_requirements": {"status": "all_required_modeled", "basis_hash": H},
    }
    return {
        "schema_version": "surgery_source_v1",
        "scenario_id": uid(100),
        "source_id": f"surgery_scenario:{uid(100)}:{H[:12]}",
        "content_hash": H,
        "governance_hash": H,
        "scope_token": uid(101),
        "original_scope_hash": H,
        "period": {"business_timezone": "Etc/UTC", "date_from": "2026-10-21", "date_to": "2026-10-21", "days": [{"business_date": "2026-10-21", "start_at": START, "end_at": END}]},
        "as_of": RECORDED,
        "captured_at": RECORDED,
        "rule_binding": {
            "rule_id": "surgery_declared_stage_resources_v1",
            "rule_version": "1",
            "profile_token": uid(102),
            "profile_content_hash": H,
            "profile_governance_hash": H,
            "recipe_hash": recipe_digest(),
            "input_policy_hash": input_policy_digest(),
        },
        "objective_mode": "all_required_then_min_declared_cost",
        "collection": {
            "collection_digest": H,
            "case_collection_digest": H,
            "resource_collection_digest": H,
            "busy_collection_digest": H,
            "fact_collection_digest": H,
            "manifest_digest": hash_content(manifest),
        },
        "problem_coverage": {"cases": coverage(), "resources": coverage(), "all_locations_busy": coverage(), "policies": coverage(), "finite_domains_status": "attested_complete", "basis_hash": H},
        "person_partition": {"status": "verified_distinct_groups", "basis_hash": H},
        "manifest": manifest,
        "resources": [resource(ROOM, "room"), resource(PERSON, "person"), resource(EQUIPMENT, "equipment")],
        "busy_intervals": [],
        "duties": [{"start_at": START, "end_at": END, "duty_id": DUTY, "person_id": PERSON, "accounting": accounting(), "ref_ids": [uid(7)], "basis_hash": H}],
        "cases": [case],
        "transition_policies": [],
        "work_policies": [],
    }


def source():
    return SurgerySource.model_validate(source_dict())


def test_exact_complete_projection_preserves_off_grid_zero_false_and_unknown():
    body = source_dict()
    body["duties"][0]["accounting"]["counted_as_work"] = False
    body["cases"][0]["timing"]["segments"][0]["start_offset_us"] = {"value": "-1", "absent_reason": None}
    body["cases"][0]["roles"][0]["choices"][0]["penalty"] = amount(None)
    item = SurgerySource.model_validate(body)
    assert item.model_dump() == body
    assert item.cases[0].starts[0].start_at.endswith("000001Z")
    assert item.duties[0].accounting.counted_as_work is False
    assert item.cases[0].roles[0].choices[0].penalty.value is None


@pytest.mark.parametrize("value", [0, False, 1.0, "-0", "+0", "00", "1e1", "NaN", "9" * 39])
def test_amount_never_coerces_noncanonical_or_oversized_values(value):
    with pytest.raises(ValidationError):
        Amount.model_validate({"value": value, "absent_reason": None})


@pytest.mark.parametrize("patch", [{"value": "0", "absent_reason": "unknown"}, {"value": None, "absent_reason": None}])
def test_quantity_missing_is_explicit(patch):
    with pytest.raises(ValidationError):
        Amount.model_validate(patch)


@pytest.mark.parametrize("value", ["-0", "+1", "01", "-31622400000001"])
def test_offset_exact_pattern_and_independent_technical_cap(value):
    with pytest.raises(ValidationError):
        Offset.model_validate({"value": value, "absent_reason": None})


@pytest.mark.parametrize(
    "mutator",
    [
        lambda s: s.update(source_id=f"surgery_scenario:{uid(100)}:{'a' * 12}"),
        lambda s: s["rule_binding"].update(recipe_hash="a" * 64),
        lambda s: s["collection"].update(manifest_digest="a" * 64),
        lambda s: s["cases"][0].update(required=1),
        lambda s: s["cases"][0].update(penalty_if_deferred=amount()),
        lambda s: s["cases"][0]["starts"].append(copy.deepcopy(s["cases"][0]["starts"][0])),
        lambda s: s["cases"][0]["room"]["occupation"].update(segment_ids=["other_case_segment"]),
        lambda s: s["cases"][0]["roles"][0]["choices"][0].update(resource_id=ROOM),
        lambda s: s["cases"][0]["roles"][0]["choices"][0].update(duty_binding=None),
        lambda s: s["cases"][0]["roles"][0]["choices"][0]["duty_binding"].update(duty_id=uid(999)),
        lambda s: s["cases"][0]["room"]["choices"][0].update(duty_binding={"duty_id": DUTY, "status": "verified", "basis_hash": H}),
        lambda s: s["resources"][0].update(ref_ids=[uid(999)]),
        lambda s: s["resources"][1].update(work_policy_review=None),
        lambda s: s["resources"][0].update(work_policy_review={"status": "unknown", "basis_hash": H}),
        lambda s: s["cases"][0]["timing"].update(method="reviewed_observed_statistic"),
        lambda s: s["cases"][0]["timing"]["segments"][0].update(segment_id="患者姓名"),
    ],
)
def test_actual_source_cross_bindings_fail_closed(mutator):
    body = source_dict()
    mutator(body)
    with pytest.raises(ValidationError):
        SurgerySource.model_validate(body)


def test_duplicate_references_and_unknown_json_fields_rejected():
    body = source_dict()
    body["resources"][0]["ref_ids"] = [REF, REF]
    with pytest.raises(ValidationError):
        SurgerySource.model_validate(body)
    body = source_dict()
    body["cases"][0]["question"] = "private arbitrary narrative"
    with pytest.raises(ValidationError):
        SurgerySource.model_validate(body)


@pytest.mark.parametrize("part", ["identity", "capability"])
def test_equipment_availability_cannot_replace_explicit_equipment_identity_capability(part):
    body = source_dict()
    equipment = body["resources"][2]
    if part == "identity":
        equipment["ref_ids"] = [uid(6)]
    else:
        equipment["capability_facts"][0]["ref_ids"] = [uid(6)]
    with pytest.raises(ValidationError, match="different clinical/operational source kind"):
        SurgerySource.model_validate(body)


def test_raw_reversed_and_zero_segments_survive_for_mathematical_classification():
    body = source_dict()
    segment = body["cases"][0]["timing"]["segments"][0]
    segment["start_offset_us"]["value"], segment["end_offset_us"]["value"] = "2", "1"
    assert SurgerySource.model_validate(body).cases[0].timing.segments[0].end_offset_us.value == "1"
    segment["end_offset_us"]["value"] = "2"
    assert SurgerySource.model_validate(body).cases[0].timing.segments[0].end_offset_us.value == "2"


def test_actual_publication_availability_clock_cannot_be_synthesized():
    row = source_dict()["manifest"][0]
    for patch in ({"published_at": None}, {"published_at": "2026-10-19T00:00:00.000000Z"}):
        with pytest.raises(ValidationError):
            FactRef.model_validate({**row, **patch})
    body = source_dict()
    body["manifest"][0]["published_at"] = "2026-10-20T00:00:00.000001Z"
    body["collection"]["manifest_digest"] = hash_content(body["manifest"])
    with pytest.raises(ValidationError):
        SurgerySource.model_validate(body)


def test_nonusable_roots_remain_manifest_only_instead_of_projecting_unreviewed_required_flags():
    body = source_dict()
    body["manifest"][0]["review"] = "unknown"
    body["collection"]["manifest_digest"] = hash_content(body["manifest"])
    with pytest.raises(ValidationError):
        SurgerySource.model_validate(body)
    body = source_dict()
    body["manifest"][1]["review"] = "excluded"
    body["manifest"][1]["status"] = "revoked"
    body["collection"]["manifest_digest"] = hash_content(body["manifest"])
    assert SurgerySource.model_validate(body).manifest[1].review == "excluded"


@pytest.mark.parametrize("zone,day", [("Unknown/NoHospitalZone", "2026-10-21"), ("Etc/UTC", "9999-12-31"), ("Pacific/Apia", "2011-12-30"), ("America/Havana", "2026-11-01")])
def test_invalid_zone_and_gregorian_and_midnight_anomalies_become_validation_errors(zone, day):
    body = source_dict()["period"]
    body.update(business_timezone=zone, date_from=day, date_to=day)
    body["days"][0]["business_date"] = day
    with pytest.raises(ValidationError):
        Period.model_validate(body)


def test_verified_accounting_requires_actual_false_or_true_and_complete_breaks():
    for patch in ({"breaks_complete": False}, {"counted_as_work": None, "absent_reason": "unknown"}, {"breaks_complete": 0}):
        with pytest.raises(ValidationError):
            Accounting.model_validate({**accounting(), **patch})


def test_public_schema_is_closed_without_loading_hospital_configuration():
    schema = SurgerySource.model_json_schema()
    assert schema["additionalProperties"] is False
    assert all(item.get("additionalProperties") is False for item in schema["$defs"].values() if item.get("type") == "object")
    assert "reviewed_observed_statistic" not in json.dumps(schema)


def test_fresh_process_import_never_reads_dotenv_or_imports_hospital_settings_or_db():
    program = """
import sys
def reject_dotenv(event, args):
    if event == 'open' and isinstance(args[0], str) and args[0].rsplit('/', 1)[-1] == '.env':
        raise AssertionError('dotenv access')
sys.addaudithook(reject_dotenv)
from app.ai.surgery_contract import SurgerySource, SurgeryAnalysis
assert SurgerySource.model_json_schema()['additionalProperties'] is False
assert SurgeryAnalysis.model_json_schema()['additionalProperties'] is False
assert not any(name in sys.modules for name in ['app.config', 'app.database', 'app.models', 'sqlalchemy'])
print('standalone public contract')
"""
    result = subprocess.run([sys.executable, "-c", program], check=True, capture_output=True, text=True, timeout=10)
    assert result.stdout.strip() == "standalone public contract"
