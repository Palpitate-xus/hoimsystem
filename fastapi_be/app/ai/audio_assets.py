"""Patient and uploader scope for immutable recordings; raw audio is never a public upload."""

from fastapi import HTTPException

from app.ai.governance import digest
from app.ai.models import AIAudioAsset

AUDIO_ROLES = {"super_admin", "doctor", "director"}
AUDIO_FEATURE = "medical_transcription"


def authorize_audio(db, user, asset, authorize_patient, *, patient_id=None, encounter_ref=None, allow_inactive=False):
    if asset is None or (patient_id is not None and asset.patient_id != patient_id):
        raise HTTPException(404, "录音不存在或不属于所选患者")
    if user.user_role not in AUDIO_ROLES or (user.user_role != "super_admin" and user.user_id != asset.created_by):
        raise HTTPException(403, "只能管理本人登记且仍有诊疗授权的录音")
    authorize_patient(db, user, asset.patient_id, "records", asset.encounter_ref)
    if encounter_ref is not None and encounter_ref != asset.encounter_ref:
        raise HTTPException(422, "录音原就诊关联与本次选择不一致；未关联录音不按日期推定归属")
    if not allow_inactive and asset.status != "ready":
        raise HTTPException(409, "录音已撤回或清除，不能继续用于转写")
    return asset


def audio_metadata(asset, *, detail=False):
    fields = (
        "asset_id",
        "patient_id",
        "encounter_ref",
        "media_type",
        "extension",
        "content_hash",
        "byte_size",
        "duration_ms",
        "sample_rate",
        "channels",
        "codec",
        "recorded_at",
        "authorized_at",
        "created_by",
        "create_time",
        "status",
        "revision",
        "withdrawn_by",
        "withdrawn_at",
        "purged_by",
        "purged_at",
    )
    data = {name: getattr(asset, name) for name in fields}
    if detail:
        data.update({"authorization_note": asset.authorization_note, "withdrawal_note": asset.withdrawal_note, "purge_note": asset.purge_note})
    return data


def audio_snapshot(asset):
    # Keep authorization prose, real filenames, actors and unrelated history out of inference.
    names = ("asset_id", "encounter_ref", "media_type", "extension", "content_hash", "byte_size", "duration_ms", "sample_rate", "channels", "codec", "recorded_at", "status", "revision")
    return {name: getattr(asset, name) for name in names}


def authorize_audio_snapshot(db, user, context, authorize_patient):
    """Withdrawal/purge immediately removes non-super access to earlier transcription results."""
    if user.user_role == "super_admin":
        return
    source = context.get("audio_source") or {}
    asset = db.get(AIAudioAsset, source.get("asset_id")) if source.get("asset_id") else None
    authorize_audio(db, user, asset, authorize_patient, allow_inactive=True)
    if asset.status != "ready" or digest(audio_snapshot(asset)) != digest({key: source.get(key) for key in audio_snapshot(asset)}):
        raise HTTPException(403, "录音授权或来源版本已失效，不能继续读取原转写结果")
