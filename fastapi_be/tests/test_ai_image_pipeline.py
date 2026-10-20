"""Native synthetic image transport and source invalidation, without a real classifier."""

import datetime
import hashlib
import json
import uuid
from email import policy
from email.parser import BytesParser

import httpx
import pytest
import pytest_asyncio

from app.ai.catalog import COMMON_SYSTEM_PROMPT, FEATURE_BY_KEY
from app.ai.gateway import AIExecutionError, generate
from app.ai.governance import encode_json
from app.ai.image_files import image_directory
from app.ai.models import AIFeatureConfig, AIImageAsset, AIPatientGrant, AIProvider, AIRun, utcnow
from app.ai.runtime import claim_next_run, create_run, describe_run, execute_claimed
from app.ai.schemas import RunRequest
from app.config import settings
from app.models import ImagingOrder, Patient, Registration
from tests.test_ai_image_sources import dicom_bytes

KEY = "imaging_detection"


@pytest_asyncio.fixture
async def image_case(db_session, seed_data, tmp_path, monkeypatch, async_client, auth_headers):
    monkeypatch.setattr(settings, "AI_IMAGE_STORAGE_DIR", str(tmp_path / "private-images"))
    for model in (AIRun, AIFeatureConfig, AIProvider, AIImageAsset):
        db_session.query(model).delete()
    db_session.query(AIPatientGrant).filter_by(user_id=seed_data["lab_tech_user"].user_id, category="diagnostics").delete()
    encounter = Registration(patient_id=seed_data["patient"].patient_id, doctor_id=seed_data["doctor"].doctor_id, department_id=seed_data["department"].department_id, time=utcnow(), status=0)
    order = ImagingOrder(
        patient_id=seed_data["patient"].patient_id,
        doctor_id=seed_data["doctor"].doctor_id,
        modality="DR",
        body_part="合成测试部位，选单内容不进入模型",
        status=0,
        create_time=utcnow(),
        accession_no="synthetic-" + uuid.uuid4().hex[:12],
    )
    db_session.add_all([encounter, order])
    db_session.commit()
    original, pixels = dicom_bytes()
    response = await async_client.post(
        "/api/ai/image-assets",
        headers=auth_headers(seed_data["doctor_user"].username),
        files={"image": ("synthetic-private-source.dcm", original, "application/dicom")},
        data={
            "patient_id": str(encounter.patient_id),
            "imaging_order_id": order.imaging_order_id,
            "encounter_ref": encounter.registration_uuid,
            "authorization_confirmed": "true",
            "authorization_note": "隔离合成像素协议测试，未作真实患者授权或临床验证",
        },
    )
    assert response.status_code == 200, response.text
    asset = db_session.get(AIImageAsset, response.json()["data"]["asset_id"])
    provider = AIProvider(
        name="isolated-image-v4",
        kind="specialist",
        api_base="http://localhost:11434",
        model="isolated-image-model",
        enabled=1,
        allows_patient_data=1,
        supported_features_json=encode_json([KEY]),
        validation_report="隔离合成协议测试，不构成医学影像识别或临床验证",
        created_by=seed_data["super_admin_user"].user_id,
    )
    db_session.add(provider)
    db_session.flush()
    db_session.add(
        AIFeatureConfig(
            feature_key=KEY,
            provider_id=provider.provider_id,
            enabled=1,
            allowed_roles_json=encode_json(FEATURE_BY_KEY[KEY].default_roles),
            validation_status="validated",
            validation_note="仅隔离测试，不改变真实启用状态",
            updated_by=seed_data["super_admin_user"].user_id,
        )
    )
    db_session.commit()
    return original, pixels, asset, encounter, order


def task(case):
    asset = case[2]
    return RunRequest(
        feature_key=KEY,
        patient_id=asset.patient_id,
        encounter_ref=asset.encounter_ref,
        input={"image_asset_id": asset.asset_id, "imaging_order_id": asset.imaging_order_id, "question": "仅隔离原像素协议测试"},
    )


def parts(request):
    message = BytesParser(policy=policy.default).parsebytes(b"MIME-Version: 1.0\r\nContent-Type: " + request.headers["content-type"].encode() + b"\r\n\r\n" + request.content)
    items = {part.get_param("name", header="content-disposition"): part for part in message.iter_parts()}
    assert set(items) == {"task", "image"} and items["image"].get_filename() == "pixels.i32le"
    return json.loads(items["task"].get_payload(decode=True)), items["image"].get_payload(decode=True)


def response_for(payload):
    source = payload["input"]["context"]["image_source"]
    metadata = source["image_metadata"]
    return {
        "schema_version": "4",
        "feature_key": KEY,
        "model_version": "isolated-image-model",
        "applicable": True,
        "result": {
            "summary": "隔离协议输出，未调用实际影像识别模型",
            "sections": [{"title": "协议测试引用", "content": "模拟返回不能用作诊断", "source_ids": [source["source_id"]]}],
            "warnings": ["未验证真实识别效果"],
            "missing_data": [],
        },
        "image_analysis": {
            **{key: source[key] for key in ("asset_id", "content_hash", "original_hash", "pixel_hash")},
            "coordinate_space": "source_pixels",
            "processing": {
                "instructions_digest": hashlib.sha256(payload["instructions"].encode()).hexdigest(),
                "input_rows": metadata["rows"],
                "input_columns": metadata["columns"],
                "input_frames": metadata["frames"],
                "processed_frames": [0],
                "analysis_region": {"x": 0, "y": 0, "width": metadata["columns"], "height": metadata["rows"]},
                "preprocessing_notes": ["隔离模拟：完整逻辑存储像素，未进行真实模型预处理"],
            },
            "findings": [
                {
                    "label": "协议测试候选（无临床含义）",
                    "description": "仅检验原图定位、来源和分数保留",
                    "location": "bounding_box",
                    "region": {"x": 0, "y": 0, "width": 1, "height": 1},
                    "score": 0.0,
                    "score_kind": "model_score",
                    "source_id": source["source_id"],
                }
            ],
        },
        "usage": {"input_tokens": 5, "output_tokens": 7},
    }


@pytest.mark.asyncio
async def test_preview_requires_native_source_and_excludes_original_identifiers_and_report_text(image_case, seed_data, db_session, async_client, auth_headers):
    asset = image_case[2]
    body = {"feature_key": KEY, "patient_id": asset.patient_id, "encounter_ref": asset.encounter_ref, "source_refs": {"image_asset_id": asset.asset_id, "imaging_order_id": asset.imaging_order_id}}
    headers = auth_headers(seed_data["doctor_user"].username)
    response = await async_client.post("/api/ai/context", headers=headers, json=body)
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["context"]["scope"] == "native_single_image_analysis" and len(data["evidence"]) == 1
    serialized = encode_json(data)
    assert not any(
        value in serialized
        for value in ("PRIVATE_NAME", "SYNTHETIC_PRIVATE", "SYNTH_PRIVATE", "合成测试部位", "authorization_note", "outpatient_records", "reviewed_imaging_reports", seed_data["patient"].name)
    )
    assert db_session.query(AIRun).count() == 0
    for refs in ({}, {"image_asset_id": asset.asset_id, "record_id": seed_data["medical_record"].medical_record_id}, {"imaging_order_id": asset.imaging_order_id}):
        assert (await async_client.post("/api/ai/context", headers=headers, json={**body, "source_refs": refs})).status_code == 422


@pytest.mark.asyncio
async def test_actual_canonical_pixels_and_complete_prompt_are_bound_without_clinical_writes(image_case, seed_data, db_session):
    original, pixels, asset, _, order = image_case
    record = seed_data["medical_record"]
    before = (record.symptom, record.result, record.status, order.status, order.report)
    run = create_run(db_session, seed_data["doctor_user"], task(image_case))
    requests = []

    def handle(request):
        payload, received = parts(request)
        requests.append(payload)
        assert received == pixels and original not in request.content
        assert payload["schema_version"] == "4" and payload["store"] is False
        assert COMMON_SYSTEM_PROMPT in payload["instructions"] and FEATURE_BY_KEY[KEY].task_prompt in payload["instructions"]
        assert payload["input"]["context"]["image_source"]["pixel_hash"] == hashlib.sha256(received).hexdigest()
        text = encode_json(payload)
        assert not any(value in text for value in ("PRIVATE_NAME", "SYNTHETIC_PRIVATE", "SYNTH_PRIVATE", "synthetic-private-source", "合成测试部位", "/private-images/"))
        return httpx.Response(200, json=response_for(payload))

    await execute_claimed(*claim_next_run(db_session), transport=httpx.MockTransport(handle))
    db_session.refresh(run)
    assert run.status == "succeeded", (run.error_code, run.error_message)
    assert len(requests) == 1 and (run.input_tokens, run.output_tokens) == (5, 7)
    result = describe_run(run)
    assert result["result"]["image_analysis"]["findings"][0]["score"] == 0.0
    assert result["image_findings"]["image_source"]["content_hash"] == asset.content_hash
    db_session.refresh(record)
    db_session.refresh(order)
    assert (record.symptom, record.result, record.status, order.status, order.report) == before


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "variant",
    [
        "asset",
        "content_hash",
        "original_hash",
        "pixel_hash",
        "rows",
        "columns",
        "frames",
        "processed_frames",
        "boolean_frame",
        "float_frame",
        "instructions",
        "source_id",
        "outside_crop",
        "out_of_image",
        "false_localization",
        "float_position",
        "boolean_score",
        "wrong_coordinates",
    ],
)
async def test_invalid_source_processing_and_locations_never_become_candidates(variant, image_case, seed_data, db_session):
    run = create_run(db_session, seed_data["doctor_user"], task(image_case))

    def handle(request):
        payload, _ = parts(request)
        value = response_for(payload)
        analysis = value["image_analysis"]
        processing, finding = analysis["processing"], analysis["findings"][0]
        if variant == "asset":
            analysis["asset_id"] = "00000000-0000-4000-8000-000000000000"
        elif variant in {"content_hash", "original_hash", "pixel_hash"}:
            analysis[variant] = "0" * 64
        elif variant in {"rows", "columns", "frames"}:
            processing["input_" + variant] += 1
        elif variant == "processed_frames":
            processing["processed_frames"] = [1]
        elif variant == "boolean_frame":
            processing["processed_frames"] = [False]
        elif variant == "float_frame":
            processing["processed_frames"] = [0.0]
        elif variant == "instructions":
            processing["instructions_digest"] = "0" * 64
        elif variant == "source_id":
            finding["source_id"] = "other-source"
        elif variant == "outside_crop":
            processing["analysis_region"] = {"x": 1, "y": 0, "width": 2, "height": 2}
        elif variant == "out_of_image":
            finding["region"]["width"] = 4
        elif variant == "false_localization":
            finding["location"] = "image"
        elif variant == "float_position":
            finding["region"]["x"] = 0.0
        elif variant == "wrong_coordinates":
            analysis["coordinate_space"] = "model_resized_pixels"
        else:
            finding["score"] = True
        return httpx.Response(200, json=value)

    await execute_claimed(*claim_next_run(db_session), transport=httpx.MockTransport(handle))
    db_session.refresh(run)
    assert run.status == "failed" and run.result_json == "{}", (variant, run.status, run.error_code)
    assert (run.input_tokens, run.output_tokens) == (5, 7)


def change_source(change, case, db, seed_data):
    _, _, asset, encounter, order = case
    if change == "withdraw":
        asset.status, asset.revision = "withdrawn", 2
    elif change == "bytes":
        (image_directory(asset.asset_id) / "pixels.i32le").write_bytes(b"x" * asset.pixel_byte_size)
    elif change == "original_bytes":
        (image_directory(asset.asset_id) / "source.dcm").write_bytes(b"x" * asset.original_byte_size)
    elif change == "encounter_removed":
        db.delete(encounter)
    elif change == "care":
        encounter.doctor_id = None
    elif change == "canceled":
        order.status = 5
    elif change == "reassociated":
        order.patient_id = seed_data["patient2"].patient_id
    elif change == "order_changed":
        order.body_part = "重新核对的部位，旧模型输出不再适用于当前申请"
    elif change == "role":
        seed_data["doctor_user"].user_role = "nurse"
    elif change == "grant":
        db.query(AIPatientGrant).filter_by(user_id=seed_data["lab_tech_user"].user_id, category="diagnostics").update({"revoked": 1})
    db.commit()


def run_author(change, seed_data, db, patient_id):
    if change != "grant":
        return seed_data["doctor_user"]
    db.add(
        AIPatientGrant(
            user_id=seed_data["lab_tech_user"].user_id,
            patient_id=patient_id,
            category="diagnostics",
            reason="隔离影像协议授权测试",
            expires_at=utcnow() + datetime.timedelta(hours=1),
            created_by=seed_data["super_admin_user"].user_id,
        )
    )
    db.commit()
    return seed_data["lab_tech_user"]


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["withdraw", "bytes", "care", "canceled", "reassociated", "role", "grant"])
async def test_queued_changes_stop_before_model_receives_pixels(change, image_case, seed_data, db_session):
    author = run_author(change, seed_data, db_session, image_case[2].patient_id)
    run = create_run(db_session, author, task(image_case))
    change_source(change, image_case, db_session, seed_data)
    calls = []
    await execute_claimed(*claim_next_run(db_session), transport=httpx.MockTransport(lambda request: calls.append(request)))
    db_session.refresh(run)
    assert run.status == "failed" and calls == [], (change, run.status, run.error_code)


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["withdraw", "bytes", "care", "canceled", "reassociated", "role", "grant"])
async def test_inflight_changes_discard_returned_candidates_and_retain_super_trace(change, image_case, seed_data, db_session, async_client, auth_headers):
    author = run_author(change, seed_data, db_session, image_case[2].patient_id)
    author_name = author.username
    run = create_run(db_session, author, task(image_case))

    def handle(request):
        payload, _ = parts(request)
        change_source(change, image_case, db_session, seed_data)
        return httpx.Response(200, json=response_for(payload))

    await execute_claimed(*claim_next_run(db_session), transport=httpx.MockTransport(handle))
    db_session.refresh(run)
    assert run.status == "failed" and run.result_json == "{}", (change, run.status, run.error_code)
    assert (run.input_tokens, run.output_tokens) == (5, 7)
    result = await async_client.get("/api/ai/runs/" + run.run_id, headers=auth_headers(author_name))
    assert result.status_code in {403, 409}, (change, result.status_code)
    trace = await async_client.get("/api/ai/admin/runs/" + run.run_id, headers=auth_headers(seed_data["super_admin_user"].username))
    assert trace.status_code == 200 and trace.json()["data"]["image_findings"]["image_source"]["revision"] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["specialist", "chat", "responses"])
async def test_native_attachment_is_required_and_text_models_cannot_substitute(kind, image_case, seed_data, db_session):
    run = create_run(db_session, seed_data["doctor_user"], task(image_case))
    payload = json.loads(run.input_json)["payload"]
    provider = db_session.get(AIProvider, run.provider_id)
    provider.kind = kind
    calls = []
    with pytest.raises(AIExecutionError) as blocked:
        await generate(provider, FEATURE_BY_KEY[KEY], FEATURE_BY_KEY[KEY].task_prompt, payload, transport=httpx.MockTransport(lambda request: calls.append(request)))
    assert blocked.value.code == ("IMAGE_FILE_REQUIRED" if kind == "specialist" else "IMAGE_ADAPTER_REQUIRED") and calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["bytes", "original_bytes", "withdraw", "canceled", "reassociated", "order_changed", "encounter_removed"])
async def test_succeeded_candidates_require_current_original_source_and_order_on_every_read(change, image_case, seed_data, db_session, async_client, auth_headers):
    run = create_run(db_session, seed_data["doctor_user"], task(image_case))
    await execute_claimed(*claim_next_run(db_session), transport=httpx.MockTransport(lambda request: httpx.Response(200, json=response_for(parts(request)[0]))))
    db_session.refresh(run)
    assert run.status == "succeeded", (run.error_code, run.error_message)
    frozen_result = run.result_json
    change_source(change, image_case, db_session, seed_data)
    ordinary = await async_client.get("/api/ai/runs/" + run.run_id, headers=auth_headers(seed_data["doctor_user"].username))
    assert ordinary.status_code in ({404} if change == "encounter_removed" else {403, 409}), (change, ordinary.status_code)
    audit = await async_client.get("/api/ai/admin/runs/" + run.run_id, headers=auth_headers(seed_data["super_admin_user"].username))
    assert audit.status_code == 200
    data = audit.json()["data"]
    assert data["status"] == "succeeded" and data["result"] == json.loads(frozen_result)
    assert data["image_findings"]["image_source"]["revision"] == 1


@pytest.mark.asyncio
async def test_doctor_with_only_requesting_order_can_execute_and_read_native_task(image_case, seed_data, db_session, async_client, auth_headers):
    patient = Patient(name="合成仅影像申请患者", identity="image-" + uuid.uuid4().hex[:12])
    db_session.add(patient)
    db_session.flush()
    order = ImagingOrder(patient_id=patient.patient_id, doctor_id=seed_data["doctor"].doctor_id, modality="DR", body_part="合成部位", status=0, create_time=utcnow())
    db_session.add(order)
    db_session.commit()
    headers = auth_headers(seed_data["doctor_user"].username)
    response = await async_client.post(
        "/api/ai/image-assets",
        headers=headers,
        files={"image": ("synthetic-only-order.dcm", image_case[0], "application/dicom")},
        data={
            "patient_id": str(patient.patient_id),
            "imaging_order_id": order.imaging_order_id,
            "authorization_confirmed": "true",
            "authorization_note": "只有真实影像申请关系，不形成其他病历访问授权",
        },
    )
    assert response.status_code == 200, response.text
    asset = db_session.get(AIImageAsset, response.json()["data"]["asset_id"])
    run = create_run(
        db_session, seed_data["doctor_user"], RunRequest(feature_key=KEY, patient_id=patient.patient_id, input={"image_asset_id": asset.asset_id, "imaging_order_id": order.imaging_order_id})
    )
    await execute_claimed(*claim_next_run(db_session), transport=httpx.MockTransport(lambda request: httpx.Response(200, json=response_for(parts(request)[0]))))
    db_session.refresh(run)
    assert run.status == "succeeded", (run.error_code, run.error_message)
    assert (await async_client.get("/api/ai/runs/" + run.run_id, headers=headers)).status_code == 200
