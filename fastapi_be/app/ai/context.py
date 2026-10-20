"""Authorized, time-labelled clinical snapshots with minimized direct identifiers."""

import datetime
import json
import re
from dataclasses import dataclass, field

from fastapi import HTTPException
from sqlalchemy import case, or_, select
from sqlalchemy.orm import Session, selectinload

from app.ai.billing_sources import attach_billing_sources
from app.ai.care import surgical_patient_ids
from app.ai.catalog import FeatureSpec
from app.ai.coding_sources import attach_coding_sources
from app.ai.governance import digest, encode_json
from app.ai.models import AIPatientGrant, utcnow
from app.ai.outpatient_billing import resolve_outpatient_charge
from app.ai.patient_sources import attach_patient_sources
from app.ai.procedural_sources import attach_procedural_sources
from app.clinical_observations import serialize_observation
from app.config import settings
from app.diagnosis_review import latest_reviews, review_state
from app.models import (
    Admission,
    Doctor,
    ImagingOrder,
    ImagingReport,
    InpatientCharge,
    LabObservation,
    LabOrder,
    LabResult,
    MedicalRecord,
    MedicalRecordHome,
    NursingRecord,
    Patient,
    PatientAllergy,
    PerioperativeAntibiotic,
    PrePha,
    Prescription,
    Registration,
    StructuredMedicalRecord,
    SurgeryApplication,
    SurgerySchedule,
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


def accessible_patients(db: Session, user: User, spec: FeatureSpec, keyword: str = "", limit: int = 50) -> list[Patient]:
    """Filter patient selection in SQL using the execution care and grant boundaries."""
    query = db.query(Patient)
    if user.user_role == "patient":
        query = query.filter(Patient.identity == user.username)
    elif user.user_role not in {"super_admin", "admin"}:
        criteria = [
            Patient.patient_id.in_(
                select(AIPatientGrant.patient_id).where(
                    AIPatientGrant.user_id == user.user_id, AIPatientGrant.category == spec.category, AIPatientGrant.revoked == 0, AIPatientGrant.expires_at > utcnow()
                )
            )
        ]
        doctors = db.query(Doctor).filter_by(user_id=user.user_id).all()
        ids = [item.doctor_id for item in doctors]
        departments = {item.department_id for item in doctors if item.department_id}
        if ids:
            for model in (Registration, MedicalRecord, Prescription, Admission, LabOrder):
                criteria.append(Patient.patient_id.in_(select(model.patient_id).where(model.doctor_id.in_(ids))))
            criteria.append(Patient.patient_id.in_(surgical_patient_ids(ids)))
        if user.user_role == "director" and departments:
            for model in (Registration, Admission):
                criteria.append(Patient.patient_id.in_(select(model.patient_id).where(model.department_id.in_(departments))))
        if user.user_role == "nurse" and spec.category in {"inpatient", "patient"}:
            criteria.append(Patient.patient_id.in_(select(NursingRecord.patient_id).where(NursingRecord.nurse_id == user.user_id)))
            criteria.append(Patient.patient_id.in_(surgical_patient_ids([], user.user_id)))
        if user.user_role == "pharmacist" and spec.category == "pharmacy":
            criteria.append(Patient.patient_id.in_(select(Prescription.patient_id).where(Prescription.status.in_([0, 1, 2]))))
        if user.user_role == "lab_technician" and spec.category == "diagnostics":
            criteria.append(Patient.patient_id.in_(select(LabOrder.patient_id)))
        query = query.filter(or_(*criteria))
    if keyword:
        query = query.filter(Patient.name.contains(keyword, autoescape=True))
    return query.order_by(Patient.patient_id.desc()).limit(limit).all()


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
    nurse_assignment = user.user_id if user.user_role == "nurse" and category in {"inpatient", "patient"} else None
    if (doctor_ids or nurse_assignment) and (encounter is None or isinstance(encounter, Admission)):
        care = surgical_patient_ids(doctor_ids, nurse_assignment, encounter.admission_id if encounter else None)
        if db.query(Patient.patient_id).filter(Patient.patient_id == patient_id, Patient.patient_id.in_(care)).first():
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


def _selected_records(db: Session, user: User, patient_id: int, references: dict) -> dict:
    """Resolve explicit row selections inside this patient's scope before bounded history queries."""
    selected = {}
    if references.get("outpatient_charge_id") not in (None, ""):
        selected["outpatient_charge_id"] = resolve_outpatient_charge(db, patient_id, references["outpatient_charge_id"])
    sources = [
        ("record_id", MedicalRecord, "medical_record_id", None),
        ("structured_record_id", StructuredMedicalRecord, "record_id", None),
        ("prescription_id", Prescription, "prescription_id", None),
        ("lab_result_id", LabResult, "lab_result_id", LabOrder),
        ("imaging_report_id", ImagingReport, "report_id", ImagingOrder),
        ("surgery_application_id", SurgeryApplication, "application_id", None),
        ("surgery_schedule_id", SurgerySchedule, "schedule_id", None),
        ("perioperative_id", PerioperativeAntibiotic, "perioperative_id", None),
        ("home_id", MedicalRecordHome, "home_id", None),
        ("inpatient_charge_id", InpatientCharge, "charge_id", None),
    ]
    for key, model, primary_key, order in sources:
        reference = references.get(key)
        if reference is None or reference == "":
            continue
        if not isinstance(reference, str) or len(reference) > 50:
            raise HTTPException(422, "所选资料标识格式不正确")
        query = db.query(model).filter(getattr(model, primary_key) == reference)
        query = query.join(order).filter(order.patient_id == patient_id) if order else query.filter(model.patient_id == patient_id)
        row = query.first()
        if not row:
            raise HTTPException(404, "所选资料不存在或不属于该患者")
        if (isinstance(row, LabResult) and row.audit_status != 1) or (isinstance(row, ImagingReport) and row.status != 2):
            raise HTTPException(409, "所选检验或影像报告尚未审核，不能用于 AI 解读")
        if user.user_role == "patient" and ((isinstance(row, MedicalRecord) and row.status != 1) or (isinstance(row, StructuredMedicalRecord) and (row.status not in {1, 2} or not row.sign_time))):
            raise HTTPException(403, "该病历尚未完成签署，不能在患者端加载")
        selected[key] = row
    return selected


def patient_snapshot(db: Session, user: User, spec: FeatureSpec, patient_id: int, encounter_ref: str | None = None, source_refs: dict | None = None) -> ContextBundle:
    """Build a bounded snapshot without mixing historical diagnoses into confirmed current ones."""
    patient = authorize_patient(db, user, patient_id, spec.category, encounter_ref)
    encounter = get_encounter(db, patient_id, encounter_ref)
    selected = _selected_records(db, user, patient_id, source_refs or {})
    bundle = ContextBundle()
    today = datetime.date.today()
    age = today.year - patient.birthday.year - ((today.month, today.day) < (patient.birthday.month, patient.birthday.day)) if patient.birthday else None
    bundle.data = {
        "snapshot_time": utcnow().isoformat(),
        "age": age,
        "sex": patient.sex,
        "encounter": None,
        "current_confirmed_diagnoses": [],
        "missing_data": [],
        "scope_note": "按近期记录和明确所选资料构建的有限快照，不代表完整病史；所选资料不等同于本次就诊资料",
        "truncated_sources": [],
        "diagnosis_reviews": [],
        "selected_sources": {key: (source_refs or {})[key] for key in selected},
    }

    def bounded(query, limit: int, label: str, key: str | None = None, primary_key: str | None = None):
        rows = query.limit(limit + 1).all()
        chosen = selected.get(key)
        if chosen:
            rows = [chosen, *[item for item in rows if getattr(item, primary_key) != getattr(chosen, primary_key)]]
        if len(rows) > limit:
            bundle.data["truncated_sources"].append({"source": label, "limit": limit, "note": "其余记录未纳入，不能据此断言无其他结果"})
        return rows[:limit]

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
        bundle.data["missing_data"].append("未指定本次就诊，将核实所选收费资料的范围" if spec.number == 69 else "未指定本次就诊，既往诊断不会视为本次确认诊断")

    def add(source_id: str, title: str, fields: dict, observed_at: object = None, *, kind: str = "patient_record") -> dict:
        clean = json.loads(encode_json(minimize_identifiers(fields, patient)))
        bundle.evidence.append({"source_id": source_id, "kind": kind, "title": title, "observed_at": str(observed_at) if observed_at else None, "content": encode_json(clean)})
        return {"source_id": source_id, **clean}

    if spec.number == 69:
        # Billing only needs the selected financial/execution links, not unrelated clinical history.
        for key in ("age", "sex", "current_confirmed_diagnoses", "diagnosis_reviews"):
            bundle.data.pop(key, None)
        attach_billing_sources(db, user, spec, patient, encounter, bundle, add, selected, bounded, authorize_patient)
        bundle.data = minimize_identifiers(bundle.data, patient)
        if len(encode_json(bundle.data)) > settings.AI_MAX_CONTEXT_CHARS:
            raise HTTPException(422, "账务资料超过上下文限制，请选择具体费用记录缩小范围")
        return bundle

    def attach_diagnosis_review(record, reviews: dict) -> str:
        state, review = review_state(record, reviews)
        if review:
            bundle.data["diagnosis_reviews"].append(
                add(
                    "diagnosis-review:" + review.review_id,
                    "责任医生诊断复核",
                    {
                        "source_kind": review.source_kind,
                        "source_id": review.source_id,
                        "diagnosis_text_at_review": review.diagnosis_text,
                        "certainty": state,
                        "reviewed_certainty": review.certainty,
                        "revision": review.revision,
                        "reason": review.reason,
                        "reviewed_at": review.reviewed_at,
                    },
                    review.reviewed_at,
                )
            )
        return state

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
    allergies = db.query(PatientAllergy).filter_by(patient_id=patient_id, status=1).order_by(PatientAllergy.allergy_id).all()
    bundle.data["allergies"] = [
        add("allergy:" + str(item.allergy_id), "结构化过敏记录", {"allergen": item.allergen, "reaction": item.reaction, "severity": item.severity}, item.update_time) for item in allergies
    ]
    bundle.data["allergy_history_text"] = patient.allergy_history
    if not allergies and not patient.allergy_history:
        bundle.data["missing_data"].append("未记录过敏信息，不能视为无过敏")

    record_query = db.query(MedicalRecord).filter_by(patient_id=patient_id)
    if user.user_role == "patient":
        record_query = record_query.filter(MedicalRecord.status == 1)
    record_query = (
        record_query.order_by(case((MedicalRecord.registration_uuid == encounter_ref, 0), else_=1), MedicalRecord.consultation_time.desc())
        if encounter_ref
        else record_query.order_by(MedicalRecord.consultation_time.desc())
    )
    records = bounded(record_query.order_by(MedicalRecord.medical_record_id), 15, "门诊病历", "record_id", "medical_record_id")
    record_reviews = latest_reviews(db, patient_id, [item.medical_record_id for item in records])
    bundle.data["outpatient_records"] = []
    for item in records:
        current = isinstance(encounter, Registration) and item.registration_uuid == encounter.registration_uuid
        certainty = attach_diagnosis_review(item, record_reviews)
        record = add(
            "outpatient:" + item.medical_record_id,
            "门诊病历",
            {"symptom": item.symptom, "diagnosis_text": item.result, "diagnosis_certainty": certainty, "signed": item.status == 1, "current_encounter": current},
            item.consultation_time,
        )
        bundle.data["outpatient_records"].append(record)
        if current and certainty == "confirmed" and item.result:
            bundle.data["current_confirmed_diagnoses"].append(item.result)
    structured_query = db.query(StructuredMedicalRecord).filter_by(patient_id=patient_id)
    if user.user_role == "patient":
        structured_query = structured_query.filter(StructuredMedicalRecord.status.in_([1, 2]), StructuredMedicalRecord.sign_time.isnot(None))
    structured_query = (
        structured_query.order_by(case((StructuredMedicalRecord.admission_id == encounter_ref, 0), else_=1), StructuredMedicalRecord.create_time.desc())
        if encounter_ref
        else structured_query.order_by(StructuredMedicalRecord.create_time.desc())
    )
    structured = bounded(structured_query.order_by(StructuredMedicalRecord.record_id), 8, "结构化病历", "structured_record_id", "record_id")
    structured_reviews = latest_reviews(db, patient_id, [item.record_id for item in structured])
    bundle.data["structured_records"] = []
    for item in structured:
        current = isinstance(encounter, Admission) and item.admission_id == encounter.admission_id
        certainty = attach_diagnosis_review(item, structured_reviews)
        bundle.data["structured_records"].append(
            add(
                "structured:" + item.record_id,
                "结构化病历",
                {
                    "current_encounter": current,
                    "diagnosis_certainty": certainty,
                    **{
                        name: getattr(item, name)
                        for name in ("record_type", "chief_complaint", "present_illness", "past_history", "physical_exam", "auxiliary_exam", "diagnosis", "treatment_plan", "status")
                    },
                },
                item.update_time,
            )
        )
        if current and certainty == "confirmed" and item.diagnosis:
            bundle.data["current_confirmed_diagnoses"].append(item.diagnosis)
    vital = db.query(VitalSign).filter_by(patient_id=patient_id).order_by(VitalSign.check_time.desc(), VitalSign.vital_id.desc()).first()
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
    prescription_query = (
        db.query(Prescription).options(selectinload(Prescription.pre_phas).selectinload(PrePha.pharmaceutical)).filter_by(patient_id=patient_id).order_by(Prescription.create_time.desc())
    )
    prescriptions = bounded(prescription_query.order_by(Prescription.prescription_id), 12, "处方", "prescription_id", "prescription_id")
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
                    for pp in sorted(item.pre_phas, key=lambda line: line.pre_pha_id)
                ],
                "note": "处方状态不等同于当前正在服用；需核实实际用药时间",
            },
            item.create_time,
        )
        for item in prescriptions
    ]
    results = bounded(
        db.query(LabResult).join(LabOrder).filter(LabOrder.patient_id == patient_id, LabResult.audit_status == 1).order_by(LabResult.report_time.desc(), LabResult.lab_result_id),
        15,
        "已审核检验",
        "lab_result_id",
        "lab_result_id",
    )
    bundle.data["reviewed_lab_reports"] = [
        add(
            "lab:" + item.lab_result_id,
            "已审核检验报告",
            {
                "result_text": item.result,
                "abnormal_flag": item.abnormal_flag,
                "critical_status": item.critical_status,
                "report_time": item.report_time,
                "audit_time": item.audit_time,
                "critical_notified_time": item.critical_notified_time,
                "critical_acknowledged_time": item.critical_acknowledged_time,
                "critical_handled_time": item.critical_handled_time,
                "critical_handling_note": item.critical_handling_note,
            },
            item.report_time,
        )
        for item in results
    ]
    observation_query = db.query(LabObservation).join(LabResult).join(LabOrder).filter(LabOrder.patient_id == patient_id, LabResult.audit_status == 1)
    if selected.get("lab_result_id"):
        observation_query = observation_query.order_by(case((LabObservation.lab_result_id == selected["lab_result_id"].lab_result_id, 0), else_=1))
    observations = bounded(observation_query.order_by(LabObservation.collected_at.desc(), LabObservation.observation_id), 60, "结构化检验指标")
    bundle.data["reviewed_observations"] = [
        add("observation:" + item.observation_id, "已审核结构化检验指标", {"lab_result_id": item.lab_result_id, **serialize_observation(item)}, item.collected_at) for item in observations
    ]
    if results and not observations:
        bundle.data["missing_data"].append("历史检验报告未提供结构化数值、原始单位和采样时间，不进行自动数值推断")
    imaging = bounded(
        db.query(ImagingReport).join(ImagingOrder).filter(ImagingOrder.patient_id == patient_id, ImagingReport.status == 2).order_by(ImagingReport.report_time.desc(), ImagingReport.report_id),
        8,
        "已审核影像",
        "imaging_report_id",
        "report_id",
    )
    bundle.data["reviewed_imaging_reports"] = [
        add("imaging:" + item.report_id, "已审核影像报告", {"findings": item.findings, "impression": item.impression, "review_time": item.review_time}, item.report_time) for item in imaging
    ]
    attach_patient_sources(db, user, spec, patient, encounter, bundle, add)
    attach_procedural_sources(db, user, spec, patient, encounter, bundle, add, selected, bounded)
    attach_coding_sources(db, user, spec, patient, encounter, bundle, add, selected, bounded, authorize_patient)
    if not bundle.data["current_confirmed_diagnoses"]:
        bundle.data["missing_data"].append("未取得本次就诊的已确认诊断")
    bundle.data = minimize_identifiers(bundle.data, patient)
    if len(encode_json(bundle.data)) > settings.AI_MAX_CONTEXT_CHARS:
        raise HTTPException(422, "患者资料超过上下文限制，请按本次就诊缩小资料范围")
    return bundle


def context_metadata(bundle: ContextBundle) -> dict:
    """Store traceability metadata independently of the clinical text."""
    return {
        "snapshot_time": bundle.data.get("snapshot_time"),
        "source_count": len(bundle.evidence),
        "context_digest": digest(bundle.data),
        "clinical_context_fingerprint": digest({key: value for key, value in bundle.data.items() if key != "snapshot_time"}),
        "missing_data": bundle.data.get("missing_data", []),
    }
