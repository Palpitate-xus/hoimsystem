"""Feature-scoped clinical connectors for an already authorized patient and selected admission."""

from sqlalchemy import case
from sqlalchemy.orm import selectinload

from app.models import (
    Admission,
    CriticalCareRecord,
    DischargeSummary,
    FollowUp,
    IcuScoreRecord,
    InpatientCharge,
    InpatientOrder,
    MedicalRecordHome,
    MedicationAdministration,
    NursingAssessment,
    NursingPlan,
    NursingRecord,
    OrderExecution,
    ProgressNote,
    WardRound,
)


def attach_patient_sources(db, user, spec, patient, encounter, bundle, add) -> None:
    """Keep admission boundaries, recorded states and source provenance in every added fact."""
    number = spec.number

    def append_rows(key, model, primary_key, time_field, fields, limit, *, admission=False, extra_filters=()):
        query = db.query(model).filter(model.patient_id == patient.patient_id, *extra_filters)
        if admission:
            query = query.filter(model.admission_id == encounter.admission_id)
        rows = query.order_by(getattr(model, time_field).desc(), getattr(model, primary_key)).limit(limit + 1).all()
        if len(rows) > limit:
            bundle.data["truncated_sources"].append({"source": key, "limit": limit, "note": "其余记录未纳入本次快照"})
        bundle.data[key] = [add(key + ":" + str(getattr(item, primary_key)), key, {name: getattr(item, name) for name in fields}, getattr(item, time_field)) for item in rows[:limit]]
        return rows[:limit]

    if number in {1, 8, 25, 54, 55, 56, 57}:
        append_rows("followup_records", FollowUp, "follow_up_id", "plan_date", ("plan_date", "content", "status", "result", "patient_feedback", "create_time"), 8)
    inpatient_features = set(range(1, 10)) | set(range(11, 21)) | set(range(23, 34)) | set(range(41, 51)) | {54, 55, 56, 57, 68, 69, 76, 77}
    if number not in inpatient_features:
        return
    if not isinstance(encounter, Admission):
        if number in {23, 24, 25, 28, 30, 41, 42, 43, 44, 45, 46, 47, 68, 69}:
            bundle.data["missing_data"].append("未选择具体住院记录，未加载住院医嘱、执行和护理资料")
        return
    admission_id = encounter.admission_id
    bundle.data["inpatient_source_scope"] = {"admission_id": admission_id, "admission_status": encounter.status, "note": "下列住院来源仅限所选住院；记录状态不等同于实际治疗完成"}
    if user.user_role == "patient":
        # Staff-only working notes are not disclosed through a patient's AI explanation.
        if encounter.status == 2 and number in {1, 25, 54, 55, 56, 57}:
            append_rows(
                "discharge_summaries",
                DischargeSummary,
                "summary_id",
                "create_time",
                ("admission_id", "discharge_time", "discharge_diagnosis", "treatment_summary", "discharge_instruction", "follow_up_plan"),
                1,
                admission=True,
            )
        return

    order_query = (
        db.query(InpatientOrder)
        .options(selectinload(InpatientOrder.items))
        .filter(InpatientOrder.patient_id == patient.patient_id, InpatientOrder.admission_id == admission_id)
        .order_by(case((InpatientOrder.status.in_([1, 2]), 0), else_=1), InpatientOrder.create_time.desc(), InpatientOrder.order_id)
    )
    orders = order_query.limit(9).all()
    if len(orders) > 8:
        bundle.data["truncated_sources"].append({"source": "inpatient_orders", "limit": 8, "note": "优先已审核或执行中医嘱，未加载全部历史医嘱"})
    bundle.data["inpatient_orders"] = [
        add(
            "inpatient-order:" + item.order_id,
            "住院医嘱",
            {
                "order_id": item.order_id,
                "admission_id": admission_id,
                **{name: getattr(item, name) for name in ("order_type", "category", "status", "priority", "start_time", "stop_time", "note")},
                "status_meaning": {0: "新开待审核", 1: "已审核", 2: "执行中", 3: "已停止", 4: "已撤销"}.get(item.status, "未知"),
                "items": [
                    {name: getattr(line, name) for name in ("item_name", "item_type", "item_id_ref", "dose", "unit", "frequency", "route", "days", "quantity", "note")} for line in item.items[:20]
                ],
                "items_truncated": len(item.items) > 20,
                "dose_note": "dose 为医嘱原始文本，unit 可能是发药单位；不进行解析推断或自动剂量换算",
            },
            item.create_time,
        )
        for item in orders[:8]
    ]
    executions = (
        db.query(OrderExecution)
        .join(InpatientOrder)
        .filter(InpatientOrder.patient_id == patient.patient_id, InpatientOrder.admission_id == admission_id)
        .order_by(OrderExecution.planned_time.desc())
        .limit(17)
        .all()
    )
    if len(executions) > 16:
        bundle.data["truncated_sources"].append({"source": "order_executions", "limit": 16, "note": "其余执行未纳入本次快照"})
    bundle.data["order_executions"] = [
        add(
            "order-execution:" + str(item.execution_id),
            "医嘱执行记录",
            {
                "order_id": item.order_id,
                "planned_time": item.planned_time,
                "execution_time": item.execution_time,
                "status": item.status,
                "status_meaning": {0: "待执行", 1: "已记录执行", 2: "已跳过", 3: "已停止"}.get(item.status, "未知"),
                "note": item.note,
            },
            item.execution_time or item.planned_time,
        )
        for item in executions[:16]
    ]
    administrations = (
        db.query(MedicationAdministration)
        .join(InpatientOrder, MedicationAdministration.order_id == InpatientOrder.order_id)
        .filter(MedicationAdministration.patient_id == patient.patient_id, InpatientOrder.admission_id == admission_id)
        .order_by(MedicationAdministration.verified_at.desc())
        .limit(13)
        .all()
    )
    if len(administrations) > 12:
        bundle.data["truncated_sources"].append({"source": "medication_administrations", "limit": 12, "note": "其余给药核对未纳入快照"})
    bundle.data["medication_administrations"] = [
        add(
            "medication-administration:" + item.administration_id,
            "给药核对记录",
            {
                "order_id": item.order_id,
                "execution_id": item.execution_id,
                "status": item.status,
                "verified_at": item.verified_at,
                "administration_time": item.administration_time,
                "recorded_as_administered": item.status == 2 and item.administration_time is not None,
                "note": item.note,
                "status_note": "扫码核对通过不等同于已给药，只有已给药状态且有实际时间时才标记已记录给药",
            },
            item.administration_time or item.verified_at,
        )
        for item in administrations[:12]
    ]

    if number in {1, 8, 23, 24, 25, 26, 28, 30, 47, 68, 76, 77}:
        append_rows("progress_notes", ProgressNote, "note_id", "record_time", ("admission_id", "note_date", "content", "record_time"), 4, admission=True)
        append_rows("ward_rounds", WardRound, "round_id", "round_time", ("admission_id", "round_type", "content", "round_time"), 4, admission=True)
        append_rows(
            "discharge_summaries",
            DischargeSummary,
            "summary_id",
            "create_time",
            ("admission_id", "discharge_time", "discharge_diagnosis", "treatment_summary", "discharge_instruction", "follow_up_plan", "discharge_status"),
            1,
            admission=True,
        )
    if number in {1, 8, 19, 24, 25, 30, 41, 42, 43, 44, 45, 46, 47, 48, 50, 76, 77}:
        append_rows(
            "nursing_records",
            NursingRecord,
            "record_id",
            "record_time",
            ("admission_id", "record_time", "consciousness", "temperature", "pulse", "respiration", "blood_pressure", "spo2", "intake", "output", "skin_condition", "drainage", "note"),
            8,
            admission=True,
        )
        append_rows(
            "completed_nursing_assessments",
            NursingAssessment,
            "assessment_id",
            "update_time",
            ("admission_id", "adl_score", "pressure_ulcer_risk", "fall_risk", "consciousness", "nutrition_risk", "note", "status", "update_time"),
            3,
            admission=True,
            extra_filters=(NursingAssessment.status == 1,),
        )
        append_rows("nursing_plans", NursingPlan, "plan_id", "update_time", ("admission_id", "nursing_diagnosis", "goal", "measures", "status", "update_time"), 4, admission=True)
        bundle.data["nursing_assessment_limitations"] = "评估分值和风险标记来自既有护理记录，未提供量表版本或完整逐项答案时不重新计算评分"
    if number in {1, 41, 42, 43, 47, 48, 50, 76, 77}:
        append_rows(
            "critical_care_records",
            CriticalCareRecord,
            "record_id",
            "record_time",
            ("admission_id", "record_time", "consciousness", "gcs_score", "oxygen_support", "blood_pressure", "pulse", "spo2", "urine_output", "note"),
            5,
            admission=True,
        )
        append_rows(
            "recorded_icu_scores", IcuScoreRecord, "score_id", "assess_time", ("admission_id", "score_type", "scene", "total_score", "detail_json", "interpretation", "assess_time"), 5, admission=True
        )
        bundle.data["score_provenance_note"] = "评分是已保存的院内计算或评估记录，不是本次 AI 重新计算的风险概率，临床适用性仍需核实"
    if number in {27, 28, 30, 68, 69}:
        append_rows(
            "medical_record_homes",
            MedicalRecordHome,
            "home_id",
            "update_time",
            ("admission_id", "admission_diagnosis", "discharge_diagnosis", "other_diagnosis", "operation_summary", "complication", "status", "submit_time", "total_fee"),
            1,
            admission=True,
        )
    if number == 69:
        append_rows(
            "inpatient_charges",
            InpatientCharge,
            "charge_id",
            "create_time",
            ("admission_id", "item_name", "item_type", "quantity", "unit_price", "total_amount", "charge_date", "related_order_id", "status", "refunded_time", "refund_reason"),
            50,
            admission=True,
        )
