"""Actual synthetic waveform intake, current care-team sharing and source governance."""

import datetime
import io
from zipfile import ZipFile

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from alembic import command
from app.ai.ecg_files import ecg_directory
from app.ai.models import AIAuditEvent, AIECGAsset, AIFeatureConfig, AIPatientGrant, AIRun, utcnow
from app.config import settings
from app.db_migrate import migrate
from app.models import LabOrder, Registration
from app.routers import ai_ecg
from tests.test_ai_ecg_files import wfdb_bytes


@pytest.fixture
def ecg_case(db_session, seed_data, tmp_path, monkeypatch):
    root = tmp_path / "private"
    monkeypatch.setattr(settings, "AI_ECG_STORAGE_DIR", str(root))
    db_session.query(AIECGAsset).delete()
    db_session.query(AIFeatureConfig).filter_by(feature_key="ecg_analysis").delete()
    encounter = Registration(patient_id=seed_data["patient"].patient_id, doctor_id=seed_data["doctor"].doctor_id, department_id=seed_data["department"].department_id, time=utcnow(), status=0)
    db_session.add(encounter)
    db_session.commit()
    header, raw = wfdb_bytes()
    return header, raw, encounter, root


async def upload(async_client, auth_headers, seed_data, ecg_case, *, role="doctor_user", **changes):
    header, raw, encounter, _ = ecg_case
    return await async_client.post(
        "/api/ai/ecg-assets",
        headers=auth_headers(seed_data[role].username),
        files={"header": ("fixture.hea", header, "application/octet-stream"), "signal": ("fixture.dat", raw, "application/octet-stream")},
        data={
            "patient_id": str(encounter.patient_id),
            "encounter_ref": encounter.registration_uuid,
            "authorization_confirmed": "true",
            "authorization_note": "隔离测试原始资料和患者关联核对说明，不是实际授权证明",
            **changes,
        },
    )


@pytest.mark.asyncio
async def test_metadata_actual_waveform_window_and_private_original_download_do_not_infer(ecg_case, seed_data, db_session, async_client, auth_headers):
    response = await upload(async_client, auth_headers, seed_data, ecg_case)
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["status"] == "ready" and data["revision"] == 1 and data["recorded_at"] is None
    assert data["patient_id"] == ecg_case[2].patient_id and data["signal_metadata"]["sample_count"] == 4
    assert not {"path", "url", "filename", "authorization_note"}.intersection(data)
    url = "/api/ai/ecg-assets/" + data["asset_id"]
    headers = auth_headers(seed_data["doctor_user"].username)
    for part, raw in (("header", ecg_case[0]), ("signal", ecg_case[1])):
        content = await async_client.get(url + "/content", params={"part": part}, headers=headers)
        assert content.status_code == 200 and content.content == raw
        assert content.headers["cache-control"] == "private, no-store"
        assert "fixture" not in content.headers["content-disposition"]
    window = await async_client.get(url + "/window", headers=headers, params={"sample_count": 4, "max_points": 50})
    assert window.status_code == 200, window.text
    assert [row["value_mv"] for row in window.json()["data"]["leads"][0]["points"]] == [1.0, 2.0, None, -1.0]
    assert window.headers["cache-control"] == "private, no-store" and db_session.query(AIRun).count() == 0
    exported = await async_client.get(url + "/content", params={"part": "pair"}, headers=headers)
    assert exported.status_code == 200 and exported.headers["content-type"] == "application/zip"
    with ZipFile(io.BytesIO(exported.content)) as archive:
        assert set(archive.namelist()) == {"fixture.hea", "fixture.dat"}
        assert archive.read("fixture.hea") == ecg_case[0] and archive.read("fixture.dat") == ecg_case[1]
    assert (await async_client.get(url + "/window")).status_code == 401
    events = db_session.query(AIAuditEvent).filter(AIAuditEvent.action.like("ecg.%")).all()
    assert {row.action for row in events} >= {"ecg.register", "ecg.content_read", "ecg.window_read"}
    assert all("13812345678" not in row.detail_json and "隔离测试原始资料" not in row.detail_json for row in events)


@pytest.mark.asyncio
@pytest.mark.parametrize("changes", [{"authorization_confirmed": "false"}, {"authorization_note": "  "}, {"recorded_at": "2026-10-20T10:00:00"}, {"patient_id": "999999999"}])
async def test_missing_authority_or_ambiguous_time_is_rejected_before_storage(changes, ecg_case, seed_data, db_session, async_client, auth_headers):
    response = await upload(async_client, auth_headers, seed_data, ecg_case, **changes)
    assert response.status_code in {404, 422}, response.text
    assert not ecg_case[3].exists() and db_session.query(AIECGAsset).count() == 0


@pytest.mark.asyncio
async def test_declared_recording_time_is_utc_and_does_not_come_from_header_or_upload(ecg_case, seed_data, async_client, auth_headers):
    response = await upload(async_client, auth_headers, seed_data, ecg_case, recorded_at="2026-10-20T12:34:56.123456+08:00")
    assert response.status_code == 200, response.text
    assert response.json()["data"]["recorded_at"] == "2026-10-20T04:34:56.123456"


@pytest.mark.asyncio
async def test_patient_and_original_encounter_are_required_for_every_team_read(ecg_case, seed_data, db_session, async_client, auth_headers):
    foreign = Registration(patient_id=seed_data["patient2"].patient_id, time=utcnow(), status=0)
    db_session.add(foreign)
    db_session.commit()
    response = await upload(async_client, auth_headers, seed_data, ecg_case, encounter_ref=foreign.registration_uuid)
    assert response.status_code == 404
    data = (await upload(async_client, auth_headers, seed_data, ecg_case)).json()["data"]
    ecg_case[2].doctor_id = None
    db_session.commit()
    for suffix in ("", "/window", "/content?part=signal"):
        assert (await async_client.get("/api/ai/ecg-assets/" + data["asset_id"] + suffix, headers=auth_headers(seed_data["doctor_user"].username))).status_code == 403


@pytest.mark.asyncio
async def test_lab_registered_waveform_is_shared_with_current_doctor_but_withdrawal_is_separate(ecg_case, seed_data, db_session, async_client, auth_headers):
    grant = AIPatientGrant(
        user_id=seed_data["lab_tech_user"].user_id,
        patient_id=ecg_case[2].patient_id,
        category="diagnostics",
        reason="隔离测试限时心电资料处理授权",
        expires_at=utcnow() + datetime.timedelta(hours=1),
        created_by=seed_data["super_admin_user"].user_id,
    )
    db_session.add(grant)
    db_session.commit()
    response = await upload(async_client, auth_headers, seed_data, ecg_case, role="lab_tech_user")
    assert response.status_code == 200, response.text
    asset_id = response.json()["data"]["asset_id"]
    url = f"/api/ai/ecg-assets/{asset_id}"
    doctor = auth_headers(seed_data["doctor_user"].username)
    assert (await async_client.get(url + "/window", headers=doctor)).status_code == 200
    assert (await async_client.post(url + "/withdraw", headers=doctor, json={"expected_revision": 1, "reason": "非登记人不能撤回他人原记录"})).status_code == 403
    listing = await async_client.get("/api/ai/ecg-assets", headers=doctor, params={"patient_id": ecg_case[2].patient_id})
    assert [row["asset_id"] for row in listing.json()["data"]["items"]] == [asset_id]
    assert listing.json()["data"]["items"][0]["can_withdraw"] is False
    grant.revoked = 1
    db_session.commit()
    assert (await async_client.get(url + "/window", headers=auth_headers(seed_data["lab_tech_user"].username))).status_code == 403
    assert (await async_client.get(url + "/window", headers=doctor)).status_code == 200


@pytest.mark.asyncio
async def test_generic_lab_order_does_not_grant_ecg_access_or_patient_encounter_options(ecg_case, seed_data, db_session, async_client, auth_headers):
    data = (await upload(async_client, auth_headers, seed_data, ecg_case)).json()["data"]
    db_session.add(LabOrder(patient_id=ecg_case[2].patient_id, doctor_id=seed_data["doctor"].doctor_id, check_type="血常规", status=0))
    db_session.commit()
    headers = auth_headers(seed_data["lab_tech_user"].username)
    response = await async_client.get("/api/ai/patients", headers=headers, params={"feature_key": "ecg_analysis"})
    assert response.status_code == 200 and response.json()["data"] == []
    response = await async_client.get("/api/ai/encounters", headers=headers, params={"feature_key": "ecg_analysis", "patient_id": ecg_case[2].patient_id})
    assert response.status_code == 403
    assert (await async_client.get(f"/api/ai/ecg-assets/{data['asset_id']}/window", headers=headers)).status_code == 403
    assert (await upload(async_client, auth_headers, seed_data, ecg_case, role="lab_tech_user")).status_code == 403


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["quota", "role", "care", "second_file"])
async def test_post_validation_failures_clean_both_staging_and_partial_install(change, ecg_case, seed_data, db_session, async_client, auth_headers, monkeypatch):
    if change == "quota":
        monkeypatch.setattr(settings, "AI_ECG_USER_QUOTA_BYTES", 1)
    elif change == "second_file":
        original_link = ai_ecg.os.link

        def fail_second(source, target):
            if source.name == "source.dat":
                raise FileExistsError("isolated second-file failure")
            return original_link(source, target)

        monkeypatch.setattr(ai_ecg.os, "link", fail_second)
    else:
        original_stage = ai_ecg.stage_ecg

        def mutate_after_validation(*args):
            result = original_stage(*args)
            if change == "role":
                seed_data["doctor_user"].user_role = "nurse"
            else:
                ecg_case[2].doctor_id = None
            db_session.commit()
            return result

        monkeypatch.setattr(ai_ecg, "stage_ecg", mutate_after_validation)
    if change == "second_file":
        with pytest.raises(FileExistsError):
            await upload(async_client, auth_headers, seed_data, ecg_case)
    else:
        response = await upload(async_client, auth_headers, seed_data, ecg_case)
        assert response.status_code == (429 if change == "quota" else 403), response.text
    assert db_session.query(AIECGAsset).count() == 0 and list(ecg_case[3].iterdir()) == []


@pytest.mark.asyncio
async def test_super_admin_withdrawal_purge_and_durable_failed_cleanup_resume(ecg_case, seed_data, db_session, async_client, auth_headers, monkeypatch):
    data = (await upload(async_client, auth_headers, seed_data, ecg_case)).json()["data"]
    asset_id = data["asset_id"]
    headers = auth_headers(seed_data["super_admin_user"].username)
    base = f"/api/ai/ecg-assets/{asset_id}"
    action = {"expected_revision": 1, "reason": "管理员核实原记录撤回请求"}
    assert (await async_client.post(base + "/withdraw", headers=headers, json=action)).status_code == 200
    assert (await async_client.post(base + "/withdraw", headers=headers, json=action)).status_code == 409
    assert (await async_client.get(base + "/window", headers=auth_headers(seed_data["doctor_user"].username))).status_code == 409
    assert (await async_client.get(base + "/window", headers=headers)).status_code == 200
    original_remove = ai_ecg.shutil.rmtree

    def fail_cleanup(path, *args, **kwargs):
        if path.name == asset_id:
            raise PermissionError("isolated cleanup failure")
        return original_remove(path, *args, **kwargs)

    monkeypatch.setattr(ai_ecg.shutil, "rmtree", fail_cleanup)
    response = await async_client.post(f"/api/ai/admin/ecg-assets/{asset_id}/purge", headers=headers, json={"expected_revision": 2, "reason": "按原请求清除当前存储的心电原文件"})
    assert response.status_code == 503
    db_session.expire_all()
    asset = db_session.get(AIECGAsset, asset_id)
    assert asset.status == "purge_pending" and asset.revision == 3 and asset.purge_note == "按原请求清除当前存储的心电原文件"
    assert (await async_client.get(base + "/content?part=header", headers=headers)).status_code == 410
    monkeypatch.setattr(ai_ecg.shutil, "rmtree", original_remove)
    response = await async_client.post(f"/api/ai/admin/ecg-assets/{asset_id}/purge", headers=headers, json={"expected_revision": 3, "reason": "恢复原清除请求，保留第一次请求说明"})
    assert response.status_code == 200 and not ecg_directory(asset_id).exists()
    db_session.refresh(asset)
    assert asset.status == "purged" and asset.revision == 4 and asset.purge_note == "按原请求清除当前存储的心电原文件"
    assert db_session.query(AIAuditEvent).filter_by(action="ecg.purged", target=asset_id).count() == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["admin", "nurse", "pharmacist", "cashier", "guide", "patient", "registrar"])
async def test_unrelated_roles_cannot_read_raw_ecg_or_manage_any_sources(role, seed_data, async_client, auth_headers):
    headers = auth_headers(seed_data[role + "_user"].username)
    for url in ("/api/ai/ecg-options", "/api/ai/ecg-assets?patient_id=1", "/api/ai/admin/ecg-assets"):
        assert (await async_client.get(url, headers=headers)).status_code == 403
    assert (await async_client.post("/api/ai/admin/ecg-assets/unknown/purge", headers=headers, json={"expected_revision": 1, "reason": "非超级管理员不能清除"})).status_code == 403


def test_ecg_migration_roundtrip_preserves_existing_rows_and_matches_registered_model(tmp_path):
    path = tmp_path / "ecg-migration.sqlite"
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", "sqlite:///" + str(path))
    assert migrate("sqlite:///" + str(path)) == "bootstrapped"
    engine = create_engine("sqlite:///" + str(path))
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO hoimsystem_patient (patient_id, name, identity) VALUES (42, 'isolated-existing-patient', 'isolated-identity')"))
    assert {column["name"] for column in inspect(engine).get_columns("hoimsystem_ai_ecg_asset")} == set(AIECGAsset.__table__.columns.keys())
    command.downgrade(config, "20261020_audio_governance")
    assert "hoimsystem_ai_ecg_asset" not in inspect(engine).get_table_names()
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT name FROM hoimsystem_patient WHERE patient_id=42")) == "isolated-existing-patient"
    assert migrate("sqlite:///" + str(path)) == "upgraded"
    engine.dispose()
