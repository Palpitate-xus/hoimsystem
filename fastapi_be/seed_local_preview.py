"""Seed only the dedicated disposable local preview database, never hospital data."""

import datetime
import os

from sqlalchemy.engine import make_url

from app.ai.catalog import FEATURE_BY_KEY
from app.ai.governance import audit, encode_json
from app.ai.models import AIFeatureConfig, AIPatientGrant, AIProvider
from app.analytics import aggregate_daily_metrics
from app.config import settings
from app.database import SessionLocal
from app.db_migrate import migrate
from app.models import Bed, Department, Doctor, MedicalRecord, Notice, Patient, User, Ward
from seed_default_accounts import seed_default_accounts

FEATURES = ("patient_summary", "outpatient_note", "operations_qa")
NOTE = "本地合成资料与模拟回复，仅验证任务、协议和重试；未经真实模型推理或临床验证。"


def main():
    url = make_url(settings.DATABASE_URL)
    if settings.is_production or os.environ.get("HOIM_LOCAL_PREVIEW") != "1" or url.get_backend_name() != "postgresql" or url.database != "hoimsystem_preview":
        raise SystemExit("This initializer only accepts HOIM_LOCAL_PREVIEW=1 and the dedicated hoimsystem_preview database.")
    if not os.environ.get("AI_PROVIDER_PREVIEW_API_KEY"):
        raise SystemExit("Missing simulator credential")
    print("Migration:", migrate())
    seed_default_accounts()
    now = datetime.datetime.now(datetime.UTC).replace(tzinfo=None)
    with SessionLocal() as db:
        actor = db.query(User).filter_by(username="super01").one()
        doctor = db.query(Doctor).join(User).filter(User.username == "doctor1").one()
        patient = db.query(Patient).filter_by(identity="patient1").one()
        if not db.query(MedicalRecord).filter_by(patient_id=patient.patient_id).first():
            db.add(MedicalRecord(
                medical_record_id="00000000-0000-4000-8000-000000000001",
                patient_id=patient.patient_id, doctor_id=doctor.doctor_id, consultation_time=now,
                symptom="合成演示：自述头痛1天，未提供其他已核实症状。",
                result="合成演示：尚未明确诊断；查体、检查及用药资料未提供。", status=0,
            ))
        department = db.get(Department, doctor.department_id)
        ward = db.query(Ward).filter_by(name="演示内科病区").first()
        if not ward:
            ward = Ward(name="演示内科病区", department_id=department.department_id, bed_count=6, location="演示楼二层", status=0)
            db.add(ward)
            db.flush()
            for number in range(1, 7):
                db.add(Bed(ward_id=ward.ward_id, bed_no=f"{number:02d}", room_no="201" if number <= 3 else "202", price_per_day=80, status=0))
        if not db.query(Notice).filter_by(title="本地演示说明").first():
            db.add(Notice(title="本地演示说明", content=NOTE + " 使用超级管理员预览患者摘要和门诊病历草稿；运营问答可直接运行。", isemergency=0, towho="all", sendtime=now, expiredtime=now + datetime.timedelta(days=365), readnum=0, writer_id=actor.user_id))
        for category in {FEATURE_BY_KEY[key].category for key in FEATURES if FEATURE_BY_KEY[key].scope == "patient"}:
            grant = db.query(AIPatientGrant).filter_by(user_id=actor.user_id, patient_id=patient.patient_id, category=category, revoked=0).first()
            if not grant:
                db.add(AIPatientGrant(user_id=actor.user_id, patient_id=patient.patient_id, category=category, reason=NOTE, expires_at=now + datetime.timedelta(days=30), created_by=actor.user_id))
        for key in FEATURES:
            provider_name = "本地模拟 · " + FEATURE_BY_KEY[key].name
            provider = db.query(AIProvider).filter_by(name=provider_name).first()
            if not provider:
                provider = AIProvider(
                    name=provider_name, kind="chat", api_base="http://127.0.0.1:51853/v1", model="hoim-simulator:" + key,
                    api_key_env="AI_PROVIDER_PREVIEW_API_KEY", enabled=1, allows_patient_data=1,
                    timeout_seconds=30, max_attempts=3, max_output_tokens=2000, temperature=0,
                    validation_report=NOTE, created_by=actor.user_id,
                )
                db.add(provider)
                db.flush()
                audit(db, actor.user_id, "preview_provider_seeded", str(provider.provider_id), {"simulated": True, "model_inference": False})
            if not db.get(AIFeatureConfig, key):
                spec = FEATURE_BY_KEY[key]
                db.add(AIFeatureConfig(
                    feature_key=key, provider_id=provider.provider_id, enabled=int(key == "operations_qa"),
                    allowed_roles_json=encode_json(spec.default_roles), validation_status="unreviewed", validation_note=NOTE,
                    updated_by=actor.user_id,
                ))
                audit(db, actor.user_id, "preview_feature_seeded", key, {"simulated": True, "clinical_validation": False})
        db.flush()
        aggregate_daily_metrics(db, now.date())
        db.commit()
    print("Local preview initialized; all clinical validation flags remain unreviewed.")


if __name__ == "__main__":
    main()
