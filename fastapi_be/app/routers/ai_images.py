"""Private order-bound DICOM intake, actual pixels and super-admin source governance."""

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
from app.ai.governance import audit, encode_json
from app.ai.image_assets import IMAGE_FEATURE, IMAGE_ROLES, ORDER_MODALITIES, authorize_image, authorize_image_order, authorize_image_patient, image_metadata
from app.ai.image_files import image_directory, open_verified_image, stage_image
from app.ai.models import AIImageAsset, utcnow
from app.ai.runtime import authorized_feature
from app.ai.schemas import ImageAssetAction
from app.config import settings
from app.database import get_db
from app.dependencies import require_roles
from app.models import ImagingOrder, User

router = APIRouter(tags=["AI 原始影像"], default_response_class=JSONResponse)


@router.get("/ai/image-options")
def image_options(db: Session = Depends(get_db), user: User = Depends(require_roles(*IMAGE_ROLES))):
    authorized_feature(db, user, IMAGE_FEATURE)
    used = db.query(func.coalesce(func.sum(AIImageAsset.byte_size), 0)).filter(AIImageAsset.created_by == user.user_id, AIImageAsset.status != "purged").scalar()
    return {
        "code": 200,
        "msg": "success",
        "data": {
            "format": "dicom_i32le_v1",
            "max_bytes": settings.AI_IMAGE_MAX_BYTES,
            "max_pixels": settings.AI_IMAGE_MAX_PIXELS,
            "user_quota_bytes": settings.AI_IMAGE_USER_QUOTA_BYTES,
            "used_bytes": int(used),
            "scope_note": "登记单帧DICOM原文件并核对患者、真实影像申请和使用授权；当前诊疗团队按权限读取，撤回限登记人与超级管理员。校验与预览不推理、不新增诊断或签署报告，文件标签不证明像素已匿名化",
        },
    }


@router.get("/ai/image-orders")
def image_orders(
    patient_id: int = Query(..., ge=1),
    encounter_ref: str | None = Query(None, max_length=64),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*IMAGE_ROLES)),
):
    authorized_feature(db, user, IMAGE_FEATURE)
    authorize_image_patient(db, user, patient_id, authorize_patient, encounter_ref)
    rows = db.query(ImagingOrder).filter_by(patient_id=patient_id).order_by(ImagingOrder.create_time.desc(), ImagingOrder.imaging_order_id).limit(101).all()
    items = []
    for order in rows[:100]:
        try:
            authorize_image_order(db, user, order, authorize_patient, patient_id=patient_id, encounter_ref=encounter_ref)
        except HTTPException as exc:
            if exc.status_code in {403, 404}:
                continue
            raise
        items.append(
            {
                "imaging_order_id": order.imaging_order_id,
                "patient_id": order.patient_id,
                "modality": order.modality if order.modality in ORDER_MODALITIES else "unknown",
                "body_part": order.body_part,
                "accession_no": order.accession_no,
                "status": order.status,
                "create_time": order.create_time,
            }
        )
    return {
        "code": 200,
        "msg": "success",
        "data": {"items": items, "truncated": len(rows) > 100, "scope_note": "原影像申请未保存就诊关联；所选就诊须另行核对，不能按申请日期推定。选单文字供院内人工核对，不直接传给模型"},
    }


@router.post("/ai/image-assets")
def upload_image(
    image: UploadFile = File(...),
    patient_id: int = Form(..., ge=1),
    imaging_order_id: str = Form(..., min_length=1, max_length=36),
    encounter_ref: str | None = Form(None, max_length=64),
    authorization_confirmed: bool = Form(False),
    authorization_note: str = Form("", max_length=1000),
    recorded_at: str | None = Form(None, max_length=80),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*IMAGE_ROLES)),
):
    authorized_feature(db, user, IMAGE_FEATURE)
    authorize_image_order(db, user, db.get(ImagingOrder, imaging_order_id), authorize_patient, patient_id=patient_id, encounter_ref=encounter_ref, for_inference=True)
    if not authorization_confirmed or len(authorization_note.strip()) < 5:
        raise HTTPException(422, "请明确核对原图来源、使用授权、患者与申请及就诊关联并记录依据")
    instant = None
    if recorded_at:
        try:
            instant = datetime.datetime.fromisoformat(recorded_at.replace("Z", "+00:00"))
            if instant.tzinfo is None:
                raise ValueError()
            instant = instant.astimezone(datetime.UTC).replace(tzinfo=None)
        except ValueError as exc:
            raise HTTPException(422, "原采集时间须携带时区；未知时留空，不用上传时刻或未经核对的DICOM时钟补写") from exc
    actor_id = user.user_id
    db.commit()
    staged, destination = None, None
    installed = False
    try:
        staged, data = stage_image(image)
        db.expire_all()
        actor = db.query(User).filter_by(user_id=actor_id).with_for_update().first()
        if actor is None or actor.user_role not in IMAGE_ROLES:
            raise HTTPException(403, "当前角色不能登记原始影像")
        authorized_feature(db, actor, IMAGE_FEATURE)
        order = db.query(ImagingOrder).filter_by(imaging_order_id=imaging_order_id).with_for_update().populate_existing().first()
        authorize_image_order(db, actor, order, authorize_patient, patient_id=patient_id, encounter_ref=encounter_ref, for_inference=True)
        used = db.query(func.coalesce(func.sum(AIImageAsset.byte_size), 0)).filter(AIImageAsset.created_by == actor_id, AIImageAsset.status != "purged").scalar()
        if used + data["byte_size"] > settings.AI_IMAGE_USER_QUOTA_BYTES:
            raise HTTPException(429, "原始影像登记额度不足，请核对原记录与清除状态")
        asset = AIImageAsset(
            asset_id=str(uuid.uuid4()),
            patient_id=patient_id,
            imaging_order_id=imaging_order_id,
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
        destination = image_directory(asset.asset_id)
        destination.mkdir(mode=0o700)
        installed = True
        for name in ("source.dcm", "pixels.i32le"):
            os.link(staged / name, destination / name)
        audit(
            db,
            actor_id,
            "image.register",
            asset.asset_id,
            {
                "patient_id": patient_id,
                "imaging_order_id": imaging_order_id,
                "encounter_ref": encounter_ref,
                "revision": asset.revision,
                "content_hash": asset.content_hash,
                "byte_size": asset.byte_size,
            },
        )
        result = image_metadata(asset, db=db, order=order, user=actor)
        db.commit()
        installed = False
        return {"code": 200, "msg": "原始影像已登记，尚未调用模型", "data": result}
    except BaseException:
        db.rollback()
        if installed:
            shutil.rmtree(destination)
        raise
    finally:
        if staged is not None:
            shutil.rmtree(staged)


@router.get("/ai/image-assets")
def list_images(
    patient_id: int = Query(..., ge=1),
    imaging_order_id: str | None = Query(None, max_length=36),
    encounter_ref: str | None = Query(None, max_length=64),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*IMAGE_ROLES)),
):
    authorized_feature(db, user, IMAGE_FEATURE)
    authorize_image_patient(db, user, patient_id, authorize_patient, encounter_ref)
    if imaging_order_id is not None:
        authorize_image_order(db, user, db.get(ImagingOrder, imaging_order_id), authorize_patient, patient_id=patient_id, encounter_ref=encounter_ref)
    query = db.query(AIImageAsset).filter_by(patient_id=patient_id)
    if imaging_order_id is not None:
        query = query.filter_by(imaging_order_id=imaging_order_id)
    if encounter_ref is not None:
        query = query.filter_by(encounter_ref=encounter_ref)
    rows = query.order_by(AIImageAsset.create_time.desc(), AIImageAsset.asset_id).limit(51).all()
    items = []
    for asset in rows[:50]:
        try:
            authorize_image(db, user, asset, authorize_patient, allow_inactive=True)
        except HTTPException as exc:
            if exc.status_code in {403, 404, 409}:
                continue
            raise
        items.append(image_metadata(asset, db=db, user=user))
    return {"code": 200, "msg": "success", "data": {"items": items, "truncated": len(rows) > 50}}


@router.get("/ai/image-assets/{asset_id}")
def inspect_image(asset_id: str, db: Session = Depends(get_db), user: User = Depends(require_roles(*IMAGE_ROLES))):
    authorized_feature(db, user, IMAGE_FEATURE)
    asset = authorize_image(db, user, db.get(AIImageAsset, asset_id), authorize_patient, allow_inactive=True)
    data = image_metadata(asset, db=db, detail=True, user=user)
    audit(db, user.user_id, "image.inspect", asset_id, {"revision": asset.revision, "status": asset.status})
    db.commit()
    return {"code": 200, "msg": "success", "data": data}


def _image_stream(asset_id, db, user, *, pixels):
    authorized_feature(db, user, IMAGE_FEATURE)
    asset = authorize_image(db, user, db.get(AIImageAsset, asset_id), authorize_patient, allow_inactive=user.user_role == "super_admin")
    if asset.status in {"purged", "purge_pending"}:
        raise HTTPException(410, "原始影像文件已进入清除流程")
    handles = open_verified_image(asset)
    selected = handles[1 if pixels else 0]
    try:
        metadata = json.loads(asset.metadata_json)
        audit(db, user.user_id, "image.pixels_read" if pixels else "image.content_read", asset_id, {"revision": asset.revision, "content_hash": asset.content_hash, "pixel_hash": asset.pixel_hash})
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

    headers = {
        "Cache-Control": "private, no-store",
        "X-Content-Type-Options": "nosniff",
        "X-Image-Asset-Id": asset.asset_id,
        "X-Image-Content-Hash": asset.content_hash,
        "X-Image-Pixel-Hash": asset.pixel_hash,
        "X-Image-Revision": str(asset.revision),
    }
    if pixels:
        headers.update({"X-Image-Rows": str(metadata["rows"]), "X-Image-Columns": str(metadata["columns"]), "X-Image-Pixel-Format": "int32le"})
    else:
        headers["Content-Disposition"] = f'attachment; filename="image-{asset.asset_id}.dcm"'
    return StreamingResponse(chunks(), media_type="application/octet-stream" if pixels else "application/dicom", headers=headers)


@router.get("/ai/image-assets/{asset_id}/pixels")
def image_pixels(asset_id: str, db: Session = Depends(get_db), user: User = Depends(require_roles(*IMAGE_ROLES))):
    return _image_stream(asset_id, db, user, pixels=True)


@router.get("/ai/image-assets/{asset_id}/content")
def image_content(asset_id: str, db: Session = Depends(get_db), user: User = Depends(require_roles(*IMAGE_ROLES))):
    return _image_stream(asset_id, db, user, pixels=False)


@router.post("/ai/image-assets/{asset_id}/withdraw")
def withdraw_image(asset_id: str, req: ImageAssetAction, db: Session = Depends(get_db), user: User = Depends(require_roles(*IMAGE_ROLES))):
    authorized_feature(db, user, IMAGE_FEATURE)
    asset = db.query(AIImageAsset).filter_by(asset_id=asset_id).with_for_update().populate_existing().first()
    if asset is None:
        raise HTTPException(404, "影像原记录不存在")
    # Governance must remain possible even if an external workflow changes the
    # order's patient linkage. This exception does not authorize raw source reads.
    if user.user_role != "super_admin":
        authorize_image(db, user, asset, authorize_patient, manage=True)
    if asset.revision != req.expected_revision:
        raise HTTPException(409, "影像原记录版本已变化，请刷新后重试")
    changed = (
        db.query(AIImageAsset)
        .filter_by(asset_id=asset_id, status="ready", revision=req.expected_revision)
        .update({"status": "withdrawn", "revision": req.expected_revision + 1, "withdrawn_by": user.user_id, "withdrawn_at": utcnow(), "withdrawal_note": req.reason}, synchronize_session=False)
    )
    if changed != 1:
        db.rollback()
        raise HTTPException(409, "影像原记录状态已变化，请刷新后重试")
    audit(db, user.user_id, "image.withdraw", asset_id, {"revision": req.expected_revision + 1})
    db.commit()
    return {"code": 200, "msg": "原图已撤回，后续模型任务及普通用户旧结果读取随之失效", "data": {"asset_id": asset_id, "status": "withdrawn", "revision": req.expected_revision + 1}}


def _admin_image_metadata(asset, db, user):
    try:
        return image_metadata(asset, db=db, user=user)
    except HTTPException as exc:
        if exc.status_code != 409:
            raise
        return {
            **{
                name: getattr(asset, name)
                for name in (
                    "asset_id",
                    "patient_id",
                    "imaging_order_id",
                    "encounter_ref",
                    "content_hash",
                    "original_hash",
                    "pixel_hash",
                    "byte_size",
                    "recorded_at",
                    "created_by",
                    "create_time",
                    "status",
                    "revision",
                )
            },
            "image_metadata": json.loads(asset.metadata_json),
            "can_withdraw": asset.status == "ready",
            "source_error": "申请缺失或患者关联已变化，原文件读取被拒绝；仍可按源标识撤回和清除",
        }


@router.get("/ai/admin/image-assets")
def admin_image_list(
    patient_id: int | None = Query(None, ge=1),
    status: Literal["ready", "withdrawn", "purge_pending", "purged"] | None = None,
    limit: int = Query(100, ge=1, le=300),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("super_admin")),
):
    query = db.query(AIImageAsset)
    if patient_id is not None:
        query = query.filter_by(patient_id=patient_id)
    if status:
        query = query.filter_by(status=status)
    rows = query.order_by(AIImageAsset.create_time.desc(), AIImageAsset.asset_id).limit(limit + 1).all()
    return {"code": 200, "msg": "success", "data": {"items": [_admin_image_metadata(asset, db, user) for asset in rows[:limit]], "truncated": len(rows) > limit}}


@router.post("/ai/admin/image-assets/{asset_id}/purge")
def purge_image(asset_id: str, req: ImageAssetAction, db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin"))):
    asset = db.query(AIImageAsset).filter_by(asset_id=asset_id).with_for_update().populate_existing().first()
    if asset is None:
        raise HTTPException(404, "原始影像不存在")
    if asset.revision != req.expected_revision or asset.status not in {"withdrawn", "purge_pending"}:
        raise HTTPException(409, "须先撤回并核对当前版本，再清除原文件")
    version = asset.revision
    if asset.status == "withdrawn":
        changed = (
            db.query(AIImageAsset)
            .filter_by(asset_id=asset_id, status="withdrawn", revision=version)
            .update({"status": "purge_pending", "revision": version + 1, "purge_note": req.reason}, synchronize_session=False)
        )
        if changed != 1:
            db.rollback()
            raise HTTPException(409, "影像来源状态已变化，请刷新后重试")
        version += 1
        audit(db, user.user_id, "image.purge_requested", asset_id, {"revision": version})
        db.commit()
    directory = image_directory(asset_id)
    try:
        if directory.exists() or directory.is_symlink():
            shutil.rmtree(directory)
    except OSError as exc:
        raise HTTPException(503, "原文件清除尚未完成，保持清除中，可按当前版本恢复") from exc
    changed = (
        db.query(AIImageAsset)
        .filter_by(asset_id=asset_id, status="purge_pending", revision=version)
        .update({"status": "purged", "revision": version + 1, "purged_by": user.user_id, "purged_at": utcnow()}, synchronize_session=False)
    )
    if changed != 1:
        db.rollback()
        raise HTTPException(409, "清除状态已变化，请重新核对当前版本")
    audit(db, user.user_id, "image.purged", asset_id, {"revision": version + 1})
    db.commit()
    return {"code": 200, "msg": "当前存储原图及派生像素已清除，冻结任务文字及审计仍保留", "data": {"asset_id": asset_id, "status": "purged", "revision": version + 1}}
