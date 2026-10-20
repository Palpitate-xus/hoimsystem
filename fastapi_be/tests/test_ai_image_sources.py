"""Synthetic actual DICOM intake, current requesting care and private source governance."""

import datetime
import io
import struct
import uuid

import pytest
from alembic.config import Config
from pydicom.dataset import FileDataset, FileMetaDataset
from pydicom.uid import DigitalXRayImageStorageForPresentation, ExplicitVRLittleEndian, generate_uid
from sqlalchemy import create_engine, inspect, text

from alembic import command
from app.ai.image_assets import authorize_image_snapshot, image_snapshot
from app.ai.image_files import image_directory
from app.ai.models import AIAuditEvent, AIFeatureConfig, AIImageAsset, AIPatientGrant, AIRun, utcnow
from app.config import settings
from app.db_migrate import migrate
from app.models import ImagingOrder, LabOrder, Patient, Registration
from app.routers import ai_images


def dicom_bytes():
    """No patient data: synthetic identifiers demonstrate that original tags stay private."""
    meta = FileMetaDataset()
    meta.MediaStorageSOPClassUID = DigitalXRayImageStorageForPresentation
    meta.MediaStorageSOPInstanceUID = generate_uid()
    meta.TransferSyntaxUID = ExplicitVRLittleEndian
    meta.ImplementationClassUID = generate_uid()
    source = FileDataset(None, {}, file_meta=meta, preamble=b"\0" * 128)
    source.SOPClassUID = meta.MediaStorageSOPClassUID
    source.SOPInstanceUID = meta.MediaStorageSOPInstanceUID
    source.StudyInstanceUID = generate_uid()
    source.SeriesInstanceUID = generate_uid()
    source.Modality = "DX"
    source.PatientName = "SYNTHETIC^PRIVATE_NAME"
    source.PatientID = "SYNTHETIC_PRIVATE_ID"
    source.AccessionNumber = "SYNTH_PRIVATE"
    source.StudyDate = "20010101"
    source.StudyTime = "010203"
    source.Rows, source.Columns = 2, 3
    source.SamplesPerPixel = 1
    source.PhotometricInterpretation = "MONOCHROME2"
    source.BitsAllocated = 16
    source.BitsStored = 12
    source.HighBit = 11
    source.PixelRepresentation = 1
    source.RescaleSlope, source.RescaleIntercept = "1", "0"
    source.WindowCenter, source.WindowWidth = "0", "1024"
    source.BurnedInAnnotation = "NO"
    source.add_new((0x0011, 0x0010), "LO", "SYNTHETIC_PRIVATE_CREATOR")
    source.add_new((0x0011, 0x1001), "LO", "SYNTHETIC_PRIVATE_TAG_VALUE")
    samples = [-1024, -1, 0, 1, 1023, 2047]
    # Non-sample high bits must not alter logical values or leak hidden overlays.
    source.PixelData = struct.pack("<6H", *((value & 0x0FFF) | 0x5000 for value in samples))
    output = io.BytesIO()
    source.save_as(output, enforce_file_format=True)
    return output.getvalue(), struct.pack("<6i", *samples)


@pytest.fixture
def image_case(db_session, seed_data, tmp_path, monkeypatch):
    root = tmp_path / "private-images"
    monkeypatch.setattr(settings, "AI_IMAGE_STORAGE_DIR", str(root))
    db_session.query(AIImageAsset).delete()
    db_session.query(AIFeatureConfig).filter_by(feature_key="imaging_detection").delete()
    db_session.query(AIPatientGrant).filter_by(user_id=seed_data["lab_tech_user"].user_id, category="diagnostics").delete()
    encounter = Registration(patient_id=seed_data["patient"].patient_id, doctor_id=seed_data["doctor"].doctor_id, department_id=seed_data["department"].department_id, time=utcnow(), status=0)
    order = ImagingOrder(
        patient_id=seed_data["patient"].patient_id,
        doctor_id=seed_data["doctor"].doctor_id,
        modality="DR",
        body_part="合成测试部位",
        status=0,
        create_time=utcnow(),
        accession_no="synthetic-" + uuid.uuid4().hex[:12],
    )
    db_session.add_all([encounter, order])
    db_session.commit()
    original, pixels = dicom_bytes()
    return original, pixels, encounter, order, root


async def upload_image(async_client, auth_headers, seed_data, image_case, *, role="doctor_user", **changes):
    original, _, encounter, order, _ = image_case
    data = {
        "patient_id": str(encounter.patient_id),
        "imaging_order_id": order.imaging_order_id,
        "encounter_ref": encounter.registration_uuid,
        "authorization_confirmed": "true",
        "authorization_note": "隔离合成测试患者、申请和原图使用依据，不是实际患者授权证明",
        **changes,
    }
    return await async_client.post(
        "/api/ai/image-assets",
        headers=auth_headers(seed_data[role].username),
        files={"image": ("synthetic-private-source.dcm", original, "application/dicom")},
        data={key: value for key, value in data.items() if value is not None},
    )


@pytest.mark.asyncio
async def test_actual_original_and_signed_pixel_bytes_are_private_and_do_not_infer(image_case, seed_data, db_session, async_client, auth_headers):
    response = await upload_image(async_client, auth_headers, seed_data, image_case)
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["status"] == "ready" and data["revision"] == 1 and data["recorded_at"] is None
    assert data["image_metadata"]["rows"] == 2 and data["image_metadata"]["columns"] == 3
    assert data["imaging_order_id"] == image_case[3].imaging_order_id
    assert not {"path", "url", "filename", "authorization_note", "body_part", "accession_no"}.intersection(data)
    assert "SYNTHETIC_PRIVATE" not in response.text and "PRIVATE_NAME" not in response.text
    assert "synthetic-private-source" not in response.text
    base = "/api/ai/image-assets/" + data["asset_id"]
    headers = auth_headers(seed_data["doctor_user"].username)
    pixels = await async_client.get(base + "/pixels", headers=headers)
    assert pixels.status_code == 200 and pixels.content == image_case[1]
    assert pixels.headers["cache-control"] == "private, no-store" and pixels.headers["x-content-type-options"] == "nosniff"
    assert pixels.headers["x-image-rows"] == "2" and pixels.headers["x-image-columns"] == "3" and pixels.headers["x-image-pixel-format"] == "int32le"
    original = await async_client.get(base + "/content", headers=headers)
    assert original.status_code == 200 and original.content == image_case[0]
    assert original.headers["content-type"] == "application/dicom"
    assert "synthetic-private-source" not in original.headers["content-disposition"]
    assert original.headers["cache-control"] == "private, no-store" and original.headers["x-content-type-options"] == "nosniff"
    assert (await async_client.get(base + "/pixels")).status_code == 401
    directory = image_directory(data["asset_id"])
    assert directory.stat().st_mode & 0o777 == 0o700
    assert (directory / "source.dcm").stat().st_mode & 0o777 == 0o600
    assert (directory / "pixels.i32le").stat().st_mode & 0o777 == 0o600
    assert db_session.query(AIRun).count() == 0
    events = db_session.query(AIAuditEvent).filter(AIAuditEvent.action.like("image.%")).all()
    assert {row.action for row in events} >= {"image.register", "image.pixels_read", "image.content_read"}
    assert all("SYNTHETIC_PRIVATE" not in row.detail_json and "隔离合成测试" not in row.detail_json for row in events)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "changes", [{"authorization_confirmed": "false"}, {"authorization_note": "  "}, {"recorded_at": "2026-10-20T10:00:00"}, {"patient_id": "999999999"}, {"imaging_order_id": "unknown-order"}]
)
async def test_missing_authority_order_patient_or_verified_time_fails_before_storage(changes, image_case, seed_data, db_session, async_client, auth_headers):
    response = await upload_image(async_client, auth_headers, seed_data, image_case, **changes)
    assert response.status_code in {404, 422}, response.text
    assert not image_case[4].exists() and db_session.query(AIImageAsset).count() == 0


@pytest.mark.asyncio
async def test_declared_capture_time_is_utc_not_derived_from_dicom_or_upload(image_case, seed_data, async_client, auth_headers):
    response = await upload_image(async_client, auth_headers, seed_data, image_case, recorded_at="2026-10-20T12:34:56.123456+08:00")
    assert response.status_code == 200, response.text
    assert response.json()["data"]["recorded_at"] == "2026-10-20T04:34:56.123456"


@pytest.mark.asyncio
async def test_requesting_order_only_grants_image_scope_and_never_infers_encounter(image_case, seed_data, db_session, async_client, auth_headers):
    patient = Patient(name="合成仅影像申请患者", identity="image-" + uuid.uuid4().hex[:12])
    db_session.add(patient)
    db_session.flush()
    own = ImagingOrder(patient_id=patient.patient_id, doctor_id=seed_data["doctor"].doctor_id, modality="DR", body_part="合成部位", status=0, create_time=utcnow())
    other = ImagingOrder(patient_id=patient.patient_id, doctor_id=seed_data["director_doctor"].doctor_id, modality="DR", body_part="其他申请", status=0, create_time=utcnow())
    encounter = Registration(patient_id=patient.patient_id, doctor_id=seed_data["director_doctor"].doctor_id, department_id=seed_data["department"].department_id, time=utcnow(), status=0)
    db_session.add_all([own, other, encounter])
    db_session.commit()
    doctor = auth_headers(seed_data["doctor_user"].username)
    directory = await async_client.get("/api/ai/image-orders", headers=doctor, params={"patient_id": patient.patient_id})
    assert directory.status_code == 200, directory.text
    assert [row["imaging_order_id"] for row in directory.json()["data"]["items"]] == [own.imaging_order_id]
    assert (await async_client.get("/api/ai/image-orders", headers=doctor, params={"patient_id": patient.patient_id, "encounter_ref": encounter.registration_uuid})).status_code == 403
    response = await upload_image(async_client, auth_headers, seed_data, image_case, patient_id=str(patient.patient_id), imaging_order_id=own.imaging_order_id, encounter_ref=None)
    assert response.status_code == 200, response.text
    assert response.json()["data"]["encounter_ref"] is None
    unrelated = await async_client.get("/api/ai/context", headers=doctor, params={"feature_key": "patient_summary", "patient_id": patient.patient_id})
    assert unrelated.status_code == 403


@pytest.mark.asyncio
async def test_foreign_patient_order_and_encounter_never_link_by_date(image_case, seed_data, db_session, async_client, auth_headers):
    foreign = Registration(patient_id=seed_data["patient2"].patient_id, time=utcnow(), status=0)
    db_session.add(foreign)
    db_session.commit()
    response = await upload_image(async_client, auth_headers, seed_data, image_case, encounter_ref=foreign.registration_uuid)
    assert response.status_code == 404
    response = await upload_image(async_client, auth_headers, seed_data, image_case, patient_id=str(seed_data["patient2"].patient_id), encounter_ref=None)
    assert response.status_code == 404
    assert db_session.query(AIImageAsset).count() == 0


@pytest.mark.asyncio
async def test_technician_needs_explicit_grant_and_team_read_does_not_grant_withdrawal(image_case, seed_data, db_session, async_client, auth_headers):
    db_session.add(LabOrder(patient_id=image_case[2].patient_id, doctor_id=seed_data["doctor"].doctor_id, check_type="合成普通检验单", status=0))
    db_session.commit()
    tech = auth_headers(seed_data["lab_tech_user"].username)
    assert (await async_client.get("/api/ai/image-orders", headers=tech, params={"patient_id": image_case[2].patient_id})).status_code == 403
    assert (await upload_image(async_client, auth_headers, seed_data, image_case, role="lab_tech_user")).status_code == 403
    grant = AIPatientGrant(
        user_id=seed_data["lab_tech_user"].user_id,
        patient_id=image_case[2].patient_id,
        category="diagnostics",
        reason="合成原图处理授权",
        expires_at=utcnow() + datetime.timedelta(hours=1),
        created_by=seed_data["super_admin_user"].user_id,
    )
    db_session.add(grant)
    db_session.commit()
    response = await upload_image(async_client, auth_headers, seed_data, image_case, role="lab_tech_user")
    assert response.status_code == 200, response.text
    base = "/api/ai/image-assets/" + response.json()["data"]["asset_id"]
    doctor = auth_headers(seed_data["doctor_user"].username)
    assert (await async_client.get(base + "/pixels", headers=doctor)).status_code == 200
    listing = await async_client.get("/api/ai/image-assets", headers=doctor, params={"patient_id": image_case[2].patient_id, "imaging_order_id": image_case[3].imaging_order_id})
    assert listing.status_code == 200 and listing.json()["data"]["items"][0]["can_withdraw"] is False
    assert (await async_client.post(base + "/withdraw", headers=doctor, json={"expected_revision": 1, "reason": "非登记人不能撤回他人原图"})).status_code == 403
    grant.revoked = 1
    db_session.commit()
    assert (await async_client.get(base + "/pixels", headers=tech)).status_code == 403
    assert (await async_client.get(base + "/content", headers=doctor)).status_code == 200


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["quota", "role", "care", "canceled", "reassociated", "configuration", "second_file"])
async def test_post_parse_revalidation_and_partial_install_cleanup(change, image_case, seed_data, db_session, async_client, auth_headers, monkeypatch):
    if change == "quota":
        monkeypatch.setattr(settings, "AI_IMAGE_USER_QUOTA_BYTES", 1)
    elif change == "second_file":
        original_link = ai_images.os.link

        def fail_second(source, target):
            if source.name == "pixels.i32le":
                raise FileExistsError("isolated derived-pixel installation failure")
            return original_link(source, target)

        monkeypatch.setattr(ai_images.os, "link", fail_second)
    else:
        original_stage = ai_images.stage_image

        def mutate_after_parsing(*args):
            result = original_stage(*args)
            if change == "role":
                seed_data["doctor_user"].user_role = "nurse"
            elif change == "care":
                image_case[2].doctor_id = None
            elif change == "canceled":
                image_case[3].status = 5
            elif change == "reassociated":
                image_case[3].patient_id = seed_data["patient2"].patient_id
            elif change == "configuration":
                db_session.add(AIFeatureConfig(feature_key="imaging_detection", allowed_roles_json='["super_admin"]', updated_by=seed_data["super_admin_user"].user_id))
            db_session.commit()
            return result

        monkeypatch.setattr(ai_images, "stage_image", mutate_after_parsing)
    if change == "second_file":
        with pytest.raises(FileExistsError):
            await upload_image(async_client, auth_headers, seed_data, image_case)
    else:
        response = await upload_image(async_client, auth_headers, seed_data, image_case)
        assert response.status_code == {"quota": 429, "role": 403, "care": 403, "canceled": 409, "reassociated": 404, "configuration": 403}[change], response.text
    assert db_session.query(AIImageAsset).count() == 0 and list(image_case[4].iterdir()) == []


@pytest.mark.asyncio
async def test_canceled_order_preserves_authorized_raw_review_and_owner_withdrawal(image_case, seed_data, db_session, async_client, auth_headers):
    data = (await upload_image(async_client, auth_headers, seed_data, image_case)).json()["data"]
    base = "/api/ai/image-assets/" + data["asset_id"]
    image_case[3].status = 5
    db_session.commit()
    doctor = auth_headers(seed_data["doctor_user"].username)
    assert (await async_client.get(base + "/pixels", headers=doctor)).status_code == 200
    assert (await upload_image(async_client, auth_headers, seed_data, image_case)).status_code == 409
    assert (await async_client.post(base + "/withdraw", headers=doctor, json={"expected_revision": 1, "reason": "申请取消后原登记人撤回原图"})).status_code == 200


@pytest.mark.asyncio
async def test_current_feature_role_and_original_encounter_are_required_on_reads(image_case, seed_data, db_session, async_client, auth_headers):
    data = (await upload_image(async_client, auth_headers, seed_data, image_case)).json()["data"]
    base = "/api/ai/image-assets/" + data["asset_id"]
    doctor = auth_headers(seed_data["doctor_user"].username)
    config = AIFeatureConfig(feature_key="imaging_detection", allowed_roles_json='["super_admin"]', updated_by=seed_data["super_admin_user"].user_id)
    db_session.add(config)
    db_session.commit()
    for suffix in ("", "/pixels", "/content"):
        assert (await async_client.get(base + suffix, headers=doctor)).status_code == 403
    db_session.delete(config)
    image_case[2].doctor_id = None
    db_session.commit()
    for suffix in ("", "/pixels", "/content"):
        assert (await async_client.get(base + suffix, headers=doctor)).status_code == 403


@pytest.mark.asyncio
async def test_super_purge_is_durable_recoverable_and_keeps_original_request_note(image_case, seed_data, db_session, async_client, auth_headers, monkeypatch):
    data = (await upload_image(async_client, auth_headers, seed_data, image_case)).json()["data"]
    asset_id = data["asset_id"]
    base = "/api/ai/image-assets/" + asset_id
    admin = auth_headers(seed_data["super_admin_user"].username)
    request = {"expected_revision": 1, "reason": "超级管理员核对撤回原图请求"}
    assert (await async_client.post(base + "/withdraw", headers=admin, json=request)).status_code == 200
    assert (await async_client.post(base + "/withdraw", headers=admin, json=request)).status_code == 409
    assert (await async_client.get(base + "/pixels", headers=auth_headers(seed_data["doctor_user"].username))).status_code == 409
    assert (await async_client.get(base + "/pixels", headers=admin)).status_code == 200
    original_remove = ai_images.shutil.rmtree

    def fail_cleanup(path, *args, **kwargs):
        if path.name == asset_id:
            raise PermissionError("isolated source purge failure")
        return original_remove(path, *args, **kwargs)

    monkeypatch.setattr(ai_images.shutil, "rmtree", fail_cleanup)
    url = f"/api/ai/admin/image-assets/{asset_id}/purge"
    response = await async_client.post(url, headers=admin, json={"expected_revision": 2, "reason": "第一次请求清除当前存储原图和派生像素"})
    assert response.status_code == 503
    db_session.expire_all()
    asset = db_session.get(AIImageAsset, asset_id)
    assert asset.status == "purge_pending" and asset.revision == 3 and asset.purge_note == "第一次请求清除当前存储原图和派生像素"
    assert (await async_client.get(base + "/content", headers=admin)).status_code == 410
    monkeypatch.setattr(ai_images.shutil, "rmtree", original_remove)
    response = await async_client.post(url, headers=admin, json={"expected_revision": 3, "reason": "恢复清除并保留第一次请求说明"})
    assert response.status_code == 200 and not image_directory(asset_id).exists()
    db_session.refresh(asset)
    assert asset.status == "purged" and asset.revision == 4 and asset.purge_note == "第一次请求清除当前存储原图和派生像素"
    assert db_session.query(AIAuditEvent).filter_by(action="image.purged", target=asset_id).count() == 1


@pytest.mark.asyncio
async def test_reassociated_order_blocks_raw_reads_but_super_can_still_govern_files(image_case, seed_data, db_session, async_client, auth_headers):
    data = (await upload_image(async_client, auth_headers, seed_data, image_case)).json()["data"]
    asset_id = data["asset_id"]
    image_case[3].patient_id = seed_data["patient2"].patient_id
    db_session.commit()
    admin = auth_headers(seed_data["super_admin_user"].username)
    assert (await async_client.get(f"/api/ai/image-assets/{asset_id}/pixels", headers=admin)).status_code == 409
    listing = await async_client.get("/api/ai/admin/image-assets", headers=admin)
    assert listing.status_code == 200 and listing.json()["data"]["items"][0]["source_error"]
    assert (await async_client.post(f"/api/ai/image-assets/{asset_id}/withdraw", headers=admin, json={"expected_revision": 1, "reason": "申请患者关联变化后撤回原图"})).status_code == 200
    assert (await async_client.post(f"/api/ai/admin/image-assets/{asset_id}/purge", headers=admin, json={"expected_revision": 2, "reason": "清除关联失效原图及派生像素"})).status_code == 200
    assert not image_directory(asset_id).exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["source.dcm", "pixels.i32le"])
async def test_tampered_original_or_pixels_fail_before_either_stream_is_served(name, image_case, seed_data, async_client, auth_headers):
    data = (await upload_image(async_client, auth_headers, seed_data, image_case)).json()["data"]
    target = image_directory(data["asset_id"]) / name
    target.write_bytes(b"synthetic changed source bytes")
    headers = auth_headers(seed_data["doctor_user"].username)
    for part in ("pixels", "content"):
        response = await async_client.get(f"/api/ai/image-assets/{data['asset_id']}/{part}", headers=headers)
        assert response.status_code == 409, response.text


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["admin", "nurse", "pharmacist", "cashier", "guide", "patient", "registrar"])
async def test_unrelated_roles_cannot_read_or_govern_internal_images(role, seed_data, async_client, auth_headers):
    headers = auth_headers(seed_data[role + "_user"].username)
    for url in ("/api/ai/image-options", "/api/ai/image-orders?patient_id=1", "/api/ai/image-assets?patient_id=1", "/api/ai/admin/image-assets"):
        assert (await async_client.get(url, headers=headers)).status_code == 403
    assert (await async_client.post("/api/ai/admin/image-assets/unknown/purge", headers=headers, json={"expected_revision": 1, "reason": "非超级管理员不能清除原图"})).status_code == 403


def test_order_state_and_source_version_invalidate_frozen_non_admin_results(image_case, seed_data, db_session):
    from fastapi import HTTPException

    order = image_case[3]
    asset = AIImageAsset(
        patient_id=order.patient_id,
        imaging_order_id=order.imaging_order_id,
        encounter_ref=image_case[2].registration_uuid,
        content_hash="a" * 64,
        original_hash="b" * 64,
        pixel_hash="c" * 64,
        byte_size=100,
        original_byte_size=76,
        pixel_byte_size=24,
        metadata_json='{"format":"dicom_i32le_v1","rows":2,"columns":3}',
        authorization_note="合成来源核对说明",
        authorized_at=utcnow(),
        created_by=seed_data["doctor_user"].user_id,
    )
    db_session.add(asset)
    db_session.commit()
    frozen = image_snapshot(asset, db=db_session)
    assert not {"patient_id", "authorization_note", "created_by", "create_time", "accession_no", "body_part"}.intersection(frozen)
    authorize_image_snapshot(db_session, seed_data["doctor_user"], {"image_source": frozen}, ai_images.authorize_patient)
    order.body_part = "修改后部位，不能继续使用旧模型结果"
    db_session.commit()
    with pytest.raises(HTTPException) as invalidated:
        authorize_image_snapshot(db_session, seed_data["doctor_user"], {"image_source": frozen}, ai_images.authorize_patient)
    assert invalidated.value.status_code == 403
    authorize_image_snapshot(db_session, seed_data["super_admin_user"], {"image_source": frozen}, ai_images.authorize_patient)


def test_image_migration_roundtrip_preserves_existing_rows_and_matches_model(tmp_path):
    path = tmp_path / "image-migration.sqlite"
    url = "sqlite:///" + str(path)
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", url)
    assert migrate(url) == "bootstrapped"
    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO hoimsystem_patient (patient_id,name,identity) VALUES(90001,'isolated-existing-image-patient','isolated-image-id')"))
    assert {column["name"] for column in inspect(engine).get_columns(AIImageAsset.__tablename__)} == set(AIImageAsset.__table__.columns.keys())
    command.downgrade(config, "20261020_ai_ecg_assets")
    assert AIImageAsset.__tablename__ not in inspect(engine).get_table_names()
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT name FROM hoimsystem_patient WHERE patient_id=90001")) == "isolated-existing-image-patient"
    assert migrate(url) == "upgraded"
    # Alembic used another engine; discard the old pooled SQLite schema state.
    engine.dispose()
    assert {column["name"] for column in inspect(engine).get_columns(AIImageAsset.__tablename__)} == set(AIImageAsset.__table__.columns.keys())
    assert {index["name"] for index in inspect(engine).get_indexes(AIImageAsset.__tablename__)} == {"idx_ai_image_patient_time", "idx_ai_image_owner_status", "idx_ai_image_order"}
    engine.dispose()
