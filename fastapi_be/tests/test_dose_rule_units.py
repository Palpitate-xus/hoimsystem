"""Exact-unit prescription rules never infer a daily frequency or silently round limits."""

import datetime
from decimal import Decimal
from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, text

from alembic import command
from app.models import PrescriptionReviewRule
from app.rx_review_engine import check_prescription, has_blocking


@pytest.fixture(autouse=True)
def isolate_rules(db_session):
    db_session.query(PrescriptionReviewRule).delete()
    db_session.commit()


def dose_rule(db_session, **changes):
    row = PrescriptionReviewRule(
        rule_type="dose", drug_a="测试药", dose_unit=changes.pop("dose_unit", "mg"), severity=3, message="测试剂量边界", status=1, create_time=datetime.datetime.now(), **changes
    )
    db_session.add(row)
    db_session.commit()
    return row


def test_decimal_daily_total_at_limit_is_not_a_binary_float_false_positive(db_session):
    dose_rule(db_session, max_daily_dose=Decimal("0.30"))
    evaluations = []
    findings = check_prescription(db_session, [{"name": "测试药", "dosage": "0.1", "dose_unit": "mg", "frequency": "tid"}], evaluation_log=evaluations)
    assert findings == []
    assert evaluations[0]["evaluation_status"] == "within_recorded_limits"
    assert evaluations[0]["calculations"][0]["calculated_daily_dose"] == "0.3"


@pytest.mark.parametrize("frequency", ["prn", "st", "q36h", "每隔36小时", "", None])
def test_uncertain_daily_frequency_is_unevaluated_instead_of_guessed(db_session, frequency):
    dose_rule(db_session, max_daily_dose=Decimal("5"))
    evaluations = []
    findings = check_prescription(db_session, [{"name": "测试药", "dosage": "1", "dose_unit": "mg", "frequency": frequency}], evaluation_log=evaluations)
    assert has_blocking(findings)
    assert findings[0]["evaluation_status"] == "not_evaluated"
    assert evaluations[0]["hit"] is False
    assert evaluations[0]["calculations"][0]["calculated_daily_dose"] is None


@pytest.mark.parametrize("unit", ["g", "MG", "盒", None])
def test_incompatible_or_missing_units_are_not_compared(db_session, unit):
    dose_rule(db_session, max_dose=Decimal("5"))
    evaluations = []
    findings = check_prescription(db_session, [{"name": "测试药", "dosage": "100", "dose_unit": unit, "frequency": "qd"}], evaluation_log=evaluations)
    assert findings[0]["evaluation_status"] == "not_evaluated"
    assert evaluations[0]["hit"] is False
    assert evaluations[0]["unit_conversion_performed"] is False
    assert evaluations[0]["calculations"] == []


def test_legacy_rule_without_unit_is_an_explicit_incomplete_safety_check(db_session):
    dose_rule(db_session, dose_unit=None, max_dose=Decimal("5"))
    findings = check_prescription(db_session, [{"name": "测试药", "dosage": "100", "dose_unit": "mg"}])
    assert findings[0]["evaluation_status"] == "not_evaluated"
    assert "规则缺少原始单位" in findings[0]["message"]
    assert has_blocking(findings)


@pytest.mark.parametrize("unit", ["mg/h", "mg/kg", "mg每小时"])
def test_rate_and_denominator_units_require_a_specialized_daily_rule(db_session, unit):
    dose_rule(db_session, dose_unit=unit, max_daily_dose=Decimal("5"))
    evaluations = []
    findings = check_prescription(db_session, [{"name": "测试药", "dosage": "1", "dose_unit": unit, "frequency": "bid"}], evaluation_log=evaluations)
    assert findings[0]["evaluation_status"] == "not_evaluated"
    assert evaluations[0]["calculations"][0]["calculated_daily_dose"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("changes", [{"dose_unit": None}, {"max_dose": "NaN"}, {"max_dose": "0.0001"}, {"min_dose": "10", "max_dose": "5"}])
async def test_invalid_rule_configuration_is_rejected_without_persisting(async_client, seed_data, auth_headers, db_session, changes):
    response = await async_client.post(
        "/api/rxReviewRule/create",
        headers=auth_headers(seed_data["pharmacist_user"].username),
        json={"rule_type": "dose", "drug_a": "测试药", "dose_unit": "mg", "max_dose": "5", "message": "测试规则", **changes},
    )
    assert response.status_code == 400, response.text
    assert db_session.query(PrescriptionReviewRule).count() == 0


def test_unit_migration_keeps_historical_rule_unit_unknown(tmp_path):
    url = f"sqlite:///{tmp_path / 'dose-rule-unit.db'}"
    engine = create_engine(url)
    with engine.begin() as conn:
        conn.exec_driver_sql("CREATE TABLE hoimsystem_rx_review_rule (rule_id INTEGER PRIMARY KEY, max_dose NUMERIC(12,2))")
        conn.exec_driver_sql("INSERT INTO hoimsystem_rx_review_rule VALUES (1, 0.5)")
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", url)
    command.stamp(config, "20261020_diagnosis_review")
    command.upgrade(config, "20261020_dose_rule_units")
    with engine.connect() as conn:
        assert tuple(conn.execute(text("SELECT max_dose, dose_unit FROM hoimsystem_rx_review_rule")).one()) == (0.5, None)
    command.downgrade(config, "20261020_diagnosis_review")
    with engine.connect() as conn:
        assert conn.scalar(text("SELECT max_dose FROM hoimsystem_rx_review_rule")) == 0.5
    engine.dispose()
