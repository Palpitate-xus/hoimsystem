"""Verify instruction fidelity, invalid-dose atomicity and legacy-compatible migration."""

from decimal import Decimal
from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from alembic import command
from app.medication_data import normalize_medication_item
from app.models import Pharmaceutical, PrePha, Prescription


@pytest.mark.parametrize(
    "field,value", [("number", 1.5), ("number", True), ("dosage", "NaN"), ("dosage", "Infinity"), ("dosage", -1), ("dosage", "0.0000001"), ("duration_days", 1.5), ("duration_days", 4000)]
)
def test_instruction_normalization_rejects_lossy_or_invalid_values(field, value):
    with pytest.raises(ValueError):
        normalize_medication_item({"number": 1, field: value})


def test_missing_legacy_instructions_remain_unknown():
    item = normalize_medication_item({"id": 1, "number": 2})
    assert item["number"] == 2
    assert all(item[field] is None for field in ("dosage", "dose_unit", "frequency", "route", "duration_days"))


@pytest.mark.asyncio
async def test_prescribing_persists_instructions_through_doctor_and_pharmacy_views(async_client, seed_data, auth_headers, db_session):
    item = {"id": seed_data["pharmaceutical"].pharmaceutical_id, "number": 2, "dosage": "500", "dose_unit": "mg", "frequency": "bid", "route": "口服", "duration_days": 7}
    response = await async_client.post("/api/prescriptionManagement/create", headers=auth_headers(seed_data["doctor_user"].username), json={"patient": seed_data["patient"].patient_id, "phas": [item]})
    assert response.status_code == 200, response.text
    reference = response.json()["data"]["uuid"]
    record = db_session.query(PrePha).filter_by(prescription_id=reference).one()
    assert record.dosage == Decimal("500")
    assert (record.dose_unit, record.frequency, record.route, record.duration_days) == ("mg", "bid", "口服", 7)
    for path, username in [("/api/prescriptionManagement/getList", seed_data["doctor_user"].username), ("/api/pharmacy/dispenseList", seed_data["pharmacist_user"].username)]:
        listed = await async_client.get(path, headers=auth_headers(username))
        row = next(row for row in listed.json()["data"] if row["uuid"] == reference)
        assert row["phas"][0]["dosage"] == "500"
        assert row["phas"][0]["frequency"] == "bid"
        assert row["phas"][0]["duration_days"] == 7


@pytest.mark.asyncio
async def test_invalid_instruction_does_not_reserve_stock_or_create_prescription(async_client, seed_data, auth_headers, db_session):
    pharmaceutical_id = seed_data["pharmaceutical"].pharmaceutical_id
    before_stock = db_session.get(Pharmaceutical, pharmaceutical_id).stock
    before_count = db_session.query(Prescription).count()
    response = await async_client.post(
        "/api/prescriptionManagement/create",
        headers=auth_headers(seed_data["doctor_user"].username),
        json={"patient": seed_data["patient"].patient_id, "phas": [{"id": pharmaceutical_id, "number": 1, "dosage": "NaN"}]},
    )
    assert response.status_code == 400
    db_session.expire_all()
    assert db_session.get(Pharmaceutical, pharmaceutical_id).stock == before_stock
    assert db_session.query(Prescription).count() == before_count


def test_instruction_migration_does_not_invent_legacy_dose(tmp_path):
    url = f"sqlite:///{tmp_path / 'instructions.db'}"
    engine = create_engine(url)
    with engine.begin() as conn:
        conn.exec_driver_sql("CREATE TABLE hoimsystem_pre_pha (pre_pha_id VARCHAR(36) PRIMARY KEY, prescription_id VARCHAR(50), pharmaceutical_id INTEGER, number INTEGER)")
        conn.exec_driver_sql("INSERT INTO hoimsystem_pre_pha VALUES ('legacy','rx',1,2)")
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", url)
    command.stamp(config, "20261020_ai_task_leases")
    command.upgrade(config, "20261020_rx_instructions")
    with engine.connect() as conn:
        row = conn.execute(text("SELECT number, dosage, dose_unit, frequency FROM hoimsystem_pre_pha")).one()
        assert tuple(row) == (2, None, None, None)
    command.downgrade(config, "20261020_ai_task_leases")
    assert "dosage" not in {item["name"] for item in inspect(engine).get_columns("hoimsystem_pre_pha")}
    with engine.connect() as conn:
        assert conn.scalar(text("SELECT number FROM hoimsystem_pre_pha")) == 2
    engine.dispose()
