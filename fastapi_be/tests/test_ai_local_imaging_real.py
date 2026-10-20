"""Opt-in real offline image classifier from original DICOM upload to frozen preview.

Uses synthetic pixels and isolated database fixtures. No diagnosis quality is
measured, no patient images are loaded, and no models or references downloaded.
"""

import hashlib
import json
import math
import os
from email import policy
from email.parser import BytesParser
from pathlib import Path

import httpx
import pytest

from app.ai.catalog import COMMON_SYSTEM_PROMPT, FEATURE_BY_KEY
from app.ai.governance import encode_json
from app.ai.models import AIFeatureConfig, AIProvider, AIRun, utcnow
from app.ai.runtime import claim_next_run, create_run, execute_claimed
from app.ai.schemas import RunRequest
from app.config import settings
from app.models import ClinicalDiagnosisReview, ExamResult, ImagingOrder, ImagingReport, InpatientOrder, LabResult, MedicalRecord, Prescription, Registration, StructuredMedicalRecord

KEY = "imaging_detection"
LABELS = [
    "Atelectasis",
    "Consolidation",
    "Infiltration",
    "Pneumothorax",
    "Edema",
    "Emphysema",
    "Fibrosis",
    "Effusion",
    "Pneumonia",
    "Pleural_Thickening",
    "Cardiomegaly",
    "Nodule",
    "Mass",
    "Hernia",
    "Lung Lesion",
    "Fracture",
    "Lung Opacity",
    "Enlarged Cardiomediastinum",
]


@pytest.mark.asyncio
@pytest.mark.skipif(not os.environ.get("HOIM_IMAGING_REAL_MODEL_DIR"), reason="Requires explicitly prepared pinned imaging weights and optional offline CPU runtime")
async def test_original_synthetic_dicom_to_actual_cpu_child_and_frozen_unvalidated_preview(db_session, seed_data, async_client, auth_headers, tmp_path, monkeypatch):
    # Ordinary backend tests never require the optional torch/safetensors runtime.
    from app.ai.imaging_config import ImagingSettings, runtime_descriptor
    from app.ai.imaging_server import create_imaging_app
    from scripts.smoke_local_imaging import synthetic_source

    monkeypatch.setattr(settings, "AI_IMAGE_STORAGE_DIR", str(tmp_path / "private-image-sources"))
    credential = "isolated-real-image-test-not-a-production-credential"
    monkeypatch.setenv("AI_PROVIDER_LOCAL_IMAGING_API_KEY", credential)
    config = ImagingSettings(model_dir=Path(os.environ["HOIM_IMAGING_REAL_MODEL_DIR"]), AI_PROVIDER_LOCAL_IMAGING_API_KEY=credential)
    descriptor = runtime_descriptor(config)
    raw, expected_source, original = synthetic_source(return_original=True)
    assert expected_source["image_metadata"]["rows"] == 225 and expected_source["image_metadata"]["columns"] == 226
    encounter = Registration(patient_id=seed_data["patient"].patient_id, doctor_id=seed_data["doctor"].doctor_id, department_id=seed_data["department"].department_id, time=utcnow(), status=0)
    order = ImagingOrder(patient_id=seed_data["patient"].patient_id, doctor_id=seed_data["doctor"].doctor_id, modality="DR", body_part="合成胸部申请，不提供为病灶依据", status=3, create_time=utcnow())
    db_session.add_all([encounter, order])
    db_session.flush()
    report = ImagingReport(imaging_order_id=order.imaging_order_id, findings="原有报告草稿，不可由模型改写", impression="原有临床意见", author_id=seed_data["doctor_user"].user_id, status=0)
    db_session.add(report)
    db_session.commit()
    doctor_headers = auth_headers(seed_data["doctor_user"].username)
    super_headers = auth_headers(seed_data["super_admin_user"].username)
    response = await async_client.post(
        "/api/ai/image-assets",
        headers=doctor_headers,
        files={"image": ("synthetic-original-potential-identifiers.dcm", original, "application/dicom")},
        data={
            "patient_id": str(order.patient_id),
            "imaging_order_id": order.imaging_order_id,
            "encounter_ref": encounter.registration_uuid,
            "authorization_confirmed": "true",
            "authorization_note": "仅合成DICOM与隔离测试患者，不是真实授权或临床验证证据",
        },
    )
    assert response.status_code == 200, response.text
    asset = response.json()["data"]
    assert asset["original_hash"] == hashlib.sha256(original).hexdigest()
    assert asset["pixel_hash"] == hashlib.sha256(raw).hexdigest()
    assert asset["image_metadata"] == expected_source["image_metadata"]
    assert asset["content_hash"] == expected_source["content_hash"] and asset["recorded_at"] is None
    assert "SYNTHETIC_ONLY" not in response.text and "SYNTHETIC^NOT_A_PATIENT" not in response.text
    source_url = "/api/ai/image-assets/" + asset["asset_id"]
    assert (await async_client.get(source_url + "/pixels", headers=doctor_headers)).content == raw
    assert (await async_client.get(source_url + "/content", headers=doctor_headers)).content == original

    spec = FEATURE_BY_KEY[KEY]
    provider = AIProvider(
        name="opt-in-real-image-cpu-test",
        kind="specialist",
        api_base="http://localhost:8812",
        model=descriptor["model_version"],
        api_key_env="AI_PROVIDER_LOCAL_IMAGING_API_KEY",
        enabled=1,
        allows_patient_data=1,
        timeout_seconds=120,
        supported_features_json=encode_json([KEY]),
        validation_report="仅合成胸片工程联调，无临床验证，不开启医生诊疗功能",
        created_by=seed_data["super_admin_user"].user_id,
    )
    db_session.add(provider)
    db_session.flush()
    feature = AIFeatureConfig(
        feature_key=KEY,
        provider_id=provider.provider_id,
        enabled=0,
        allowed_roles_json=encode_json(spec.default_roles),
        validation_status="unreviewed",
        updated_by=seed_data["super_admin_user"].user_id,
    )
    db_session.add(feature)
    db_session.commit()
    body = {
        "feature_key": KEY,
        "patient_id": order.patient_id,
        "encounter_ref": encounter.registration_uuid,
        "input": {"image_asset_id": asset["asset_id"], "imaging_order_id": order.imaging_order_id, "question": "只核对合成原图，不将本问题作为病灶证据"},
    }
    assert (await async_client.post("/api/ai/runs", headers=doctor_headers, json=body)).status_code == 409
    assert (await async_client.post("/api/ai/runs", headers=doctor_headers, json={**body, "preview": True})).status_code == 403
    assert db_session.query(AIRun).count() == 0
    record = seed_data["medical_record"]
    before_record = (record.symptom, record.result, record.status, record.sign_time)
    before_report = (report.findings, report.impression, report.status, report.author_id, report.reviewer_id, report.report_time, report.review_time)
    before_order = (order.patient_id, order.doctor_id, order.status, order.body_part, order.modality)
    business_models = (MedicalRecord, StructuredMedicalRecord, ClinicalDiagnosisReview, Prescription, InpatientOrder, LabResult, ImagingOrder, ImagingReport, ExamResult)
    counts = {model: db_session.query(model).count() for model in business_models}
    run = create_run(db_session, seed_data["super_admin_user"], RunRequest(**body, preview=True))
    assert run.preview == 1 and run.status == "queued"
    requests = []

    class NativeServiceTransport(httpx.AsyncBaseTransport):
        """Inspect real wire bytes, then forward unchanged to the real ASGI service."""

        def __init__(self):
            self.local = httpx.ASGITransport(app=create_imaging_app(config))

        async def handle_async_request(self, request):
            assert request.method == "POST" and request.url.path == "/tasks"
            assert request.headers["authorization"] == "Bearer " + credential
            content = await request.aread()
            message = BytesParser(policy=policy.default).parsebytes(b"MIME-Version: 1.0\r\nContent-Type: " + request.headers["content-type"].encode() + b"\r\n\r\n" + content)
            parts = {item.get_param("name", header="content-disposition"): item for item in message.iter_parts()}
            assert set(parts) == {"task", "image"} and parts["image"].get_filename() == "pixels.i32le"
            assert parts["image"].get_payload(decode=True) == raw
            task = json.loads(parts["task"].get_payload(decode=True))
            assert task["schema_version"] == "4" and task["store"] is False
            assert task["model"] == descriptor["model_version"]
            assert task["instructions"] == COMMON_SYSTEM_PROMPT + "\n\n" + spec.task_prompt
            source = task["input"]["context"]["image_source"]
            assert source["asset_id"] == asset["asset_id"] and source["imaging_order_id"] == order.imaging_order_id
            assert source["pixel_hash"] == hashlib.sha256(raw).hexdigest()
            assert original not in content
            assert not any(text in content.decode(errors="replace") for text in ("SYNTHETIC_ONLY", "SYNTHETIC^NOT_A_PATIENT", "synthetic-original-potential-identifiers", "原有报告草稿"))
            assert "authorization_note" not in encode_json(task) and "合成胸部申请" not in encode_json(task)
            requests.append(task)
            # Default execute_job spawns the actual isolated CPU worker; no
            # model/executor/output is mocked, replaced or synthesized here.
            return await self.local.handle_async_request(request)

        async def aclose(self):
            await self.local.aclose()

    await execute_claimed(*claim_next_run(db_session), transport=NativeServiceTransport())
    db_session.refresh(run)
    assert run.status == "succeeded", (run.error_code, run.error_message)
    assert len(requests) == 1
    response = await async_client.get("/api/ai/runs/" + run.run_id, headers=super_headers)
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["preview"] == 1 and data["requires_human_review"] is True
    analysis = data["result"]["image_analysis"]
    assert all(analysis[key] == asset[key] for key in ("asset_id", "content_hash", "original_hash", "pixel_hash"))
    assert analysis["coordinate_space"] == "source_pixels"
    frozen_source = data["image_findings"]["image_source"]
    assert frozen_source["asset_id"] == asset["asset_id"] and frozen_source["imaging_order_id"] == order.imaging_order_id
    assert frozen_source["recorded_at"] is None
    processing = analysis["processing"]
    assert processing["input_rows"] == 225 and processing["input_columns"] == 226
    assert processing["input_frames"] == 1 and processing["processed_frames"] == [0]
    assert processing["analysis_region"] == {"x": 1, "y": 0, "width": 225, "height": 225}
    assert processing["instructions_digest"] == hashlib.sha256((COMMON_SYSTEM_PROMPT + "\n\n" + spec.task_prompt).encode()).hexdigest()
    runtime = processing["local_runtime"]
    for key in ("model_revision", "model_digest", "runtime_digest", "preprocessing_digest", "preprocessing", "engine_versions"):
        assert runtime[key] == descriptor[key]
    assert runtime["prompt_handling"] == "pixels_only" and runtime["clinical_validation"] == "not_provided" and runtime["population_applicability"] == "not_verified"
    native = processing["local_preprocessing"]
    assert native["normalization_maxval"] == 4095 and native["prepared_shape"] == [1, 1, 224, 224]
    assert native["input_pixel_count"] == 225 * 226 and native["cropped_pixel_count"] == 225 * 225 and native["discarded_pixel_count"] == 225
    assert native["padding_pixels_in_input"] == native["padding_pixels_in_crop"] == 0 and native["valid_pixels_in_crop"] == 225 * 225
    assert -1024.01 <= native["prepared_min"] <= native["prepared_max"] <= 1024.01
    findings = analysis["findings"]
    assert [finding["label"] for finding in findings] == LABELS
    assert all(
        finding["source_id"] == frozen_source["source_id"]
        and finding["location"] == "image"
        and finding["region"] is None
        and finding["score_kind"] == "model_score"
        and math.isfinite(finding["score"])
        and 0 <= finding["score"] <= 1
        for finding in findings
    )
    trace = await async_client.get("/api/ai/admin/runs/" + run.run_id, headers=super_headers)
    assert trace.status_code == 200
    frozen_request = trace.json()["data"]["frozen_request"]
    assert frozen_request["task_prompt"] == spec.task_prompt and frozen_request["provider_snapshot"]["model"] == descriptor["model_version"]
    assert frozen_request["payload"]["context"]["image_source"]["pixel_hash"] == asset["pixel_hash"]
    assert (await async_client.get("/api/ai/runs/" + run.run_id, headers=doctor_headers)).status_code == 403
    db_session.refresh(record)
    db_session.refresh(report)
    db_session.refresh(order)
    assert (record.symptom, record.result, record.status, record.sign_time) == before_record
    assert (report.findings, report.impression, report.status, report.author_id, report.reviewer_id, report.report_time, report.review_time) == before_report
    assert (order.patient_id, order.doctor_id, order.status, order.body_part, order.modality) == before_order
    assert {model: db_session.query(model).count() for model in business_models} == counts
    db_session.refresh(feature)
    assert feature.enabled == 0 and feature.validation_status == "unreviewed" and feature.validated_by is None and feature.validated_at is None
    assert db_session.query(AIRun).count() == 1
    artifact = tmp_path / "real-imaging-pipeline.json"
    artifact.write_text(
        encode_json(
            {
                "synthetic_only": True,
                "clinical_validation": "not_provided",
                "execution": "main_api_native_source_to_real_offline_cpu_child_super_admin_preview",
                "model_version": descriptor["model_version"],
                "model_digest": descriptor["model_digest"],
                "runtime_digest": descriptor["runtime_digest"],
                "preprocessing_digest": descriptor["preprocessing_digest"],
                "engine_versions": descriptor["engine_versions"],
                "original_hash": asset["original_hash"],
                "pixel_hash": asset["pixel_hash"],
                "content_hash": asset["content_hash"],
                "instructions_digest": processing["instructions_digest"],
                "input_rows": 225,
                "input_columns": 226,
                "actual_crop": processing["analysis_region"],
                "actual_preprocessing": native,
                "raw_scores": [{"label": finding["label"], "score": finding["score"]} for finding in findings],
                "feature_enabled": bool(feature.enabled),
                "feature_validation_status": feature.validation_status,
                "business_tables_unchanged": [model.__tablename__ for model in business_models],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    print("Synthetic real image pipeline artifact:", artifact)
