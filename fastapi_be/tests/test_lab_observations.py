"""Typed laboratory provenance, transactional ingestion and parent-report review boundaries."""

import datetime
from decimal import Decimal
from pathlib import Path

import pytest
from alembic.config import Config
from pydantic import ValidationError
from sqlalchemy import create_engine, inspect, text

from alembic import command
from app.ai.catalog import FEATURE_BY_KEY
from app.ai.context import patient_snapshot
from app.clinical_observations import LabObservationInput
from app.config import settings
from app.models import LabObservation, LabOrder, LabResult


def observation(**changes):
    return {
        "code": "TEST_K",
        "display": "测试检验指标",
        "value_num": "4.12345678",
        "unit": "mmol/L",
        "reference_low": "3.5",
        "reference_high": "5.5",
        "collected_at": "2026-10-20T10:15:00+08:00",
        **changes,
    }


@pytest.mark.parametrize(
    "changes",
    [
        {"value_num": "NaN"},
        {"value_num": "Infinity"},
        {"value_num": "0.000000001"},
        {"unit": None},
        {"value_text": "阴性"},
        {"value_num": None},
        {"reference_low": "6", "reference_high": "3"},
        {"collected_at": "2026-10-20T10:15:00"},
    ],
)
def test_ambiguous_or_lossy_observations_are_rejected(changes):
    with pytest.raises(ValidationError):
        LabObservationInput(**observation(**changes))


def new_order(db_session, seed_data, **kwargs):
    row = LabOrder(patient_id=seed_data["patient"].patient_id, doctor_id=seed_data["doctor"].doctor_id, check_type="测试项目", status=0, sample_status=1, create_time=datetime.datetime.now(), **kwargs)
    db_session.add(row)
    db_session.commit()
    return row


@pytest.mark.asyncio
async def test_manual_result_retains_exact_values_and_requires_independent_review(async_client, seed_data, auth_headers, db_session):
    order = new_order(db_session, seed_data)
    value = observation(value_num="1234567890123456.12345678", flag="unknown")
    created = await async_client.post(
        "/api/labResult/create",
        headers=auth_headers(seed_data["lab_tech_user"].username),
        json={"lab_order_id": order.lab_order_id, "sample_id": "T-typed", "result": "原始报告文本保留", "abnormal_flag": 0, "observations": [value]},
    )
    assert created.status_code == 200, created.text
    report = db_session.query(LabResult).filter_by(lab_order_id=order.lab_order_id).one()
    typed = db_session.query(LabObservation).filter_by(lab_result_id=report.lab_result_id).one()
    assert typed.value_num == Decimal(value["value_num"])
    assert typed.collected_at == datetime.datetime(2026, 10, 20, 2, 15)
    assert report.result == "原始报告文本保留"
    before = patient_snapshot(db_session, seed_data["doctor_user"], FEATURE_BY_KEY["lab_interpretation"], order.patient_id)
    assert "observation:" + typed.observation_id not in {item["source_id"] for item in before.evidence}
    denied = await async_client.post("/api/labResult/audit", headers=auth_headers(seed_data["lab_tech_user"].username), json={"lab_result_id": report.lab_result_id})
    assert denied.status_code == 400
    approved = await async_client.post("/api/labResult/audit", headers=auth_headers(seed_data["admin_user"].username), json={"lab_result_id": report.lab_result_id})
    assert approved.status_code == 200, approved.text
    db_session.expire_all()
    after = patient_snapshot(db_session, seed_data["doctor_user"], FEATURE_BY_KEY["lab_interpretation"], order.patient_id)
    seen = next(item for item in after.data["reviewed_observations"] if item["observation_id"] == typed.observation_id)
    assert seen["value_num"] == value["value_num"]
    assert seen["unit"] == "mmol/L"
    assert seen["flag"] == "unknown"
    assert seen["collected_at"] == "2026-10-20T02:15:00+00:00"
    listed = await async_client.get("/api/labResult/getList", headers=auth_headers(seed_data["lab_tech_user"].username))
    row = next(item for item in listed.json()["data"] if item["id"] == report.lab_result_id)
    assert row["patient_id"] == order.patient_id
    assert row["audit_status"] == 1
    assert row["observations"][0]["value_num"] == value["value_num"]


@pytest.mark.asyncio
async def test_lis_typed_critical_flag_preserves_notifications_and_callback_idempotency(async_client, seed_data, db_session, monkeypatch):
    monkeypatch.setattr(settings, "LIS_INTEGRATION_KEY", "typed-lis-test")
    order = new_order(db_session, seed_data)
    payload = {"lab_order_id": order.lab_order_id, "result": "外部原始结果", "observations": [observation(flag="critical")]}
    response = await async_client.post("/api/integration/lis/result", headers={"X-Integration-Key": "typed-lis-test"}, json=payload)
    assert response.status_code == 200, response.text
    report_id = response.json()["data"]["lab_result_id"]
    report = db_session.get(LabResult, report_id)
    assert report.critical_status == 1
    assert report.abnormal_flag == 1
    assert report.audit_status == 0
    payload["observations"] = [observation(value_num="2", flag="normal")]
    repeated = await async_client.post("/api/integration/lis/result", headers={"X-Integration-Key": "typed-lis-test"}, json=payload)
    assert repeated.json()["data"]["idempotent"] is True
    db_session.expire_all()
    assert db_session.query(LabObservation).filter_by(lab_result_id=report_id).count() == 1
    assert db_session.query(LabObservation).filter_by(lab_result_id=report_id).one().value_num == Decimal("4.12345678")


@pytest.mark.asyncio
async def test_duplicate_observation_batch_does_not_partially_advance_order(async_client, seed_data, auth_headers, db_session):
    order = new_order(db_session, seed_data)
    response = await async_client.post(
        "/api/labResult/create",
        headers=auth_headers(seed_data["lab_tech_user"].username),
        json={"lab_order_id": order.lab_order_id, "result": "重复数据", "observations": [observation(), observation()]},
    )
    assert response.status_code == 422
    db_session.expire_all()
    assert db_session.get(LabOrder, order.lab_order_id).status == 0
    assert db_session.query(LabResult).filter_by(lab_order_id=order.lab_order_id).count() == 0


def test_observation_migration_preserves_legacy_report_and_downgrade(tmp_path):
    url = f"sqlite:///{tmp_path / 'lab-observations.db'}"
    engine = create_engine(url)
    with engine.begin() as conn:
        conn.exec_driver_sql("CREATE TABLE hoimsystem_lab_result (lab_result_id VARCHAR(36) PRIMARY KEY, result TEXT)")
        conn.exec_driver_sql("INSERT INTO hoimsystem_lab_result VALUES ('old', '历史原始报告')")
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", url)
    command.stamp(config, "20261020_rx_instructions")
    command.upgrade(config, "20261020_lab_observations")
    assert "hoimsystem_lab_observation" in inspect(engine).get_table_names()
    with engine.connect() as conn:
        assert conn.scalar(text("SELECT result FROM hoimsystem_lab_result")) == "历史原始报告"
        assert conn.scalar(text("SELECT count(*) FROM hoimsystem_lab_observation")) == 0
    command.downgrade(config, "20261020_rx_instructions")
    assert "hoimsystem_lab_observation" not in inspect(engine).get_table_names()
    engine.dispose()
