"""Actual local-profile publication/configuration; all validation evidence synthetic."""

import copy

import pytest
from fastapi import HTTPException
from sqlalchemy import event, text

from app.ai import infection_cluster_contract as c
from app.ai import infection_cluster_profiles as p
from app.ai import infection_cluster_registry as r
from app.ai.infection_cluster_models import AIInfectionSnapshot
from app.ai.infection_cluster_profile_models import AIInfectionLocalProfile, AIInfectionLocalSelection
from app.ai.models import AIAuditEvent, AIFeatureConfig
from app.models import User
from tests.test_ai_infection_cluster_profile_foundation import request
from tests.test_ai_infection_cluster_scenario import scenario_case
from tests.test_ai_infection_cluster_sources import NOTE, cas


@pytest.fixture
def profile_case(db_session, seed_data, monkeypatch):
    db = db_session
    db.query(AIInfectionLocalSelection).delete(synchronize_session=False)
    db.query(AIInfectionLocalProfile).delete(synchronize_session=False)
    db.query(AIFeatureConfig).filter_by(feature_key=p.KEY).delete(synchronize_session=False)
    db.query(AIAuditEvent).filter(AIAuditEvent.action.like("infection.local_%")).delete(synchronize_session=False)
    db.commit()
    generator = scenario_case.__wrapped__(db_session, seed_data, monkeypatch)
    case = next(generator)
    snapshot = db.get(AIInfectionSnapshot, case["meta"]["snapshot_id"])
    definition, _ = r.definition_current(db, snapshot.definition_id)
    value = request()
    value["scope"].update(
        definition_id=definition.record_id, definition_content_hash=definition.content_hash, definition_governance_hash=definition.governance_hash, department_ids=case["create"]["department_ids"]
    )
    case["profile_request"] = value
    yield case
    db.rollback()
    db.query(AIInfectionLocalSelection).delete(synchronize_session=False)
    db.query(AIInfectionLocalProfile).delete(synchronize_session=False)
    db.query(AIFeatureConfig).filter_by(feature_key=p.KEY).delete(synchronize_session=False)
    db.query(AIAuditEvent).filter(AIAuditEvent.action.like("infection.local_%")).delete(synchronize_session=False)
    db.commit()
    with pytest.raises(StopIteration):
        next(generator)


def create(case, *, validated=False):
    req = copy.deepcopy(case["profile_request"])
    if validated:
        req.update(
            validation_status="validated",
            validation_evidence_reference="synthetic-only:not-a-hospital-clinical-validation",
            validation_basis_note="显式合成记录只测试权限状态机；没有真实本地临床验证。",
        )
    out = p.create_profile(case["db"], case["author"], req)
    case["db"].commit()
    return out


def publish(case, value):
    result = p.review_profile(
        case["db"], case["reviewer"], value.profile_id, {**cas(value), "decision": "publish", "privacy_review": "confirmed", "faithfulness_review": "confirmed", "parameters_review": "confirmed"}
    )
    case["db"].commit()
    return result


def configuration_request(profile_id=None, **extra):
    return dict(
        expected_feature_revision=0,
        expected_selection_revision=0,
        profile_id=profile_id,
        enabled=False,
        allowed_roles=["super_admin", "admin", "director"],
        validation_status="unreviewed",
        validation_note=None,
        daily_limit=20,
        basis_note=NOTE,
        **extra,
    )


def save(case, req):
    value = p.configure(case["db"], case["author"], req)
    case["db"].commit()
    return value


def test_actual_independent_publication_does_not_validate_enable_or_create_provider(profile_case):
    case = profile_case
    full = create(case)
    assert not full.eligible and full.current_issues == ["not_published"]
    with pytest.raises(HTTPException):
        p.review_profile(
            case["db"], case["author"], full.profile_id, {**cas(full), "decision": "publish", "privacy_review": "confirmed", "faithfulness_review": "confirmed", "parameters_review": "confirmed"}
        )
    full = publish(case, full)
    assert full.eligible and full.payload.validation_status == "unreviewed"
    assert full.governance.create_event_id != full.governance.review_event_id
    assert case["db"].get(AIFeatureConfig, p.KEY) is None
    current = save(case, configuration_request(full.profile_id))
    assert not current["enabled"] and current["provider_id"] is None
    assert current["profile"]["payload"]["expected_implementation_hash"] == c.digest(p.implementation_descriptor())
    assert case["db"].get(AIFeatureConfig, p.KEY).provider_id is None
    # Preview bypasses activation/validation only; this helper grants no Source
    # rights. The dedicated Task must still establish every patient's purpose.
    assert p.execution_configuration(case["db"], case["author"], preview=True)[3].profile_id == full.profile_id
    with pytest.raises(HTTPException):
        p.execution_configuration(case["db"], case["author"], preview=False)


def test_recorded_validated_configuration_requires_explicit_enable_and_both_cas(profile_case):
    case = profile_case
    full = publish(case, create(case, validated=True))
    first = save(case, configuration_request(full.profile_id))
    with pytest.raises(HTTPException):
        p.configure(case["db"], case["author"], configuration_request(full.profile_id))
    req = configuration_request(full.profile_id)
    req.update(
        expected_feature_revision=first["feature_revision"],
        expected_selection_revision=first["selection_revision"],
        enabled=True,
        validation_status="validated",
        validation_note="仅合成工程状态机依据，不构成真实医院临床验证。",
    )
    result = save(case, req)
    assert result["enabled"] and result["validation_status"] == "validated"
    assert p.execution_configuration(case["db"], case["author"])[1].revision == 2
    config = case["db"].get(AIFeatureConfig, p.KEY)
    assert config.update_time.microsecond == config.validated_at.microsecond == 0
    assert config.update_time == r.utcnow().replace(microsecond=0)


def test_unreviewed_profile_cannot_be_enabled_by_forging_only_config_validation(profile_case):
    case = profile_case
    full = publish(case, create(case))
    req = configuration_request(full.profile_id)
    req.update(enabled=True, validation_status="validated", validation_note="只改配置不能代替独立Profile的范围验证证据。")
    with pytest.raises(HTTPException):
        p.configure(case["db"], case["author"], req)
    assert case["db"].get(AIFeatureConfig, p.KEY) is None
    assert case["db"].query(AIInfectionLocalSelection).count() == 0


@pytest.mark.parametrize("mutation", ["implementation", "definition", "directory", "alpha", "code"])
def test_create_full_actual_scope_mismatch_has_no_profile_or_audit_write(profile_case, mutation):
    case = profile_case
    req = copy.deepcopy(case["profile_request"])
    if mutation == "implementation":
        req["expected_implementation_hash"] = "e" * 64
    elif mutation == "definition":
        req["scope"]["definition_governance_hash"] = "e" * 64
    elif mutation == "directory":
        req["scope"]["department_ids"] = [2147483647]
    elif mutation == "alpha":
        req["scope"]["alpha_decimals"] = ["1e-2"]
    else:
        req["scope"]["pathogen_codes"] = ["NOT_IN_DEFINITION"]
    before = case["db"].query(AIAuditEvent).count()
    with pytest.raises((ValueError, HTTPException)):
        p.create_profile(case["db"], case["author"], req)
    assert case["db"].query(AIInfectionLocalProfile).count() == 0
    assert case["db"].query(AIAuditEvent).count() == before


def test_actual_profile_withdrawal_blocks_execution_and_retains_technical_configuration(profile_case):
    case = profile_case
    full = publish(case, create(case))
    save(case, configuration_request(full.profile_id))
    revoked = p.revoke_profile(case["db"], case["reviewer"], full.profile_id, cas(full))
    case["db"].commit()
    assert not revoked.eligible and revoked.governance.status == "revoked"
    assert p.configuration(case["db"], case["author"], management=True)["profile"]["current_issues"] == ["not_published"]
    with pytest.raises(HTTPException):
        p.execution_configuration(case["db"], case["author"], preview=True)


def test_technical_profile_admin_does_not_read_raw_patient_clinical_source(profile_case):
    case = profile_case
    # Withdraw this operator's processing grant. Technical method governance
    # remains separate; it cannot grant them access to Source or a Task.
    grant = case["grants"][0]
    r.revoke_record(case["db"], case["reviewer"], "grant", grant.record_id, cas(grant))
    case["db"].commit()
    queries = []

    def capture(conn, cursor, sql, params, context, many):
        queries.append(sql)

    event.listen(case["db"].get_bind(), "before_cursor_execute", capture)
    try:
        full = publish(case, create(case))
        save(case, configuration_request(full.profile_id))
    finally:
        event.remove(case["db"].get_bind(), "before_cursor_execute", capture)
    assert not any("hoimsystem_infection_case.description" in sql or "hoimsystem_ai_infection_snapshot.private_json" in sql for sql in queries)


@pytest.mark.parametrize("bad", ['"super_admin"', "[{}]", "[null]", '["imaginary_role"]', '["super_admin","super_admin"]'])
def test_malformed_current_role_json_and_generic_changes_do_not_restore_execution(profile_case, bad):
    case = profile_case
    full = publish(case, create(case))
    save(case, configuration_request(full.profile_id))
    case["db"].execute(text("UPDATE hoimsystem_ai_feature_config SET allowed_roles_json=:roles WHERE feature_key='infection_cluster'"), {"roles": bad})
    case["db"].commit()
    with pytest.raises(HTTPException) as error:
        p.execution_configuration(case["db"], case["author"], preview=True)
    assert error.value.status_code == 409


def test_super_configuration_role_intersection_has_no_execution_exemption(profile_case):
    case = profile_case
    full = publish(case, create(case))
    req = configuration_request(full.profile_id)
    req["allowed_roles"] = ["doctor", "admin"]
    value = save(case, req)
    assert not value["current_role_in_fixed_and_configured"]
    with pytest.raises(HTTPException) as error:
        p.execution_configuration(case["db"], case["author"], preview=True)
    assert error.value.status_code == 403
    doctor = case["db"].query(User).filter_by(user_role="doctor").first()
    with pytest.raises(HTTPException) as denied:
        p.execution_configuration(case["db"], doctor)
    assert denied.value.status_code == 403


@pytest.mark.parametrize("fault", ["audit", "config", "selection"])
def test_actual_after_write_configuration_faults_rollback_every_coupled_row(profile_case, fault):
    case = profile_case
    full = publish(case, create(case))
    before = case["db"].query(AIAuditEvent).count()
    if fault == "audit":
        body = "UPDATE hoimsystem_ai_audit_event SET detail_json='{}' WHERE event_id=NEW.change_event_id;"
    elif fault == "config":
        body = "UPDATE hoimsystem_ai_feature_config SET daily_limit=999 WHERE feature_key=NEW.feature_key;"
    else:
        body = "UPDATE hoimsystem_ai_infection_local_selection SET revision=999 WHERE feature_key=NEW.feature_key;"
    case["db"].execute(text("CREATE TRIGGER local_config_bad AFTER INSERT ON hoimsystem_ai_infection_local_selection BEGIN " + body + " END"))
    case["db"].commit()
    try:
        with pytest.raises(HTTPException):
            p.configure(case["db"], case["author"], configuration_request(full.profile_id))
        assert case["db"].get(AIFeatureConfig, p.KEY) is None
        assert case["db"].query(AIInfectionLocalSelection).count() == 0
        assert case["db"].query(AIAuditEvent).count() == before
    finally:
        case["db"].rollback()
        case["db"].execute(text("DROP TRIGGER local_config_bad"))
        case["db"].commit()


def test_same_scope_reconfigure_preserves_declared_second_clock_instead_of_legacy_onupdate(profile_case):
    case = profile_case
    first = save(case, configuration_request())
    req = configuration_request()
    req.update(expected_feature_revision=first["feature_revision"], expected_selection_revision=first["selection_revision"])
    result = save(case, req)
    assert result["feature_revision"] == result["selection_revision"] == 2
    cfg = case["db"].get(AIFeatureConfig, p.KEY)
    assert cfg.update_time == r.utcnow().replace(microsecond=0)


def test_new_current_super_can_disable_after_old_config_governor_epoch_changed_without_restoring_execution(profile_case):
    case = profile_case
    first = save(case, configuration_request())
    uid = case["author"].user_id
    case["db"].query(User).filter_by(user_id=uid).update({"user_role": "admin"}, synchronize_session=False)
    case["db"].commit()
    value = p.configuration(case["db"], case["reviewer"], management=True)
    assert not value["configuration_governor_current"]
    req = configuration_request()
    req.update(expected_feature_revision=first["feature_revision"], expected_selection_revision=first["selection_revision"])
    out = p.configure(case["db"], case["reviewer"], req)
    case["db"].commit()
    assert not out["enabled"] and out["profile_id"] is None and out["configuration_governor_current"]
