"""Patient-bound raw ECG intake, calibrated viewing and super-admin source governance."""

import datetime
import json
import os
import shutil
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.ai.context import authorize_patient
from app.ai.ecg_assets import ECG_FEATURE, ECG_ROLES, authorize_ecg, authorize_ecg_patient, ecg_metadata
from app.ai.ecg_files import LEADS, ecg_directory, open_verified_ecg, signal_window, stage_ecg
from app.ai.governance import audit, encode_json
from app.ai.models import AIECGAsset, utcnow
from app.ai.runtime import authorized_feature
from app.ai.schemas import ECGAssetAction
from app.config import settings
from app.database import get_db
from app.dependencies import require_roles
from app.models import User

router = APIRouter(tags=["AI 原始心电"], default_response_class=JSONResponse)


@router.get("/ai/ecg-options")
def ecg_options(db: Session = Depends(get_db), user: User = Depends(require_roles(*ECG_ROLES))):
    authorized_feature(db, user, ECG_FEATURE)
    used = db.query(func.coalesce(func.sum(AIECGAsset.byte_size), 0)).filter(AIECGAsset.created_by == user.user_id, AIECGAsset.status != "purged").scalar()
    return {
        "code": 200,
        "msg": "success",
        "data": {
            "format": "wfdb16",
            "max_bytes": settings.AI_ECG_MAX_BYTES,
            "max_duration_seconds": settings.AI_ECG_MAX_DURATION_SECONDS,
            "user_quota_bytes": settings.AI_ECG_USER_QUOTA_BYTES,
            "used_bytes": int(used),
            "lead_names": list(LEADS),
            "scope_note": "登记成对WFDB原文件并核对患者、就诊和使用授权；当前诊疗团队按患者范围读取，撤回限登记人与超级管理员。校验与预览不推理、不新增诊断或签署报告",
        },
    }


@router.post("/ai/ecg-assets")
def upload_ecg(
    header: UploadFile = File(...),
    signal: UploadFile = File(...),
    patient_id: int = Form(..., ge=1),
    encounter_ref: str | None = Form(None, max_length=64),
    authorization_confirmed: bool = Form(False),
    authorization_note: str = Form("", max_length=1000),
    recorded_at: str | None = Form(None, max_length=80),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*ECG_ROLES)),
):
    authorized_feature(db, user, ECG_FEATURE)
    authorize_ecg_patient(db, user, patient_id, authorize_patient, encounter_ref)
    if not authorization_confirmed or len(authorization_note.strip()) < 5:
        raise HTTPException(422, "请明确核对原文件来源、使用授权、患者与就诊关联并记录依据")
    instant = None
    if recorded_at:
        try:
            instant = datetime.datetime.fromisoformat(recorded_at.replace("Z", "+00:00"))
            if instant.tzinfo is None:
                raise ValueError()
            instant = instant.astimezone(datetime.UTC).replace(tzinfo=None)
        except ValueError as exc:
            raise HTTPException(422, "原采集时间须携带时区；未知时留空，不用上传时刻补写") from exc
    actor_id = user.user_id
    db.commit()
    staged, destination = None, None
    installed = False
    try:
        staged, data = stage_ecg(header, signal)
        db.expire_all()
        actor = db.query(User).filter_by(user_id=actor_id).with_for_update().first()
        if actor is None or actor.user_role not in ECG_ROLES:
            raise HTTPException(403, "当前角色不能登记心电原文件")
        authorized_feature(db, actor, ECG_FEATURE)
        authorize_ecg_patient(db, actor, patient_id, authorize_patient, encounter_ref)
        used = db.query(func.coalesce(func.sum(AIECGAsset.byte_size), 0)).filter(AIECGAsset.created_by == actor_id, AIECGAsset.status != "purged").scalar()
        if used + data["byte_size"] > settings.AI_ECG_USER_QUOTA_BYTES:
            raise HTTPException(429, "心电原文件登记额度不足，请核对原记录与清除状态")
        asset = AIECGAsset(
            asset_id=str(uuid.uuid4()),
            patient_id=patient_id,
            encounter_ref=encounter_ref,
            recorded_at=instant,
            authorization_note=authorization_note.strip(),
            authorized_at=utcnow(),
            created_by=actor_id,
            metadata_json=encode_json(data.pop("metadata")),
            **{key: value for key, value in data.items() if key != "format"},
        )
        db.add(asset)
        db.flush()
        destination = ecg_directory(asset.asset_id)
        destination.mkdir(mode=0o700)
        installed = True
        for name in ("source.hea", "source.dat"):
            os.link(staged / name, destination / name)
        audit(
            db,
            actor_id,
            "ecg.register",
            asset.asset_id,
            {"patient_id": patient_id, "encounter_ref": encounter_ref, "revision": asset.revision, "content_hash": asset.content_hash, "byte_size": asset.byte_size},
        )
        result = ecg_metadata(asset)
        db.commit()
        installed = False
        return {"code": 200, "msg": "原心电已登记，尚未调用模型", "data": result}
    except BaseException:
        db.rollback()
        if installed:
            shutil.rmtree(destination)
        raise
    finally:
        if staged is not None:
            shutil.rmtree(staged)


@router.get("/ai/ecg-assets")
def list_ecg(patient_id: int, encounter_ref: str | None = None, db: Session = Depends(get_db), user: User = Depends(require_roles(*ECG_ROLES))):
    authorized_feature(db, user, ECG_FEATURE)
    authorize_ecg_patient(db, user, patient_id, authorize_patient, encounter_ref)
    query = db.query(AIECGAsset).filter_by(patient_id=patient_id)
    if encounter_ref is not None:
        query = query.filter_by(encounter_ref=encounter_ref)
    rows = query.order_by(AIECGAsset.create_time.desc(), AIECGAsset.asset_id).limit(51).all()
    items = []
    for asset in rows[:50]:
        try:
            authorize_ecg(db, user, asset, authorize_patient, allow_inactive=True)
        except HTTPException as exc:
            if exc.status_code in {403, 404}:
                continue
            raise
        items.append(ecg_metadata(asset))
    return {"code": 200, "msg": "success", "data": {"items": items, "truncated": len(rows) > 50}}


@router.get("/ai/ecg-assets/{asset_id}")
def inspect_ecg(asset_id: str, db: Session = Depends(get_db), user: User = Depends(require_roles(*ECG_ROLES))):
    asset = authorize_ecg(db, user, db.get(AIECGAsset, asset_id), authorize_patient, allow_inactive=True)
    audit(db, user.user_id, "ecg.inspect", asset_id, {"revision": asset.revision, "status": asset.status})
    db.commit()
    return {"code": 200, "msg": "success", "data": ecg_metadata(asset, detail=True)}


@router.get("/ai/ecg-assets/{asset_id}/window")
def ecg_window(
    asset_id: str,
    start_sample: int = Query(0, ge=0),
    sample_count: int = Query(5000, ge=1, le=50000),
    max_points: int = Query(1000, ge=50, le=2000),
    lead: list[str] | None = Query(None, max_length=16),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*ECG_ROLES)),
):
    asset = authorize_ecg(db, user, db.get(AIECGAsset, asset_id), authorize_patient, allow_inactive=user.user_role == "super_admin")
    if asset.status in {"purged", "purge_pending"}:
        raise HTTPException(410, "原心电文件已进入清除流程")
    handles = open_verified_ecg(asset)
    try:
        data = signal_window(handles[1], json.loads(asset.metadata_json), start_sample, sample_count, max_points, lead)
        data.update(asset_id=asset.asset_id, content_hash=asset.content_hash)
        audit(db, user.user_id, "ecg.window_read", asset_id, {"revision": asset.revision, "start_sample": start_sample, "end_sample_exclusive": data["end_sample_exclusive"], "max_points": max_points})
        db.commit()
    finally:
        for stream in handles:
            stream.close()
    return JSONResponse({"code": 200, "msg": "success", "data": data}, headers={"Cache-Control": "private, no-store"})


@router.get("/ai/ecg-assets/{asset_id}/content")
def download_ecg(asset_id: str, part: Literal["header", "signal"], db: Session = Depends(get_db), user: User = Depends(require_roles(*ECG_ROLES))):
    asset = authorize_ecg(db, user, db.get(AIECGAsset, asset_id), authorize_patient, allow_inactive=user.user_role == "super_admin")
    if asset.status in {"purged", "purge_pending"}:
        raise HTTPException(410, "原心电文件已进入清除流程")
    handles = open_verified_ecg(asset)
    selected = handles[0 if part == "header" else 1]
    try:
        audit(db, user.user_id, "ecg.content_read", asset_id, {"revision": asset.revision, "part": part, "content_hash": asset.content_hash})
        db.commit()
    except BaseException:
        for stream in handles:
            stream.close()
        raise
    for stream in handles:
        if stream is not selected:
            stream.close()

    def chunks():
        try:
            while block := selected.read(65536):
                yield block
        finally:
            selected.close()

    extension = ".hea" if part == "header" else ".dat"
    return StreamingResponse(
        chunks(),
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="ecg-{asset.asset_id}{extension}"', "Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"},
    )


@router.post("/ai/ecg-assets/{asset_id}/withdraw")
def withdraw_ecg(asset_id: str, req: ECGAssetAction, db: Session = Depends(get_db), user: User = Depends(require_roles(*ECG_ROLES))):
    asset = db.query(AIECGAsset).filter_by(asset_id=asset_id).with_for_update().populate_existing().first()
    authorize_ecg(db, user, asset, authorize_patient, manage=True)
    if asset.revision != req.expected_revision:
        raise HTTPException(409, "心电原记录版本已变化，请刷新后重试")
    changed = (
        db.query(AIECGAsset)
        .filter_by(asset_id=asset_id, status="ready", revision=req.expected_revision)
        .update({"status": "withdrawn", "revision": req.expected_revision + 1, "withdrawn_by": user.user_id, "withdrawn_at": utcnow(), "withdrawal_note": req.reason}, synchronize_session=False)
    )
    if changed != 1:
        db.rollback()
        raise HTTPException(409, "心电原记录状态已变化，请刷新后重试")
    audit(db, user.user_id, "ecg.withdraw", asset_id, {"revision": req.expected_revision + 1})
    db.commit()
    return {"code": 200, "msg": "原记录已撤回，后续模型任务及普通用户旧结果读取随之失效", "data": {"asset_id": asset_id, "status": "withdrawn", "revision": req.expected_revision + 1}}


@router.get("/ai/admin/ecg-assets")
def admin_ecg_list(
    patient_id: int | None = Query(None, ge=1),
    status: Literal["ready", "withdrawn", "purge_pending", "purged"] | None = None,
    limit: int = Query(100, ge=1, le=300),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("super_admin")),
):
    query = db.query(AIECGAsset)
    if patient_id is not None:
        query = query.filter_by(patient_id=patient_id)
    if status:
        query = query.filter_by(status=status)
    rows = query.order_by(AIECGAsset.create_time.desc(), AIECGAsset.asset_id).limit(limit + 1).all()
    return {"code": 200, "msg": "success", "data": {"items": [ecg_metadata(asset) for asset in rows[:limit]], "truncated": len(rows) > limit}}


@router.post("/ai/admin/ecg-assets/{asset_id}/purge")
def purge_ecg(asset_id: str, req: ECGAssetAction, db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin"))):
    asset = db.query(AIECGAsset).filter_by(asset_id=asset_id).with_for_update().populate_existing().first()
    if asset is None:
        raise HTTPException(404, "原心电记录不存在")
    if asset.revision != req.expected_revision or asset.status not in {"withdrawn", "purge_pending"}:
        raise HTTPException(409, "须先撤回并核对当前版本，再清除原文件")
    version = asset.revision
    if asset.status == "withdrawn":
        changed = (
            db.query(AIECGAsset)
            .filter_by(asset_id=asset_id, status="withdrawn", revision=version)
            .update({"status": "purge_pending", "revision": version + 1, "purge_note": req.reason}, synchronize_session=False)
        )
        if changed != 1:
            db.rollback()
            raise HTTPException(409, "心电来源状态已变化，请刷新后重试")
        version += 1
        audit(db, user.user_id, "ecg.purge_requested", asset_id, {"revision": version})
        db.commit()
    directory = ecg_directory(asset_id)
    try:
        if directory.exists() or directory.is_symlink():
            shutil.rmtree(directory)
    except OSError as exc:
        raise HTTPException(503, "原文件清除尚未完成，保持清除中，可按当前版本恢复") from exc
    changed = (
        db.query(AIECGAsset)
        .filter_by(asset_id=asset_id, status="purge_pending", revision=version)
        .update({"status": "purged", "revision": version + 1, "purged_by": user.user_id, "purged_at": utcnow()}, synchronize_session=False)
    )
    if changed != 1:
        db.rollback()
        raise HTTPException(409, "清除状态已变化，请重新核对当前版本")
    audit(db, user.user_id, "ecg.purged", asset_id, {"revision": version + 1})
    db.commit()
    return {"code": 200, "msg": "当前存储原文件已清除，冻结任务文字及审计仍保留", "data": {"asset_id": asset_id, "status": "purged", "revision": version + 1}}
