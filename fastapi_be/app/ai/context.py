"""Authorized, time-labelled clinical snapshots with minimized direct identifiers."""

import datetime
import json
import re
import uuid
from dataclasses import dataclass, field

from fastapi import HTTPException
from sqlalchemy import case, or_, select
from sqlalchemy.orm import Session, selectinload

from app.ai.adr_sources import attach_adr_sources
from app.ai.audio_assets import audio_snapshot, authorize_audio
from app.ai.audio_files import open_verified_audio
from app.ai.billing_sources import attach_billing_sources
from app.ai.care import surgical_patient_ids
from app.ai.catalog import FeatureSpec
from app.ai.coding_sources import attach_coding_sources
from app.ai.consultation_sources import attach_consultation_sources
from app.ai.ecg_assets import authorize_ecg, ecg_granted_patients, ecg_snapshot
from app.ai.ecg_files import open_verified_ecg
from app.ai.governance import digest, encode_json
from app.ai.image_assets import authorize_image, authorize_image_patient, image_granted_patients, image_snapshot
from app.ai.image_files import open_verified_image
from app.ai.incident_sources import attach_incident_sources
from app.ai.models import AIAudioAsset, AIECGAsset, AIImageAsset, AIPatientGrant, utcnow
from app.ai.nursing_sources import validate_nursing_selection
from app.ai.outpatient_billing import resolve_outpatient_charge
from app.ai.pathway_sources import PATHWAY_SOURCE_FEATURES, attach_pathway_sources
from app.ai.patient_sources import attach_patient_sources
from app.ai.procedural_sources import attach_procedural_sources
from app.ai.references import SOURCE_REFERENCE_KEYS
from app.clinical_observations import serialize_observation
from app.config import settings
from app.diagnosis_review import latest_reviews, review_state
from app.models import (
    Admission,
    AdverseEvent,
    AdverseReaction,
    ClinicalPathway,
    CriticalCareRecord,
    Doctor,
    IcuScoreRecord,
    ImagingOrder,
    ImagingReport,
    InpatientCharge,
    LabObservation,
    LabOrder,
    LabResult,
    MdtCase,
    MedicalRecord,
    MedicalRecordHome,
    NursingAssessment,
    NursingPlan,
    NursingRecord,
    PathwayEnrollment,
    Patient,
    PatientAllergy,
    PerioperativeAntibiotic,
    PrePha,
    Prescription,
    Referral,
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

        def opaque(key, item):
            if not isinstance(item, str):
                return False
            if key == "support_source_kind" and item in {"map", "respiratory_support", "arterial_pair", "vasoactive", "infection_episode"}:
                return True
            if key in {"content_hash", "header_hash", "signal_hash", "chunk_hash", "snapshot_hash", "source_snapshot_hash", "context_digest", "prompt_hash", "governance_hash"} and re.fullmatch(
                r"[a-f0-9]{64}", item
            ):
                return True
            if key in SOURCE_REFERENCE_KEYS | {
                "asset_id",
                "document_id",
                "encounter_ref",
                "admission_id",
                "review_id",
                "run_id",
                "forecast_series_id",
                "series_id",
                "window_id",
                "observation_id",
                "interval_id",
            }:
                try:
                    return str(uuid.UUID(item)) == item
                except ValueError:
                    return False
            if key == "source_id" and re.fullmatch(r"(?:audio|ecg|observation_window|inpatient_observation|urine_interval):[a-f0-9-]{36}:[a-f0-9]{12}", item):
                try:
                    return str(uuid.UUID(item.split(":")[1])) == item.split(":")[1]
                except ValueError:
                    return False
            if key == "source_id" and re.fullmatch(r"(?:completed_nursing_assessments|nursing_plans|critical_care_records):[a-f0-9-]{36}", item):
                try:
                    return str(uuid.UUID(item.split(":")[1])) == item.split(":")[1]
                except ValueError:
                    return False
            return False

        return {key: item if opaque(key, item) else minimize_identifiers(item, patient) for key, item in value.items()}
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
            if spec.number == 36:
                criteria.append(Patient.patient_id.in_(select(ImagingOrder.patient_id).where(ImagingOrder.doctor_id.in_(ids))))
        if user.user_role == "director" and departments:
            for model in (Registration, Admission):
                criteria.append(Patient.patient_id.in_(select(model.patient_id).where(model.department_id.in_(departments))))
        if user.user_role == "nurse" and spec.category in {"inpatient", "patient"}:
            for model in (NursingRecord, NursingAssessment, NursingPlan, CriticalCareRecord):
                criteria.append(Patient.patient_id.in_(select(model.patient_id).where(model.nurse_id == user.user_id)))
            criteria.append(Patient.patient_id.in_(select(IcuScoreRecord.patient_id).where(IcuScoreRecord.assessor_id == user.user_id)))
            criteria.append(Patient.patient_id.in_(surgical_patient_ids([], user.user_id)))
        if user.user_role == "pharmacist" and spec.category == "pharmacy":
            criteria.append(Patient.patient_id.in_(select(Prescription.patient_id).where(Prescription.status.in_([0, 1, 2]))))
        if user.user_role == "lab_technician" and spec.category == "diagnostics":
            criteria.append(Patient.patient_id.in_(select(LabOrder.patient_id)))
        query = query.filter(or_(*criteria))
        if user.user_role == "lab_technician" and spec.number == 36:
            query = query.filter(Patient.patient_id.in_(image_granted_patients(user.user_id)))
        if user.user_role == "lab_technician" and spec.number == 37:
            query = query.filter(Patient.patient_id.in_(ecg_granted_patients(user.user_id)))
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
        if encounter is None or isinstance(encounter, Admission):
            for model in (NursingRecord, NursingAssessment, NursingPlan, CriticalCareRecord, IcuScoreRecord):
                author = model.assessor_id if model is IcuScoreRecord else model.nurse_id
                query = db.query(model).filter(model.patient_id == patient_id, author == user.user_id)
                if encounter is not None:
                    query = query.filter(model.admission_id == encounter.admission_id)
                if query.first():
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
    for key, model, primary_key in (
        ("adverse_event_id", AdverseEvent, "event_id"),
        ("reaction_id", AdverseReaction, "reaction_id"),
        ("referral_id", Referral, "referral_id"),
        ("mdt_id", MdtCase, "mdt_id"),
        ("pathway_enrollment_id", PathwayEnrollment, "enrollment_id"),
        ("pathway_id", ClinicalPathway, "pathway_id"),
        ("icu_score_id", IcuScoreRecord, "score_id"),
    ):
        reference = references.get(key)
        if reference in (None, ""):
            continue
        if not isinstance(reference, str) or len(reference) > 10 or not reference.isascii() or not reference.isdigit() or not 0 < int(reference) <= 2147483647 or str(int(reference)) != reference:
            raise HTTPException(422, "所选事件、会诊、路径或评分标识须为规范的正整数字符串")
        if user.user_role == "patient":
            raise HTTPException(403, "患者端不提供内部事件、转诊、会诊和路径工作资料")
        query = db.query(model).filter(getattr(model, primary_key) == int(reference))
        if model is not ClinicalPathway:
            query = query.filter(model.patient_id == patient_id)
        row = query.first()
        if row is None:
            raise HTTPException(404, "所选事件、会诊或路径不存在或不属于该患者")
        selected[key] = row
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
        ("audio_asset_id", AIAudioAsset, "asset_id", None),
        ("ecg_asset_id", AIECGAsset, "asset_id", None),
        ("image_asset_id", AIImageAsset, "asset_id", None),
        ("imaging_order_id", ImagingOrder, "imaging_order_id", None),
        ("nursing_assessment_id", NursingAssessment, "assessment_id", None),
        ("nursing_plan_id", NursingPlan, "plan_id", None),
        ("critical_care_record_id", CriticalCareRecord, "record_id", None),
    ]
    for key, model, primary_key, order in sources:
        reference = references.get(key)
        if reference is None or reference == "":
            continue
        if not isinstance(reference, str) or len(reference) > 50:
            raise HTTPException(422, "所选资料标识格式不正确")
        if key in {"audio_asset_id", "ecg_asset_id", "image_asset_id", "imaging_order_id"} and user.user_role == "patient":
            raise HTTPException(403, "患者端不提供内部录音或原始心电工作资料")
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
    if spec.number == 73 or "drug_label_source_binding_id" in (source_refs or {}):
        raise HTTPException(422, "说明书原文复核须使用独立明确来源，不接受患者资料")
    if "coding_case_id" in (source_refs or {}):
        if spec.number != 68:
            raise HTTPException(422, "受审编码证据仅用于单份实际病案与同次住院的证据核对")
        from app.ai.coding_evidence_context import coding_context

        return coding_context(db, user, patient_id, encounter_ref, source_refs)
    if "roster_plan_id" in (source_refs or {}):
        raise HTTPException(422, "受审排班计划仅用于独立运营优化，不接受患者资料")
    if "bed_series_id" in (source_refs or {}):
        raise HTTPException(422, "受审床位序列仅用于独立病区预测，不接受患者资料")
    if "surgery_scenario_id" in (source_refs or {}):
        raise HTTPException(422, "受审手术场景仅用于独立运营排程，不接受患者资料")
    if "inventory_scenario_id" in (source_refs or {}):
        raise HTTPException(422, "受审库存场景仅用于独立物资候选比较，不接受患者资料")
    if "supply_series_id" in (source_refs or {}):
        raise HTTPException(422, "受审物资原量序列仅用于独立库存范围预测，不接受患者资料")
    if any(key in (source_refs or {}) for key in ("sofa_assessment_id", "sofa_change_assessment_id")):
        if spec.number != 42:
            raise HTTPException(422, "完整SOFA日评估及变化核实引用仅用于独立的脓毒症相关原资料核对")
        from app.ai.sofa_context import sofa_context

        return sofa_context(db, user, patient_id, encounter_ref, source_refs)
    if any((source_refs or {}).get(key) not in (None, "") for key in ("support_source_id", "support_source_kind")):
        if spec.number != 47:
            raise HTTPException(422, "原器官支持资料引用仅用于明确单条交班资料整理")
        from app.ai.support_context import support_context

        return support_context(db, user, patient_id, encounter_ref, source_refs)
    if (source_refs or {}).get("qsofa_assessment_id") not in (None, ""):
        if spec.number != 42:
            raise HTTPException(422, "qSOFA评估仅供明确原床旁三项资料核对使用")
        from app.ai.qsofa_context import qsofa_context

        return qsofa_context(db, user, patient_id, encounter_ref, source_refs)
    if (source_refs or {}).get("aki_assessment_id") not in (None, ""):
        if spec.number != 43:
            raise HTTPException(422, "AKI评估仅供所选肾功能原资料的独立判据核对使用")
        from app.ai.aki_context import aki_context

        return aki_context(db, user, patient_id, encounter_ref, source_refs)
    if (source_refs or {}).get("news2_assessment_id") not in (None, ""):
        if spec.number != 41:
            raise HTTPException(422, "NEWS2评估仅供病情恶化预警的独立评分使用")
        from app.ai.news2_context import news2_context

        return news2_context(db, user, patient_id, encounter_ref, source_refs)
    if spec.number in {41, 42, 43}:
        from app.ai.observation_windows import observation_context

        return observation_context(db, user, patient_id, encounter_ref, source_refs or {})
    if (source_refs or {}).get("observation_window_id") not in (None, ""):
        raise HTTPException(422, "原住院观测窗仅供41至43风险输入使用")
    if spec.number == 77 and encounter_ref:
        raise HTTPException(422, "不良事件没有就诊关联字段，请清除本次就诊选择，不能按日期推定事件归属")
    patient = authorize_image_patient(db, user, patient_id, authorize_patient, encounter_ref) if spec.number == 36 else authorize_patient(db, user, patient_id, spec.category, encounter_ref)
    encounter = get_encounter(db, patient_id, encounter_ref)
    if spec.number == 21 and user.user_role == "patient":
        raise HTTPException(403, "患者端不提供内部录音工作资料")
    if spec.number == 21 and any(key in SOURCE_REFERENCE_KEYS - {"audio_asset_id"} and item not in (None, "") for key, item in (source_refs or {}).items()):
        raise HTTPException(422, "录音转写只接受明确的原录音引用，不加载其他临床历史")
    if (source_refs or {}).get("ecg_asset_id") not in (None, "") and user.user_role == "patient":
        raise HTTPException(403, "患者端不提供内部原始心电工作资料")
    if spec.number != 37 and (source_refs or {}).get("ecg_asset_id") not in (None, ""):
        raise HTTPException(422, "该功能不接受原始心电文件，须使用专用心电辅助判读与人工复核")
    if spec.number == 37 and any(key in SOURCE_REFERENCE_KEYS - {"ecg_asset_id"} and item not in (None, "") for key, item in (source_refs or {}).items()):
        raise HTTPException(422, "心电辅助判读只加载明确原波形及技术资料，不把其他报告当作原始信号")
    image_keys = {"image_asset_id", "imaging_order_id"}
    if spec.number != 36 and any((source_refs or {}).get(key) not in (None, "") for key in image_keys):
        raise HTTPException(422, "原始影像与申请引用仅供专用影像辅助识别使用")
    if spec.number == 36 and any(key in SOURCE_REFERENCE_KEYS - image_keys and item not in (None, "") for key, item in (source_refs or {}).items()):
        raise HTTPException(422, "影像辅助识别只接受真实原像素与申请引用，不把文字报告当成影像")
    selected = _selected_records(db, user, patient_id, source_refs or {})
    validate_nursing_selection(spec, selected, encounter)
    if spec.number != 21 and "audio_asset_id" in selected:
        raise HTTPException(422, "该功能不接受录音文件，须先完成医疗语音转写和人工核对")
    if spec.number not in PATHWAY_SOURCE_FEATURES and any(key in selected for key in ("pathway_id", "pathway_enrollment_id")):
        raise HTTPException(422, "该功能不接受内部临床路径资料")
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

    if spec.number == 36:
        if not selected.get("image_asset_id") or not selected.get("imaging_order_id"):
            raise HTTPException(422, "请选择已登记的原始影像及其真实影像申请，不能以报告或调阅链接代替像素")
        asset = authorize_image(
            db,
            user,
            selected["image_asset_id"],
            authorize_patient,
            patient_id=patient_id,
            encounter_ref=encounter_ref,
            imaging_order_id=selected["imaging_order_id"].imaging_order_id,
            for_inference=True,
        )
        handles = open_verified_image(asset)
        for stream in handles:
            stream.close()
        source_id = "image:" + asset.asset_id + ":" + asset.content_hash[:12]
        fields = json.loads(encode_json(image_snapshot(asset, db=db)))
        source = {"source_id": source_id, **fields}
        bundle.evidence.append(
            {
                "source_id": source_id,
                "kind": "image_asset",
                "title": "当前申请对应的单帧原影像及白名单技术参数",
                "observed_at": str(asset.recorded_at) if asset.recorded_at else None,
                "content": encode_json(fields),
            }
        )
        bundle.data = {
            "scope": "native_single_image_analysis",
            "snapshot_time": bundle.data["snapshot_time"],
            "selected_sources": {"image_asset_id": asset.asset_id, "imaging_order_id": asset.imaging_order_id},
            "image_source": source,
            "scope_note": "仅所选单帧原像素及技术参数，不代表完整序列、容积或整次检查；像素保持原行列坐标，不推测解剖方向。头标签未传给模型，但像素仍可能包含身份信息，不能声称匿名化。申请未保存就诊关联，不能按日期推定。登记校验不证明临床诊断质量",
            "missing_data": ["未提供经核实的采集时年龄及人群适用信息；不能以当前年龄或标签猜测", *([] if asset.recorded_at else ["原采集时间未知，不以上传时刻代替"])],
        }
        return bundle
    if spec.number == 37:
        if not selected.get("ecg_asset_id"):
            raise HTTPException(422, "请选择已登记且当前获授权的原始心电，不能以文字报告代替波形")
        asset = authorize_ecg(db, user, selected["ecg_asset_id"], authorize_patient, patient_id=patient_id, encounter_ref=encounter_ref)
        handles = open_verified_ecg(asset)
        for stream in handles:
            stream.close()
        # These are server-parsed technical fields only. Reapplying free-text PII
        # replacement would corrupt gain/frequency strings or real lead names.
        source_id = "ecg:" + asset.asset_id + ":" + asset.content_hash[:12]
        fields = json.loads(encode_json(ecg_snapshot(asset)))
        source = {"source_id": source_id, **fields}
        bundle.evidence.append(
            {
                "source_id": source_id,
                "kind": "ecg_asset",
                "title": "当前诊疗授权范围内的原始心电及校准资料",
                "observed_at": str(asset.recorded_at) if asset.recorded_at else None,
                "content": encode_json(fields),
            }
        )
        bundle.data = {
            "scope": "raw_ecg_analysis",
            "snapshot_time": bundle.data["snapshot_time"],
            "selected_sources": {"ecg_asset_id": asset.asset_id},
            "ecg_source": source,
            "scope_note": "只提供所选原波形与经文件校验的技术声明，不加载无关病史或把文字报告当原信号。导联顺序、缺失值和单位保留；文件校验不证明患者身份、设备校准或生理/诊断质量。采样位置相对原记录，不代表诊疗发生时刻",
            "missing_data": [
                "未提供经核实的采集时年龄、人群及临床适用信息，专用模型须核对其验证范围；不能以当前年龄或未审核头注释补写",
                *([] if asset.recorded_at else ["未记录带时区的原始采集时间，头时钟不自动升级为诊疗时刻"]),
            ],
        }
        return bundle
    if spec.number == 21:
        if not selected.get("audio_asset_id"):
            raise HTTPException(422, "请选择已登记并获授权的原录音，不能以文字资料冒充语音识别")
        asset = authorize_audio(db, user, selected.get("audio_asset_id"), authorize_patient, patient_id=patient_id, encounter_ref=encounter_ref)
        with open_verified_audio(asset):
            pass
        source = add("audio:" + asset.asset_id + ":" + asset.content_hash[:12], "本人登记并获当前访问授权的原录音", audio_snapshot(asset), asset.recorded_at, kind="audio_asset")
        bundle.data = {
            "scope": "recording_transcription",
            "snapshot_time": bundle.data["snapshot_time"],
            "selected_sources": {"audio_asset_id": asset.asset_id},
            "audio_source": source,
            "scope_note": "仅所选原录音及其技术元数据；未加载无关病史。原音频可能含直接标识，不能保证匿名化。分段时间以解码音频为参考，不代表临床发生时刻；说话人标签不证明真实身份和职业",
            "missing_data": ["未取得经核实的说话人身份映射，角色保持未知", *([] if asset.recorded_at else ["未记录原录音发生时间，不以登记或上传时间代替"])],
        }
        return bundle
    if spec.number in {69, 77}:
        # These tasks need selected source links rather than unrelated clinical history.
        for key in ("age", "sex", "current_confirmed_diagnoses", "diagnosis_reviews"):
            bundle.data.pop(key, None)
        if spec.number == 69:
            attach_billing_sources(db, user, spec, patient, encounter, bundle, add, selected, bounded, authorize_patient)
        else:
            bundle.data["missing_data"] = []
            attach_incident_sources(db, selected, bundle, add)
        bundle.data = minimize_identifiers(bundle.data, patient)
        if len(encode_json(bundle.data)) > settings.AI_MAX_CONTEXT_CHARS:
            raise HTTPException(422, "所选专项资料超过上下文限制，请缩小资料范围")
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
    attach_consultation_sources(db, user, spec, patient, encounter, bundle, add, selected, bounded)
    attach_adr_sources(db, user, spec, patient, bundle, add, selected, bounded)
    attach_pathway_sources(db, user, spec, patient, encounter, bundle, add, selected, bounded, authorize_patient)
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
        "department_ids": sorted(bundle.department_ids),
        "context_digest": digest(bundle.data),
        "clinical_context_fingerprint": digest({key: value for key, value in bundle.data.items() if key != "snapshot_time"}),
        "missing_data": bundle.data.get("missing_data", []),
    }
