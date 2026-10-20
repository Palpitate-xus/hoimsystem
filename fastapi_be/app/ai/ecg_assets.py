"""Care-team access to patient-chart ECG sources; governance remains separately authorized."""

import json

from fastapi import HTTPException
from sqlalchemy import select

from app.ai.governance import digest
from app.ai.models import AIECGAsset, AIPatientGrant, utcnow

ECG_FEATURE = "ecg_analysis"
ECG_ROLES = {"super_admin", "doctor", "director", "lab_technician"}


def ecg_granted_patients(user_id):
    return select(AIPatientGrant.patient_id).where(AIPatientGrant.user_id == user_id, AIPatientGrant.category == "diagnostics", AIPatientGrant.revoked == 0, AIPatientGrant.expires_at > utcnow())


def authorize_ecg_patient(db, user, patient_id, authorize_patient, encounter_ref=None):
    patient = authorize_patient(db, user, patient_id, "diagnostics", encounter_ref)
    # A generic laboratory order does not identify an ECG operator or grant access
    # to unrelated raw signals. Until that workflow exists, use an explicit grant.
    if (
        user.user_role == "lab_technician"
        and db.query(AIPatientGrant.patient_id).filter(AIPatientGrant.patient_id.in_(ecg_granted_patients(user.user_id)), AIPatientGrant.patient_id == patient_id).first() is None
    ):
        raise HTTPException(403, "检验技师须取得当前患者的限时诊断用途授权，普通检验单不自动形成原始心电权限")
    return patient


def authorize_ecg(db, user, asset, authorize_patient, *, patient_id=None, encounter_ref=None, allow_inactive=False, manage=False):
    if asset is None or (patient_id is not None and asset.patient_id != patient_id):
        raise HTTPException(404, "心电原记录不存在或不属于所选患者")
    if user.user_role not in ECG_ROLES:
        raise HTTPException(403, "当前角色不能使用内部心电原始资料")
    authorize_ecg_patient(db, user, asset.patient_id, authorize_patient, asset.encounter_ref)
    if manage and user.user_role != "super_admin" and user.user_id != asset.created_by:
        raise HTTPException(403, "撤回限原登记人与超级管理员处理")
    if encounter_ref is not None and asset.encounter_ref != encounter_ref:
        raise HTTPException(422, "心电原记录的就诊关联与本次选择不一致，不按日期推定归属")
    if not allow_inactive and asset.status != "ready":
        raise HTTPException(409, "心电原记录已撤回或清除，不能继续用于辅助判读")
    return asset


def ecg_metadata(asset, *, detail=False):
    names = (
        "asset_id",
        "patient_id",
        "encounter_ref",
        "content_hash",
        "header_hash",
        "signal_hash",
        "byte_size",
        "header_byte_size",
        "signal_byte_size",
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
    data["signal_metadata"] = json.loads(asset.metadata_json)
    if detail:
        data.update(authorization_note=asset.authorization_note, withdrawal_note=asset.withdrawal_note, purge_note=asset.purge_note)
    return data


def ecg_snapshot(asset):
    data = ecg_metadata(asset)
    for key in ("patient_id", "authorized_at", "created_by", "create_time", "withdrawn_by", "withdrawn_at", "purged_by", "purged_at"):
        data.pop(key)
    return data


def authorize_ecg_snapshot(db, user, context, authorize_patient):
    if user.user_role == "super_admin":
        return
    source = context.get("ecg_source") or {}
    asset = db.get(AIECGAsset, source.get("asset_id")) if source.get("asset_id") else None
    authorize_ecg(db, user, asset, authorize_patient, allow_inactive=True)
    if asset.status != "ready" or digest(ecg_snapshot(asset)) != digest({key: source.get(key) for key in ecg_snapshot(asset)}):
        raise HTTPException(403, "心电来源已撤回或版本失效，不能继续读取旧辅助判读结果")
