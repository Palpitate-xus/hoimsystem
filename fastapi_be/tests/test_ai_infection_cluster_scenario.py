"""Actual synthetic SQL Source→Department→independent Scenario governance."""

from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import event, text

from app.ai import infection_cluster_contract as c
from app.ai import infection_cluster_registry as r
from app.ai import infection_cluster_scenario as s
from app.ai import infection_cluster_sources as sources
from app.ai import infection_cluster_statistics as engine
from app.ai import infection_cluster_statistics_contract as k
from app.ai.infection_cluster_models import AIInfectionSnapshot
from app.ai.infection_cluster_scenario_models import AIInfectionScenario
from app.ai.models import AIAuditEvent, AIFeatureConfig
from app.models import Department, User
from tests.test_ai_infection_cluster_sources import NOTE, cas, infection_case, publish


@pytest.fixture
def scenario_case(db_session, seed_data, monkeypatch):
    db_session.query(AIInfectionScenario).delete(synchronize_session=False)
    db_session.commit()
    actual = infection_case.__wrapped__(db_session, seed_data, monkeypatch)
    db, author, reviewer, patient, row = actual
    department = db.query(Department).order_by(Department.department_id).first()
    zero = db.query(Department).filter_by(name="明确零病例科室").one_or_none()
    if zero is None:
        zero = Department(name="明确零病例科室")
        db.add(zero)
    row.department_id, row.pathogen = department.department_id, "原病原"
    db.commit()
    grants = []
    for actor in (author, reviewer):
        value = r.create_grant(
            db,
            author,
            dict(
                patient_id=patient.patient_id,
                user_id=actor.user_id,
                purpose="infection_surveillance_processing",
                valid_from="2026-10-01T00:00:00.000000Z",
                valid_to="2026-11-01T00:00:00.000000Z",
                basis_note=NOTE,
            ),
        )
        db.commit()
        grants.append(publish(db, reviewer, value))
    definition = r.create_definition(db, author, dict(version_label="明确本地定义v1", definition_text="只用于合成工程，非院感诊断依据。", infection_type_codes=[], pathogen_codes=["LOCAL_P"]))
    db.commit()
    definition = publish(db, reviewer, definition)
    req = dict(
        patient_ids=[patient.patient_id],
        definition_id=definition.record_id,
        window=dict(date_from="2026-10-01", date_to="2026-10-21", coordinate_basis="recorded_onset_date_inclusive_no_event_timezone"),
    )
    preview = sources.preview_roots(db, author, req)
    raw = preview["originals"][0]
    proposal = dict(
        case_id=row.case_id,
        original_content_hash=raw["content_hash"],
        definition_id=definition.record_id,
        definition_content_hash=preview["definition"]["content_hash"],
        definition_governance_hash=preview["definition"]["governance_hash"],
        assessment="meets_definition",
        basis_note=NOTE,
    )
    for field in ("infection_type", "pathogen"):
        proposal[field] = dict(
            original_state=c.value_state(raw["original"][field]),
            original_value_hash=c.digest(raw["original"][field]),
            assessment="mapped" if field == "pathogen" else "not_mapped",
            reviewed_code="LOCAL_P" if field == "pathogen" else None,
            basis_note=NOTE,
        )
    review = r.create_case_review(db, author, proposal)
    db.commit()
    publish(db, reviewer, review)
    meta = sources.create_snapshot(db, author, req)
    db.commit()
    public = sources.snapshot_part(db, author, meta["snapshot_id"], "public")["value"]
    create = dict(
        source_binding=dict(
            snapshot_id=meta["snapshot_id"], source_id=public["source_id"], private_collection_hash=meta["private_hash"], public_source_hash=meta["public_hash"], witness_hash=meta["witness_hash"]
        ),
        department_ids=[department.department_id, zero.department_id],
        windows=[dict(date_from="2026-10-09", date_to="2026-10-11", coordinate_basis="recorded_onset_date_inclusive_no_event_timezone")],
        pathogen_code="LOCAL_P",
        alpha_decimal="0.0500",
        basis_note=NOTE,
    )
    yield dict(db=db, author=author, reviewer=reviewer, patient=patient, row=row, grants=grants, meta=meta, public=public, create=create, department=department, zero=zero)
    db.rollback()
    db.query(AIInfectionScenario).delete(synchronize_session=False)
    db.query(AIAuditEvent).filter(AIAuditEvent.action.like("infection.scenario.%")).delete(synchronize_session=False)
    db.commit()


def draft(case):
    value = s.create_scenario(case["db"], case["author"], case["create"])
    case["db"].commit()
    return value


def publish_scenario(case, value, **extra):
    result = s.review_scenario(
        case["db"],
        case["reviewer"],
        value.scenario_id,
        {**cas(value), "decision": "publish", "privacy_review": "confirmed", "faithfulness_review": "confirmed", "parameters_review": "confirmed", **extra},
    )
    case["db"].commit()
    return result


def body_queries(sql):
    return [
        q
        for q in sql
        if q.lstrip().startswith("SELECT")
        and (
            "hoimsystem_ai_infection_scenario.payload_json" in q
            or "hoimsystem_ai_infection_scenario.review_basis" in q
            or "hoimsystem_ai_infection_snapshot.private_json" in q
            or "hoimsystem_infection_case.description" in q
        )
    ]


def observe(case, function):
    sql = []

    def capture(conn, cursor, query, parameters, context, many):
        sql.append(query)

    event.listen(case["db"].get_bind(), "before_cursor_execute", capture)
    try:
        result = function()
    finally:
        event.remove(case["db"].get_bind(), "before_cursor_execute", capture)
    return result, sql


def test_actual_current_zero_record_department_complete_family_and_independent_publication(scenario_case):
    case = scenario_case
    value = draft(case)
    assert value.governance.revision == 1 and not value.eligible
    before = case["db"].query(AIAuditEvent).count()
    with pytest.raises(HTTPException):
        s.review_scenario(
            case["db"], case["author"], value.scenario_id, {**cas(value), "decision": "publish", "privacy_review": "confirmed", "faithfulness_review": "confirmed", "parameters_review": "confirmed"}
        )
    assert case["db"].query(AIAuditEvent).count() == before
    value = publish_scenario(case, value)
    assert value.eligible and value.governance.review_event_id != value.governance.create_event_id
    assert value.governance.created_by != value.governance.reviewed_by
    assert value.payload.plan.alpha_decimal == "0.0500" and len(value.payload.departments) == 2
    assert value.payload.plan.department_tokens[0] == case["public"]["reports"][0]["department_token"]
    assert value.payload.departments[1].department_id == case["zero"].department_id
    assert value.publication_does_not_enable_execution is True
    stats = k.StatisticsInput(
        schema_version="infection_statistics_input_v1",
        source=case["public"],
        scenario=value.payload.plan,
        scenario_content_hash=value.payload.plan_hash,
        scenario_governance_hash=value.governance_hash,
        recipe_hash=value.payload.recipe_hash,
        authority_basis="pure_structure_and_arithmetic_only_server_must_verify_current_authority",
    )
    result = engine.evaluate(stats)
    assert result.family_size == 2 and all(c.status == "no_information" for c in result.candidates)
    assert result.candidates[1].table.window_in_department == 0
    assert "mapping_key" not in c.canonical(value)


def test_parameter_only_rejection_cas_and_revoke_are_actual_sql(scenario_case):
    case = scenario_case
    value = draft(case)
    with pytest.raises(HTTPException):
        publish_scenario(case, value, expected_content_hash="e" * 64)
    rejected = s.review_scenario(
        case["db"], case["reviewer"], value.scenario_id, {**cas(value), "decision": "reject", "privacy_review": "confirmed", "faithfulness_review": "confirmed", "parameters_review": "not_confirmed"}
    )
    case["db"].commit()
    assert rejected.governance.status == "rejected" and not rejected.eligible
    result = s.revoke_scenario(case["db"], case["reviewer"], value.scenario_id, cas(rejected))
    case["db"].commit()
    assert result["status"] == "revoked" and result["revision"] == 3 and not result["can_execute"]
    with pytest.raises(HTTPException):
        s.scenario_current(case["db"], case["author"], value.scenario_id, execution=True)


@pytest.mark.parametrize("mutation", ["source_hash", "unknown_code", "missing_department", "outside_window"])
def test_current_source_and_real_directory_required_before_any_draft_or_audit(scenario_case, mutation):
    import copy

    case = scenario_case
    request = copy.deepcopy(case["create"])
    if mutation == "source_hash":
        request["source_binding"]["witness_hash"] = "c" * 64
    elif mutation == "unknown_code":
        request["pathogen_code"] = "NOT_DECLARED"
    elif mutation == "missing_department":
        request["department_ids"] = [2147483647]
    else:
        request["windows"][0]["date_to"] = "2026-10-22"
    before = case["db"].query(AIAuditEvent).count()
    with pytest.raises((ValueError, HTTPException)):
        s.create_scenario(case["db"], case["author"], request)
    assert case["db"].query(AIInfectionScenario).count() == 0
    assert case["db"].query(AIAuditEvent).count() == before


@pytest.mark.parametrize("operation", ["read", "review", "revoke"])
def test_purpose_withdrawal_even_super_denies_before_source_or_scenario_body(scenario_case, operation):
    case = scenario_case
    value = draft(case)
    r.revoke_record(case["db"], case["reviewer"], "grant", case["grants"][0].record_id, cas(case["grants"][0]))
    case["db"].commit()

    def denied():
        with pytest.raises(HTTPException) as error:
            if operation == "read":
                s.scenario_current(case["db"], case["author"], value.scenario_id)
            elif operation == "review":
                s.review_scenario(
                    case["db"],
                    case["author"],
                    value.scenario_id,
                    {**cas(value), "decision": "publish", "privacy_review": "confirmed", "faithfulness_review": "confirmed", "parameters_review": "confirmed"},
                )
            else:
                s.revoke_scenario(case["db"], case["author"], value.scenario_id, cas(value))
        assert error.value.status_code == 403

    _, sql = observe(case, denied)
    assert body_queries(sql) == []
    directory, sql = observe(case, lambda: s.scenario_directory(case["db"], case["author"]))
    assert directory["items"][0]["content_hash"] == value.content_hash and body_queries(sql) == []


@pytest.mark.parametrize("mutation", ["department_name", "original_status", "audit_deleted", "header_rebound", "implementation"])
def test_parent_changes_or_forged_header_do_not_read_old_scenario_payload(scenario_case, mutation, monkeypatch):
    case = scenario_case
    value = draft(case)
    rid = value.scenario_id
    if mutation == "department_name":
        case["department"].name = "已改变的真实科室名称"
    elif mutation == "original_status":
        case["row"].status = -17
    elif mutation == "audit_deleted":
        case["db"].query(AIAuditEvent).filter_by(event_id=value.governance.create_event_id).delete(synchronize_session=False)
    elif mutation == "header_rebound":
        case["db"].query(AIInfectionScenario).filter_by(scenario_id=rid).update({"source_witness_hash": "c" * 64}, synchronize_session=False)
    else:
        old = s.implementation_descriptor()
        monkeypatch.setattr(s, "implementation_descriptor", lambda: {**old, "version": "changed_without_approval"})
    case["db"].commit()

    def denied():
        with pytest.raises(HTTPException):
            s.scenario_current(case["db"], case["author"], rid)

    _, sql = observe(case, denied)
    assert not any("hoimsystem_ai_infection_scenario.payload_json" in q for q in sql)


def test_author_epoch_and_current_execution_roles_are_not_replaced_by_reloaded_actor(scenario_case):
    case = scenario_case
    value = publish_scenario(case, draft(case))
    db = case["db"]
    db.add(AIFeatureConfig(feature_key="infection_cluster", allowed_roles_json='["admin"]', updated_by=case["author"].user_id, enabled=0, revision=1))
    db.commit()

    def denied():
        with pytest.raises(HTTPException) as error:
            s.scenario_current(db, case["author"], value.scenario_id, execution=True)
        assert error.value.status_code == 403

    _, sql = observe(case, denied)
    assert body_queries(sql) == []
    uid = case["author"].user_id
    db.query(User).filter_by(user_id=uid).update({"token_invalid_before": r.utcnow()}, synchronize_session=False)
    db.commit()
    fresh = SimpleNamespace(user_id=uid, user_role="super_admin", token_invalid_before=r.utcnow())

    def epoch_denied():
        with pytest.raises(HTTPException):
            s.scenario_current(db, fresh, value.scenario_id)

    _, sql = observe(case, epoch_denied)
    assert body_queries(sql) == []


@pytest.mark.parametrize("fault", ["stored_plan", "delete_audit"])
def test_actual_after_write_fault_rolls_back_scenario_and_exact_audit(scenario_case, fault):
    case = scenario_case
    db = case["db"]
    before = db.query(AIAuditEvent).count()
    if fault == "stored_plan":
        trigger = (
            "CREATE TRIGGER scenario_fault AFTER INSERT ON hoimsystem_ai_infection_scenario BEGIN UPDATE hoimsystem_ai_infection_scenario SET plan_hash='"
            + "e" * 64
            + "' WHERE scenario_id=NEW.scenario_id; END"
        )
    else:
        trigger = "CREATE TRIGGER scenario_fault AFTER INSERT ON hoimsystem_ai_infection_scenario BEGIN DELETE FROM hoimsystem_ai_audit_event WHERE event_id=NEW.create_event_id; END"
    db.execute(text(trigger))
    db.commit()
    try:
        with pytest.raises(HTTPException):
            s.create_scenario(db, case["author"], case["create"])
        assert db.query(AIInfectionScenario).count() == 0 and db.query(AIAuditEvent).count() == before
    finally:
        db.rollback()
        db.execute(text("DROP TRIGGER scenario_fault"))
        db.commit()


def test_same_source_department_mapping_does_not_bind_mutable_phone_or_director(scenario_case):
    case = scenario_case
    value = draft(case)
    case["department"].phone = "01012345678"
    case["department"].director = 2147483647
    case["db"].commit()
    full = s.scenario_current(case["db"], case["author"], value.scenario_id)
    assert full.payload.departments == value.payload.departments
    stored = case["db"].get(AIInfectionSnapshot, case["meta"]["snapshot_id"])
    assert stored.mapping_key.hex() not in c.canonical(full)


def test_business_directory_requires_explicit_snapshot_and_current_processing_purpose(scenario_case):
    case = scenario_case
    full = publish_scenario(case, draft(case))
    actor = case["db"].query(User).filter_by(user_role="admin").first()
    with pytest.raises(HTTPException) as missing:
        s.scenario_directory(case["db"], actor)
    assert missing.value.status_code == 422
    grant = r.create_grant(
        case["db"],
        case["author"],
        dict(
            patient_id=case["patient"].patient_id,
            user_id=actor.user_id,
            purpose="infection_surveillance_processing",
            valid_from="2026-10-01T00:00:00.000000Z",
            valid_to="2026-11-01T00:00:00.000000Z",
            basis_note=NOTE,
        ),
    )
    case["db"].commit()
    publish(case["db"], case["reviewer"], grant)
    value, sql = observe(case, lambda: s.scenario_directory(case["db"], actor, snapshot_id=case["meta"]["snapshot_id"]))
    assert value["total"] == 1 and value["items"][0]["scenario_id"] == full.scenario_id
    assert body_queries(sql) == []
    assert s.scenario_current(case["db"], actor, full.scenario_id).eligible


def test_actual_revoke_trigger_changes_actor_epoch_rollback_instead_of_committing_old_request(scenario_case):
    case = scenario_case
    full = publish_scenario(case, draft(case))
    db = case["db"]
    uid = case["reviewer"].user_id
    before = db.query(AIAuditEvent).count()
    db.execute(
        text(
            f"CREATE TRIGGER scenario_revoke_epoch AFTER UPDATE ON hoimsystem_ai_infection_scenario WHEN NEW.status='revoked' BEGIN UPDATE hoimsystem_users SET token_invalid_before='2026-10-21 12:00:01.123456' WHERE user_id={uid}; END"
        )
    )
    db.commit()
    try:
        with pytest.raises(HTTPException):
            s.revoke_scenario(db, case["reviewer"], full.scenario_id, cas(full))
        assert db.get(AIInfectionScenario, full.scenario_id).status == "published"
        assert db.query(AIAuditEvent).count() == before
        assert db.get(User, uid).token_invalid_before is None
    finally:
        db.rollback()
        db.execute(text("DROP TRIGGER scenario_revoke_epoch"))
        db.commit()
