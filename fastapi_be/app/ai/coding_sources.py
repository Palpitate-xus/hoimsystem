"""Recorded case-home codes and local dictionary candidates; this module never binds or groups."""

import re

from fastapi import HTTPException
from sqlalchemy import or_

from app.ai.governance import digest, encode_json
from app.models import Admission, DrgGrouping, DrgRule, HomeIcdBinding, Icd10Diagnosis, Icd10Operation, MedicalRecordHome


def dictionary_entry(row, kind: str) -> dict:
    fields = {name: getattr(row, name) for name in ("code", "name", "category", "status", "update_time")}
    reference = row.diagnosis_id if kind == "diagnosis" else row.operation_id
    return {"source_id": f"icd:{kind}:{reference}:{digest(fields)[:12]}", "kind": kind, **fields}


def attach_coding_sources(db, user, spec, patient, encounter, bundle, add, selected, bounded, authorize) -> None:
    if spec.number not in {27, 28, 30, 68, 69}:
        return
    chosen = selected.get("home_id")
    if chosen is not None:
        admission = db.get(Admission, chosen.admission_id)
        if admission is None or admission.patient_id != patient.patient_id:
            raise HTTPException(422, "病案首页与住院患者关联不一致")
        if encounter is not None and (not isinstance(encounter, Admission) or chosen.admission_id != encounter.admission_id):
            raise HTTPException(422, "病案首页与所选住院不一致")
        authorize(db, user, patient.patient_id, spec.category, admission.admission_id)
        query = db.query(MedicalRecordHome).filter_by(home_id=chosen.home_id, patient_id=patient.patient_id)
    elif isinstance(encounter, Admission):
        query = db.query(MedicalRecordHome).filter_by(admission_id=encounter.admission_id, patient_id=patient.patient_id)
    else:
        if spec.number in {28, 68}:
            bundle.data["missing_data"].append("未选择病案首页或对应住院，未加载首页编码和分组资料")
        return
    homes = bounded(query.order_by(MedicalRecordHome.update_time.desc(), MedicalRecordHome.home_id), 1, "病案首页", "home_id", "home_id")
    ids = [row.home_id for row in homes]
    fields = ("home_id", "admission_id", "admission_diagnosis", "discharge_diagnosis", "other_diagnosis", "operation_summary", "complication", "status", "submit_time", "total_fee")
    bundle.data["medical_record_homes"] = [add("medical-record-home:" + row.home_id, "病案首页原始记录", {name: getattr(row, name) for name in fields}, row.update_time) for row in homes]
    bindings = db.query(HomeIcdBinding).filter(HomeIcdBinding.home_id.in_(ids)).order_by(HomeIcdBinding.binding_id).limit(101).all()
    if len(bindings) > 100:
        bundle.data["truncated_sources"].append({"source": "首页编码绑定", "limit": 100, "note": "编码清单未完整纳入，不能据此判断无其他编码"})
    dictionaries = {}
    for kind, model in (("diagnosis", Icd10Diagnosis), ("operation", Icd10Operation)):
        codes = {row.icd_code for row in bindings[:100] if row.kind == kind}
        dictionaries.update({(kind, row.code): row for row in db.query(model).filter(model.code.in_(codes)).all()})
    bundle.data["home_icd_bindings"] = []
    for row in bindings[:100]:
        entry = dictionaries.get((row.kind, row.icd_code))
        state = "entry_unavailable" if not entry else "entry_inactive" if entry.status != 1 else "stored_name_differs" if row.icd_name != entry.name else "matches_current_dictionary"
        bundle.data["home_icd_bindings"].append(
            add(
                "home-icd:" + str(row.binding_id),
                "首页已绑定编码",
                {
                    "binding_id": row.binding_id,
                    "home_id": row.home_id,
                    "kind": row.kind,
                    "icd_code": row.icd_code,
                    "stored_name": row.icd_name,
                    "is_primary": row.is_primary,
                    "code_time": row.code_time,
                    "remark": row.remark,
                    "current_dictionary_state": state,
                    "current_dictionary_name": entry.name if entry else None,
                },
                row.code_time,
            )
        )
    if spec.number == 68:
        groups = (
            db.query(DrgGrouping).filter(DrgGrouping.patient_id == patient.patient_id, DrgGrouping.home_id.in_(ids)).order_by(DrgGrouping.create_time.desc(), DrgGrouping.grouping_id).limit(5).all()
        )
        bundle.data["recorded_drg_groups"] = [
            add(
                "drg-group:" + row.grouping_id,
                "已记录DRG或DIP分组",
                {
                    name: getattr(row, name)
                    for name in ("grouping_id", "home_id", "rule_id", "group_code", "payment_method", "diagnosis", "diagnosis_codes", "procedure_codes", "grouping_method", "create_time")
                },
                row.create_time,
            )
            for row in groups
        ]
        rules = db.query(DrgRule).filter(DrgRule.rule_id.in_({row.rule_id for row in groups if row.rule_id is not None})).order_by(DrgRule.rule_id).all()
        bundle.data["current_linked_drg_rules"] = [
            add(
                "drg-rule:" + str(row.rule_id) + ":" + row.version,
                "当前关联分组规则",
                {
                    name: getattr(row, name)
                    for name in ("rule_id", "group_code", "group_name", "payment_method", "diagnosis_prefix", "procedure_prefix", "version", "status", "effective_from", "effective_to", "update_time")
                },
                row.update_time,
                kind="rule",
            )
            for row in rules
        ]
        bundle.data["drg_comparison_scope"] = "关联规则是当前数据库版本；旧分组未冻结原规则版本时，不能宣称此版本就是分组当时依据。不推断新诊断，不按结算收益选择编码。"


def local_icd_candidates(db, context: dict, task_input: dict) -> tuple[dict, list[dict]]:
    """Offer bounded literal matches from active hospital dictionaries, with exact source entries."""
    values = [task_input.get("icd_query", "")]
    values.extend(context.get("current_confirmed_diagnoses", []))
    for home in context.get("medical_record_homes", []):
        values.extend(home.get(field) or "" for field in ("discharge_diagnosis", "other_diagnosis", "operation_summary"))
    terms = list(dict.fromkeys(term.strip() for value in values if isinstance(value, str) for term in re.split(r"[,，;；、\n]", value) if 2 <= len(term.strip()) <= 80))[:12]
    candidates, evidence, truncated = [], [], False
    if terms:
        for kind, model in (("diagnosis", Icd10Diagnosis), ("operation", Icd10Operation)):
            filters = [condition for term in terms for condition in (model.name.contains(term, autoescape=True), model.code.contains(term.upper(), autoescape=True))]
            rows = db.query(model).filter(model.status == 1, or_(*filters)).order_by(model.code).limit(26).all()
            truncated = truncated or len(rows) > 25
            for row in rows[:25]:
                item = dictionary_entry(row, kind)
                candidates.append(item)
                evidence.append({"source_id": item["source_id"], "kind": "dictionary", "title": "院内有效编码字典条目", "content": encode_json(item)})
    return {
        "candidates": candidates,
        "truncated": truncated,
        "search_terms": terms,
        "matching_method": "literal_name_or_code",
        "changes_written": [],
        "scope_note": "仅院内当前有效字典的文字匹配候选，不是确诊、最终编码或自动绑定结果；未命中需编码人员补充检索词",
    }, evidence
