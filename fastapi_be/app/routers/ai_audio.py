"""Private audio intake and explicit super-admin governance, without calling a model."""

import datetime
import os
import shutil
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.ai.audio_assets import AUDIO_FEATURE, AUDIO_ROLES, audio_metadata, authorize_audio
from app.ai.audio_files import AUDIO_FORMATS, audio_path, open_verified_audio, stage_audio
from app.ai.context import authorize_patient
from app.ai.governance import audit
from app.ai.models import AIAudioAsset, utcnow
from app.ai.runtime import authorized_feature
from app.ai.schemas import AudioAssetAction
from app.config import settings
from app.database import get_db
from app.dependencies import require_roles
from app.models import User

router = APIRouter(tags=["AI 私有录音"], default_response_class=JSONResponse)


@router.get("/ai/audio-options")
def audio_options(db: Session = Depends(get_db), user: User = Depends(require_roles(*AUDIO_ROLES))):
    authorized_feature(db, user, AUDIO_FEATURE)
    used = db.query(func.coalesce(func.sum(AIAudioAsset.byte_size), 0)).filter(AIAudioAsset.created_by == user.user_id, AIAudioAsset.status != "purged").scalar()
    return {
        "code": 200,
        "msg": "success",
        "data": {
            "extensions": list(AUDIO_FORMATS),
            "max_bytes": settings.AI_AUDIO_MAX_BYTES,
            "max_duration_seconds": settings.AI_AUDIO_MAX_DURATION_SECONDS,
            "user_quota_bytes": settings.AI_AUDIO_USER_QUOTA_BYTES,
            "used_bytes": int(used),
            "processor_available": bool(shutil.which("ffmpeg") and shutil.which("ffprobe")),
            "scope_note": "录音可能包含可识别信息。登记须核对患者、原就诊及采集处理授权；仅登记人和超级管理员在当前诊疗授权内访问。上传不发起转写、不签署或修改病历",
        },
    }


@router.post("/ai/audio-assets")
def upload_audio(
    file: UploadFile = File(...),
    patient_id: int = Form(..., ge=1),
    encounter_ref: str | None = Form(None, max_length=64),
    authorization_confirmed: bool = Form(False),
    authorization_note: str = Form(..., min_length=5, max_length=1000),
    recorded_at: datetime.datetime | None = Form(None),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*AUDIO_ROLES)),
):
    authorized_feature(db, user, AUDIO_FEATURE)
    encounter_ref = encounter_ref.strip() or None if encounter_ref else None
    authorize_patient(db, user, patient_id, "records", encounter_ref)
    if not authorization_confirmed or len(authorization_note.strip()) < 5:
        raise HTTPException(422, "须明确核对录音采集与处理授权并填写说明，不能由上传行为推定授权")
    if recorded_at is not None:
        if recorded_at.utcoffset() is None:
            raise HTTPException(422, "原录音时间须携带时区；未记录则留空，不用上传时间代替")
        recorded_at = recorded_at.astimezone(datetime.UTC).replace(tzinfo=None)
    user_id = user.user_id
    db.commit()  # Release SQL during native file validation.
    staged, metadata = stage_audio(file)
    identifier, linked = str(uuid.uuid4()), False
    destination = None
    try:
        destination = audio_path(identifier)
        db.expire_all()
        actor = db.query(User).filter_by(user_id=user_id).with_for_update().populate_existing().first()
        if actor is None or actor.user_role not in AUDIO_ROLES:
            raise HTTPException(403, "登记人权限已变化，请重新核对")
        authorized_feature(db, actor, AUDIO_FEATURE)
        authorize_patient(db, actor, patient_id, "records", encounter_ref)
        used = db.query(func.coalesce(func.sum(AIAudioAsset.byte_size), 0)).filter(AIAudioAsset.created_by == user_id, AIAudioAsset.status != "purged").scalar()
        if used + metadata["byte_size"] > settings.AI_AUDIO_USER_QUOTA_BYTES:
            raise HTTPException(429, "本人录音存储额度不足；撤回仅停用，清除原文件后才释放存储额度")
        now = utcnow()
        asset = AIAudioAsset(
            asset_id=identifier,
            patient_id=patient_id,
            encounter_ref=encounter_ref,
            authorization_note=authorization_note.strip(),
            authorized_at=now,
            recorded_at=recorded_at,
            created_by=user_id,
            create_time=now,
            status="ready",
            revision=1,
            **metadata,
        )
        db.add(asset)
        db.flush()
        os.link(staged, destination)  # Refuse an existing destination instead of overwriting it.
        linked = True
        staged.unlink()
        audit(db, user_id, "audio.register", identifier, {"patient_id": patient_id, "content_hash": asset.content_hash, "byte_size": asset.byte_size, "revision": 1})
        db.commit()
        return {"code": 200, "msg": "录音已登记，尚未调用转写模型", "data": audio_metadata(asset)}
    except BaseException:
        db.rollback()
        if linked:
            destination.unlink(missing_ok=True)
        raise
    finally:
        staged.unlink(missing_ok=True)


@router.get("/ai/audio-assets")
def list_audio(patient_id: int = Query(ge=1), encounter_ref: str | None = Query(None, max_length=64), db: Session = Depends(get_db), user: User = Depends(require_roles(*AUDIO_ROLES))):
    authorized_feature(db, user, AUDIO_FEATURE)
    authorize_patient(db, user, patient_id, "records", encounter_ref)
    query = db.query(AIAudioAsset).filter_by(patient_id=patient_id)
    if user.user_role != "super_admin":
        query = query.filter_by(created_by=user.user_id)
    if encounter_ref:
        query = query.filter_by(encounter_ref=encounter_ref)
    rows = query.order_by(AIAudioAsset.create_time.desc(), AIAudioAsset.asset_id).limit(51).all()
    items = []
    for asset in rows[:50]:
        try:
            authorize_audio(db, user, asset, authorize_patient, allow_inactive=True)
        except HTTPException as exc:
            if exc.status_code in {403, 404}:
                continue
            raise
        items.append(audio_metadata(asset))
    return {"code": 200, "msg": "success", "data": {"items": items, "truncated": len(rows) > 50}}


@router.get("/ai/audio-assets/{asset_id}")
def inspect_audio_asset(asset_id: str, db: Session = Depends(get_db), user: User = Depends(require_roles(*AUDIO_ROLES))):
    asset = authorize_audio(db, user, db.get(AIAudioAsset, asset_id), authorize_patient, allow_inactive=True)
    audit(db, user.user_id, "audio.inspect", asset_id, {"revision": asset.revision, "status": asset.status})
    db.commit()
    return {"code": 200, "msg": "success", "data": audio_metadata(asset, detail=True)}


@router.get("/ai/audio-assets/{asset_id}/content")
def download_audio(asset_id: str, db: Session = Depends(get_db), user: User = Depends(require_roles(*AUDIO_ROLES))):
    asset = authorize_audio(db, user, db.get(AIAudioAsset, asset_id), authorize_patient, allow_inactive=user.user_role == "super_admin")
    if asset.status in {"purged", "purge_pending"}:
        raise HTTPException(410, "原录音已进入清除流程，不能下载")
    source = open_verified_audio(asset)
    try:
        audit(db, user.user_id, "audio.content_read", asset_id, {"revision": asset.revision, "content_hash": asset.content_hash})
        db.commit()
    except BaseException:
        source.close()
        raise

    def chunks():
        try:
            while chunk := source.read(65536):
                yield chunk
        finally:
            source.close()

    return StreamingResponse(
        chunks(),
        media_type=asset.media_type,
        headers={"Content-Disposition": f'attachment; filename="audio-{asset.asset_id}{asset.extension}"', "Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"},
    )


@router.post("/ai/audio-assets/{asset_id}/withdraw")
def withdraw_audio(asset_id: str, req: AudioAssetAction, db: Session = Depends(get_db), user: User = Depends(require_roles(*AUDIO_ROLES))):
    asset = db.query(AIAudioAsset).filter_by(asset_id=asset_id).with_for_update().populate_existing().first()
    authorize_audio(db, user, asset, authorize_patient)
    if asset.revision != req.expected_revision:
        raise HTTPException(409, "录音版本已变化，请重新加载")
    changed = (
        db.query(AIAudioAsset)
        .filter_by(asset_id=asset_id, status="ready", revision=req.expected_revision)
        .update({"status": "withdrawn", "revision": req.expected_revision + 1, "withdrawn_by": user.user_id, "withdrawn_at": utcnow(), "withdrawal_note": req.reason}, synchronize_session=False)
    )
    if changed != 1:
        db.rollback()
        raise HTTPException(409, "录音状态已变化，请重新加载")
    audit(db, user.user_id, "audio.withdraw", asset_id, {"revision": req.expected_revision + 1})
    db.commit()
    return {"code": 200, "msg": "录音已撤回，原转写任务和普通用户历史访问随之失效", "data": {"asset_id": asset_id, "status": "withdrawn", "revision": req.expected_revision + 1}}


@router.get("/ai/admin/audio-assets")
def admin_audio_list(
    patient_id: int | None = Query(None, ge=1),
    status: Literal["ready", "withdrawn", "purge_pending", "purged"] | None = None,
    limit: int = Query(100, ge=1, le=300),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("super_admin")),
):
    query = db.query(AIAudioAsset)
    if patient_id is not None:
        query = query.filter_by(patient_id=patient_id)
    if status:
        query = query.filter_by(status=status)
    rows = query.order_by(AIAudioAsset.create_time.desc(), AIAudioAsset.asset_id).limit(limit + 1).all()
    return {"code": 200, "msg": "success", "data": {"items": [audio_metadata(asset) for asset in rows[:limit]], "truncated": len(rows) > limit}}


@router.post("/ai/admin/audio-assets/{asset_id}/purge")
def purge_audio(asset_id: str, req: AudioAssetAction, db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin"))):
    asset = db.query(AIAudioAsset).filter_by(asset_id=asset_id).with_for_update().populate_existing().first()
    if asset is None:
        raise HTTPException(404, "录音不存在")
    if asset.revision != req.expected_revision or asset.status not in {"withdrawn", "purge_pending"}:
        raise HTTPException(409, "须先撤回并核对当前版本，再清除原录音")
    version = asset.revision
    if asset.status == "withdrawn":
        changed = (
            db.query(AIAudioAsset)
            .filter_by(asset_id=asset_id, status="withdrawn", revision=version)
            .update({"status": "purge_pending", "revision": version + 1, "purge_note": req.reason}, synchronize_session=False)
        )
        if changed != 1:
            db.rollback()
            raise HTTPException(409, "录音状态已变化，请重新加载")
        version += 1
        audit(db, user.user_id, "audio.purge_requested", asset_id, {"revision": version})
        db.commit()  # A crash or storage failure stays visibly pending and can be resumed.
    try:
        audio_path(asset_id).unlink(missing_ok=True)
    except OSError as exc:
        raise HTTPException(503, "原文件暂未清除，状态保留为清除中；核实存储后可按当前版本重试") from exc
    changed = (
        db.query(AIAudioAsset)
        .filter_by(asset_id=asset_id, status="purge_pending", revision=version)
        .update({"status": "purged", "revision": version + 1, "purged_by": user.user_id, "purged_at": utcnow()}, synchronize_session=False)
    )
    if changed != 1:
        db.rollback()
        raise HTTPException(409, "清除状态已变化，请重新加载")
    audit(db, user.user_id, "audio.purge", asset_id, {"revision": version + 1, "content_hash": asset.content_hash})
    db.commit()
    return {"code": 200, "msg": "原录音文件已清除，来源哈希与审计元数据保留", "data": {"asset_id": asset_id, "status": "purged", "revision": version + 1}}
