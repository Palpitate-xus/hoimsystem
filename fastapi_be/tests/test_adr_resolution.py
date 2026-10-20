"""ADR processing is distinct from exclusion and never silently creates drug allergies."""

import datetime
from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from alembic import command
from app.adr_status import describe_adr_status
from app.models import AdverseReaction, PatientAllergy, Prescription


@pytest.fixture
def adr_case(db_session, seed_data):
    row = AdverseReaction(
        patient_id=seed_data["patient"].patient_id,
        pharmaceutical_id=seed_data["pharmaceutical"].pharmaceutical_id,
        symptom="原上报症状",
        status=0,
        report_time=datetime.datetime.now(),
        note="原上报备注",
    )
    seed_data["patient"].allergy_history = "既有过敏史不应被ADR处理修改"
    db_session.add(row)
    db_session.commit()
    return row


async def update(async_client, auth_headers, row, **values):
    return await async_client.post("/api/adverseReaction/updateStatus", headers=auth_headers("admin"), json={"reaction_id": row.reaction_id, **values})


@pytest.mark.asyncio
async def test_confirmation_and_processing_do_not_write_allergy_history(async_client, auth_headers, db_session, seed_data, adr_case):
    before = db_session.query(PatientAllergy).filter_by(patient_id=adr_case.patient_id).count()
    response = await update(async_client, auth_headers, adr_case, status=1)
    assert response.json()["code"] == 200
    db_session.refresh(adr_case)
    assert adr_case.status_resolution == "confirmed"
    response = await update(async_client, auth_headers, adr_case, status=2, resolution="processed", note="已完成人工处理")
    assert response.json()["code"] == 200
    db_session.refresh(adr_case)
    db_session.refresh(seed_data["patient"])
    assert adr_case.status_resolution == "processed" and adr_case.status_reviewed_by == seed_data["admin_user"].user_id
    assert adr_case.note == "原上报备注" and adr_case.resolution_note == "已完成人工处理"
    assert seed_data["patient"].allergy_history == "既有过敏史不应被ADR处理修改"
    assert db_session.query(PatientAllergy).filter_by(patient_id=adr_case.patient_id).count() == before


@pytest.mark.asyncio
async def test_pending_case_exclusion_requires_explicit_result_and_reason(async_client, auth_headers, db_session, adr_case):
    response = await update(async_client, auth_headers, adr_case, status=2)
    assert response.json()["code"] == 400
    response = await update(async_client, auth_headers, adr_case, status=2, resolution="excluded", note="经人工评估排除本次ADR")
    assert response.json()["code"] == 200
    db_session.refresh(adr_case)
    assert describe_adr_status(adr_case)["recorded_state"] == "excluded"
    response = await update(async_client, auth_headers, adr_case, status=2, resolution="processed")
    assert response.json()["code"] == 400
    db_session.refresh(adr_case)
    assert adr_case.status_resolution == "excluded"


@pytest.mark.asyncio
async def test_legacy_status_two_remains_unknown_until_manual_resolution(async_client, auth_headers, db_session, adr_case):
    adr_case.status = 2
    db_session.commit()
    response = await async_client.get("/api/adverseReaction/getList", headers=auth_headers("admin"))
    row = next(item for item in response.json()["data"] if item["reaction_id"] == adr_case.reaction_id)
    assert row["recorded_state"] == "legacy_ambiguous" and row["status_resolution"] is None
    assert row["patient_id"] == adr_case.patient_id and row["status_text"] == "历史含义待核实"
    assert (await update(async_client, auth_headers, adr_case, status=2)).json()["code"] == 400
    response = await update(async_client, auth_headers, adr_case, status=2, resolution="processed", note="根据原处置记录核实为已处理")
    assert response.json()["code"] == 200
    db_session.refresh(adr_case)
    assert describe_adr_status(adr_case)["recorded_state"] == "processed" and adr_case.status_reviewed_at is not None


@pytest.mark.asyncio
@pytest.mark.parametrize("field,value", [("reaction_id", True), ("reaction_id", "1"), ("status", True), ("status", 1.0), ("status", 3)])
async def test_invalid_typed_status_input_does_not_mutate_record(field, value, async_client, auth_headers, db_session, adr_case):
    payload = {"reaction_id": adr_case.reaction_id, "status": 1, field: value}
    response = await async_client.post("/api/adverseReaction/updateStatus", headers=auth_headers("admin"), json=payload)
    assert response.status_code == 422
    db_session.refresh(adr_case)
    assert adr_case.status == 0 and adr_case.status_resolution is None


def test_migration_does_not_infer_legacy_resolution_or_rewrite_business_rows(tmp_path):
    path = tmp_path / "adr-resolution.db"
    engine = create_engine(f"sqlite:///{path}")
    with engine.begin() as conn:
        conn.exec_driver_sql("CREATE TABLE hoimsystem_users (user_id INTEGER PRIMARY KEY)")
        conn.exec_driver_sql("CREATE TABLE hoimsystem_adverse_reaction (reaction_id INTEGER PRIMARY KEY, status INTEGER, symptom TEXT)")
        conn.exec_driver_sql("INSERT INTO hoimsystem_adverse_reaction VALUES (7, 2, '历史症状')")
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{path}")
    command.stamp(config, "20261020_ai_review_excerpts")
    command.upgrade(config, "20261020_adr_resolution")
    with engine.connect() as conn:
        assert conn.execute(text("SELECT status, status_resolution, status_reviewed_at FROM hoimsystem_adverse_reaction")).one() == (2, None, None)
    assert "status_resolution" in {item["name"] for item in inspect(engine).get_columns("hoimsystem_adverse_reaction")}
    command.downgrade(config, "20261020_ai_review_excerpts")
    with engine.connect() as conn:
        assert conn.execute(text("SELECT status, symptom FROM hoimsystem_adverse_reaction")).one() == (2, "历史症状")
    engine.dispose()


@pytest.mark.asyncio
async def test_pharmacist_read_scope_follows_prescription_care_without_status_write_permission(async_client, auth_headers, db_session, seed_data, adr_case):
    foreign = AdverseReaction(patient_id=seed_data["patient2"].patient_id, symptom="其他患者的ADR", status=0, report_time=datetime.datetime.now())
    db_session.add(foreign)
    db_session.commit()
    headers = auth_headers(seed_data["pharmacist_user"].username)
    response = await async_client.get("/api/adverseReaction/getList", headers=headers)
    assert response.status_code == 200, response.text
    ids = {item["reaction_id"] for item in response.json()["data"]}
    assert adr_case.reaction_id in ids and foreign.reaction_id not in ids
    denied = await async_client.post("/api/adverseReaction/updateStatus", headers=headers, json={"reaction_id": adr_case.reaction_id, "status": 1})
    assert denied.status_code == 403
    db_session.query(Prescription).filter_by(patient_id=adr_case.patient_id).update({"status": 3})
    db_session.commit()
    response = await async_client.get("/api/adverseReaction/getList", headers=headers)
    assert adr_case.reaction_id not in {item["reaction_id"] for item in response.json()["data"]}
    admin = await async_client.get("/api/adverseReaction/getList", headers=auth_headers(seed_data["admin_user"].username))
    assert {adr_case.reaction_id, foreign.reaction_id} <= {item["reaction_id"] for item in admin.json()["data"]}
