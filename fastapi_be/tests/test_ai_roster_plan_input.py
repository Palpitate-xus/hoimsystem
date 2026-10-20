"""Complete actual-ORM scenario collection, declared capacity and frozen projection."""

import copy
import datetime
import uuid

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.ai import roster_contract as core
from app.ai import roster_facts as facts
from app.ai import roster_plan_input as plans
from app.ai.models import AIAuditEvent
from app.ai.roster_models import AIRosterSource
from app.models import Doctor, DoctorSchedule
from tests.test_ai_roster_facts import NOTE, NOW, create, limit, publish, request
from tests.test_ai_roster_facts import roster_case as roster_case


def plan_request(db, case, *, session_count=1):
    people = db.query(Doctor).filter_by(department_id=case["department"].department_id).order_by(Doctor.doctor_id).all()
    sessions = []
    for index in range(session_count):
        start = 8 + index * 2
        sessions.append(
            {
                "session_key": str(uuid.uuid4()),
                "start_at": f"2026-10-22T{start:02d}:00:00.000000Z",
                "end_at": f"2026-10-22T{start + 2:02d}:00:00.000000Z",
                "business_date": "2026-10-22",
                "required_job_key": "general_clinic",
                "minimum_staff": 0,
                "maximum_staff": 2,
                "required_slots": limit(0),
                "facility_slot_ceiling": limit(20),
                "requirements_basis": NOTE,
                "capacity_basis": NOTE,
            }
        )
    return {
        "department_id": case["department"].department_id,
        "date_from": "2026-10-22",
        "date_to": "2026-10-22",
        "business_timezone": "UTC",
        "objective_mode": "meet_targets_min_penalty",
        "personnel_coverage": {"status": "unknown", "basis": NOTE},
        "session_requirements_coverage": {"status": "unknown", "basis": NOTE},
        "staff": [
            {"doctor_id": person.doctor_id, "all_locations_duty_coverage": {"start_at": "2026-10-01T00:00:00.000000Z", "end_at": "2026-11-05T00:00:00.000000Z", "status": "unknown", "basis": NOTE}}
            for person in people
        ],
        "sessions": sessions,
        "options": [
            {
                "doctor_id": person.doctor_id,
                "session_key": session["session_key"],
                "cost_points": limit(0),
                "slot_capacity": limit(10),
                "breaks": [],
                "breaks_complete": True,
                "time_accounting_status": "verified",
                "basis": NOTE,
            }
            for person in people
            for session in sessions
        ],
        "submitted_candidate": None,
    }


@pytest.fixture
def plan_case(roster_case, db_session, monkeypatch):
    monkeypatch.setattr(plans, "utcnow", lambda: NOW)
    case = roster_case
    case["facts"] = {kind: publish(db_session, case, create(db_session, case, kind)) for kind in facts.KINDS}
    case["plan_request"] = plan_request(db_session, case)
    case["problem_id"] = str(uuid.uuid4())
    return case


def capture(db, case, values=None):
    return plans.capture_input(db, case["director"], values or case["plan_request"], case["problem_id"])


def test_actual_full_cohort_four_kinds_exact_projection_and_no_names_notes_or_stock(db_session, plan_case):
    case = plan_case
    before_audit = db_session.query(AIAuditEvent).count()
    before_schedules = [(row.schedule_id, row.week, row.time, row.number) for row in db_session.query(DoctorSchedule).all()]
    preview = plans.preview_input(db_session, case["director"], case["plan_request"])
    snapshot = plans.capture_input(db_session, case["director"], case["plan_request"], case["problem_id"], expected_collection_digest=preview["collection_digest"])
    assert len(snapshot["cohort"]) == len(case["plan_request"]["staff"]) and case["unscheduled"].doctor_id in {member["doctor_id"] for member in snapshot["cohort"]}
    assert len(snapshot["fact_manifest"]) == 4 and snapshot["as_of"] == snapshot["captured_at"] == facts.utc_text(NOW)
    source = plans.project_source(snapshot, "a" * 64)
    assert core.RosterSource.model_validate(source).problem_id == case["problem_id"]
    assert source["content_hash"] == facts.hash_content(snapshot)
    assert source["personnel_coverage"] == source["session_requirements_coverage"] == "unknown"
    assert len(source["options"]) == len(source["staff"]) * len(source["sessions"])
    assert source["sessions"][0]["required_slots"] == limit(0) and source["options"][0]["cost_points"] == limit(0)
    assert len(source["work_policies"]) == 1 and set(source["work_policies"][0]["applicable_staff_ids"]) == {item["staff_id"] for item in source["staff"]}
    public = facts.canonical_json(source)
    for forbidden in ('"doctor_id"', '"department_id"', '"created_by"', "general_clinic", NOTE, case["doctor"].name, case["doctor"].phone, 'policy_reference"'):
        assert forbidden not in public
    assert source["source_id"] == f"roster_problem:{case['problem_id']}:{facts.hash_content(snapshot)[:12]}"
    assert db_session.query(AIAuditEvent).count() == before_audit
    assert before_schedules == [(row.schedule_id, row.week, row.time, row.number) for row in db_session.query(DoctorSchedule).all()]


@pytest.mark.parametrize("change", ["missing_staff", "missing_pair", "duplicate_pair", "outside_candidate", "unknown_field", "bad_boolean", "bad_utc", "wrong_business_date"])
def test_strict_private_request_requires_complete_pairs_and_actual_scope(db_session, plan_case, change):
    case = plan_case
    data = copy.deepcopy(case["plan_request"])
    if change == "missing_staff":
        removed = data["staff"].pop()["doctor_id"]
        data["options"] = [item for item in data["options"] if item["doctor_id"] != removed]
        with pytest.raises(HTTPException, match="409"):
            plans.preview_input(db_session, case["director"], data)
        return
    if change == "missing_pair":
        data["options"].pop()
    elif change == "duplicate_pair":
        data["options"].append(data["options"][0])
    elif change == "outside_candidate":
        data["submitted_candidate"] = [{"doctor_id": case["outsider"].doctor_id, "session_key": data["sessions"][0]["session_key"]}]
    elif change == "unknown_field":
        data["sessions"][0]["current_shared_stock"] = 10
    elif change == "bad_boolean":
        data["options"][0]["breaks_complete"] = 1
    elif change == "bad_utc":
        data["sessions"][0]["start_at"] = "2026-10-22T08:00:00"
    else:
        data["sessions"][0]["business_date"] = "2026-10-23"
    with pytest.raises(ValidationError):
        plans.PlanRequest.model_validate(data)


def test_unknown_or_empty_collections_remain_unknown_not_zero_work_or_unrestricted(db_session, plan_case):
    case = plan_case
    db_session.query(AIRosterSource).delete()
    db_session.commit()
    values = plan_request(db_session, case, session_count=0)
    source = plans.project_source(capture(db_session, case, values), "b" * 64)
    assert source["sessions"] == source["options"] == source["work_policies"] == []
    assert source["session_requirements_coverage"] == "unknown"
    assert all(not person["qualifications"] and not person["availability"] and person["all_locations_duty_coverage"]["status"] == "unknown" for person in source["staff"])


def test_dst_business_midnights_are_not_a_fixed_86400_seconds(db_session, plan_case):
    case = plan_case
    data = plan_request(db_session, case, session_count=0)
    data.update(date_from="2026-11-01", date_to="2026-11-01", business_timezone="America/New_York")
    snapshot = capture(db_session, case, data)
    assert snapshot["planning_start_at"] == "2026-11-01T04:00:00.000000Z"
    assert snapshot["planning_end_at"] == "2026-11-02T05:00:00.000000Z"
    assert facts.instant(snapshot["planning_end_at"]) - facts.instant(snapshot["planning_start_at"]) == datetime.timedelta(hours=25)
    assert plans.project_source(snapshot, "a" * 64)["business_dates"] == ["2026-11-01"]


def test_future_planning_boundary_is_separate_from_ended_frozen_history(db_session, plan_case, monkeypatch):
    case = plan_case
    snapshot = capture(db_session, case)
    original = plans.project_source(snapshot, "b" * 64)
    monkeypatch.setattr(plans, "utcnow", lambda: datetime.datetime(2026, 11, 15))
    assert plans.verify_snapshot(snapshot) == snapshot
    assert plans.project_source(snapshot, "b" * 64) == original
    assert plans.current_collection(db_session, case["director"], case["department"].department_id)["collection_digest"] == snapshot["collection_digest"]
    with pytest.raises(HTTPException, match="422"):
        plans.validate_planning_period(snapshot["request"])
    with pytest.raises(HTTPException, match="422"):
        capture(db_session, case)


def test_source_added_after_original_cutoff_changes_current_collection_and_preview_binding(db_session, plan_case, monkeypatch):
    case = plan_case
    snapshot = capture(db_session, case)
    monkeypatch.setattr(facts, "utcnow", lambda: NOW + datetime.timedelta(seconds=1))
    create(db_session, case, "availability")
    current = plans.current_collection(db_session, case["director"], case["department"].department_id)
    assert current["collection_digest"] != snapshot["collection_digest"] and len(current["fact_manifest"]) == 5
    with pytest.raises(HTTPException, match="409"):
        plans.capture_input(db_session, case["director"], case["plan_request"], str(uuid.uuid4()), expected_collection_digest=snapshot["collection_digest"])


@pytest.mark.parametrize("transition", ["revoke", "new_person", "transfer_person"])
def test_all_live_membership_not_only_selected_or_winning_member_is_bound(db_session, plan_case, transition):
    case = plan_case
    snapshot = capture(db_session, case)
    if transition == "revoke":
        row = case["facts"]["availability"]
        facts.revoke_source(db_session, case["super"], "availability", row.source_record_id, {"expected_revision": 2, "reason": "非赢家原记录变化也改变完整计划集合"})
    elif transition == "new_person":
        db_session.add(Doctor(name="新增无周期排班人员", department_id=case["department"].department_id))
    else:
        case["unscheduled"].department_id = case["foreign"].department_id
    db_session.commit()
    assert plans.current_collection(db_session, case["director"], case["department"].department_id)["collection_digest"] != snapshot["collection_digest"]


def test_stale_rejected_draft_and_revoked_members_remain_manifest_but_not_public_and_no_private_note_restore(db_session, plan_case):
    case = plan_case
    rejected = create(db_session, case)
    publish(db_session, case, rejected, decision="reject")
    create(db_session, case, "availability")
    row = case["facts"]["availability"]
    facts.revoke_source(db_session, case["super"], "availability", row.source_record_id, {"expected_revision": 2, "reason": "原未公开资料不可恢复到新场景"})
    case["doctor"].department_id = case["foreign"].department_id
    db_session.commit()
    data = plan_request(db_session, case)
    snapshot = plans.capture_input(db_session, case["super"], data, case["problem_id"])
    assert len(snapshot["fact_manifest"]) == 6
    for record in snapshot["facts"]:
        if not record["parent_current"] or record["status"] in {"rejected", "revoked"}:
            assert record["payload"] is record["parent_binding"] is record["review_basis_note"] is record["revoke_reason"] is None
    source = plans.project_source(snapshot, "b" * 64)
    assert all(not person["qualifications"] and not person["availability"] and not person["duties"] for person in source["staff"])
    assert len(source["work_policies"]) == 1


def test_corrupt_potential_member_blocks_capture_even_super_cannot_skip_it(db_session, plan_case):
    case = plan_case
    case["facts"]["qualification"].payload_json += " "
    db_session.commit()
    with pytest.raises(HTTPException, match="409"):
        plans.capture_input(db_session, case["super"], case["plan_request"], case["problem_id"])


def test_frozen_recipe_self_proof_never_silently_rewrites_old_snapshot_to_new_algorithm(db_session, plan_case, monkeypatch):
    case = plan_case
    snapshot = capture(db_session, case)
    before = plans.project_source(snapshot, "b" * 64, validate_current_recipe=False)
    monkeypatch.setattr(core, "RECIPE", {**core.RECIPE, "new_future_algorithm": "changed"})
    assert plans.verify_snapshot(snapshot) == snapshot
    assert plans.project_source(snapshot, "b" * 64, validate_current_recipe=False) == before
    with pytest.raises(HTTPException, match="409"):
        plans.project_source(snapshot, "b" * 64)


@pytest.mark.parametrize("change", ["mapping", "fact_value", "cohort", "manifest", "recipe", "restore_stale_notes"])
def test_private_original_projection_proof_rejects_inconsistent_full_content(db_session, plan_case, change):
    case = plan_case
    snapshot = copy.deepcopy(capture(db_session, case))
    if change == "mapping":
        snapshot["mapping"]["staff"][str(case["doctor"].doctor_id)] = str(uuid.uuid4())
    elif change == "fact_value":
        record = next(record for record in snapshot["facts"] if record["source_kind"] == "availability")
        record["payload"]["availability"] = "available"
    elif change == "cohort":
        snapshot["cohort"].pop()
    elif change == "manifest":
        snapshot["fact_manifest"].pop()
    elif change == "recipe":
        snapshot["algorithm"]["recipe"]["version"] = "tampered"
    else:
        record = snapshot["facts"][0]
        record.update(parent_current=False, eligible=False, exclusion_reasons=["doctor_department_binding_changed"])
    with pytest.raises(HTTPException, match="409"):
        plans.verify_snapshot(snapshot)


def test_more_than_old_200_sources_are_wholly_captured_and_technical_cap_rejects_atomically(db_session, plan_case, monkeypatch):
    case = plan_case
    for _ in range(201):
        facts.create_source(db_session, case["director"], "availability", request(case, "availability"))
    db_session.commit()
    snapshot = capture(db_session, case)
    assert len(snapshot["facts"]) == len(snapshot["fact_manifest"]) == 205
    assert len({record["source_record_id"] for record in snapshot["facts"]}) == 205
    assert len(facts.canonical_json(snapshot).encode()) > 65535
    monkeypatch.setattr(plans, "MAX_FACTS", 204)
    with pytest.raises(HTTPException, match="422"):
        plans.current_collection(db_session, case["director"], case["department"].department_id)


def test_personnel_cap_never_chooses_a_subset(db_session, plan_case):
    case = plan_case
    db_session.add_all([Doctor(name="实际候选上限合成人员", department_id=case["department"].department_id) for _ in range(core.MAX_STAFF)])
    db_session.commit()
    with pytest.raises(HTTPException, match="422"):
        plans.current_collection(db_session, case["director"], case["department"].department_id)


def test_cross_scope_and_extra_person_cannot_be_used_as_a_staffing_scenario(db_session, plan_case):
    case = plan_case
    with pytest.raises(HTTPException, match="403"):
        plans.current_collection(db_session, case["director"], case["foreign"].department_id)
    values = copy.deepcopy(case["plan_request"])
    values["staff"][0]["doctor_id"] = case["outsider"].doctor_id
    for option in values["options"]:
        if option["doctor_id"] == case["plan_request"]["staff"][0]["doctor_id"]:
            option["doctor_id"] = case["outsider"].doctor_id
    with pytest.raises(HTTPException, match="409"):
        plans.capture_input(db_session, case["admin"], values, case["problem_id"])
