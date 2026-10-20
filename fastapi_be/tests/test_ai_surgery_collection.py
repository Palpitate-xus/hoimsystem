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


def capture_request(case):
    from tests.test_ai_surgery_facts import NOW

    return {
        "pool_id": case["pool"].pool_id,
        "period": {"business_timezone": "Asia/Shanghai", "date_from": "2026-10-21", "date_to": "2026-10-21", "as_of": facts.utc_text(NOW)},
        "application_ids": [case["application"].application_id],
    }


def complete_originals(db, case):
    return [publish(db, case, create(db, case, kind)) for kind in facts.SOURCE_KINDS]


def test_actual_capture_keeps_all_eight_originals_unknowns_and_actor_independent_digest(db_session, surgery_case):
    case = surgery_case
    complete_originals(db_session, case)
    values = capture_request(case)
    actual = collection.capture_input(db_session, case["director"], values)
    audit = collection.capture_input(db_session, case["super"], values)
    assert actual["collection_digest"] == audit["collection_digest"]
    assert len(actual["cases"]) == 1 and len(actual["resources"]) == 3 and len(actual["member_manifest"]) == 8
    assert len({item["source_record_id"] for item in actual["member_manifest"]}) == 8
    assert actual["as_of"] == values["period"]["as_of"] and not actual["known_gaps"]
    for record in actual["source_records"]:
        if record["metadata"]["source_kind"] in facts.CASE_KINDS:
            assert record["original"] is not None and record["capsule"] is None
            item = record["original"]
            body = {key: item[key] for key in facts.SourceFrozenIdentity.model_fields}
            body.update(payload=item["payload"], parent_binding=item["parent_binding"])
            assert facts.hash_content(body) == item["content_hash"]
        else:
            assert record["original"] is None and record["capsule"]["eligible_for_new_use"]
    equipment = next(item["capsule"] for item in actual["source_records"] if item["metadata"]["source_kind"] == "equipment_identity_capability")
    assert equipment["payload"]["capability_status"] == "unknown" and equipment["payload"]["capability_hashes"] == []
    assert actual["period"]["days"] == [{"business_date": "2026-10-21", "start_at": "2026-10-20T16:00:00.000000Z", "end_at": "2026-10-21T16:00:00.000000Z"}]


def test_case_cohort_is_explicit_sorted_distinct_and_ops_does_not_replace_actual_care(db_session, surgery_case):
    import uuid

    from pydantic import ValidationError

    case = surgery_case
    values = capture_request(case)
    duplicate = copy.deepcopy(values)
    duplicate["application_ids"] *= 2
    with pytest.raises(ValidationError):
        collection.CaptureRequest.model_validate(duplicate)
    reversed_ids = sorted([values["application_ids"][0], str(uuid.uuid4())], reverse=True)
    with pytest.raises(ValidationError):
        collection.CaptureRequest.model_validate({**values, "application_ids": reversed_ids})
    # Being an authorized Pool member/admin is not patient-care authority.
    from app.models import User

    outsider = case["seed"]["admin_user"]
    registry(db_session, case["super"], {"kind": "person_account", "resource_id": case["resources"]["person"].resource_id, "user_id": outsider.user_id, "basis_note": NOTE})
    assert db_session.query(User).filter_by(user_id=outsider.user_id).one().user_role == "admin"
    with pytest.raises(HTTPException) as error:
        collection.capture_input(db_session, outsider, values)
    assert error.value.status_code == 403
    with pytest.raises(HTTPException) as error:
        collection.capture_input(db_session, case["doctor_user"], values)
    assert error.value.status_code == 403


def test_case_wrong_original_department_and_admission_patient_are_rejected(db_session, surgery_case):
    case = surgery_case
    case["admission"].department_id = case["foreign"].department_id
    db_session.commit()
    with pytest.raises(HTTPException) as error:
        collection.capture_input(db_session, case["super"], capture_request(case))
    assert error.value.status_code == 403
    case["admission"].department_id = case["department"].department_id
    case["admission"].patient_id = case["patient"].patient_id + 100000
    db_session.commit()
    with pytest.raises(HTTPException) as error:
        collection.capture_input(db_session, case["super"], capture_request(case))
    assert error.value.status_code in {404, 409}


def test_complete_capture_has_no_latest_selection_and_same_count_different_row_changes_digest(db_session, surgery_case):
    case = surgery_case
    row = publish(db_session, case, create(db_session, case))
    first = collection.capture_input(db_session, case["director"], capture_request(case))
    another = publish(db_session, case, create(db_session, case))
    second = collection.capture_input(db_session, case["director"], capture_request(case))
    assert {item["source_record_id"] for item in second["member_manifest"]} == {row.source_record_id, another.source_record_id}
    assert first["collection_digest"] != second["collection_digest"]
    # Same number of relevant roots; different technical original cannot collide.
    db_session.delete(another)
    db_session.commit()
    third = collection.capture_input(db_session, case["director"], capture_request(case))
    replacement = publish(db_session, case, create(db_session, case))
    db_session.delete(row)
    db_session.commit()
    fourth = collection.capture_input(db_session, case["director"], capture_request(case))
    assert len(third["member_manifest"]) == len(fourth["member_manifest"]) == 1
    assert fourth["member_manifest"][0]["source_record_id"] == replacement.source_record_id
    assert third["collection_digest"] != fourth["collection_digest"]


def test_revoked_draft_and_rejected_originals_are_metadata_only_even_in_super_capture(db_session, surgery_case):
    case = surgery_case
    draft = create(db_session, case)
    rejected = publish(db_session, case, create(db_session, case), decision="reject")
    revoked = publish(db_session, case, create(db_session, case))
    facts.review_source(
        db_session, case["super"], revoked.source_kind, revoked.source_record_id, {"expected_revision": 2, "expected_content_hash": revoked.content_hash, "basis_note": NOTE}, revoke=True
    )
    db_session.commit()
    actual = collection.capture_input(db_session, case["super"], capture_request(case))
    assert {item["metadata"]["status"] for item in actual["source_records"]} == {"draft", "rejected", "revoked"}
    assert {item["metadata"]["source_record_id"] for item in actual["source_records"]} == {draft.source_record_id, rejected.source_record_id, revoked.source_record_id}
    for record in actual["source_records"]:
        assert record["original"] is None and record["governance"] is None and record["capsule"] is None
        assert NOTE not in facts.canonical_json(record)


def test_own_bad_body_is_not_hidden_by_revocation_or_super_capture(db_session, surgery_case):
    case = surgery_case
    row = create(db_session, case)
    row.content_hash = "0" * 64
    db_session.commit()
    with pytest.raises(HTTPException) as error:
        collection.capture_input(db_session, case["super"], capture_request(case))
    assert error.value.status_code == 409


def test_late_root_preview_is_complete_but_capture_requires_refreshed_actual_cutoff(db_session, surgery_case, monkeypatch):
    import datetime

    from tests.test_ai_surgery_facts import NOW

    case = surgery_case
    old = collection.capture_input(db_session, case["director"], capture_request(case))
    monkeypatch.setattr(facts, "utcnow", lambda: NOW + datetime.timedelta(seconds=2))
    late = publish(db_session, case, create(db_session, case))
    preview = collection.preview_input(db_session, case["director"], capture_request(case))
    assert preview["max_available_at"] == facts.utc_text(NOW + datetime.timedelta(seconds=2))
    assert preview["collection_digest"] != old["collection_digest"] and preview["member_manifest"][0]["source_record_id"] == late.source_record_id
    with pytest.raises(HTTPException) as error:
        collection.capture_input(db_session, case["director"], capture_request(case))
    assert error.value.status_code == 409
    refreshed = capture_request(case)
    refreshed["period"]["as_of"] = preview["max_available_at"]
    assert collection.capture_input(db_session, case["director"], refreshed)["as_of"] == refreshed["period"]["as_of"]


def test_foreign_shared_qualification_duty_and_policy_are_complete_and_no_raw_foreign_ids_escape(db_session, surgery_case):
    case = surgery_case
    foreign_pool = registry(db_session, case["super"], {"kind": "pool", "department_id": case["foreign"].department_id, "name": "合成外部资源池", "basis_note": NOTE})
    person_id = case["resources"]["person"].resource_id
    registry(db_session, case["super"], {"kind": "pool_membership", "pool_id": foreign_pool.pool_id, "resource_id": person_id, "basis_note": NOTE})
    ids = set()
    for kind in ("person_identity_qualification", "resource_availability_busy", "resource_occupation_policy"):
        values = request(case, kind)
        values["pool_id"] = foreign_pool.pool_id
        row = facts.create_source(db_session, case["foreign_user"], kind, values)
        db_session.commit()
        publish(db_session, case, row)
        ids.add(row.source_record_id)
    actual = collection.capture_input(db_session, case["director"], capture_request(case))
    assert {item["source_record_id"] for item in actual["member_manifest"]} == ids
    encoded = facts.canonical_json(actual["source_records"])
    assert foreign_pool.pool_id not in encoded and NOTE not in encoded
    for field in ("patient_id", "admission_id", "doctor_id", "user_id", "basis_note", "policy_reference"):
        assert '"' + field + '":' not in encoded


def test_pool_membership_and_equipment_child_state_are_bound_without_using_inventory_snapshot(db_session, surgery_case):
    from tests.test_ai_surgery_facts import maintenance

    case = surgery_case
    first = collection.capture_input(db_session, case["director"], capture_request(case))
    maintenance(db_session, case)
    second = collection.capture_input(db_session, case["director"], capture_request(case))
    assert first["resource_collection_digest"] != second["resource_collection_digest"]
    member = registry(db_session, case["super"], {"kind": "resource", "resource_kind": "room", "equipment_id": None, "cssd_instrument_id": None, "label": "第二合成物理室", "basis_note": NOTE})
    registry(db_session, case["super"], {"kind": "pool_membership", "pool_id": case["pool"].pool_id, "resource_id": member.resource_id, "basis_note": NOTE})
    third = collection.capture_input(db_session, case["director"], capture_request(case))
    assert len(third["resources"]) == 4 and third["resource_collection_digest"] != second["resource_collection_digest"]


def test_legacy_foreign_schedule_gap_is_opaque_and_cannot_be_erased_by_complete_declarations(db_session, surgery_case):
    from tests.test_ai_surgery_facts import protected_request

    case = surgery_case
    protected_request(db_session, case, foreign_pool=True)
    actual = collection.capture_input(db_session, case["director"], capture_request(case))
    assert {item["code"] for item in actual["known_gaps"]} >= {"legacy_room_identity_unresolved", "legacy_resource_busy_not_curated"}
    encoded = facts.canonical_json(actual["known_gaps"])
    assert "patient_id" not in encoded and "schedule_id" not in encoded and NOTE not in encoded
    assert all(set(item) == {"code", "commitment"} for item in actual["known_gaps"])


def test_bounded_keyset_roots_reject_whole_collection_and_bytes_before_source_proof(db_session, surgery_case, monkeypatch):
    case = surgery_case
    publish(db_session, case, create(db_session, case))
    publish(db_session, case, create(db_session, case))
    monkeypatch.setattr(collection, "MAX_ROOTS", 1)
    with pytest.raises(HTTPException) as error:
        collection.capture_input(db_session, case["director"], capture_request(case))
    assert error.value.status_code == 422
    monkeypatch.setattr(collection, "MAX_ROOTS", 8192)
    row = db_session.query(facts.AISurgerySource).first()
    budget = collection._Budget()
    budget.used = facts.FACT_BYTES - 5
    with pytest.raises(HTTPException) as error:
        budget.raw(row)
    assert error.value.status_code == 422
    assert facts.source_proof(row)[0]["source_record_id"] == row.source_record_id


def test_locking_shape_has_65_gate_before_current_reads_and_bounded_for_update(db_session, surgery_case, monkeypatch):
    from sqlalchemy import event
    from sqlalchemy.dialects import mysql

    case = surgery_case
    complete_originals(db_session, case)
    values = capture_request(case)
    actor = case["director"]
    queries = []
    statements = []
    original = facts.current_query

    def capture(query, *, locking=False):
        result = original(query, locking=locking)
        queries.append(str(result.statement.compile(dialect=mysql.dialect(), compile_kwargs={"literal_binds": True})))
        return result

    def sql(_conn, _cursor, statement, _parameters, _context, _many):
        statements.append(statement)

    monkeypatch.setattr(facts, "current_query", capture)
    event.listen(db_session.get_bind(), "before_cursor_execute", sql)
    try:
        collection.capture_input(db_session, actor, values, locking=True)
    finally:
        event.remove(db_session.get_bind(), "before_cursor_execute", sql)
    assert "hoimsystem_ai_surgery_write_gate" in statements[0] and "INSERT" in statements[0].upper()
    assert queries and all("FOR UPDATE" in query for query in queries)
    source_queries = [query for query in queries if "FROM hoimsystem_ai_surgery_source" in query and "ORDER BY" in query]
    assert source_queries and all("LIMIT 128" in query for query in source_queries)
    # SQLite executes the reads; its dialect deliberately emits no FOR UPDATE.
    assert not any("FOR UPDATE" in statement for statement in statements)


def test_actual_keyset_reads_all_129_related_roots_and_excludes_other_physical_subjects(db_session, surgery_case):
    from app.ai.surgery_models import AISurgerySource

    case = surgery_case
    for _index in range(129):
        create(db_session, case)
    foreign_pool = registry(db_session, case["super"], {"kind": "pool", "department_id": case["foreign"].department_id, "name": "合成不相关池", "basis_note": NOTE})
    room = registry(db_session, case["super"], {"kind": "resource", "resource_kind": "room", "equipment_id": None, "cssd_instrument_id": None, "label": "无关物理房间", "basis_note": NOTE})
    registry(db_session, case["super"], {"kind": "pool_membership", "pool_id": foreign_pool.pool_id, "resource_id": room.resource_id, "basis_note": NOTE})
    values = request(case, "operating_room_identity_capability")
    values.update(pool_id=foreign_pool.pool_id, resource_id=room.resource_id)
    unrelated = facts.create_source(db_session, case["foreign_user"], "operating_room_identity_capability", values)
    db_session.commit()
    unrelated.content_hash = "0" * 64
    db_session.commit()
    result = collection.capture_input(db_session, case["director"], capture_request(case))
    assert len(result["member_manifest"]) == 129
    assert unrelated.source_record_id not in {item["source_record_id"] for item in result["member_manifest"]}
    assert db_session.query(AISurgerySource).filter(AISurgerySource.pool_id.in_([case["pool"].pool_id, foreign_pool.pool_id])).count() == 130
    assert len({item["source_record_id"] for item in result["member_manifest"]}) == 129


def test_current_clinical_parent_change_cannot_restore_stale_free_text_in_super_capture(db_session, surgery_case):
    case = surgery_case
    row = publish(db_session, case, create(db_session, case))
    before = collection.capture_input(db_session, case["super"], capture_request(case))
    assert before["source_records"][0]["original"] is not None
    case["application"].preop_diagnosis = "变更后的合成原临床内容"
    db_session.commit()
    after = collection.capture_input(db_session, case["super"], capture_request(case))
    record = after["source_records"][0]
    assert record["metadata"]["source_record_id"] == row.source_record_id and not record["metadata"]["eligible_for_new_use"]
    assert record["original"] is None and record["governance"] is None and record["capsule"] is None
    assert after["case_collection_digest"] != before["case_collection_digest"] and after["collection_digest"] != before["collection_digest"]
    assert NOTE not in facts.canonical_json(record) and "变更后的合成原临床内容" not in facts.canonical_json(after)


def test_current_revocation_after_original_cutoff_is_visible_but_not_historical_capture(db_session, surgery_case, monkeypatch):
    import datetime

    from tests.test_ai_surgery_facts import NOW

    case = surgery_case
    row = publish(db_session, case, create(db_session, case))
    previous = collection.capture_input(db_session, case["director"], capture_request(case))
    monkeypatch.setattr(facts, "utcnow", lambda: NOW + datetime.timedelta(seconds=1))
    facts.review_source(db_session, case["super"], row.source_kind, row.source_record_id, {"expected_revision": 2, "expected_content_hash": row.content_hash, "basis_note": NOTE}, revoke=True)
    db_session.commit()
    current = collection.current_collection(db_session, case["director"], capture_request(case))
    assert current["collection_digest"] != previous["collection_digest"] and current["max_available_at"] > previous["as_of"]
    assert current["source_records"][0]["original"] is None
    with pytest.raises(HTTPException) as error:
        collection.capture_input(db_session, case["director"], capture_request(case))
    assert error.value.status_code == 409


def test_latest_available_clock_is_actual_original_clock_not_the_requested_cutoff(db_session, surgery_case, monkeypatch):
    import datetime

    from tests.test_ai_surgery_facts import NOW

    case = surgery_case
    values = capture_request(case)
    values["period"]["as_of"] = facts.utc_text(NOW + datetime.timedelta(seconds=10))
    monkeypatch.setattr(facts, "utcnow", lambda: NOW + datetime.timedelta(seconds=20))
    actual = collection.capture_input(db_session, case["director"], values)
    assert actual["max_available_at"] == facts.utc_text(NOW)
    assert actual["as_of"] == values["period"]["as_of"]
    assert actual["captured_at"] == facts.utc_text(NOW + datetime.timedelta(seconds=20))


def test_published_foreign_protected_capsule_is_captured_without_exposing_raw_witness(db_session, surgery_case):
    from tests.test_ai_surgery_facts import protected_request

    case = surgery_case
    values, schedule = protected_request(db_session, case, foreign_pool=True)
    foreign_application_id = schedule.application_id
    row = facts.create_protected_capsule(db_session, case["super"], values)
    db_session.commit()
    publish(db_session, case, row)
    captured = collection.capture_input(db_session, case["director"], capture_request(case))
    assert len(captured["source_records"]) == 1
    record = captured["source_records"][0]
    assert record["metadata"]["source_record_id"] == row.source_record_id
    assert record["original"] is None and record["capsule"]["eligible_for_new_use"]
    assert record["capsule"]["payload"]["basis_code"] == "protected_legacy_witness"
    assert record["capsule"]["payload"]["protected_witness_hash"] is not None
    assert "legacy_resource_busy_not_curated" not in {gap["code"] for gap in captured["known_gaps"]}
    text = facts.canonical_json(captured)
    assert foreign_application_id not in text and schedule.schedule_id not in text
    assert "witness_json" not in text and "original_schedule" not in text
