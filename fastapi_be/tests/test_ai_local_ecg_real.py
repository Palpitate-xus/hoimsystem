"""Opt-in actual CPU classifier through native upload, preview task and frozen review.

Uses deterministic synthetic waveforms and isolated database fixtures. Agreement
with the source/protocol is tested; clinical accuracy is not evaluated. No model
or reference downloads occur in this test.
"""

import hashlib
import json
import math
import os
import struct
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
from app.models import ClinicalDiagnosisReview, ExamResult, ImagingReport, InpatientOrder, LabResult, MedicalRecord, Prescription, Registration, StructuredMedicalRecord

KEY = "ecg_analysis"
LEADS = ["I", "II", "III", "aVR", "aVL", "aVF", "V1", "V2", "V3", "V4", "V5", "V6"]
ORIGINAL_LEADS = ["V3", "I", "aVF", "V6", "II", "aVR", "V2", "III", "V4", "aVL", "V1", "V5"]
LABELS = ["NORM", "CD", "HYP", "MI", "STTC"]


def synthetic_wfdb_pair():
    import numpy as np

    time = np.arange(1000, dtype=np.float64) / 100
    channels, fields = [], []
    for column, name in enumerate(ORIGINAL_LEADS):
        index = LEADS.index(name)
        values_mv = (0.3 + index * 0.03) * np.sin(2 * np.pi * (1 + index / 10) * time) + 0.07 * np.cos(2 * np.pi * 3 * time)
        gain, unit, scale = ((1000, "mV", 1), (2, "uV", 0.001), (1000000, "V", 1000))[column % 3]
        baseline = column * 17 - 100
        digital = np.rint(values_mv / scale * gain + baseline).astype(np.int64)
        assert digital.min() > -32768 and digital.max() <= 32767
        channels.append(digital)
        checksum = int(digital.sum()) & 0xFFFF
        if checksum >= 32768:
            checksum -= 65536
        fields.append(f"synthetic.dat 16 {gain}({baseline})/{unit} 16 0 {int(digital[0])} {checksum} 0 {name}")
    samples = np.stack(channels, axis=1)
    raw = struct.pack("<" + "h" * samples.size, *(int(value) for value in samples.flat))
    header = "\n".join(["synthetic 12 100 1000", *fields, "# synthetic-only-private-header-comment-do-not-send-to-classifier", ""])
    return header.encode(), raw


@pytest.mark.asyncio
@pytest.mark.skipif(not os.environ.get("HOIM_ECG_REAL_MODEL_DIR"), reason="Requires explicitly prepared pinned ECG weights and optional CPU runtime")
async def test_synthetic_ecg_registration_to_actual_cpu_classifier_and_frozen_preview(db_session, seed_data, async_client, auth_headers, tmp_path, monkeypatch):
    # Delayed optional imports keep the ordinary backend suite independent of
    # the optional PyTorch/safetensors runtime and its prepared weights.
    from app.ai.ecg_config import ECGSettings, runtime_descriptor
    from app.ai.ecg_server import create_ecg_app

    monkeypatch.setattr(settings, "AI_ECG_STORAGE_DIR", str(tmp_path / "private"))
    credential = "isolated-real-ecg-test-not-a-production-credential"
    monkeypatch.setenv("AI_PROVIDER_LOCAL_ECG_API_KEY", credential)
    config = ECGSettings(model_dir=Path(os.environ["HOIM_ECG_REAL_MODEL_DIR"]), AI_PROVIDER_LOCAL_ECG_API_KEY=credential)
    descriptor = runtime_descriptor(config)
    header, raw = synthetic_wfdb_pair()
    encounter = Registration(patient_id=seed_data["patient"].patient_id, doctor_id=seed_data["doctor"].doctor_id, department_id=seed_data["department"].department_id, time=utcnow(), status=0)
    db_session.add(encounter)
    db_session.commit()
    doctor_headers = auth_headers(seed_data["doctor_user"].username)
    super_headers = auth_headers(seed_data["super_admin_user"].username)
    response = await async_client.post(
        "/api/ai/ecg-assets",
        headers=doctor_headers,
        files={"header": ("synthetic.hea", header, "application/octet-stream"), "signal": ("synthetic.dat", raw, "application/octet-stream")},
        data={
            "patient_id": str(encounter.patient_id),
            "encounter_ref": encounter.registration_uuid,
            "authorization_confirmed": "true",
            "authorization_note": "固定非临床合成波形与隔离测试患者，不是实际临床授权或质量验证",
        },
    )
    assert response.status_code == 200, response.text
    asset = response.json()["data"]
    assert asset["header_hash"] == hashlib.sha256(header).hexdigest()
    assert asset["signal_hash"] == hashlib.sha256(raw).hexdigest()
    assert [lead["name"] for lead in asset["signal_metadata"]["leads"]] == ORIGINAL_LEADS
    assert {lead["unit"] for lead in asset["signal_metadata"]["leads"]} == {"mV", "uV", "V"}
    assert all(lead["missing_samples"] == 0 for lead in asset["signal_metadata"]["leads"])

    spec = FEATURE_BY_KEY[KEY]
    provider = AIProvider(
        name="opt-in-real-ecg-cpu-test",
        kind="specialist",
        api_base="http://localhost:8811",
        model=descriptor["model_version"],
        api_key_env="AI_PROVIDER_LOCAL_ECG_API_KEY",
        enabled=1,
        allows_patient_data=1,
        timeout_seconds=120,
        supported_features_json=encode_json([KEY]),
        validation_report="仅隔离合成波形联调，未提供临床验证，不启用医生诊疗功能",
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
        "patient_id": encounter.patient_id,
        "encounter_ref": encounter.registration_uuid,
        "input": {"ecg_asset_id": asset["asset_id"], "question": "仅核对合成原波形研究输出，不用于诊断"},
    }
    assert (await async_client.post("/api/ai/runs", headers=doctor_headers, json=body)).status_code == 409
    assert (await async_client.post("/api/ai/runs", headers=doctor_headers, json={**body, "preview": True})).status_code == 403
    assert db_session.query(AIRun).count() == 0
    record = seed_data["medical_record"]
    before = (record.symptom, record.result, record.status, record.sign_time)
    business_models = (MedicalRecord, StructuredMedicalRecord, ClinicalDiagnosisReview, Prescription, InpatientOrder, LabResult, ImagingReport, ExamResult)
    counts = {model: db_session.query(model).count() for model in business_models}
    run = create_run(db_session, seed_data["super_admin_user"], RunRequest(**body, preview=True))
    assert run.preview == 1 and run.status == "queued"

    requests = []
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_ecg_app(config)), base_url="http://localhost:8811") as local_client:

        async def forward(request):
            assert request.method == "POST" and request.url.path == "/tasks"
            assert request.headers["authorization"] == "Bearer " + credential
            content = await request.aread()
            message = BytesParser(policy=policy.default).parsebytes(b"MIME-Version: 1.0\r\nContent-Type: " + request.headers["content-type"].encode() + b"\r\n\r\n" + content)
            parts = {item.get_param("name", header="content-disposition"): item for item in message.iter_parts()}
            assert set(parts) == {"task", "waveform"}
            assert parts["waveform"].get_filename() == "signal.dat"
            assert parts["waveform"].get_payload(decode=True) == raw
            task = json.loads(parts["task"].get_payload(decode=True))
            assert task["schema_version"] == "3" and task["store"] is False
            assert task["model"] == descriptor["model_version"]
            assert task["instructions"] == COMMON_SYSTEM_PROMPT + "\n\n" + spec.task_prompt
            assert "synthetic-only-private-header-comment" not in content.decode(errors="replace")
            assert "authorization_note" not in json.dumps(task)
            requests.append(task)
            # This forwards native bytes to the real service with its default
            # executor; the classifier is run by the actual isolated child.
            return await local_client.request(request.method, request.url.path, headers=dict(request.headers), content=content)

        await execute_claimed(*claim_next_run(db_session), transport=httpx.MockTransport(forward))

    db_session.refresh(run)
    assert run.status == "succeeded", (run.error_code, run.error_message)
    assert len(requests) == 1
    response = await async_client.get("/api/ai/runs/" + run.run_id, headers=super_headers)
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["preview"] == 1 and data["requires_human_review"] is True
    analysis = data["result"]["ecg_analysis"]
    assert analysis["asset_id"] == asset["asset_id"] and analysis["content_hash"] == asset["content_hash"] and analysis["signal_hash"] == hashlib.sha256(raw).hexdigest()
    assert analysis["time_basis"] == "relative_samples"
    source = data["ecg_findings"]["ecg_source"]
    assert source["asset_id"] == asset["asset_id"] and source["header_hash"] == hashlib.sha256(header).hexdigest()
    assert source["recorded_at"] is None
    processing = analysis["processing"]
    assert processing["input_sample_count"] == processing["processed_original_sample_count"] == 1000
    assert processing["input_sample_rate_hz"] == "100" and processing["complete_input"] is True
    assert processing["input_leads"] == ORIGINAL_LEADS and processing["used_leads"] == LEADS
    assert processing["missing_sample_handling"] == "none_present"
    assert processing["instructions_digest"] == hashlib.sha256((COMMON_SYSTEM_PROMPT + "\n\n" + spec.task_prompt).encode()).hexdigest()
    runtime = processing["local_runtime"]
    for key in ("model_revision", "model_digest", "runtime_digest", "preprocessing_digest"):
        assert runtime[key] == descriptor[key]
    assert runtime["prompt_handling"] == "signal_only"
    assert runtime["population_applicability"] == "not_verified"
    findings = analysis["findings"]
    assert [finding["label"] for finding in findings] == LABELS
    for finding in findings:
        assert finding["source_id"] == source["source_id"] and finding["leads"] == LEADS
        assert finding["location"] == "recording" and finding["start_sample"] is None and finding["end_sample_exclusive"] is None
        assert finding["score_kind"] == "model_score" and math.isfinite(finding["score"]) and 0 <= finding["score"] <= 1
    assert (await async_client.get("/api/ai/runs/" + run.run_id, headers=doctor_headers)).status_code == 403
    db_session.refresh(record)
    assert (record.symptom, record.result, record.status, record.sign_time) == before
    assert {model: db_session.query(model).count() for model in business_models} == counts
    db_session.refresh(feature)
    assert feature.enabled == 0 and feature.validation_status == "unreviewed" and feature.validated_by is None and feature.validated_at is None
    assert db_session.query(AIRun).count() == 1
