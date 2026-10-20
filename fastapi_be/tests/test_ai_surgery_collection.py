"""Curated operational capsules and complete collection boundaries, isolated SQL."""

import copy

import pytest
from fastapi import HTTPException

from app.ai import surgery_collection as collection
from app.ai import surgery_facts as facts
from tests.test_ai_surgery_facts import NOTE, create, payload, publish, registry, request
from tests.test_ai_surgery_facts import surgery_case as surgery_case


@pytest.mark.parametrize("kind", [kind for kind in facts.SOURCE_KINDS if kind not in facts.CASE_KINDS])
def test_safe_operational_payload_is_exact_typed_and_keeps_no_foreign_free_text_or_staff_ids(kind, surgery_case):
    original = payload(kind, surgery_case)
    if "capability_keys" in original:
        original["capability_keys"] = ["private_capability_key"]
    safe = collection.project_safe_resource_payload(original)
    text = facts.canonical_json(safe)
    assert NOTE not in text and "basis_note" not in text and "user_id" not in text and "doctor_id" not in text and "private_capability_key" not in text
    assert safe["kind"] == kind and safe["basis_hash"] == facts.hash_content(NOTE)
    if "capability_keys" in original:
        assert safe["capability_hashes"] == [facts.hash_content("private_capability_key")]
        assert safe["valid_until"] == {"kind": "unknown", "basis_hash": facts.hash_content(NOTE)}
    if original.get("policy_type") == "work":
        assert safe["minimum_rest"] == {"value": "0", "unit": "min", "absent_reason": None}
        assert safe["max_work_rolling_7d"]["value"] is None and safe["policy_reference_hash"] == facts.hash_content(NOTE)


def test_safe_duty_keeps_false_and_explicit_null_in_original_accounting(surgery_case):
    original = payload("resource_availability_busy", surgery_case)
    original["accounting"]["counted_as_work"] = False
    safe = collection.project_safe_resource_payload(original)
    assert safe["accounting"]["counted_as_work"] is False and safe["accounting"]["absent_reason"] is None
    assert safe["accounting"]["breaks"] == [] and safe["accounting"]["breaks_complete"] is True


def test_case_payload_cannot_be_relabelled_as_a_safe_resource(surgery_case):
    with pytest.raises(ValueError):
        collection.project_safe_resource_payload(payload("case_duration_estimate", surgery_case))


@pytest.mark.parametrize("kind", ["person_identity_qualification", "resource_availability_busy", "resource_occupation_policy"])
def test_actual_global_shared_resource_facts_are_safe_across_foreign_pool_and_bind_exact_hash(db_session, surgery_case, kind):
    case = surgery_case
    pool = registry(db_session, case["super"], {"kind": "pool", "department_id": case["foreign"].department_id, "name": "合成共享人员外池", "basis_note": NOTE})
    resource_id = case["resources"]["person"].resource_id
    registry(db_session, case["super"], {"kind": "pool_membership", "pool_id": pool.pool_id, "resource_id": resource_id, "basis_note": NOTE})
    values = request(case, kind)
    values["pool_id"] = pool.pool_id
    row = facts.create_source(db_session, case["foreign_user"], kind, values)
    db_session.commit()
    publish(db_session, case, row)
    with pytest.raises(HTTPException) as error:
        facts.source_current(db_session, case["director"], kind, row.source_record_id)
    assert error.value.status_code == 403
    safe = collection.safe_resource_original_current(db_session, case["director"], resource_id, row.source_record_id, case["pool"].pool_id)
    assert safe["eligible_for_new_use"] and not safe["redacted"]
    assert facts.hash_content({key: value for key, value in safe.items() if key != "capsule_hash"}) == safe["capsule_hash"]
    encoded = facts.canonical_json(safe)
    assert all(key not in encoded for key in ("pool_id", "department_id", "patient_id", "admission_id", "doctor_id", "user_id", "basis_note", NOTE))
    if kind == "resource_occupation_policy":
        assert '"policy_reference":' not in encoded
    old = copy.deepcopy(safe)
    facts.review_source(db_session, case["super"], kind, row.source_record_id, {"expected_revision": 2, "expected_content_hash": row.content_hash, "basis_note": NOTE}, revoke=True)
    db_session.commit()
    revoked = collection.safe_resource_original_current(db_session, case["director"], resource_id, row.source_record_id, case["pool"].pool_id)
    assert revoked["redacted"] and revoked["payload"] is None and not revoked["eligible_for_new_use"]
    assert revoked["source_content_hash"] == old["source_content_hash"] and revoked["capsule_hash"] != old["capsule_hash"]


def test_even_super_does_not_restore_unpublished_resource_raw_body_through_capture_capsule(db_session, surgery_case):
    case = surgery_case
    row = create(db_session, case, "person_identity_qualification")
    safe = collection.safe_resource_original_current(db_session, case["super"], row.resource_id, row.source_record_id, case["pool"].pool_id)
    assert safe["payload"] is None and safe["redacted"] and safe["status"] == "draft"
