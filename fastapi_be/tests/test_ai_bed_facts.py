"""Real governed bed originals: preserve quantities, clocks and stable historical scope."""

import datetime
import json
import uuid

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import event
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Session

from app.ai import bed_facts as facts
from app.ai import governance
from app.ai.bed_models import AIBedSource
from app.ai.models import AIFeatureConfig
from app.models import Admission, Bed, Department, Doctor, User, Ward

NOTE = "合成病区床位原证据仅用于隔离工程验证，已明确核对观察与登记时刻及缺项状态，不代表真实医院运营资料。"
NOW = datetime.datetime(2026, 10, 20, 9, 10, 11, 123456)


def count(value=None, reason="unknown"):
    return {"value": value, "absent_reason": None if value is not None else reason}


def payload(kind):
    if kind == "capacity_interval":
        return {
            "schema_version": "bed_capacity_interval_v1",
            "start_at": "2026-10-19T00:00:00.000000Z",
            "end_at": "2026-10-20T00:00:00.000000Z",
            "basis_kind": "observed_operational_capacity",
            "operational_total_beds": count(20),
            "coverage": "attested_complete",
            "capacity_definition": "total_operational_physical_beds_v1",
            "capacity_basis_note": NOTE,
            "observed_at": "2026-10-20T00:00:00.000001Z",
            "staff_readiness": "unknown",
            "equipment_readiness": "confirmed",
            "isolation_applicability": "not_confirmed",
            "immediate_admittable_slots": count(0),
            "immediate_slots_observed_at": "2026-10-20T08:00:00.000000Z",
        }
    result = {
        "schema_version": "bed_census_observation_v1" if kind == "census" else "bed_flow_day_v1",
        "business_date": "2026-10-19",
        "business_timezone": "Etc/UTC",
        "observed_at": "2026-10-20T00:00:00.000001Z",
        "method": "direct_tally",
        "external_record_key": None,
        "external_record_key_absent_reason": "not_applicable",
        "coverage": "unknown",
        "coverage_basis_note": NOTE,
    }
    if kind == "census":
        result.update(census_at="2026-10-20T00:00:00.000000Z", definition="occupied_physical_beds_at_boundary_v1", boundary_state_confirmed="unknown", occupied_beds=count(0))
    else:
        result.update(
            day_start_at="2026-10-19T00:00:00.000000Z",
            day_end_at="2026-10-20T00:00:00.000000Z",
            definition="ward_physical_day_events_v1",
            admission_events=count(3),
            discharge_events=count(0),
            transfer_in_events=count(),
            transfer_out_events=count(None, "not_recorded"),
            event_definition_basis_note=NOTE,
        )
    return result


@pytest.fixture
def bed_case(seed_data, db_session, monkeypatch):
    db_session.query(AIBedSource).delete()
    db_session.query(AIFeatureConfig).filter_by(feature_key="bed_forecast").delete()
    foreign = Department(name="床位隔离外科" + uuid.uuid4().hex[:6])
    director = User(username="bdir" + uuid.uuid4().hex[:12], password=seed_data["director_user"].password, user_role="director")
    db_session.add_all([foreign, director])
    db_session.flush()
    person = Doctor(name="合成病区负责人", department_id=seed_data["department"].department_id, user_id=director.user_id)
    ward = Ward(name="合成病区", department_id=seed_data["department"].department_id, bed_count=999, status=0)
    foreign_ward = Ward(name="隔离病区", department_id=foreign.department_id)
    db_session.add_all([person, ward, foreign_ward])
    db_session.commit()
    monkeypatch.setattr(facts, "utcnow", lambda: NOW)
    return {
        "seed": seed_data,
        "department": seed_data["department"],
        "director": director,
        "person": person,
        "ward": ward,
        "foreign": foreign,
        "foreign_ward": foreign_ward,
        "admin": seed_data["admin_user"],
        "super": seed_data["super_admin_user"],
    }


def request(case, kind="census"):
    return {"ward_id": case["ward"].ward_id, "payload": payload(kind)}


def create(db, case, kind="census", actor=None):
    row = facts.create_source(db, actor or case["director"], kind, request(case, kind))
    db.commit()
    return row


def publish(db, case, row, decision="publish"):
    facts.review_source(db, case["super"], row.source_kind, row.source_record_id, {"expected_revision": 1, "expected_content_hash": row.content_hash, "decision": decision, "review_basis_note": NOTE})
    db.commit()
    return row


@pytest.mark.parametrize("kind", facts.KINDS)
def test_actual_three_original_kinds_and_governance_do_not_mutate_body(db_session, bed_case, kind):
    case = bed_case
    row = create(db_session, case, kind)
    original = row.payload_json, row.parent_binding_json, row.content_hash
    draft = facts.source_current(db_session, case["director"], kind, row.source_record_id)
    assert draft["recorded_at"] == "2026-10-20T09:10:11.123456Z"
    assert draft["status"] == "draft" and draft["revision"] == 1 and draft["eligible"] is False
    assert draft["source_id"] == f"{facts.PREFIXES[kind]}:{row.source_record_id}:{row.content_hash[:12]}"
    assert facts.hash_content(facts.immutable_body(row, draft["payload"], draft["parent_binding"])) == row.content_hash
    with pytest.raises(HTTPException, match="409"):
        facts.authorize_source(db_session, case["director"], kind, row.source_record_id)
    publish(db_session, case, row)
    current = facts.authorize_source(db_session, case["director"], kind, row.source_record_id, as_of=facts.utc_text(NOW))
    assert current["eligible"] is True and current["revision"] == 2
    assert current["payload"] == payload(kind)
    assert original == (row.payload_json, row.parent_binding_json, row.content_hash)
    assert current["governance_hash"] != draft["governance_hash"]
    # Source eligibility is not attestation that unknown original coverage/readiness is complete.
    if kind == "capacity_interval":
        assert current["payload"]["operational_total_beds"] == count(20)
        assert current["payload"]["immediate_admittable_slots"] == count(0)
        assert current["payload"]["staff_readiness"] == "unknown"
    else:
        assert current["payload"]["coverage"] == "unknown"


def test_asof_requires_actual_publication_not_just_original_recording(db_session, bed_case, monkeypatch):
    row = create(db_session, bed_case)
    monkeypatch.setattr(facts, "utcnow", lambda: NOW + datetime.timedelta(seconds=1))
    publish(db_session, bed_case, row)
    with pytest.raises(HTTPException, match="409"):
        facts.authorize_source(db_session, bed_case["super"], "census", row.source_record_id, as_of=facts.utc_text(NOW))
    assert facts.authorize_source(db_session, bed_case["director"], "census", row.source_record_id, as_of=facts.utc_text(NOW + datetime.timedelta(seconds=1)))["eligible"]


@pytest.mark.parametrize("value,reason", [(False, None), (1.0, None), ("0", None), (-1, None), (2147483648, None), (None, None), (0, "unknown"), (None, "not_applicable")])
def test_count_rejects_coercion_and_imputed_zero(value, reason):
    with pytest.raises(ValidationError):
        facts.CountValue.model_validate({"value": value, "absent_reason": reason})


@pytest.mark.parametrize(
    "field,value",
    [
        ("census_at", "2026-10-19T00:00:00.000000Z"),
        ("census_at", "2026-10-20T00:00:00Z"),
        ("observed_at", "2026-10-20T00:00:00.000000+00:00"),
        ("business_timezone", "imaginary/timezone"),
        ("business_date", "2026-02-30"),
        ("business_date", "9999-12-31"),
        ("boundary_state_confirmed", True),
        ("coverage", "complete"),
    ],
)
def test_census_requires_true_calendar_boundary_and_exact_utc6(field, value):
    data = payload("census")
    data[field] = value
    with pytest.raises(ValidationError):
        facts.CensusPayload.model_validate(data)


@pytest.mark.parametrize("day,hours", [("2026-03-08", 23), ("2026-11-01", 25)])
def test_closed_day_uses_actual_dst_midnights(day, hours):
    start, end = facts.day_bounds(day, "America/New_York")
    assert (facts.instant(end) - facts.instant(start)).total_seconds() == hours * 3600
    data = payload("flow_day")
    data.update(business_date=day, business_timezone="America/New_York", day_start_at=start, day_end_at=end, observed_at=end)
    assert facts.FlowDayPayload.model_validate(data).day_start_at == start


@pytest.mark.parametrize("day,zone", [("2011-12-30", "Pacific/Apia"), ("2020-11-01", "America/Havana")])
def test_nonexistent_or_ambiguous_local_midnight_is_not_guessed(day, zone):
    with pytest.raises(ValueError):
        facts.day_bounds(day, zone)


@pytest.mark.parametrize("kind", facts.KINDS)
def test_new_original_observation_cannot_follow_server_recording(db_session, bed_case, kind):
    data = request(bed_case, kind)
    data["payload"]["observed_at"] = "2026-10-20T09:10:11.123457Z"
    with pytest.raises(HTTPException, match="422"):
        facts.create_source(db_session, bed_case["director"], kind, data)
    assert db_session.query(AIBedSource).count() == 0


@pytest.mark.parametrize("change", ["open", "early", "naive", "instant_without_count", "count_without_instant"])
def test_historical_capacity_entire_interval_and_independent_slots_clock(change):
    data = payload("capacity_interval")
    if change == "open":
        data["end_at"] = data["start_at"]
    elif change == "early":
        data["observed_at"] = "2026-10-19T23:59:59.999999Z"
    elif change == "naive":
        data["observed_at"] = "2026-10-20T00:00:00"
    elif change == "instant_without_count":
        data["immediate_admittable_slots"] = count()
    else:
        data["immediate_slots_observed_at"] = None
    with pytest.raises(ValidationError):
        facts.CapacityIntervalPayload.model_validate(data)


def test_future_total_scenario_can_begin_before_recording_but_has_no_observed_or_current_slots(db_session, bed_case, monkeypatch):
    data = request(bed_case, "capacity_interval")
    data["payload"].update(
        basis_kind="reviewed_future_scenario", observed_at=None, end_at="2026-10-21T00:00:00.000000Z", immediate_admittable_slots=count(None, "not_recorded"), immediate_slots_observed_at=None
    )
    row = facts.create_source(db_session, bed_case["director"], "capacity_interval", data)
    db_session.commit()
    monkeypatch.setattr(facts, "utcnow", lambda: NOW + datetime.timedelta(days=10))
    publish(db_session, bed_case, row)
    assert facts.source_current(db_session, bed_case["director"], "capacity_interval", row.source_record_id)["payload"] == data["payload"]
    # Time passing cannot change this original's own hash or historical eligibility.
    with pytest.raises(HTTPException, match="422"):
        facts.create_source(db_session, bed_case["director"], "capacity_interval", data)
    for update in ({"observed_at": facts.utc_text(NOW)}, {"immediate_admittable_slots": count(0), "immediate_slots_observed_at": facts.utc_text(NOW)}):
        invalid = {**data["payload"], **update}
        with pytest.raises(ValidationError):
            facts.CapacityIntervalPayload.model_validate(invalid)


def test_today_status_admission_and_catalog_counts_never_rewrite_historical_source(db_session, bed_case):
    case = bed_case
    row = publish(db_session, case, create(db_session, case))
    original = facts.source_current(db_session, case["director"], "census", row.source_record_id)
    bed = Bed(ward_id=case["ward"].ward_id, bed_no="X", status=1)
    db_session.add(bed)
    db_session.flush()
    admission = Admission(
        admission_id=str(uuid.uuid4()),
        admission_no="S" + uuid.uuid4().hex[:16],
        patient_id=case["seed"]["patient"].patient_id,
        department_id=case["department"].department_id,
        ward_id=case["ward"].ward_id,
        bed_id=bed.bed_id,
        status=1,
        admission_time=NOW,
    )
    db_session.add(admission)
    db_session.commit()
    bed.status = 2
    admission.status, admission.discharge_time = 2, NOW
    case["ward"].bed_count, case["ward"].name, case["ward"].status = 0, "更名的当前病区", 1
    db_session.commit()
    assert facts.authorize_source(db_session, case["director"], "census", row.source_record_id) == original
    assert original["payload"]["occupied_beds"] == count(0)
    assert facts.options(db_session, case["director"], case["department"].department_id)["wards"][0]["status"] == 1


def test_changed_original_ward_scope_redacts_ordinary_but_super_can_audit_and_revoke(db_session, bed_case):
    case = bed_case
    row = publish(db_session, case, create(db_session, case))
    original = row.payload_json, row.parent_binding_json, row.content_hash
    case["ward"].department_id = case["foreign"].department_id
    db_session.commit()
    ordinary = facts.source_current(db_session, case["director"], "census", row.source_record_id)
    assert ordinary["parent_current"] is ordinary["eligible"] is ordinary["can_record"] is False
    assert ordinary["exclusion_reasons"] == ["ward_department_binding_changed"]
    assert all(ordinary[key] is None for key in ("payload", "parent_binding", "review_basis_note", "revoke_reason"))
    with pytest.raises(HTTPException, match="409"):
        facts.authorize_source(db_session, case["super"], "census", row.source_record_id)
    frozen = facts.source_current(db_session, case["super"], "census", row.source_record_id, audit_only=True)
    assert frozen["payload"] == payload("census") and frozen["can_revoke"] is True
    facts.revoke_source(db_session, case["super"], "census", row.source_record_id, {"expected_revision": 2, "reason": "原病区变更后保留冻结原件并停止使用"})
    db_session.commit()
    assert original == (row.payload_json, row.parent_binding_json, row.content_hash)


def test_current_actor_real_department_and_feature_roles_independent_of_provider(db_session, bed_case):
    case = bed_case
    values = request(case)
    values["ward_id"] = case["foreign_ward"].ward_id
    with pytest.raises(HTTPException, match="403"):
        facts.create_source(db_session, case["director"], "census", values)
    with pytest.raises(HTTPException, match="403"):
        facts.create_source(db_session, case["seed"]["doctor_user"], "census", request(case))
    db_session.add(AIFeatureConfig(feature_key="bed_forecast", enabled=False, allowed_roles_json='["admin"]', updated_by=case["super"].user_id))
    db_session.commit()
    with pytest.raises(HTTPException, match="403"):
        facts.create_source(db_session, case["director"], "census", request(case))
    assert create(db_session, case, actor=case["admin"]).status == "draft"
    assert create(db_session, case, actor=case["super"]).status == "draft"


def test_old_author_role_does_not_invalidate_published_fact(db_session, bed_case):
    row = publish(db_session, bed_case, create(db_session, bed_case))
    bed_case["director"].user_role = "nurse"
    db_session.commit()
    assert facts.authorize_source(db_session, bed_case["super"], "census", row.source_record_id)["eligible"] is True
    with pytest.raises(HTTPException, match="403"):
        facts.source_current(db_session, bed_case["director"], "census", row.source_record_id)


@pytest.mark.parametrize("mutation", ["hash", "body", "parent", "clock", "governance"])
def test_bad_own_integrity_is_never_super_frozen_bypass(db_session, bed_case, mutation):
    row = create(db_session, bed_case)
    if mutation == "hash":
        row.content_hash = "a" * 64
    elif mutation == "body":
        data = json.loads(row.payload_json)
        data["occupied_beds"] = count(42)
        row.payload_json = facts.canonical_json(data)
    elif mutation == "parent":
        row.parent_binding_json = facts.canonical_json({"department": {"department_id": bed_case["foreign"].department_id}, "ward": {"ward_id": row.ward_id, "department_id": row.department_id}})
    elif mutation == "clock":
        row.recorded_at -= datetime.timedelta(days=2)
    else:
        # Valid SQL shape but broken review provenance is still rejected by the loader.
        publish(db_session, bed_case, row)
        row.review_basis_note = "x"
    db_session.commit()
    with pytest.raises(HTTPException, match="409"):
        facts.source_current(db_session, bed_case["super"], "census", row.source_record_id, audit_only=True)


def test_review_postcas_parent_current_check_and_atomic_audit_rollback(db_session, bed_case, monkeypatch):
    row = create(db_session, bed_case)
    original = row.content_hash
    real = facts.parent_exclusion_reasons

    def changed_after_cas(db, candidate, parent, *, locking=False):
        if locking:
            db.query(Ward).filter_by(ward_id=candidate.ward_id).update({"department_id": bed_case["foreign"].department_id}, synchronize_session=False)
        return real(db, candidate, parent, locking=locking)

    monkeypatch.setattr(facts, "parent_exclusion_reasons", changed_after_cas)
    with pytest.raises(HTTPException, match="409"):
        facts.review_source(
            db_session, bed_case["super"], "census", row.source_record_id, {"expected_revision": 1, "expected_content_hash": original, "decision": "publish", "review_basis_note": NOTE}
        )
    db_session.rollback()
    assert facts.source_row(db_session, row.source_record_id).status == "draft"
    assert db_session.get(Ward, row.ward_id).department_id == row.department_id


def test_locked_current_reads_have_for_update_sql_and_refresh_real_second_session(db_session, bed_case):
    actor = bed_case["director"]
    query = facts.current_query(db_session.query(User).filter_by(user_id=actor.user_id), locking=True)
    assert str(query.statement.compile(dialect=mysql.dialect())).endswith("FOR UPDATE")
    assert query._execution_options.get("populate_existing") is True or query.load_options._populate_existing is True
    # SQLite cannot prove row locks. It does prove expired/stale ORM state is refreshed.
    with Session(db_session.get_bind()) as second:
        second.query(User).filter_by(user_id=actor.user_id).update({"user_role": "nurse"}, synchronize_session=False)
        second.commit()
    with pytest.raises(HTTPException, match="403"):
        facts.current_actor(db_session, actor, locking=True)


def test_locked_actor_primary_key_does_not_implicitly_load_expired_user(db_session, bed_case):
    user = bed_case["director"]
    db_session.expire(user)
    statements = []

    def capture(conn, cursor, statement, parameters, context, executemany):
        if statement.startswith("SELECT") and "hoimsystem_user" in statement:
            statements.append((statement, context.compiled.statement._for_update_arg is not None))

    event.listen(db_session.get_bind(), "before_cursor_execute", capture)
    try:
        facts.current_actor(db_session, user, locking=True)
    finally:
        event.remove(db_session.get_bind(), "before_cursor_execute", capture)
    assert len(statements) == 1 and statements[0][1]


def test_original_kind_mismatch_and_utf8_review_capacity(db_session, bed_case):
    with pytest.raises(HTTPException, match="422"):
        facts.create_source(db_session, bed_case["director"], "flow_day", request(bed_case, "census"))
    with pytest.raises(ValidationError):
        facts.SourceReview(expected_revision=1, expected_content_hash="a" * 64, decision="publish", review_basis_note="字" * 1400)
    with pytest.raises(ValidationError):
        facts.SourceCreate.model_validate({**request(bed_case), "department_id": bed_case["department"].department_id})


def test_terminal_reject_and_draft_revoke_are_versioned_and_ordinary_redacted(db_session, bed_case):
    row = publish(db_session, bed_case, create(db_session, bed_case), decision="reject")
    value = facts.source_current(db_session, bed_case["director"], "census", row.source_record_id)
    assert value["status"] == "rejected" and value["revision"] == 2
    assert all(value[key] is None for key in ("payload", "parent_binding", "review_basis_note", "revoke_reason"))
    with pytest.raises(HTTPException, match="409"):
        facts.revoke_source(db_session, bed_case["super"], "census", row.source_record_id, {"expected_revision": 2, "reason": "终态不可再撤销"})
    draft = create(db_session, bed_case)
    facts.revoke_source(db_session, bed_case["director"], "census", draft.source_record_id, {"expected_revision": 1, "reason": "撤销本人尚未审核草稿"})
    db_session.commit()
    value = facts.source_current(db_session, bed_case["super"], "census", draft.source_record_id, audit_only=True)
    assert value["status"] == "revoked" and value["revision"] == 2 and value["reviewed_at"] is None


@pytest.mark.parametrize("action", ["create", "publish", "reject", "revoke"])
def test_source_and_sql_audit_one_transaction(db_session, bed_case, monkeypatch, action):
    row = None if action == "create" else create(db_session, bed_case)
    source_id = row.source_record_id if row is not None else None
    before = db_session.query(AIBedSource).count()

    def fail(*args, **kwargs):
        raise RuntimeError("synthetic audit insertion failure")

    monkeypatch.setattr(governance, "audit", fail)
    with pytest.raises(RuntimeError, match="audit"):
        if action == "create":
            facts.create_source(db_session, bed_case["director"], "census", request(bed_case))
        elif action in {"publish", "reject"}:
            facts.review_source(db_session, bed_case["super"], "census", source_id, {"expected_revision": 1, "expected_content_hash": row.content_hash, "decision": action, "review_basis_note": NOTE})
        else:
            facts.revoke_source(db_session, bed_case["director"], "census", source_id, {"expected_revision": 1, "reason": "合成撤销以验证同事务回滚"})
    db_session.rollback()
    assert db_session.query(AIBedSource).count() == before
    if source_id:
        assert facts.source_row(db_session, source_id).status == "draft"
