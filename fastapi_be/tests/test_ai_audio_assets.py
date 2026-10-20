"""Private intake, care/owner boundaries and super-admin withdrawal/purge without inference."""

import datetime
import io
import wave
from pathlib import Path

import pytest

from app.ai.audio_files import audio_path
from app.ai.models import AIAudioAsset, AIAuditEvent, AIFeatureConfig, AIPatientGrant, AIRun, utcnow
from app.config import settings
from app.models import Registration


@pytest.fixture
def audio_case(db_session, seed_data, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "AI_AUDIO_STORAGE_DIR", str(tmp_path / "private"))
    for model in (AIAudioAsset, AIFeatureConfig):
        db_session.query(model).delete()
    raw = io.BytesIO()
    with wave.open(raw, "wb") as writer:
        writer.setparams((1, 2, 8000, 2000, "NONE", "not compressed"))
        writer.writeframes(b"\0" * 4000)
    encounter = Registration(patient_id=seed_data["patient"].patient_id, doctor_id=seed_data["doctor"].doctor_id, department_id=seed_data["department"].department_id, time=utcnow(), status=0)
    db_session.add(encounter)
    db_session.commit()
    return raw.getvalue(), encounter, tmp_path / "private"


async def upload(async_client, auth_headers, seed_data, audio_case, **changes):
    raw, encounter, _ = audio_case
    data = {
        "patient_id": str(encounter.patient_id),
        "encounter_ref": encounter.registration_uuid,
        "authorization_confirmed": "true",
        "authorization_note": "隔离测试中由登记人核对的授权说明，不代表真实临床授权",
        **changes,
    }
    return await async_client.post(
        "/api/ai/audio-assets", headers=auth_headers(seed_data["doctor_user"].username), files={"file": ("患者姓名手机号-test.wav", raw, "application/octet-stream")}, data=data
    )


@pytest.mark.asyncio
async def test_private_metadata_download_and_audit_do_not_create_inference(seed_data, db_session, audio_case, async_client, auth_headers):
    raw, encounter, root = audio_case
    response = await upload(async_client, auth_headers, seed_data, audio_case)
    assert response.status_code == 200, response.text
    metadata = response.json()["data"]
    assert metadata["patient_id"] == encounter.patient_id and metadata["encounter_ref"] == encounter.registration_uuid
    assert metadata["byte_size"] == len(raw) and metadata["duration_ms"] == 250 and metadata["status"] == "ready" and metadata["revision"] == 1
    assert metadata["recorded_at"] is None and not {"path", "url", "filename", "authorization_note"}.intersection(metadata)
    path = audio_path(metadata["asset_id"])
    assert path.parent == root and path.read_bytes() == raw
    url = "/api/ai/audio-assets/" + metadata["asset_id"] + "/content"
    content = await async_client.get(url, headers=auth_headers(seed_data["doctor_user"].username))
    assert content.status_code == 200 and content.content == raw
    assert content.headers["cache-control"] == "private, no-store" and content.headers["x-content-type-options"] == "nosniff"
    assert "患者姓名" not in content.headers["content-disposition"] and db_session.query(AIRun).count() == 0
    events = db_session.query(AIAuditEvent).filter(AIAuditEvent.action.like("audio.%")).all()
    assert {row.action for row in events} >= {"audio.register", "audio.content_read"}
    assert all("隔离测试中由登记人核对" not in row.detail_json and "患者姓名手机号" not in row.detail_json for row in events)
    assert (await async_client.get(url)).status_code == 401


@pytest.mark.asyncio
@pytest.mark.parametrize("changes", [{"authorization_confirmed": "false"}, {"authorization_note": "    "}, {"recorded_at": "2026-10-20T09:00:00"}, {"patient_id": "999999999"}])
async def test_authorization_time_and_patient_requirements_precede_file_storage(changes, seed_data, db_session, audio_case, async_client, auth_headers):
    response = await upload(async_client, auth_headers, seed_data, audio_case, **changes)
    assert response.status_code in {404, 422}, response.text
    assert db_session.query(AIAudioAsset).count() == 0 and not audio_case[2].exists()


@pytest.mark.asyncio
async def test_foreign_encounter_and_unrelated_care_cannot_be_used(seed_data, db_session, audio_case, async_client, auth_headers):
    foreign = Registration(patient_id=seed_data["patient2"].patient_id, time=utcnow(), status=0)
    db_session.add(foreign)
    db_session.commit()
    mismatch = await upload(async_client, auth_headers, seed_data, audio_case, encounter_ref=foreign.registration_uuid)
    assert mismatch.status_code == 404
    denied = await upload(async_client, auth_headers, seed_data, audio_case, patient_id=str(foreign.patient_id), encounter_ref=foreign.registration_uuid)
    assert denied.status_code == 403 and db_session.query(AIAudioAsset).count() == 0


@pytest.mark.asyncio
async def test_patient_grant_does_not_transfer_another_uploaders_audio_and_source_care_is_rechecked(seed_data, db_session, audio_case, async_client, auth_headers):
    metadata = (await upload(async_client, auth_headers, seed_data, audio_case)).json()["data"]
    director = seed_data["director_user"]
    db_session.add(
        AIPatientGrant(
            user_id=director.user_id,
            patient_id=audio_case[1].patient_id,
            category="records",
            reason="隔离测试核对访问边界",
            expires_at=utcnow() + datetime.timedelta(hours=1),
            created_by=seed_data["super_admin_user"].user_id,
        )
    )
    db_session.commit()
    url = "/api/ai/audio-assets/" + metadata["asset_id"]
    for suffix in ("", "/content"):
        assert (await async_client.get(url + suffix, headers=auth_headers(director.username))).status_code == 403
    listing = await async_client.get("/api/ai/audio-assets", headers=auth_headers(director.username), params={"patient_id": audio_case[1].patient_id})
    assert listing.status_code == 200 and listing.json()["data"]["items"] == []
    assert (await async_client.get(url + "/content", headers=auth_headers("super01"))).status_code == 200
    audio_case[1].doctor_id = None
    db_session.commit()
    assert (await async_client.get(url + "/content", headers=auth_headers(seed_data["doctor_user"].username))).status_code == 403


@pytest.mark.asyncio
async def test_quota_rejection_leaves_no_file_or_metadata(seed_data, db_session, audio_case, async_client, auth_headers, monkeypatch):
    monkeypatch.setattr(settings, "AI_AUDIO_USER_QUOTA_BYTES", 1024)
    response = await upload(async_client, auth_headers, seed_data, audio_case)
    assert response.status_code == 429, response.text
    assert db_session.query(AIAudioAsset).count() == 0 and list(audio_case[2].iterdir()) == []


@pytest.mark.asyncio
async def test_withdrawal_is_revision_checked_and_only_super_admin_can_purge(seed_data, db_session, audio_case, async_client, auth_headers):
    asset_id = (await upload(async_client, auth_headers, seed_data, audio_case)).json()["data"]["asset_id"]
    headers = auth_headers(seed_data["doctor_user"].username)
    body = {"expected_revision": 1, "reason": "由登记人主动撤回本次测试录音"}
    early = await async_client.post(f"/api/ai/admin/audio-assets/{asset_id}/purge", headers=auth_headers("super01"), json=body)
    assert early.status_code == 409
    stale = await async_client.post(f"/api/ai/audio-assets/{asset_id}/withdraw", headers=headers, json={**body, "expected_revision": 2})
    assert stale.status_code == 409
    response = await async_client.post(f"/api/ai/audio-assets/{asset_id}/withdraw", headers=headers, json=body)
    assert response.status_code == 200 and response.json()["data"]["revision"] == 2 and audio_path(asset_id).exists()
    assert (await async_client.get(f"/api/ai/audio-assets/{asset_id}/content", headers=headers)).status_code == 409
    denied = await async_client.post(f"/api/ai/admin/audio-assets/{asset_id}/purge", headers=headers, json={**body, "expected_revision": 2})
    assert denied.status_code == 403
    purged = await async_client.post(f"/api/ai/admin/audio-assets/{asset_id}/purge", headers=auth_headers("super01"), json={"expected_revision": 2, "reason": "管理员按明确清除请求删除当前测试原文件"})
    assert purged.status_code == 200, purged.text
    db_session.expire_all()
    asset = db_session.get(AIAudioAsset, asset_id)
    assert asset.status == "purged" and asset.revision == 4 and not audio_path(asset_id).exists()
    assert asset.purge_note == "管理员按明确清除请求删除当前测试原文件" and asset.withdrawal_note == body["reason"]
    assert (await async_client.get(f"/api/ai/audio-assets/{asset_id}/content", headers=auth_headers("super01"))).status_code == 410
    events = db_session.query(AIAuditEvent).filter_by(target=asset_id).all()
    assert {row.action for row in events} >= {"audio.purge_requested", "audio.purge", "audio.withdraw"}
    assert all(body["reason"] not in row.detail_json for row in events)


@pytest.mark.asyncio
async def test_failed_purge_stays_pending_and_resumes_with_current_version(seed_data, db_session, audio_case, async_client, auth_headers, monkeypatch):
    asset_id = (await upload(async_client, auth_headers, seed_data, audio_case)).json()["data"]["asset_id"]
    headers = auth_headers("super01")
    await async_client.post(f"/api/ai/audio-assets/{asset_id}/withdraw", headers=headers, json={"expected_revision": 1, "reason": "测试清除失败后的恢复路径"})
    original = Path.unlink

    def fail_audio(path, *args, **kwargs):
        if path.suffix == ".audio":
            raise PermissionError("isolated test failure")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_audio)
    first = await async_client.post(f"/api/ai/admin/audio-assets/{asset_id}/purge", headers=headers, json={"expected_revision": 2, "reason": "明确要求清除当前测试音频原文件"})
    assert first.status_code == 503
    db_session.expire_all()
    asset = db_session.get(AIAudioAsset, asset_id)
    assert asset.status == "purge_pending" and asset.revision == 3 and audio_path(asset_id).exists()
    monkeypatch.setattr(Path, "unlink", original)
    resumed = await async_client.post(f"/api/ai/admin/audio-assets/{asset_id}/purge", headers=headers, json={"expected_revision": 3, "reason": "恢复上次明确要求的清除操作"})
    assert resumed.status_code == 200 and not audio_path(asset_id).exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["admin", "nurse", "pharmacist", "cashier", "guide", "patient", "lab_tech", "registrar"])
async def test_non_speech_roles_cannot_access_private_audio_or_management(role, seed_data, async_client, auth_headers):
    headers = auth_headers(seed_data[role + "_user"].username)
    for url in ("/api/ai/audio-options", "/api/ai/audio-assets?patient_id=1", "/api/ai/admin/audio-assets"):
        assert (await async_client.get(url, headers=headers)).status_code == 403
    assert (await async_client.post("/api/ai/admin/audio-assets/unknown/purge", headers=headers, json={"expected_revision": 1, "reason": "不应被允许的清除请求"})).status_code == 403
