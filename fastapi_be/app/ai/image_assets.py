"""Current patient and requesting-order scope for private native image sources."""

import json

from fastapi import HTTPException
from sqlalchemy import select

from app.ai.governance import digest
from app.ai.models import AIImageAsset, AIPatientGrant, utcnow
from app.models import Doctor, ImagingOrder, Patient

IMAGE_FEATURE = "imaging_detection"
IMAGE_ROLES = {"super_admin", "doctor", "director", "lab_technician"}
# Preserve only known enum values, never a free-text order field in model context.
# The declared order modality remains distinct from the parsed DICOM modality.
ORDER_MODALITIES = frozenset({"CR", "DX", "DR", "CT", "MR", "MRI", "US", "MG", "XA", "RF", "NM", "PT", "OT", "ES", "XC", "IO", "PX", "SC", "超声", "内镜"})


def image_granted_patients(user_id):
    return select(AIPatientGrant.patient_id).where(AIPatientGrant.user_id == user_id, AIPatientGrant.category == "diagnostics", AIPatientGrant.revoked == 0, AIPatientGrant.expires_at > utcnow())


def authorize_image_patient(db, user, patient_id, authorize_patient, encounter_ref=None, order=None):
    """Add only actual requesting-doctor care, without granting unrelated EHR access."""
    try:
        patient = authorize_patient(db, user, patient_id, "diagnostics", encounter_ref)
    except HTTPException as exc:
        if exc.status_code != 403 or user.user_role not in {"doctor", "director"} or encounter_ref is not None:
            raise
        own_doctors = select(Doctor.doctor_id).where(Doctor.user_id == user.user_id)
        query = db.query(ImagingOrder.imaging_order_id).filter(ImagingOrder.patient_id == patient_id, ImagingOrder.doctor_id.in_(own_doctors))
        if order is not None:
            query = query.filter(ImagingOrder.imaging_order_id == order.imaging_order_id)
        if query.first() is None:
            raise
        patient = db.get(Patient, patient_id)
        if patient is None:
            raise HTTPException(404, "患者不存在") from exc
    if user.user_role not in IMAGE_ROLES:
        raise HTTPException(403, "当前角色不能使用内部原始影像资料")
    if order is not None and order.patient_id != patient_id:
        raise HTTPException(404, "影像申请不存在或不属于所选患者")
    if (
        user.user_role == "lab_technician"
        and db.query(AIPatientGrant.patient_id).filter(AIPatientGrant.patient_id.in_(image_granted_patients(user.user_id)), AIPatientGrant.patient_id == patient_id).first() is None
    ):
        raise HTTPException(403, "检验技师须取得当前患者的限时诊断用途授权，普通检验单不自动形成原始影像权限")
    return patient


def authorize_image_order(db, user, order, authorize_patient, *, patient_id=None, encounter_ref=None, for_inference=False):
    """An imaging order supplies patient linkage, never an inferred encounter linkage."""
    if order is None or (patient_id is not None and order.patient_id != patient_id):
        raise HTTPException(404, "影像申请不存在或不属于所选患者")
    authorize_image_patient(db, user, order.patient_id, authorize_patient, encounter_ref, order)
    if for_inference and order.status == 5:
        raise HTTPException(409, "影像申请已取消，不能继续登记或调用辅助识别")
    return order


def _current_order(asset, *, db=None, order=None):
    if order is not None and order.imaging_order_id != asset.imaging_order_id:
        raise HTTPException(422, "影像原记录与所选申请不一致")
    if db is not None:
        order = db.query(ImagingOrder).filter_by(imaging_order_id=asset.imaging_order_id).populate_existing().first()
    elif order is None:
        raise ValueError("An image source requires its current imaging order or database session")
    if order is None or order.patient_id != asset.patient_id:
        raise HTTPException(409, "原始影像的申请关联已不存在或患者归属已变化，请核对来源")
    return order


def authorize_image(
    db,
    user,
    asset,
    authorize_patient,
    *,
    patient_id=None,
    encounter_ref=None,
    imaging_order_id=None,
    order=None,
    manage=False,
    allow_inactive=False,
    for_inference=False,
):
    if asset is None or (patient_id is not None and asset.patient_id != patient_id):
        raise HTTPException(404, "影像原记录不存在或不属于所选患者")
    if user.user_role not in IMAGE_ROLES:
        raise HTTPException(403, "当前角色不能使用内部原始影像资料")
    if imaging_order_id is not None and asset.imaging_order_id != imaging_order_id:
        raise HTTPException(422, "影像原记录与所选申请不一致")
    order = _current_order(asset, db=db, order=order)
    authorize_image_order(db, user, order, authorize_patient, patient_id=asset.patient_id, encounter_ref=asset.encounter_ref, for_inference=for_inference)
    if manage and user.user_role != "super_admin" and user.user_id != asset.created_by:
        raise HTTPException(403, "撤回限原登记人与超级管理员处理")
    if encounter_ref is not None and asset.encounter_ref != encounter_ref:
        raise HTTPException(422, "影像原记录的就诊关联与本次选择不一致，不按日期推定归属")
    if not allow_inactive and asset.status != "ready":
        raise HTTPException(409, "影像原记录已撤回或清除，不能继续用于辅助识别")
    return asset


def image_metadata(asset, *, db=None, order=None, detail=False, user=None):
    order = _current_order(asset, db=db, order=order)
    names = (
        "asset_id",
        "patient_id",
        "imaging_order_id",
        "encounter_ref",
        "content_hash",
        "original_hash",
        "pixel_hash",
        "byte_size",
        "original_byte_size",
        "pixel_byte_size",
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
    data = {name: getattr(asset, name) for name in names}
    data["image_metadata"] = json.loads(asset.metadata_json)
    data["order_status"] = order.status
    data["order_modality"] = order.modality if order.modality in ORDER_MODALITIES else "unknown"
    data["source_order_hash"] = digest({name: getattr(order, name) for name in ("patient_id", "doctor_id", "modality", "body_part", "status")})
    if user is not None:
        data["can_withdraw"] = asset.status == "ready" and (user.user_role == "super_admin" or user.user_id == asset.created_by)
    if detail:
        data.update(authorization_note=asset.authorization_note, withdrawal_note=asset.withdrawal_note, purge_note=asset.purge_note)
    return data


def image_snapshot(asset, *, db=None, order=None):
    data = image_metadata(asset, db=db, order=order)
    for key in ("patient_id", "authorized_at", "created_by", "create_time", "withdrawn_by", "withdrawn_at", "purged_by", "purged_at"):
        data.pop(key)
    return data


def authorize_image_snapshot(db, user, context, authorize_patient):
    if user.user_role == "super_admin":
        return
    source = context.get("image_source") or {}
    asset = db.get(AIImageAsset, source.get("asset_id")) if source.get("asset_id") else None
    authorize_image(db, user, asset, authorize_patient, allow_inactive=True)
    current = image_snapshot(asset, db=db)
    if asset.status != "ready" or digest(current) != digest({key: source.get(key) for key in current}):
        raise HTTPException(403, "影像来源或申请状态已变化，不能继续读取旧辅助识别结果")
