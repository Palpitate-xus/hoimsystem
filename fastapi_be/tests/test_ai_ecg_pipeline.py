"""Actual synthetic signal bytes and isolated responses test source-bound model transport.

No classifier or diagnostic accuracy is evaluated here.
"""

import hashlib
import json
from email import policy
from email.parser import BytesParser

import httpx
import pytest
import pytest_asyncio

from app.ai.catalog import COMMON_SYSTEM_PROMPT, FEATURE_BY_KEY
from app.ai.context import patient_snapshot
from app.ai.ecg_files import ecg_directory
from app.ai.governance import encode_json
from app.ai.models import AIECGAsset, AIFeatureConfig, AIProvider, AIRun, utcnow
from app.ai.runtime import claim_next_run, create_run, describe_run, execute_claimed
from app.ai.schemas import RunRequest
from app.config import settings
from app.models import Registration
from tests.test_ai_ecg_files import wfdb_bytes

KEY = "ecg_analysis"


@pytest_asyncio.fixture
async def ecg_case(db_session, seed_data, tmp_path, monkeypatch, async_client, auth_headers):
    monkeypatch.setattr(settings, "AI_ECG_STORAGE_DIR", str(tmp_path / "private"))
    for model in (AIRun, AIFeatureConfig, AIProvider, AIECGAsset):
        db_session.query(model).delete()
    header, raw = wfdb_bytes()
    encounter = Registration(patient_id=seed_data["patient"].patient_id, doctor_id=seed_data["doctor"].doctor_id, department_id=seed_data["department"].department_id, time=utcnow(), status=0)
    db_session.add(encounter)
    db_session.commit()
    response = await async_client.post(
        "/api/ai/ecg-assets",
        headers=auth_headers(seed_data["doctor_user"].username),
        files={"header": ("fixture.hea", header, "application/octet-stream"), "signal": ("fixture.dat", raw, "application/octet-stream")},
        data={
            "patient_id": str(encounter.patient_id),
            "encounter_ref": encounter.registration_uuid,
            "authorization_confirmed": "true",
            "authorization_note": "隔离合成信号测试原始资料核对，不表示临床授权或验证",
        },
    )
    assert response.status_code == 200, response.text
    asset = db_session.get(AIECGAsset, response.json()["data"]["asset_id"])
    provider = AIProvider(
        name="isolated-ecg-v3",
        kind="specialist",
        api_base="http://localhost:11434",
        model="isolated-signal-model",
        enabled=1,
        allows_patient_data=1,
        supported_features_json=encode_json([KEY]),
        validation_report="隔离协议测试，不构成心电识别或临床验证",
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
            validation_note="只用于隔离测试，不改变真实启用状态",
            updated_by=seed_data["super_admin_user"].user_id,
        )
    )
    db_session.commit()
    return header, raw, asset, encounter


def task(case):
    _, _, asset, encounter = case
    return RunRequest(feature_key=KEY, patient_id=asset.patient_id, encounter_ref=encounter.registration_uuid, input={"ecg_asset_id": asset.asset_id, "question": "仅隔离协议测试"})


def parts(request):
    message = BytesParser(policy=policy.default).parsebytes(b"MIME-Version: 1.0\r\nContent-Type: " + request.headers["content-type"].encode() + b"\r\n\r\n" + request.content)
    items = {item.get_param("name", header="content-disposition"): item for item in message.iter_parts()}
    assert set(items) == {"task", "waveform"}
    assert items["waveform"].get_filename() == "signal.dat"
    return json.loads(items["task"].get_payload(decode=True)), items["waveform"].get_payload(decode=True)


def response_for(payload):
    source = payload["input"]["context"]["ecg_source"]
    metadata = source["signal_metadata"]
    names = [lead["name"] for lead in metadata["leads"]]
    return {
        "schema_version": "3",
        "feature_key": KEY,
        "model_version": "isolated-signal-model",
        "applicable": True,
        "result": {
            "summary": "隔离测试输出，未调用实际心电模型",
            "sections": [{"title": "协议测试引用", "content": "模拟返回不作为诊断", "source_ids": [source["source_id"]]}],
            "warnings": ["未验证识别效果"],
            "missing_data": [],
        },
        "ecg_analysis": {
            "asset_id": source["asset_id"],
            "content_hash": source["content_hash"],
            "signal_hash": source["signal_hash"],
            "time_basis": "relative_samples",
            "processing": {
                "instructions_digest": hashlib.sha256(payload["instructions"].encode()).hexdigest(),
                "input_sample_count": metadata["sample_count"],
                "input_sample_rate_hz": metadata["sample_rate_hz"],
                "input_leads": names,
                "used_leads": names,
                "processed_original_sample_count": metadata["sample_count"],
                "complete_input": True,
                "missing_sample_handling": "masked",
                "preprocessing_notes": ["隔离模拟缺失样本说明，未评估真实模型适用性"],
            },
            "findings": [
                {
                    "category": "other",
                    "label": "测试候选（无临床含义）",
                    "description": "仅校验采样定位、导联和引用，不是真实识别结果",
                    "leads": [names[0]],
                    "location": "sample_interval",
                    "start_sample": 0,
                    "end_sample_exclusive": metadata["sample_count"],
                    "score": 0.0,
                    "score_kind": "model_score",
                    "source_id": source["source_id"],
                }
            ],
        },
        "usage": {"input_tokens": 5, "output_tokens": 7},
    }


@pytest.mark.asyncio
async def test_preview_is_source_only_and_cannot_substitute_a_text_report(ecg_case, seed_data, db_session, async_client, auth_headers):
    _, _, asset, encounter = ecg_case
    headers = auth_headers(seed_data["doctor_user"].username)
    body = {"feature_key": KEY, "patient_id": asset.patient_id, "encounter_ref": encounter.registration_uuid, "source_refs": {"ecg_asset_id": asset.asset_id}}
    response = await async_client.post("/api/ai/context", headers=headers, json=body)
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["context"]["scope"] == "raw_ecg_analysis" and len(data["evidence"]) == 1
    text = encode_json(data)
    assert not any(value in text for value in ("13812345678", "authorization_note", "allergy_history", "outpatient_records", seed_data["patient"].name))
    assert "ecg_source" in text and db_session.query(AIRun).count() == 0
    assert (await async_client.post("/api/ai/context", headers=headers, json={**body, "source_refs": {}})).status_code == 422
    assert (
        await async_client.post("/api/ai/context", headers=headers, json={**body, "source_refs": {"ecg_asset_id": asset.asset_id, "record_id": seed_data["medical_record"].medical_record_id}})
    ).status_code == 422


@pytest.mark.asyncio
async def test_native_signal_and_full_prompts_are_sent_without_header_phi_or_clinical_writes(ecg_case, seed_data, db_session, async_client, auth_headers):
    header, raw, asset, _ = ecg_case
    record = seed_data["medical_record"]
    before = (record.symptom, record.result, record.status)
    run = create_run(db_session, seed_data["doctor_user"], task(ecg_case))
    requests = []

    def handle(request):
        payload, received = parts(request)
        requests.append(payload)
        assert received == raw and header not in request.content
        assert payload["schema_version"] == "3" and payload["store"] is False
        assert COMMON_SYSTEM_PROMPT in payload["instructions"] and FEATURE_BY_KEY[KEY].task_prompt in payload["instructions"]
        assert payload["input"]["context"]["ecg_source"]["signal_hash"] == hashlib.sha256(received).hexdigest()
        assert "13812345678" not in request.content.decode(errors="replace") and "/private/" not in json.dumps(payload)
        return httpx.Response(200, json=response_for(payload))

    await execute_claimed(*claim_next_run(db_session), transport=httpx.MockTransport(handle))
    db_session.refresh(run)
    assert run.status == "succeeded", (run.error_code, run.error_message)
    assert len(requests) == 1 and (run.input_tokens, run.output_tokens) == (5, 7)
    data = describe_run(run)
    assert data["result"]["ecg_analysis"]["findings"][0]["score"] == 0.0
    assert data["ecg_findings"]["ecg_source"]["content_hash"] == asset.content_hash
    db_session.refresh(record)
    assert (record.symptom, record.result, record.status) == before


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "variant",
    [
        "asset",
        "hash",
        "signal_hash",
        "rate",
        "sample_count",
        "input_order",
        "partial",
        "incomplete",
        "missing_handling",
        "instructions",
        "source_id",
        "unavailable_lead",
        "range",
        "false_localization",
        "float_position",
        "boolean_score",
    ],
)
async def test_invalid_native_reports_never_become_candidates_and_reported_usage_is_retained(variant, ecg_case, seed_data, db_session):
    run = create_run(db_session, seed_data["doctor_user"], task(ecg_case))

    def handle(request):
        payload, _ = parts(request)
        value = response_for(payload)
        analysis = value["ecg_analysis"]
        processing, finding = analysis["processing"], analysis["findings"][0]
        if variant == "asset":
            analysis["asset_id"] = "00000000-0000-4000-8000-000000000000"
        elif variant in {"hash", "signal_hash"}:
            analysis["content_hash" if variant == "hash" else "signal_hash"] = "0" * 64
        elif variant == "rate":
            processing["input_sample_rate_hz"] = "250"
        elif variant == "sample_count":
            processing["input_sample_count"] = processing["processed_original_sample_count"] = 5
        elif variant == "input_order":
            processing["input_leads"].reverse()
        elif variant == "partial":
            processing["processed_original_sample_count"] = 2
        elif variant == "incomplete":
            processing["complete_input"] = False
        elif variant == "missing_handling":
            processing["missing_sample_handling"] = "none_present"
        elif variant == "instructions":
            processing["instructions_digest"] = "0" * 64
        elif variant == "source_id":
            finding["source_id"] = "other-source"
        elif variant == "unavailable_lead":
            finding["leads"] = ["III"]
        elif variant == "range":
            finding["end_sample_exclusive"] = 5
        elif variant == "false_localization":
            finding["location"] = "recording"
        elif variant == "float_position":
            finding["start_sample"] = 0.0
        else:
            finding["score"] = True
        return httpx.Response(200, json=value)

    await execute_claimed(*claim_next_run(db_session), transport=httpx.MockTransport(handle))
    db_session.refresh(run)
    assert run.status == "failed" and run.result_json == "{}", run.error_code
    assert (run.input_tokens, run.output_tokens) == (5, 7)


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["withdraw", "bytes", "care"])
async def test_queued_source_changes_stop_before_any_model_call(change, ecg_case, seed_data, db_session):
    _, _, asset, encounter = ecg_case
    run = create_run(db_session, seed_data["doctor_user"], task(ecg_case))
    if change == "withdraw":
        asset.status, asset.revision = "withdrawn", 2
    elif change == "bytes":
        (ecg_directory(asset.asset_id) / "source.dat").write_bytes(b"x" * asset.signal_byte_size)
    else:
        encounter.doctor_id = None
    db_session.commit()
    calls = []
    await execute_claimed(*claim_next_run(db_session), transport=httpx.MockTransport(lambda request: calls.append(request)))
    db_session.refresh(run)
    assert run.status == "failed" and calls == []


@pytest.mark.asyncio
async def test_inflight_withdrawal_rejects_result_hides_old_history_and_keeps_super_trace(ecg_case, seed_data, db_session, async_client, auth_headers):
    _, _, asset, _ = ecg_case
    run = create_run(db_session, seed_data["doctor_user"], task(ecg_case))

    def handle(request):
        payload, _ = parts(request)
        asset.status, asset.revision = "withdrawn", 2
        db_session.commit()
        return httpx.Response(200, json=response_for(payload))

    await execute_claimed(*claim_next_run(db_session), transport=httpx.MockTransport(handle))
    db_session.refresh(run)
    assert run.status == "failed" and run.result_json == "{}" and (run.input_tokens, run.output_tokens) == (5, 7)
    assert (await async_client.get("/api/ai/runs/" + run.run_id, headers=auth_headers(seed_data["doctor_user"].username))).status_code == 403
    trace = await async_client.get("/api/ai/admin/runs/" + run.run_id, headers=auth_headers(seed_data["super_admin_user"].username))
    assert trace.status_code == 200 and trace.json()["data"]["ecg_findings"]["ecg_source"]["revision"] == 1


@pytest.mark.asyncio
async def test_parser_owned_numeric_calibration_and_actual_lead_names_are_not_redacted_as_identifiers(ecg_case, seed_data, db_session, async_client, auth_headers):
    _, _, _, encounter = ecg_case
    seed_data["patient"].name = "I"
    db_session.commit()
    header, raw = wfdb_bytes(gain="13812345678")
    response = await async_client.post(
        "/api/ai/ecg-assets",
        headers=auth_headers(seed_data["doctor_user"].username),
        files={"header": ("fixture.hea", header, "application/octet-stream"), "signal": ("fixture.dat", raw, "application/octet-stream")},
        data={
            "patient_id": str(encounter.patient_id),
            "encounter_ref": encounter.registration_uuid,
            "authorization_confirmed": "true",
            "authorization_note": "实际合成头文件的数值校准测试，不使用伪造元数据",
        },
    )
    assert response.status_code == 200, response.text
    asset = db_session.get(AIECGAsset, response.json()["data"]["asset_id"])
    bundle = patient_snapshot(db_session, seed_data["doctor_user"], FEATURE_BY_KEY[KEY], asset.patient_id, encounter.registration_uuid, {"ecg_asset_id": asset.asset_id})
    lead = bundle.data["ecg_source"]["signal_metadata"]["leads"][0]
    assert lead["name"] == "I" and lead["gain"] == "13812345678"
