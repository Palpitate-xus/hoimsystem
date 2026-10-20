"""Actual governed SQL captures projected and checked by the native solver."""

import copy
import uuid

import pytest

from app.ai import surgery_collection as collection
from app.ai import surgery_facts as facts
from app.ai.surgery_config import runtime_descriptor, runtime_from_descriptor
from app.ai.surgery_contract import SurgerySource, canonical_json, hash_content
from app.ai.surgery_model import compute_surgery
from app.ai.surgery_projection import PublicIdentity
from app.ai.surgery_snapshot import build_snapshot, capture_request, project_snapshot, verify_snapshot
from tests.test_ai_surgery_collection import capture_request as collection_request
from tests.test_ai_surgery_facts import NOTE, amount, publish, request
from tests.test_ai_surgery_facts import surgery_case as surgery_case

START = "2026-10-20T00:00:00.000000Z"
END = "2026-10-23T00:00:00.000000Z"


def declaration_for(captured):
    coverage = {"start_at": START, "end_at": END, "status": "attested_complete", "basis_note": NOTE}
    policy = {"status": "attested_not_required", "basis_note": NOTE}
    meta = {item["source_kind"]: item for item in captured["member_manifest"]}

    def reference(kind):
        item = meta[kind]
        return {"source_record_id": item["source_record_id"], "expected_content_hash": item["content_hash"], "expected_governance_hash": item["governance_hash"]}

    room = next(item for item in captured["resources"] if item["resource_kind"] == "room")
    return {
        "pool_id": captured["pool"]["pool_id"],
        "period": captured["request"]["period"],
        "expected_capture_digest": captured["collection_digest"],
        "objective_mode": "all_required_then_min_declared_cost",
        "problem_coverage": {**{key: copy.deepcopy(coverage) for key in ("cases", "resources", "all_locations_busy", "policies")}, "finite_domains_status": "attested_complete", "basis_note": NOTE},
        "person_partition": {
            "status": "verified_distinct_groups",
            "resource_ids": sorted(item["resource_id"] for item in captured["resources"] if item["resource_kind"] == "person"),
            "basis_note": NOTE,
        },
        "members": [
            {
                "source_record_id": item["source_record_id"],
                "source_kind": item["source_kind"],
                "expected_content_hash": item["content_hash"],
                "expected_governance_hash": item["governance_hash"],
                "selection": "confirmed" if item["eligible_for_new_use"] else "excluded",
                "basis_note": NOTE,
            }
            for item in captured["member_manifest"]
        ],
        "resources": [
            {
                "resource_id": item["resource_id"],
                "expected_resource_hash": item["content_hash"],
                "expected_membership_id": item["membership"]["membership_id"],
                "expected_membership_hash": item["membership"]["content_hash"],
                "expected_membership_governance_hash": item["membership"]["governance_hash"],
                "availability_coverage": copy.deepcopy(coverage),
                "all_locations_busy_coverage": copy.deepcopy(coverage),
                "transition_class_status": "attested_complete",
                "transition_policy_review": policy,
                "work_policy_review": policy if item["resource_kind"] == "person" else None,
                "all_locations_duty_coverage": copy.deepcopy(coverage) if item["resource_kind"] == "person" else None,
                "basis_note": NOTE,
            }
            for item in captured["resources"]
        ],
        "cases": [
            {
                "application_id": captured["cases"][0]["application_id"],
                "requirements": reference("case_requirements"),
                "duration_estimate": reference("case_duration_estimate"),
                "start_domain_status": "attested_complete",
                "starts": [{"start_at": "2026-10-21T08:00:00.000001Z", "penalty": amount("0")}],
                "room": {
                    "slot_id": "room",
                    "domain_status": "attested_complete",
                    "choices": [{"resource_id": room["resource_id"], "penalty": amount("0"), "duty_source": None, "duty_binding_status": None, "duty_basis_note": None}],
                    "basis_note": NOTE,
                },
                "roles": [],
                "equipment": [],
                "penalty_if_scheduled": amount("0"),
                "penalty_if_deferred": None,
                "basis_note": NOTE,
            }
        ],
        "basis_note": NOTE,
    }


@pytest.fixture
def snapshot_case(db_session, surgery_case):
    case = surgery_case
    for kind in ("case_requirements", "case_duration_estimate", "operating_room_identity_capability", "person_identity_qualification", "equipment_identity_capability"):
        body = request(case, kind)
        payload = body["payload"]
        if kind == "case_requirements":
            payload.update(
                required=True,
                required_absent_reason=None,
                procedure_group_key="patient_private_procedure",
                procedure_group_absent_reason=None,
                release={"kind": "known", "at": START},
                deadline={"kind": "known", "at": END},
                other_requirements_status="attested_not_required",
            )
            payload["room"]["occupation"].update(transition_class_absent_reason="not_applicable", counted_as_work=True, counted_as_work_absent_reason=None)
        elif kind == "case_duration_estimate":
            payload["segments"][0]["end_offset_us"] = amount("60000000")
        else:
            payload.update(identity_status="verified", valid_from_at=START, valid_until={"kind": "known", "at": END})
            payload["qualification_status" if kind == "person_identity_qualification" else "capability_status"] = "verified"
        actor = case["doctor_user"] if kind in facts.CASE_KINDS else case["director"]
        row = facts.create_source(db_session, actor, kind, body)
        db_session.commit()
        publish(db_session, case, row)
    for resource in case["resources"].values():
        body = request(case, "resource_availability_busy")
        body.update(
            resource_id=resource.resource_id, payload={"kind": "resource_availability_busy", "record_type": "availability", "start_at": START, "end_at": END, "state": "available", "basis_note": NOTE}
        )
        row = facts.create_source(db_session, case["director"], "resource_availability_busy", body)
        db_session.commit()
        publish(db_session, case, row)
    captured = collection.capture_input(db_session, case["director"], collection_request(case))
    declaration = declaration_for(captured)
    snapshot = build_snapshot(declaration, captured, scenario_id=str(uuid.uuid4()), created_by=case["director"].user_id)
    return snapshot, captured, declaration, case


def native(source):
    return compute_surgery(SurgerySource.model_validate(source), "1" * 64, runtime_from_descriptor(runtime_descriptor())).model_dump(mode="json")


def test_actual_complete_capture_proves_only_declared_synthetic_problem_and_sends_no_private_body(snapshot_case):
    snapshot, captured, declaration, case = snapshot_case
    assert capture_request(declaration).model_dump(mode="json") == captured["request"]
    projected = project_snapshot(snapshot, "2" * 64)
    source = projected["source"]
    assert projected["issues"] == [] and len(source["resources"]) == 3 and len(source["cases"]) == 1 and len(source["manifest"]) == 8
    assert source["collection"]["manifest_digest"] == hash_content(source["manifest"]) != captured["private_manifest_digest"]
    assert source["content_hash"] == hash_content(snapshot) and source["rule_binding"]["profile_content_hash"] == hash_content(snapshot["rule_profile"])
    encoded = canonical_json(source)
    assert all(value not in encoded for value in (NOTE, snapshot["identity_secret"], case["application"].application_id, case["pool"].pool_id, "patient_private_procedure"))
    assert all('"' + key + '":' not in encoded for key in ("patient_id", "user_id", "doctor_id", "department_id", "application_id", "basis_note"))
    result = native(source)
    assert result["solve_status"] == "optimal_proven" and result["scope_status"] == "closed_declared_problem"
    assert result["automatic_booking"] is False and result["forecast_or_clinical_guarantee"] == "not_provided"


@pytest.mark.parametrize(
    "change",
    ["source_omitted", "source_unknown", "source_sha", "membership", "resource_omitted", "person_partition", "profile_recipe", "private_clock", "late_root", "capture_digest", "extra_snapshot"],
)
def test_whole_original_identity_review_cohort_clocks_and_recipe_cannot_be_substituted(change, snapshot_case):
    snapshot, _, _, _ = snapshot_case
    value = copy.deepcopy(snapshot)
    if change == "source_omitted":
        value["request"]["members"].pop()
    elif change == "source_unknown":
        value["request"]["members"][0]["source_kind"] = "duration_observation"
    elif change == "source_sha":
        value["collection"]["source_records"][0]["metadata"]["content_hash"] = "0" * 64
    elif change == "membership":
        value["request"]["resources"][0]["expected_membership_hash"] = "0" * 64
    elif change == "resource_omitted":
        value["request"]["resources"].pop()
    elif change == "person_partition":
        value["request"]["person_partition"]["resource_ids"] = []
    elif change == "profile_recipe":
        value["rule_profile"]["recipe"]["fabricated"] = True
    elif change == "private_clock":
        value["captured_at"] = "2026-10-20T01:00:00.000000Z"
    elif change == "late_root":
        value["collection"]["max_available_at"] = "2026-10-21T01:00:00.000000Z"
    elif change == "capture_digest":
        value["collection"]["collection_digest"] = "0" * 64
    else:
        value["unreviewed"] = True
    with pytest.raises(ValueError):
        verify_snapshot(value, validate_current_recipe=True)


def test_concrete_legacy_gap_cannot_be_removed_by_all_coverage_attestations(snapshot_case):
    _, captured, declaration, case = snapshot_case
    captured = copy.deepcopy(captured)
    captured["known_gaps"] = [{"code": "legacy_patient_busy_not_curated", "commitment": hash_content("synthetic uncurated original")}]
    captured["busy_collection_digest"] = hash_content(
        {"gaps": captured["known_gaps"], "sources": [item for item in captured["source_records"] if item["metadata"]["source_kind"] == "resource_availability_busy"]}
    )
    captured["collection_digest"] = hash_content({key: value for key, value in captured.items() if key not in {"captured_at", "collection_digest"}})
    declaration = copy.deepcopy(declaration)
    declaration["expected_capture_digest"] = captured["collection_digest"]
    snapshot = build_snapshot(declaration, captured, scenario_id=str(uuid.uuid4()), created_by=case["director"].user_id)
    projected = project_snapshot(snapshot, "3" * 64)
    assert projected["issues"][0]["code"] == "legacy_patient_busy_not_curated"
    assert all(projected["source"]["problem_coverage"][name]["status"] == "unknown" for name in ("cases", "resources", "all_locations_busy", "policies"))
    assert native(projected["source"])["solve_status"] == "input_unknown"


def test_current_excluded_resource_original_cannot_silently_remove_a_contrary_fact(snapshot_case):
    snapshot, _, _, _ = snapshot_case
    value = copy.deepcopy(snapshot)
    selected = next(item for item in value["request"]["members"] if item["source_kind"] == "operating_room_identity_capability")
    selected["selection"] = "excluded"
    result = project_snapshot(value, "4" * 64)
    assert {item["code"] for item in result["issues"]} == {"current_resource_original_not_confirmed", "case_choice_resource_not_projectable"}
    assert len(result["source"]["resources"]) == 2 and result["source"]["cases"] == []
    assert native(result["source"])["solve_status"] == "input_unknown"


def test_actual_case_person_choice_uses_safe_duty_capsule_without_foreign_account_body(snapshot_case, db_session):
    snapshot, _, _, case = snapshot_case
    duty_body = request(case, "resource_availability_busy")
    duty_body["payload"].update(start_at="2026-10-21T00:00:00.000000Z", end_at=END)
    duty_body["payload"]["accounting"]["counted_as_work"] = False
    duty = facts.create_source(db_session, case["director"], "resource_availability_busy", duty_body)
    db_session.commit()
    publish(db_session, case, duty)
    old = next(item["original"] for item in snapshot["collection"]["source_records"] if item["metadata"]["source_kind"] == "case_requirements")
    requirement_body = request(case, "case_requirements")
    requirement_body["payload"] = copy.deepcopy(old["payload"])
    role = copy.deepcopy(old["payload"]["room"])
    role.update(slot_id="patient_private_surgeon", role_kind="surgeon", other_role_key=None)
    requirement_body["payload"]["roles"] = [role]
    requirement = facts.create_source(db_session, case["doctor_user"], "case_requirements", requirement_body)
    db_session.commit()
    publish(db_session, case, requirement)
    captured = collection.capture_input(db_session, case["director"], collection_request(case))
    declaration = declaration_for(captured)
    refs = {
        item["source_record_id"]: {"source_record_id": item["source_record_id"], "expected_content_hash": item["content_hash"], "expected_governance_hash": item["governance_hash"]}
        for item in captured["member_manifest"]
    }
    declaration["cases"][0]["requirements"] = refs[requirement.source_record_id]
    declaration["cases"][0]["roles"] = [
        {
            "slot_id": role["slot_id"],
            "domain_status": "attested_complete",
            "basis_note": NOTE,
            "choices": [{"resource_id": duty.resource_id, "penalty": amount("0"), "duty_source": refs[duty.source_record_id], "duty_binding_status": "verified", "duty_basis_note": NOTE}],
        }
    ]
    frozen = build_snapshot(declaration, captured, scenario_id=str(uuid.uuid4()), created_by=case["director"].user_id)
    result = project_snapshot(frozen, "5" * 64)
    assert not result["issues"]
    public = result["source"]
    assert public["cases"][0]["roles"][0]["choices"][0]["duty_binding"]["duty_id"] == public["duties"][0]["duty_id"]
    assert public["duties"][0]["accounting"]["counted_as_work"] is False
    assert "patient_private_surgeon" not in canonical_json(public)
    wrong = copy.deepcopy(frozen)
    wrong["request"]["cases"][0]["roles"][0]["choices"][0]["resource_id"] = case["resources"]["room"].resource_id
    with pytest.raises(ValueError, match="different actual person"):
        project_snapshot(wrong, "5" * 64)


def test_multiple_actual_identity_originals_are_all_kept_with_canonical_public_refs(snapshot_case, db_session):
    original_snapshot, _, _, case = snapshot_case
    body = request(case, "operating_room_identity_capability")
    body["payload"] = copy.deepcopy(
        next(item["capsule"]["payload"] for item in original_snapshot["collection"]["source_records"] if item["metadata"]["source_kind"] == "operating_room_identity_capability")
    )
    # Source payloads retain original basis/key text; safe capsule hashes cannot
    # be submitted back as though they were the undisclosed original text.
    body["payload"].pop("basis_hash")
    body["payload"].pop("capability_hashes")
    body["payload"].update(basis_note=NOTE, capability_keys=[])
    row = facts.create_source(db_session, case["director"], "operating_room_identity_capability", body)
    db_session.commit()
    publish(db_session, case, row)
    captured = collection.capture_input(db_session, case["director"], collection_request(case))
    frozen = build_snapshot(declaration_for(captured), captured, scenario_id=str(uuid.uuid4()), created_by=case["director"].user_id)
    originals = [item["metadata"]["source_record_id"] for item in captured["source_records"] if item["metadata"]["source_kind"] == "operating_room_identity_capability"]
    assert len(originals) == 2
    # Select an actual private key for which source UUID order and public UUID
    # order differ, so the test always exercises the canonicalization boundary.
    for index in range(256):
        secret = f"{index:064x}"
        refs = [PublicIdentity(secret).uuid("fact", key) for key in originals]
        if refs != sorted(refs):
            frozen["identity_secret"] = secret
            break
    else:
        pytest.fail("No reversed two-original identity mapping found")
    projected = project_snapshot(frozen, "6" * 64)["source"]
    room = next(item for item in projected["resources"] if item["kind"] == "room")
    assert room["ref_ids"] == sorted(refs) and len(room["capability_facts"]) == 2
    assert native(projected)["solve_status"] == "optimal_proven"


@pytest.mark.parametrize("change", ["empty_registry", "registry_membership_governance", "patient_parent", "clinical_parent"])
def test_internally_conflicting_parent_or_registry_is_rejected_even_after_all_collection_hashes_are_replaced(snapshot_case, change):
    snapshot, _, _, _ = snapshot_case
    value = copy.deepcopy(snapshot)
    captured = value["collection"]
    if change == "empty_registry":
        captured["registry_manifest"] = []
    elif change == "registry_membership_governance":
        next(item for item in captured["registry_manifest"] if item["registry_kind"] == "pool_membership")["governance_hash"] = "0" * 64
    elif change == "patient_parent":
        captured["cases"][0]["patient_id"] += 1
    else:
        captured["cases"][0]["clinical_content_hash"] = "0" * 64
    captured["case_collection_digest"] = hash_content(captured["cases"])
    captured["resource_collection_digest"] = hash_content({"resources": captured["resources"], "registry_manifest": captured["registry_manifest"]})
    captured["collection_digest"] = hash_content({key: item for key, item in captured.items() if key not in {"captured_at", "collection_digest"}})
    value["collection_digest"] = value["request"]["expected_capture_digest"] = captured["collection_digest"]
    with pytest.raises(ValueError, match="registry|clinical parent"):
        verify_snapshot(value)
