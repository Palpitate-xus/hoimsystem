"""Actual staffing originals preserve unknowns, hashes, scope and SQL governance."""

import datetime
import json
import uuid

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Query, Session

from app.ai import roster_facts as facts
from app.ai.models import AIFeatureConfig
from app.ai.roster_models import AIRosterSource
from app.models import Appointment, Attendance, Department, Doctor, DoctorSchedule, Registration, User

NOTE = "合成人员证据仅用于工程验证，已逐项核对本次原资料时刻身份和明确缺项状态，不代表外部事实已验证。"
NOW = datetime.datetime(2026, 10, 20, 9, 10, 11, 123456)
START = "2026-10-22T08:00:00.000000Z"
END = "2026-10-22T16:00:00.000000Z"


def limit(value=None, reason="unknown"):
    return {"value": value, "absent_reason": None if value is not None else reason}


def payload(kind):
    if kind == "qualification":
        return {
            "employment_status": "active",
            "qualification_status": "verified",
            "authorized_job_keys": ["general_clinic"],
            "valid_from_at": "2026-01-01T00:00:00Z",
            "valid_until_at": "2026-12-31T00:00:00Z",
            "expiry_status": "known",
            "evidence_basis_note": NOTE,
        }
    if kind == "duty_interval":
        return {
            "start_at": START,
            "end_at": END,
            "commitment_status": "committed",
            "work_location": "external",
            "job_key": None,
            "job_key_absent_reason": "unknown",
            "breaks": [{"start_at": "2026-10-22T12:00:00Z", "end_at": "2026-10-22T12:30:00Z", "counted_as_work": False, "counted_as_work_absent_reason": None}],
            "breaks_complete": True,
            "time_accounting_status": "verified",
            "evidence_basis_note": NOTE,
        }
    if kind == "availability":
        return {"start_at": START, "end_at": END, "availability": "unknown", "basis_kind": "staff_declaration", "evidence_basis_note": NOTE}
    return {
        "effective_from_at": "2026-01-01T00:00:00Z",
        "effective_until_at": None,
        "effective_until_absent_reason": "unknown",
        "max_single_duty_presence_minutes": limit(0),
        "max_work_minutes_rolling_24h": limit(480),
        "max_work_minutes_rolling_7d": limit(),
        "minimum_rest_minutes": limit(None, "not_applicable"),
        "fixed_work_windows": [{"start_at": "2026-10-19T00:00:00Z", "end_at": "2026-10-26T00:00:00Z", "minimum_work_minutes": limit(0), "maximum_work_minutes": limit(2400)}],
        "policy_reference": "合成本地工时政策原件，不作为通用劳动规则",
        "evidence_basis_note": NOTE,
    }


@pytest.fixture
def roster_case(seed_data, db_session, monkeypatch):
    db_session.query(AIRosterSource).delete()
    db_session.query(AIFeatureConfig).filter_by(feature_key="roster_optimization").delete()
    foreign = Department(name="排班隔离科室" + uuid.uuid4().hex[:6])
    db_session.add(foreign)
    db_session.flush()
    outsider = Doctor(name="外科原医生", department_id=foreign.department_id)
    unscheduled = Doctor(name="无周期排班仍须纳入", department_id=seed_data["department"].department_id, title="职称不代表资格")
    # The reusable baseline deliberately retains earlier affiliations. A separate
    # real actor gives this case one exact current department without erasing them.
    director = User(username="rdir" + uuid.uuid4().hex[:12], password=seed_data["director_user"].password, user_role="director")
    db_session.add(director)
    db_session.flush()
    director_person = Doctor(name="合成排班负责人", department_id=seed_data["department"].department_id, user_id=director.user_id)
    db_session.add_all([outsider, unscheduled, director_person])
    db_session.commit()
    monkeypatch.setattr(facts, "utcnow", lambda: NOW)
    return {
        "seed": seed_data,
        "department": seed_data["department"],
        "doctor": seed_data["doctor"],
        "director": director,
        "admin": seed_data["admin_user"],
        "super": seed_data["super_admin_user"],
        "foreign": foreign,
        "outsider": outsider,
        "unscheduled": unscheduled,
    }


def request(case, kind="qualification"):
    return {"department_id": case["department"].department_id, "doctor_id": None if kind == "work_rule_policy" else case["doctor"].doctor_id, "payload": payload(kind)}


def create(db, case, kind="qualification", actor=None):
    row = facts.create_source(db, actor or case["director"], kind, request(case, kind))
    db.commit()
    return row


def publish(db, case, row, decision="publish"):
    facts.review_source(db, case["super"], row.source_kind, row.source_record_id, {"expected_revision": 1, "expected_content_hash": row.content_hash, "decision": decision, "review_basis_note": NOTE})
    db.commit()
    return row


@pytest.mark.parametrize("kind", facts.KINDS)
def test_actual_four_original_kinds_complete_proof_publish_and_microsecond_clock(db_session, roster_case, kind):
    case = roster_case
    row = create(db_session, case, kind)
    original = row.payload_json, row.parent_binding_json, row.content_hash
    value = facts.source_current(db_session, case["director"], kind, row.source_record_id)
    assert value["status"] == "draft" and value["revision"] == 1 and value["eligible"] is False
    assert value["payload"] is not None and value["recorded_at"].endswith(".123456Z")
    assert value["source_id"] == facts.PREFIXES[kind] + ":" + row.source_record_id + ":" + row.content_hash[:12]
    assert facts.hash_content(facts.immutable_body(row, value["payload"], value["parent_binding"])) == row.content_hash
    with pytest.raises(HTTPException, match="409"):
        facts.authorize_source(db_session, case["director"], kind, row.source_record_id)
    publish(db_session, case, row)
    current = facts.authorize_source(db_session, case["director"], kind, row.source_record_id, as_of="2026-10-20T09:10:11.123456Z")
    assert current["eligible"] is True and current["revision"] == 2
    assert original == (row.payload_json, row.parent_binding_json, row.content_hash)
    assert current["governance_hash"] != value["governance_hash"]
    with pytest.raises(HTTPException, match="409"):
        facts.authorize_source(db_session, case["super"], kind, row.source_record_id, as_of="2026-10-20T09:10:11.123455Z")


def test_unknown_zero_false_and_external_duty_remain_exact_originals(db_session, roster_case):
    case = roster_case
    rows = {kind: create(db_session, case, kind) for kind in facts.KINDS}
    duty = json.loads(rows["duty_interval"].payload_json)
    assert duty["breaks"][0]["counted_as_work"] is False
    assert duty["work_location"] == "external" and duty["job_key"] is None
    assert json.loads(rows["availability"].payload_json)["availability"] == "unknown"
    policy = json.loads(rows["work_rule_policy"].payload_json)
    assert policy["max_single_duty_presence_minutes"] == {"value": 0, "absent_reason": None}
    assert policy["max_work_minutes_rolling_7d"] == limit()
    assert policy["minimum_rest_minutes"] == limit(None, "not_applicable")


@pytest.mark.parametrize(
    "field,value",
    [
        ("employment_status", True),
        ("expiry_status", "permanent"),
        ("authorized_job_keys", ["general_clinic", "general_clinic"]),
        ("valid_from_at", "2026-01-01 00:00:00"),
        ("valid_from_at", "9999-12-31T23:59:59-23:59"),
        ("valid_until_at", None),
    ],
)
def test_qualification_rejects_coercion_unknown_clock_duplicate_jobs_and_missing_expiry(field, value):
    data = payload("qualification")
    data[field] = value
    with pytest.raises(ValidationError):
        facts.QualificationPayload.model_validate(data)


@pytest.mark.parametrize("value,reason", [(False, None), (1.0, None), ("0", None), (-1, None), (None, None), (0, "unknown")])
def test_constraint_value_never_coerces_or_fills_zero(value, reason):
    with pytest.raises(ValidationError):
        facts.ConstraintValue.model_validate({"value": value, "absent_reason": reason})


def test_minutes_preserve_exact_cross_runtime_microsecond_bound():
    maximum = facts.ConstraintValue(value=facts.MAX_CONSTRAINT_MINUTES, absent_reason=None)
    assert maximum.value * 60000000 <= 9007199254740991
    assert (maximum.value + 1) * 60000000 > 9007199254740991
    with pytest.raises(ValidationError):
        facts.ConstraintValue(value=maximum.value + 1, absent_reason=None)


@pytest.mark.parametrize("change", ["outside", "overlap", "reverse", "not_complete", "unknown_break", "naive_clock"])
def test_duty_true_intervals_complete_breaks_and_accounting_are_explicit(change):
    data = payload("duty_interval")
    if change == "outside":
        data["breaks"][0]["start_at"] = "2026-10-22T07:00:00Z"
    elif change == "overlap":
        data["breaks"].append(dict(data["breaks"][0]))
    elif change == "reverse":
        data["end_at"] = data["start_at"]
    elif change == "not_complete":
        data["breaks_complete"] = False
    elif change == "unknown_break":
        data["breaks"][0].update(counted_as_work=None, counted_as_work_absent_reason="unknown")
    else:
        data["start_at"] = "2026-10-22T08:00:00"
    with pytest.raises(ValidationError):
        facts.DutyIntervalPayload.model_validate(data)


def test_unknown_break_accounting_may_be_saved_as_unknown_without_imputation():
    data = payload("duty_interval")
    data["breaks"][0].update(counted_as_work=None, counted_as_work_absent_reason="unknown")
    data.update(time_accounting_status="unknown", breaks_complete=False)
    result = facts.DutyIntervalPayload.model_validate(data)
    assert result.breaks[0].counted_as_work is None and result.breaks_complete is False


@pytest.mark.parametrize("change", ["min_above_max", "year_plus", "too_many", "unsupported_rule", "missing_windows"])
def test_actual_fixed_work_windows_and_unsupported_policy_are_never_silently_reinterpreted(change):
    data = payload("work_rule_policy")
    if change == "min_above_max":
        data["fixed_work_windows"][0]["minimum_work_minutes"] = limit(2401)
    elif change == "year_plus":
        data["fixed_work_windows"][0].update(start_at="2026-01-01T00:00:00Z", end_at="2027-01-03T00:00:00Z")
    elif change == "too_many":
        data["fixed_work_windows"] *= 65
    elif change == "unsupported_rule":
        data["max_consecutive_local_work_days"] = 5
    else:
        data.pop("fixed_work_windows")
    with pytest.raises(ValidationError):
        facts.WorkRulePolicyPayload.model_validate(data)


def test_complete_ended_work_not_future_completion_and_unknown_job_reason(db_session, roster_case):
    case = roster_case
    values = request(case, "duty_interval")
    values["payload"]["commitment_status"] = "completed"
    with pytest.raises(HTTPException, match="422"):
        facts.create_source(db_session, case["director"], "duty_interval", values)
    values["payload"]["start_at"] = "2026-10-19T08:00:00Z"
    values["payload"]["end_at"] = "2026-10-19T16:00:00Z"
    values["payload"]["breaks"] = []
    row = facts.create_source(db_session, case["director"], "duty_interval", values)
    assert facts.source_proof(row)[0]["commitment_status"] == "completed"


def test_options_includes_real_people_without_schedule_and_no_title_credential_inference(db_session, roster_case):
    case = roster_case
    result = facts.options(db_session, case["director"], case["department"].department_id)
    assert case["unscheduled"].doctor_id in {item["doctor_id"] for item in result["doctors"]}
    assert case["outsider"].doctor_id not in {item["doctor_id"] for item in result["doctors"]}
    assert result["personnel_collection_complete_in_database"] is True and result["personnel_qualification_verified"] is False
    assert result["provider_required"] is False


def test_cross_department_creation_forbidden_even_with_admin_staff_id_bypass(db_session, roster_case):
    case = roster_case
    with pytest.raises(HTTPException, match="403"):
        facts.options(db_session, case["director"], case["foreign"].department_id)
    values = request(case)
    values["doctor_id"] = case["outsider"].doctor_id
    with pytest.raises(HTTPException, match="409"):
        facts.create_source(db_session, case["admin"], "qualification", values)
    with pytest.raises(HTTPException, match="403"):
        facts.create_source(db_session, case["seed"]["doctor_user"], "qualification", request(case))


def test_current_role_config_is_independent_of_provider_enabled_and_historical_author_role(db_session, roster_case):
    case = roster_case
    row = publish(db_session, case, create(db_session, case))
    config = AIFeatureConfig(feature_key="roster_optimization", enabled=0, allowed_roles_json='["admin"]', updated_by=case["super"].user_id)
    db_session.add(config)
    db_session.commit()
    with pytest.raises(HTTPException, match="403"):
        facts.source_current(db_session, case["director"], "qualification", row.source_record_id)
    assert facts.authorize_source(db_session, case["admin"], "qualification", row.source_record_id)["eligible"] is True
    case["director"].user_role = "doctor"
    db_session.commit()
    assert facts.authorize_source(db_session, case["super"], "qualification", row.source_record_id)["eligible"] is True


def test_transferred_subject_redacts_ordinary_but_super_frozen_and_revoke_preserve_body(db_session, roster_case):
    case = roster_case
    row = publish(db_session, case, create(db_session, case))
    original = row.payload_json, row.parent_binding_json, row.content_hash
    case["doctor"].department_id = case["foreign"].department_id
    db_session.commit()
    ordinary = facts.source_current(db_session, case["director"], "qualification", row.source_record_id)
    assert ordinary["payload"] is ordinary["parent_binding"] is None
    assert ordinary["review_basis_note"] is ordinary["revoke_reason"] is None
    assert ordinary["can_record"] is ordinary["can_revoke"] is ordinary["eligible"] is False
    frozen = facts.source_current(db_session, case["super"], "qualification", row.source_record_id, audit_only=True)
    assert frozen["payload"] is not None and frozen["parent_current"] is False and frozen["can_revoke"] is True
    assert frozen["review_basis_note"] == NOTE and frozen["revoke_reason"] == ""
    with pytest.raises(HTTPException, match="409"):
        facts.review_source(
            db_session, case["super"], "qualification", row.source_record_id, {"expected_revision": 1, "expected_content_hash": row.content_hash, "decision": "publish", "review_basis_note": NOTE}
        )
    facts.revoke_source(db_session, case["super"], "qualification", row.source_record_id, {"expected_revision": 2, "reason": "合成转科后停止供新计划使用"})
    db_session.commit()
    assert row.revision == 3 and original == (row.payload_json, row.parent_binding_json, row.content_hash)


@pytest.mark.parametrize("column", ["content_hash", "payload_json", "parent_binding_json", "created_by"])
def test_bad_own_proof_is_never_frozen_or_revoked_as_intact_even_for_super(db_session, roster_case, column):
    case = roster_case
    row = create(db_session, case)
    if column == "content_hash":
        row.content_hash = "0" * 64
    elif column == "payload_json":
        row.payload_json = row.payload_json + " "
    elif column == "parent_binding_json":
        row.parent_binding_json = "{}"
    else:
        row.created_by = case["super"].user_id
    db_session.commit()
    with pytest.raises(HTTPException, match="409"):
        facts.source_current(db_session, case["super"], "qualification", row.source_record_id, audit_only=True)
    with pytest.raises(HTTPException, match="409"):
        facts.revoke_source(db_session, case["super"], "qualification", row.source_record_id, {"expected_revision": 1, "reason": "不接受损坏原件"})


def test_rejected_is_final_and_cas_replay_does_not_rewrite_original(db_session, roster_case):
    case = roster_case
    row = publish(db_session, case, create(db_session, case), decision="reject")
    assert row.status == "rejected" and row.revision == 2
    assert facts.source_current(db_session, case["director"], "qualification", row.source_record_id)["payload"] is None
    with pytest.raises(HTTPException, match="409"):
        facts.revoke_source(db_session, case["super"], "qualification", row.source_record_id, {"expected_revision": 2, "reason": "终态不能重用"})


def test_review_note_complete_utf8_sql_bound_and_no_space_only_evidence():
    with pytest.raises(ValidationError):
        facts.SourceReview(expected_revision=1, expected_content_hash="a" * 64, decision="publish", review_basis_note="合" * 1334)
    with pytest.raises(ValidationError):
        facts.QualificationPayload.model_validate({**payload("qualification"), "evidence_basis_note": " " * 100})
    assert len(facts.SourceReview(expected_revision=1, expected_content_hash="a" * 64, decision="publish", review_basis_note="a" * 4000).review_basis_note) == 4000


def test_real_sql_cas_rejects_state_changed_after_application_precheck(db_session, roster_case, monkeypatch):
    case = roster_case
    row = create(db_session, case)
    identifier, content_hash = row.source_record_id, row.content_hash
    values = {"expected_revision": 1, "expected_content_hash": content_hash, "decision": "publish", "review_basis_note": NOTE}
    original_update = Query.update
    raced = []

    def update_after_another_transaction(query, *args, **kwargs):
        if not raced and query.column_descriptions[0].get("entity") is AIRosterSource:
            raced.append(True)
            with Session(bind=db_session.get_bind()) as other:
                facts.review_source(other, case["super"], "qualification", identifier, values)
                other.commit()
        return original_update(query, *args, **kwargs)

    monkeypatch.setattr(Query, "update", update_after_another_transaction)
    with pytest.raises(HTTPException, match="409"):
        facts.review_source(db_session, case["super"], "qualification", identifier, values)
    db_session.rollback()
    current = facts.source_row(db_session, identifier, "qualification")
    assert raced == [True] and current.status == "published" and current.revision == 2
    from app.ai.models import AIAuditEvent

    assert db_session.query(AIAuditEvent).filter_by(target=identifier, action="roster_source.publish").count() == 1


def test_fact_governance_does_not_mutate_any_original_staff_schedule_attendance_or_booking_row(db_session, roster_case):
    case = roster_case
    legacy = (Doctor, Department, DoctorSchedule, Attendance, Appointment, Registration)

    def original_rows():
        return {model.__tablename__: sorted(repr(tuple(row)) for row in db_session.execute(select(model.__table__)).all()) for model in legacy}

    before = original_rows()
    for kind in facts.KINDS:
        row = publish(db_session, case, create(db_session, case, kind))
        facts.revoke_source(db_session, case["super"], kind, row.source_record_id, {"expected_revision": 2, "reason": "合成原件生命周期保持旧临床与排班资料不变"})
        db_session.commit()
    assert original_rows() == before
