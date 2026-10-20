"""Authorized, time-labelled clinical snapshots with minimized direct identifiers."""

import datetime
import json
import re
from dataclasses import dataclass, field

from fastapi import HTTPException
from sqlalchemy.orm import Session, selectinload

from app.ai.catalog import FeatureSpec
from app.ai.governance import digest, encode_json
from app.ai.models import AIPatientGrant, utcnow
from app.config import settings
from app.models import (
    Admission,
    Doctor,
    ImagingOrder,
    ImagingReport,
    LabOrder,
    LabResult,
    MedicalRecord,
    NursingRecord,
    Patient,
    PatientAllergy,
    PrePha,
    Prescription,
    Registration,
    StructuredMedicalRecord,
    User,
    VitalSign,
)


@dataclass
class ContextBundle:
    """A server-owned snapshot plus its separately citable source records."""

    data: dict = field(default_factory=dict)
    evidence: list[dict] = field(default_factory=list)
    department_ids: set[int] = field(default_factory=set)


def minimize_identifiers(value: object, patient: Patient | None = None) -> object:
    """Remove known direct identifiers; this is minimization, not guaranteed anonymization."""
    if isinstance(value, dict):
        return {key: minimize_identifiers(item, patient) for key, item in value.items()}
    if isinstance(value, list):
        return [minimize_identifiers(item, patient) for item in value]
    if not isinstance(value, str):
        return value
    text = value
    if patient:
        for item in (patient.name, patient.identity, patient.phone, patient.address):
            if item and len(item) >= 2:
                text = text.replace(item, "[已隐藏直接标识]")
    text = re.sub(r"(?<!\d)\d{17}[\dXx](?!\d)", "[证件号已隐藏]", text)
    return re.sub(r"(?<!\d)1[3-9]\d{9}(?!\d)", "[手机号已隐藏]", text)


def get_encounter(db: Session, patient_id: int, reference: str | None) -> Registration | Admission | None:
    """Resolve a real encounter belonging to the patient; never trust caller-supplied joins."""
    if not reference:
        return None
    encounter = db.query(Registration).filter_by(registration_uuid=reference, patient_id=patient_id).first()
    if encounter is None:
        encounter = db.query(Admission).filter_by(admission_id=reference, patient_id=patient_id).first()
    if encounter is None:
        raise HTTPException(404, "本次就诊不存在或不属于该患者")
    return encounter


def authorize_patient(db: Session, user: User, patient_id: int, category: str, encounter_ref: str | None = None) -> Patient:
    """Check ownership, real care relations or explicit expiring access before loading PHI."""
    patient = db.get(Patient, patient_id)
    if patient is None:
        raise HTTPException(404, "患者不存在")
    encounter = get_encounter(db, patient_id, encounter_ref)
    if user.user_role in {"super_admin", "admin"}:
        return patient
    if user.user_role == "patient":
        if patient.identity != user.username:
            raise HTTPException(403, "只能访问本人的 AI 资料")
        return patient
    grant = (
        db.query(AIPatientGrant.grant_id)
        .filter(
            AIPatientGrant.user_id == user.user_id,
            AIPatientGrant.patient_id == patient_id,
            AIPatientGrant.category == category,
            AIPatientGrant.revoked == 0,
            AIPatientGrant.expires_at > utcnow(),
        )
        .first()
    )
    if grant:
        return patient
    doctors = db.query(Doctor).filter_by(user_id=user.user_id).all()
    doctor_ids = [item.doctor_id for item in doctors]
    departments = {item.department_id for item in doctors if item.department_id}
    if encounter:
        if encounter.doctor_id in doctor_ids or (user.user_role == "director" and encounter.department_id in departments):
            return patient
    elif doctor_ids:
        for model in (Registration, MedicalRecord, Prescription, Admission, LabOrder):
            if db.query(model).filter(model.patient_id == patient_id, model.doctor_id.in_(doctor_ids)).first():
                return patient
        if user.user_role == "director" and departments:
            for model in (Registration, Admission):
                if db.query(model).filter(model.patient_id == patient_id, model.department_id.in_(departments)).first():
                    return patient
    if user.user_role == "nurse" and category in {"inpatient", "patient"}:
        if db.query(NursingRecord.record_id).filter_by(patient_id=patient_id, nurse_id=user.user_id).first():
            return patient
    if user.user_role == "pharmacist" and category == "pharmacy":
        if db.query(Prescription.prescription_id).filter(Prescription.patient_id == patient_id, Prescription.status.in_([0, 1, 2])).first():
            return patient
    if user.user_role == "lab_technician" and category == "diagnostics":
        if db.query(LabOrder.lab_order_id).filter_by(patient_id=patient_id).first():
            return patient
    raise HTTPException(403, "未确认本次诊疗关系，请由超级管理员按用途授予限时访问权限")


def patient_snapshot(db: Session, user: User, spec: FeatureSpec, patient_id: int, encounter_ref: str | None = None) -> ContextBundle:
    """Build a bounded snapshot without mixing historical diagnoses into confirmed current ones."""
    patient = authorize_patient(db, user, patient_id, spec.category, encounter_ref)
    encounter = get_encounter(db, patient_id, encounter_ref)
    bundle = ContextBundle()
    today = datetime.date.today()
    age = today.year - patient.birthday.year - ((today.month, today.day) < (patient.birthday.month, patient.birthday.day)) if patient.birthday else None
    bundle.data = {"snapshot_time": utcnow().isoformat(), "age": age, "sex": patient.sex, "encounter": None, "current_confirmed_diagnoses": [], "missing_data": []}
    if encounter:
        bundle.data["encounter"] = {
            "kind": "outpatient" if isinstance(encounter, Registration) else "inpatient",
            "status": encounter.status,
            "time": str(encounter.time if isinstance(encounter, Registration) else encounter.admission_time),
        }
        if encounter.department_id:
            bundle.department_ids.add(encounter.department_id)
        if isinstance(encounter, Admission) and encounter.admission_diagnosis:
            bundle.data["encounter"]["recorded_admission_diagnosis"] = encounter.admission_diagnosis
    else:
        bundle.data["missing_data"].append("未指定本次就诊，既往诊断不会视为本次确认诊断")

    def add(source_id: str, title: str, fields: dict, observed_at: object = None) -> dict:
        clean = json.loads(encode_json(minimize_identifiers(fields, patient)))
        bundle.evidence.append({"source_id": source_id, "kind": "patient_record", "title": title, "observed_at": str(observed_at) if observed_at else None, "content": encode_json(clean)})
        return {"source_id": source_id, **clean}

    profile = patient.clinical_profile
    if profile:

        def profile_json(raw: str | None, expected: type, label: str) -> object:
            try:
                value = json.loads(raw or ("[]" if expected is list else "{}"))
                if not isinstance(value, expected):
                    raise ValueError("unexpected profile shape")
                return value
            except (ValueError, TypeError):
                bundle.data["missing_data"].append(label + "格式无效，未作为可靠事实使用")
                return expected()

        bundle.data["clinical_profile"] = add(
            "profile:" + str(patient_id),
            "人工维护的临床档案",
            {
                "pregnant": bool(profile.pregnant) if profile.pregnant is not None else None,
                "egfr": str(profile.egfr) if profile.egfr is not None else None,
                "hepatic_impairment": profile.hepatic_impairment,
                "recorded_diagnoses": profile_json(profile.diagnoses_json, list, "人工诊断资料"),
                "manual_labs": profile_json(profile.labs_json, dict, "人工检验资料"),
                "updated_at": profile.update_time,
                "provenance": "人工维护；manual_labs 未携带逐项采样时间、单位和审核状态，不用于自动剂量计算",
            },
            profile.update_time,
        )
    else:
        bundle.data["missing_data"].append("尚未维护结构化临床档案")
    allergies = db.query(PatientAllergy).filter_by(patient_id=patient_id, status=1).all()
    bundle.data["allergies"] = [
        add("allergy:" + str(item.allergy_id), "结构化过敏记录", {"allergen": item.allergen, "reaction": item.reaction, "severity": item.severity}, item.update_time) for item in allergies
    ]
    bundle.data["allergy_history_text"] = patient.allergy_history
    if not allergies and not patient.allergy_history:
        bundle.data["missing_data"].append("未记录过敏信息，不能视为无过敏")

    records = db.query(MedicalRecord).filter_by(patient_id=patient_id).order_by(MedicalRecord.consultation_time.desc()).limit(15).all()
    bundle.data["outpatient_records"] = []
    for item in records:
        current = isinstance(encounter, Registration) and item.registration_uuid == encounter.registration_uuid
        record = add(
            "outpatient:" + item.medical_record_id,
            "门诊病历",
            {"symptom": item.symptom, "diagnosis_text": item.result, "signed": item.status == 1, "current_encounter": current},
            item.consultation_time,
        )
        bundle.data["outpatient_records"].append(record)
        if current and item.status == 1 and item.result:
            bundle.data["current_confirmed_diagnoses"].append(item.result)
    structured = db.query(StructuredMedicalRecord).filter_by(patient_id=patient_id).order_by(StructuredMedicalRecord.create_time.desc()).limit(8).all()
    bundle.data["structured_records"] = []
    for item in structured:
        current = isinstance(encounter, Admission) and item.admission_id == encounter.admission_id
        bundle.data["structured_records"].append(
            add(
                "structured:" + item.record_id,
                "结构化病历",
                {
                    "current_encounter": current,
                    **{
                        name: getattr(item, name)
                        for name in ("record_type", "chief_complaint", "present_illness", "past_history", "physical_exam", "auxiliary_exam", "diagnosis", "treatment_plan", "status")
                    },
                },
                item.update_time,
            )
        )
        if current and item.status in {1, 2} and item.sign_time and item.diagnosis:
            bundle.data["current_confirmed_diagnoses"].append(item.diagnosis)
    vital = db.query(VitalSign).filter_by(patient_id=patient_id).order_by(VitalSign.check_time.desc()).first()
    bundle.data["latest_vitals"] = (
        add(
            "vital:" + str(vital.vital_id),
            "生命体征记录",
            {name: getattr(vital, name) for name in ("temperature", "blood_pressure_systolic", "blood_pressure_diastolic", "pulse", "weight", "check_time")},
            vital.check_time,
        )
        if vital
        else None
    )
    prescriptions = (
        db.query(Prescription)
        .options(selectinload(Prescription.pre_phas).selectinload(PrePha.pharmaceutical))
        .filter_by(patient_id=patient_id)
        .order_by(Prescription.create_time.desc())
        .limit(12)
        .all()
    )
    bundle.data["prescriptions"] = [
        add(
            "prescription:" + item.prescription_id,
            "处方记录",
            {
                "status": item.status,
                "created_at": item.create_time,
                "administration_confirmed": False,
                "items": [
                    {
                        "drug_name": pp.pharmaceutical.name if pp.pharmaceutical else None,
                        "quantity": pp.number,
                        "dosage": getattr(pp, "dosage", None),
                        "dose_unit": getattr(pp, "dose_unit", None),
                        "frequency": getattr(pp, "frequency", None),
                        "route": getattr(pp, "route", None),
                        "duration_days": getattr(pp, "duration_days", None),
                    }
                    for pp in item.pre_phas
                ],
                "note": "处方状态不等同于当前正在服用；需核实实际用药时间",
            },
            item.create_time,
        )
        for item in prescriptions
    ]
    results = db.query(LabResult).join(LabOrder).filter(LabOrder.patient_id == patient_id, LabResult.audit_status == 1).order_by(LabResult.report_time.desc()).limit(15).all()
    bundle.data["reviewed_lab_reports"] = [
        add(
            "lab:" + item.lab_result_id,
            "已审核检验报告",
            {"result_text": item.result, "abnormal_flag": item.abnormal_flag, "critical_status": item.critical_status, "report_time": item.report_time, "audit_time": item.audit_time},
            item.report_time,
        )
        for item in results
    ]
    imaging = db.query(ImagingReport).join(ImagingOrder).filter(ImagingOrder.patient_id == patient_id, ImagingReport.status == 2).order_by(ImagingReport.report_time.desc()).limit(8).all()
    bundle.data["reviewed_imaging_reports"] = [
        add("imaging:" + item.report_id, "已审核影像报告", {"findings": item.findings, "impression": item.impression, "review_time": item.review_time}, item.report_time) for item in imaging
    ]
    if not bundle.data["current_confirmed_diagnoses"]:
        bundle.data["missing_data"].append("未取得本次就诊的已确认诊断")
    bundle.data = minimize_identifiers(bundle.data, patient)
    if len(encode_json(bundle.data)) > settings.AI_MAX_CONTEXT_CHARS:
        raise HTTPException(422, "患者资料超过上下文限制，请按本次就诊缩小资料范围")
    return bundle


def context_metadata(bundle: ContextBundle) -> dict:
    """Store traceability metadata independently of the clinical text."""
    return {"snapshot_time": bundle.data.get("snapshot_time"), "source_count": len(bundle.evidence), "context_digest": digest(bundle.data), "missing_data": bundle.data.get("missing_data", [])}
