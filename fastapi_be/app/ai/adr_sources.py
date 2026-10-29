"""Recorded ADR signals and explicit handling outcomes, without inferred onset or drug allergy."""

from sqlalchemy.orm import selectinload

from app.adr_status import describe_adr_status
from app.models import AdverseReaction

ADR_SOURCE_FEATURES = frozenset({1, 5, 6, 7, 8, 11, 14, 17, 18, 19, 20, 48, 49})


def attach_adr_sources(db, user, spec, patient, bundle, add, selected, bounded):
    if user.user_role == "patient" or spec.number not in ADR_SOURCE_FEATURES:
        return
    rows = bounded(
        db.query(AdverseReaction)
        .options(selectinload(AdverseReaction.pharmaceutical))
        .filter_by(patient_id=patient.patient_id)
        .order_by(AdverseReaction.report_time.desc(), AdverseReaction.reaction_id.desc()),
        8,
        "ADR上报与处理记录",
        "reaction_id",
        "reaction_id",
    )
    bundle.data["adr_sources"] = {
        "scope_note": "所选患者的ADR上报记录。对应就诊、给药执行和症状发生时间尚未记录；药物过敏请另行核实。",
        "encounter_assignment": "not_recorded",
        "administration_link": "not_recorded",
        "symptom_onset_time": "not_recorded",
        "reports": [
            add(
                "adr:" + str(row.reaction_id),
                "ADR上报与原处理记录",
                {
                    "reaction_id": row.reaction_id,
                    "pharmaceutical_id": row.pharmaceutical_id,
                    "pharmaceutical_name": row.pharmaceutical.name if row.pharmaceutical else None,
                    "current_drug_catalog_status": row.pharmaceutical.status if row.pharmaceutical else None,
                    "drug_reference_resolved": row.pharmaceutical is not None,
                    "reported_symptom": row.symptom,
                    "recorded_severity": row.severity,
                    "report_time": row.report_time,
                    "recorded_note": row.note,
                    **describe_adr_status(row),
                    "explicitly_selected": selected.get("reaction_id") is not None and selected["reaction_id"].reaction_id == row.reaction_id,
                    "onset_and_exposure_note": "上报严重度1轻度、2中度、3重度，未知值保留未知；原记录未提供独立起病、首剂、末剂、停药/再暴露时间或剂量，不推断时间关联或计算因果评分",
                },
                row.status_reviewed_at or row.report_time,
            )
            for row in rows
        ],
    }
    if spec.number in {14, 19}:
        bundle.data["missing_data"].append("ADR与药物过敏资料需分别核查；缺少起病、暴露、停药/再暴露时间及因果评估，不把上报、确认标记或模型信号写成已证实因果或过敏")
    if any(describe_adr_status(row)["recorded_state"] in {"legacy_ambiguous", "unknown"} for row in rows):
        bundle.data["missing_data"].append("ADR存在未核实的历史状态或状态组合，不能将其当已处理或已排除")
