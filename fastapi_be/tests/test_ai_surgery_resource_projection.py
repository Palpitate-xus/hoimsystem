"""Actual SQL resource originals and disclosed capsules retain exact native facts."""

import copy
import json

import pytest

from app.ai import surgery_facts as facts
from app.ai.surgery_collection import safe_resource_original_current
from app.ai.surgery_models import AISurgeryPoolMembership
from app.ai.surgery_projection import PublicIdentity, project_resource, public_operational_fact, verified_safe_resource
from app.ai.surgery_scenario_input import ResourceDeclaration
from tests.test_ai_surgery_facts import NOTE, accounting, amount, publish, request
from tests.test_ai_surgery_facts import surgery_case as surgery_case

START, END = "2026-10-20T00:00:00.000000Z", "2026-11-01T00:00:00.000000Z"


@pytest.fixture
def resource_case(db_session, surgery_case):
    case = surgery_case
    values = {}
    for kind, fact_kind in (("room", "operating_room_identity_capability"), ("person", "person_identity_qualification"), ("equipment", "equipment_identity_capability")):
        rid = case["resources"][kind].resource_id
        original_requests = [request(case, fact_kind)]
        original_requests[0]["payload"]["capability_keys"] = ["patient_private_capability"]
        original_requests.append(
            {
                **request(case, "resource_availability_busy"),
                "resource_id": rid,
                "payload": {"kind": "resource_availability_busy", "record_type": "availability", "start_at": START, "end_at": END, "state": "unknown", "basis_note": NOTE},
            }
        )
        if kind == "person":
            duty = request(case, "resource_availability_busy")
            duty["payload"]["accounting"]["counted_as_work"] = False
            original_requests.extend([duty, request(case, "resource_occupation_policy")])
        if kind == "room":
            original_requests.append(
                {
                    **request(case, "resource_occupation_policy"),
                    "resource_id": rid,
                    "payload": {
                        "kind": "resource_occupation_policy",
                        "policy_type": "transition",
                        "effective_from_at": START,
                        "effective_until": {"kind": "known", "at": END},
                        "pairs": [{"from_class_key": "patient_private_from", "to_class_key": "patient_private_to", "minimum_gap_us": amount("0"), "penalty": amount(None), "basis_note": NOTE}],
                        "pair_coverage": "attested_complete",
                        "basis_note": NOTE,
                    },
                }
            )
            original_requests.append(
                {
                    **request(case, "resource_availability_busy"),
                    "resource_id": rid,
                    "payload": {
                        "kind": "resource_availability_busy",
                        "record_type": "busy_capsule",
                        "start_at": START,
                        "end_at": None,
                        "end_absent_reason": "ongoing_unknown_end",
                        "verified_until_at": None,
                        "continuity_status": "unknown",
                        "busy_status": "committed",
                        "transition_class_key": "patient_private_from",
                        "transition_class_absent_reason": None,
                        "accounting": accounting(),
                        "basis_code": "explicit_local_operational_observation",
                        "basis_hash": facts.hash_content(NOTE),
                        "protected_witness_hash": None,
                    },
                }
            )
        capsules = []
        for body in original_requests:
            row = facts.create_source(db_session, case["director"], body["payload"]["kind"], body)
            db_session.commit()
            publish(db_session, case, row)
            capsules.append(safe_resource_original_current(db_session, case["director"], rid, row.source_record_id, case["pool"].pool_id))
        member = db_session.query(AISurgeryPoolMembership).filter_by(pool_id=case["pool"].pool_id, resource_id=rid, status="published").one()
        coverage = {"start_at": START, "end_at": END, "status": "attested_complete", "basis_note": NOTE}
        declaration = ResourceDeclaration(
            resource_id=rid,
            expected_resource_hash=case["resources"][kind].content_hash,
            expected_membership_id=member.membership_id,
            expected_membership_hash=member.content_hash,
            expected_membership_governance_hash=facts.hash_content(facts.governance_fields(member)),
            availability_coverage=coverage,
            all_locations_busy_coverage=coverage,
            transition_class_status="unknown",
            transition_policy_review={"status": "reviewed_policies" if kind == "room" else "attested_not_required", "basis_note": NOTE},
            work_policy_review={"status": "reviewed_policies", "basis_note": NOTE} if kind == "person" else None,
            all_locations_duty_coverage=coverage if kind == "person" else None,
            basis_note=NOTE,
        )
        members = {
            item["source_record_id"]: {
                "source_record_id": item["source_record_id"],
                "source_kind": item["source_kind"],
                "expected_content_hash": item["source_content_hash"],
                "expected_governance_hash": item["source_governance_hash"],
                "selection": "confirmed",
                "basis_note": NOTE,
            }
            for item in capsules
        }
        values[kind] = {
            "resource_id": rid,
            "kind": kind,
            "original_identity_hash": case["resources"][kind].content_hash,
            "declaration": declaration,
            "capsules": capsules,
            "members": members,
            "identities": PublicIdentity("5" * 64),
        }
    return values, case


def test_actual_resource_duty_busy_and_both_policy_projection_preserve_unknown_zero_false_and_hmac_domain(resource_case):
    values, _ = resource_case
    projected = {kind: project_resource(**value) for kind, value in values.items()}
    for kind, result in projected.items():
        assert result["issues"] == [] and result["resource"].kind == kind
        assert result["resource"].identity_status == "unknown"
        assert result["resource"].availability[0].state == "unknown"
        assert result["resource"].capability_facts[0].capability_hashes == [values[kind]["identities"].hashed_key("capability", "patient_private_capability")]
        serialized = json.dumps({key: [item.model_dump() for item in value] if isinstance(value, list) else value.model_dump() for key, value in result.items() if key != "issues"})
        assert "patient_private" not in serialized and NOTE not in serialized and values[kind]["resource_id"] not in serialized
        assert '"user_id"' not in serialized and '"doctor_id"' not in serialized
    assert projected["person"]["duties"][0].accounting.counted_as_work is False
    assert projected["person"]["work_policies"][0].minimum_rest.value == "0"
    assert projected["person"]["work_policies"][0].max_work_rolling_24h.value is None
    pair = projected["room"]["transition_policies"][0].pairs[0]
    assert pair.minimum_gap_us.value == "0" and pair.penalty.value is None
    assert pair.from_class_hash == projected["room"]["busy_intervals"][0].transition_class_hash
    busy = projected["room"]["busy_intervals"][0]
    assert busy.end_at is None and busy.end_absent_reason == "ongoing_unknown_end" and busy.busy_status == "committed"


@pytest.mark.parametrize("change", ["payload", "member_source", "member_hash", "foreign_resource", "wrong_kind", "partial_work", "duplicate"])
def test_capsule_sha_member_identity_and_physical_kind_are_checked_before_public_resource(change, resource_case):
    values, _ = resource_case
    value = copy.deepcopy(values["room"])
    if change == "payload":
        value["capsules"][0]["payload"]["identity_status"] = "verified"
    elif change == "member_source":
        value["members"][value["capsules"][0]["source_record_id"]]["source_record_id"] = values["person"]["capsules"][0]["source_record_id"]
    elif change == "member_hash":
        value["members"][value["capsules"][0]["source_record_id"]]["expected_content_hash"] = "0" * 64
    elif change == "foreign_resource":
        value["capsules"].append(values["person"]["capsules"][0])
    elif change == "wrong_kind":
        value["kind"] = "equipment"
    elif change == "partial_work":
        value["declaration"].work_policy_review = values["person"]["declaration"].work_policy_review
    else:
        value["capsules"].append(copy.deepcopy(value["capsules"][0]))
    if change == "wrong_kind":
        assert project_resource(**value)["resource"] is None
    else:
        with pytest.raises(ValueError):
            project_resource(**value)


def test_current_contrary_original_cannot_be_omitted_to_prove_resource_complete(resource_case):
    values, _ = resource_case
    value = copy.deepcopy(values["room"])
    value["members"][value["capsules"][1]["source_record_id"]]["selection"] = "excluded"
    result = project_resource(**value)
    assert result["resource"] is None and result["issues"] == ["current_resource_original_not_confirmed"]


def test_public_fact_verifies_complete_disclosed_capsule_without_claiming_hidden_raw_sha_reconstruction(resource_case):
    values, _ = resource_case
    value = values["equipment"]
    capsule = value["capsules"][0]
    original = verified_safe_resource(capsule)
    fact = public_operational_fact(capsule, value["members"][capsule["source_record_id"]], value["identities"], "2026-10-20T12:00:01.000000Z")
    assert fact.kind == "equipment_identity_capability" and fact.content_hash == original.source_content_hash
    assert fact.fact_id != original.source_record_id and original.capsule_hash != original.source_content_hash
    bad = copy.deepcopy(capsule)
    bad["payload"]["capability_status"] = "verified"
    with pytest.raises(ValueError):
        verified_safe_resource(bad)
