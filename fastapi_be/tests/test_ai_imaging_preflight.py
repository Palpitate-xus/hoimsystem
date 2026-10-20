"""Queue-time XRV scope checks against privately uploaded, actual synthetic DICOMs."""

import hashlib
import io
import json
import struct

import pydicom
import pytest
from pydicom.uid import ComputedRadiographyImageStorage, CTImageStorage, DigitalXRayImageStorageForPresentation

from app.ai.models import AIFeatureConfig, AIProvider, AIRun
from tests.test_ai_image_pipeline import KEY, task
from tests.test_ai_image_pipeline import image_case as image_case

LOCAL_MODEL = "xrv:" + "c" * 64


@pytest.fixture
def local_image_case(image_case, db_session):
    """Change only this test's isolated provider; retain the real upload fixture."""
    feature = db_session.get(AIFeatureConfig, KEY)
    provider = db_session.get(AIProvider, feature.provider_id)
    provider.model = LOCAL_MODEL
    db_session.commit()
    return image_case


def run_body(case, asset=None, *, preview=False):
    body = task(case).model_dump()
    body["preview"] = preview
    if asset is not None:
        body["input"]["image_asset_id"] = asset["asset_id"]
        body["input"]["imaging_order_id"] = asset["imaging_order_id"]
    return body


async def upload_native_variant(async_client, auth_headers, seed_data, case, *, modality="DX", body_part="CHEST", view="PA", bits=12, signed=False, slope=1, intercept=0):
    """Edit and serialize original bytes, then use the production multipart parser."""
    source = pydicom.dcmread(io.BytesIO(case[0]))
    source.Modality = modality
    sop = {"CR": ComputedRadiographyImageStorage, "DX": DigitalXRayImageStorageForPresentation, "CT": CTImageStorage}[modality]
    source.SOPClassUID = source.file_meta.MediaStorageSOPClassUID = sop
    source.BodyPartExamined = body_part
    source.ViewPosition = view
    source.BitsAllocated = 8 if bits <= 8 else 16
    source.BitsStored = bits
    source.HighBit = bits - 1
    source.PixelRepresentation = int(signed)
    source.RescaleSlope = str(slope)
    source.RescaleIntercept = str(intercept)
    source.WindowCenter = "0" if signed else str((1 << bits) // 2)
    source.WindowWidth = str(1 << bits)
    maximum = (1 << (bits - int(signed))) - 1
    samples = [-maximum, -1, 0, 1, maximum // 2, maximum] if signed else [0, 1, maximum // 4, maximum // 2, maximum - 1, maximum]
    source.PixelData = struct.pack("<6" + ("B" if source.BitsAllocated == 8 else "H"), *(sample & ((1 << bits) - 1) for sample in samples))
    # The fixture's old ambiguous PixelData VR must match its newly saved depth.
    source["PixelData"].VR = "OB" if source.BitsAllocated == 8 else "OW"
    output = io.BytesIO()
    source.save_as(output, enforce_file_format=True)
    original = output.getvalue()
    pixels = struct.pack("<6i", *samples)
    encounter, order = case[3:]
    headers = auth_headers(seed_data["doctor_user"].username)
    response = await async_client.post(
        "/api/ai/image-assets",
        headers=headers,
        files={"image": ("synthetic-native-preflight.dcm", original, "application/dicom")},
        data={
            "patient_id": str(order.patient_id),
            "imaging_order_id": order.imaging_order_id,
            "encounter_ref": encounter.registration_uuid,
            "authorization_confirmed": "true",
            "authorization_note": "合成原DICOM适用范围测试，未使用真实患者资料或临床验证证据",
        },
    )
    assert response.status_code == 200, response.text
    asset = response.json()["data"]
    assert asset["original_hash"] == hashlib.sha256(original).hexdigest()
    assert asset["pixel_hash"] == hashlib.sha256(pixels).hexdigest()
    metadata = asset["image_metadata"]
    assert metadata["modality"] == modality and metadata["sop_class_uid"] == str(sop)
    assert metadata["body_part_examined"] == body_part and metadata["view_position"] == view
    assert metadata["bits_stored"] == bits and metadata["pixel_representation"] == int(signed)
    assert metadata["rescale_slope"] == slope and metadata["rescale_intercept"] == intercept
    private_source = await async_client.get("/api/ai/image-assets/" + asset["asset_id"] + "/content", headers=headers)
    assert private_source.status_code == 200 and private_source.content == original
    return asset


def assert_no_task(db_session):
    assert db_session.query(AIRun).count() == 0


def assert_local_queued(response, db_session, asset):
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["status"] == "queued"
    assert db_session.query(AIRun).count() == 1
    run = db_session.get(AIRun, data["run_id"])
    frozen = json.loads(run.input_json)
    assert frozen["provider_snapshot"]["model"] == LOCAL_MODEL
    source = frozen["payload"]["context"]["image_source"]
    for key in ("asset_id", "imaging_order_id", "original_hash", "pixel_hash", "content_hash", "image_metadata"):
        assert source[key] == asset[key]
    assert run.result_json == "{}" and run.start_time is None


@pytest.mark.asyncio
async def test_existing_uploaded_signed_source_rejected_before_any_xrv_task(local_image_case, seed_data, db_session, async_client, auth_headers):
    # This is the actual original Part10 upload from the existing pipeline,
    # including signed 12-bit pixels; no database metadata is fabricated.
    asset = local_image_case[2]
    assert json.loads(asset.metadata_json)["pixel_representation"] == 1
    assert json.loads(asset.metadata_json)["bits_stored"] == 12
    assert_no_task(db_session)
    response = await async_client.post("/api/ai/runs", headers=auth_headers(seed_data["doctor_user"].username), json=run_body(local_image_case))
    assert response.status_code == 409, response.text
    assert "CR/DX" in response.json()["detail"] and "PA/AP" in response.json()["detail"]
    assert_no_task(db_session)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("variant", "accepted"),
    [
        pytest.param({"bits": 8}, True, id="unsigned-DX-CHEST-PA-8bit"),
        pytest.param({"view": "AP"}, True, id="unsigned-DX-CHEST-AP-12bit"),
        pytest.param({"bits": 16}, True, id="unsigned-DX-CHEST-PA-16bit"),
        pytest.param({"modality": "CR"}, True, id="unsigned-CR-CHEST-PA-identity"),
        pytest.param({"view": "LL"}, False, id="unsigned-DX-lateral"),
        pytest.param({"body_part": "HEAD"}, False, id="unsigned-DX-head"),
        pytest.param({"modality": "CT"}, False, id="actual-CT-SOP-and-modality"),
        pytest.param({"modality": "CR", "slope": 2}, False, id="CR-nonidentity-slope"),
        pytest.param({"modality": "CR", "intercept": -100}, False, id="CR-nonidentity-intercept"),
        pytest.param({"signed": True}, False, id="signed-DX-CHEST-PA"),
        pytest.param({"modality": "CR", "bits": 7}, False, id="unsigned-CR-7bit"),
    ],
)
async def test_actual_dicom_scope_is_checked_before_local_model_queue(variant, accepted, local_image_case, seed_data, db_session, async_client, auth_headers):
    asset = await upload_native_variant(async_client, auth_headers, seed_data, local_image_case, **variant)
    assert_no_task(db_session)
    response = await async_client.post("/api/ai/runs", headers=auth_headers(seed_data["doctor_user"].username), json=run_body(local_image_case, asset))
    if accepted:
        assert_local_queued(response, db_session, asset)
    else:
        assert response.status_code == 409, response.text
        assert "CR/DX" in response.json()["detail"] and "恒等重标定" in response.json()["detail"]
        assert_no_task(db_session)


@pytest.mark.asyncio
async def test_general_specialist_can_still_queue_the_original_signed_source(image_case, seed_data, db_session, async_client, auth_headers):
    feature = db_session.get(AIFeatureConfig, KEY)
    assert not db_session.get(AIProvider, feature.provider_id).model.startswith("xrv:")
    response = await async_client.post("/api/ai/runs", headers=auth_headers(seed_data["doctor_user"].username), json=run_body(image_case))
    assert response.status_code == 200, response.text
    assert response.json()["data"]["status"] == "queued" and db_session.query(AIRun).count() == 1
    run = db_session.get(AIRun, response.json()["data"]["run_id"])
    source = json.loads(run.input_json)["payload"]["context"]["image_source"]
    assert source["pixel_hash"] == image_case[2].pixel_hash
    assert source["image_metadata"]["pixel_representation"] == 1


@pytest.mark.asyncio
async def test_super_preview_of_disabled_unvalidated_feature_still_checks_native_scope(local_image_case, seed_data, db_session, async_client, auth_headers):
    asset = await upload_native_variant(async_client, auth_headers, seed_data, local_image_case)
    feature = db_session.get(AIFeatureConfig, KEY)
    feature.enabled = 0
    feature.validation_status = "unreviewed"
    feature.validated_by = feature.validated_at = None
    db_session.commit()
    doctor_headers = auth_headers(seed_data["doctor_user"].username)
    super_headers = auth_headers(seed_data["super_admin_user"].username)
    body = run_body(local_image_case, asset)
    assert (await async_client.post("/api/ai/runs", headers=doctor_headers, json=body)).status_code == 409
    assert (await async_client.post("/api/ai/runs", headers=doctor_headers, json={**body, "preview": True})).status_code == 403
    assert (await async_client.post("/api/ai/runs", headers=super_headers, json=body)).status_code == 409
    invalid_preview = await async_client.post("/api/ai/runs", headers=super_headers, json=run_body(local_image_case, preview=True))
    assert invalid_preview.status_code == 409 and "CR/DX" in invalid_preview.json()["detail"]
    assert_no_task(db_session)
    response = await async_client.post("/api/ai/runs", headers=super_headers, json={**body, "preview": True})
    assert_local_queued(response, db_session, asset)
    assert response.json()["data"]["preview"] == 1
    db_session.refresh(feature)
    assert feature.enabled == 0 and feature.validation_status == "unreviewed"
    assert feature.validated_by is None and feature.validated_at is None
