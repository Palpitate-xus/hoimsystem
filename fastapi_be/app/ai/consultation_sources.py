"""Patient-level referral and MDT records, kept separate from confirmed encounter diagnoses."""

import json

from app.models import Department, MdtCase, Referral


def department_references(value):
    """Accept actual CSV/JSON identifiers; never extract numbers from prose or invent departments."""
    if value is None or value == "":
        return [], 0
    if not isinstance(value, str) or len(value) > 1000:
        return [], 1
    text = value.strip()
    try:
        parts = json.loads(text) if text.startswith("[") else text.split(",")
    except (ValueError, TypeError):
        return [], 1
    if not isinstance(parts, list) or len(parts) > 50:
        return [], 1
    ids, invalid = [], 0
    for part in parts:
        if isinstance(part, str):
            part = part.strip()
            if not part.isascii() or not part.isdigit() or len(part) > 10 or str(int(part)) != part:
                invalid += 1
                continue
            part = int(part)
        if type(part) is not int or not 0 < part <= 2147483647:
            invalid += 1
        elif part not in ids:
            ids.append(part)
    return ids, invalid


def attach_consultation_sources(db, user, spec, patient, encounter, bundle, add, selected, bounded):
    if user.user_role == "patient" or spec.number not in {1, 5, 7, 9}:
        return
    referrals = bounded(db.query(Referral).filter_by(patient_id=patient.patient_id).order_by(Referral.create_time.desc(), Referral.referral_id.desc()), 6, "转诊记录", "referral_id", "referral_id")
    cases = bounded(db.query(MdtCase).filter_by(patient_id=patient.patient_id).order_by(MdtCase.create_time.desc(), MdtCase.mdt_id.desc()), 6, "MDT记录", "mdt_id", "mdt_id")
    parsed = {row.mdt_id: department_references(row.department_ids) for row in cases}
    identifiers = {value for row in referrals for value in (row.from_department_id, row.to_department_id) if value is not None}
    identifiers.update(value for ids, _ in parsed.values() for value in ids)
    departments = {row.department_id: row for row in db.query(Department).filter(Department.department_id.in_(identifiers)).all()}

    def department(identifier):
        row = departments.get(identifier)
        return {"department_id": identifier, "name": row.name if row else None, "exists_in_current_directory": row is not None}

    envelope = {
        "scope_note": "仅本患者的有限转诊/MDT历史及明确所选记录；原记录未注明对应就诊，不按日期归属本次门诊或住院。原申请诊断、结果和审批意见不是本次已确认诊断；科室名称取当前目录，不推断人员资质、可用时段或已实际接诊",
        "encounter_assignment": "not_recorded",
        "referrals": [],
        "mdt_cases": [],
    }
    for row in referrals:
        envelope["referrals"].append(
            add(
                "referral:" + str(row.referral_id),
                "转诊申请与原审批记录",
                {
                    "referral_id": row.referral_id,
                    "from_department": department(row.from_department_id),
                    "to_department": department(row.to_department_id),
                    "recorded_type": row.referral_type,
                    "recorded_reason": row.reason,
                    "recorded_status": row.status,
                    "recorded_status_meaning": {0: "待审批/待接收标记", 1: "审批通过/接收标记", 2: "退回标记"}.get(row.status, "未知"),
                    "created_at": row.create_time,
                    "reviewed_at": row.review_time,
                    "recorded_review_note": row.review_note,
                    "review_identity_recorded": row.reviewer_id is not None and row.review_time is not None,
                    "encounter_assignment": "not_recorded",
                    "explicitly_selected": selected.get("referral_id") is not None and selected["referral_id"].referral_id == row.referral_id,
                    "definition_note": "原状态1可能由审批接口写入，不证明已到达转入科室、已会诊或已完成治疗；审批时间不作实际接诊时间。原转诊类型未知编码不推测上下转含义",
                },
                row.review_time or row.create_time,
            )
        )
    for row in cases:
        ids, malformed = parsed[row.mdt_id]
        mapped = [department(identifier) for identifier in ids]
        envelope["mdt_cases"].append(
            add(
                "mdt:" + str(row.mdt_id),
                "MDT申请、审批与原结果记录",
                {
                    "mdt_id": row.mdt_id,
                    "recorded_diagnosis": row.diagnosis,
                    "participating_departments": mapped,
                    "unparsed_department_tokens": malformed,
                    "missing_department_count": sum(not item["exists_in_current_directory"] for item in mapped),
                    "recorded_status": row.status,
                    "recorded_status_meaning": {0: "待审批", 1: "会诊中", 2: "已完成标记", 3: "已退回"}.get(row.status, "未知"),
                    "recorded_result": row.result,
                    "result_on_completed_case": row.status == 2 and bool((row.result or "").strip()),
                    "created_at": row.create_time,
                    "reviewed_at": row.review_time,
                    "recorded_review_note": row.review_note,
                    "review_identity_recorded": row.reviewer_id is not None and row.review_time is not None,
                    "encounter_assignment": "not_recorded",
                    "explicitly_selected": selected.get("mdt_id") is not None and selected["mdt_id"].mdt_id == row.mdt_id,
                    "definition_note": "原初步诊断不作为本次确认诊断；结果字段可能在未完成或退回状态下已有内容，保留原状态，不作最终意见。原表未记录实际会诊时刻、个体参会确认及结果签署/诊断复核，完成标记不等同已核验治疗方案",
                },
                row.review_time or row.create_time,
            )
        )
        if malformed or any(not item["exists_in_current_directory"] for item in mapped):
            bundle.data["missing_data"].append("MDT科室引用存在无法解析或目录缺失项；未编造科室名，参与范围不完整")
    bundle.data["consultation_sources"] = envelope
    if spec.number == 9:
        bundle.data["missing_data"].append("转诊/MDT缺少就诊归属、实际接诊或会诊时间、个体参会与结果签署核验；不能仅据审批或完成状态认定治疗建议已确认")
