"""审方规则引擎：开方/审方时自动执行的用药安全检查。

规则由药师在系统中维护（rxReviewRule CRUD），不预置数据。
检查类型：
- interaction   两药配伍禁忌（drug_a × drug_b）
- contraindication 单药禁忌关键词（drug_a 命中药品名即触发）
- dose          剂量范围（对药品 drug_a 的每次/每日剂量）
- duplicate     重复用药（同成分 drug_a 关键词的两药同开）
- allergy_key   过敏拦截补充关键词（与 patient.allergy_history 匹配）
"""
import datetime
import json
import re

from sqlalchemy.orm import Session

from app.models import MedicalRecord, PrescriptionReviewRule, VitalSign


def _match_drug(name: str, keyword: str | None) -> bool:
    """关键词匹配：空关键词不匹配；支持中英文药名（子串含前缀匹配）。"""
    if not keyword:
        return False
    return keyword.strip().lower() in (name or "").lower()


def build_patient_context(db: Session, patient) -> dict:
    age = None
    if patient and patient.birthday:
        today = datetime.date.today()
        age = today.year - patient.birthday.year - ((today.month, today.day) < (patient.birthday.month, patient.birthday.day))
    profile = patient.clinical_profile if patient else None
    latest_vital = (
        db.query(VitalSign)
        .filter(VitalSign.patient_id == patient.patient_id)
        .order_by(VitalSign.check_time.desc())
        .first()
        if patient
        else None
    )
    record_diagnoses = (
        db.query(MedicalRecord.result)
        .filter(MedicalRecord.patient_id == patient.patient_id, MedicalRecord.result.isnot(None))
        .order_by(MedicalRecord.consultation_time.desc())
        .limit(20)
        .all()
        if patient
        else []
    )
    diagnoses = [row[0] for row in record_diagnoses if row[0]]
    labs = {}
    if profile:
        try:
            diagnoses.extend(json.loads(profile.diagnoses_json or "[]"))
        except (TypeError, ValueError):
            pass
        try:
            labs = json.loads(profile.labs_json or "{}")
        except (TypeError, ValueError):
            pass
    return {
        "age": age,
        "sex": patient.sex if patient else None,
        "weight": float(latest_vital.weight) if latest_vital and latest_vital.weight is not None else None,
        "pregnant": bool(profile.pregnant) if profile and profile.pregnant is not None else None,
        "egfr": float(profile.egfr) if profile and profile.egfr is not None else None,
        "hepatic_impairment": profile.hepatic_impairment if profile else 0,
        "diagnoses": diagnoses,
        "labs": labs,
    }


def _context_matches(condition: dict, context: dict) -> bool:
    try:
        checks = []
        for key in ("min_age", "max_age", "min_weight", "max_weight", "min_egfr", "max_egfr", "hepatic_min"):
            if key not in condition:
                continue
            context_key = "hepatic_impairment" if key == "hepatic_min" else key.split("_", 1)[1]
            value = context.get(context_key)
            if value is None:
                checks.append(False)
            elif key.startswith("min_") or key == "hepatic_min":
                checks.append(float(value) >= float(condition[key]))
            else:
                checks.append(float(value) <= float(condition[key]))
        if "pregnant" in condition:
            checks.append(context.get("pregnant") is condition["pregnant"])
        if condition.get("sex") is not None:
            checks.append(context.get("sex") == condition["sex"])
        if condition.get("diagnosis_keywords"):
            diagnosis_text = " ".join(context.get("diagnoses") or []).lower()
            checks.append(any(str(keyword).lower() in diagnosis_text for keyword in condition["diagnosis_keywords"]))
        for lab_name, bounds in (condition.get("labs") or {}).items():
            value = (context.get("labs") or {}).get(lab_name)
            if value is None:
                checks.append(False)
                continue
            if "min" in bounds:
                checks.append(float(value) >= float(bounds["min"]))
            if "max" in bounds:
                checks.append(float(value) <= float(bounds["max"]))
        return bool(checks) and all(checks)
    except (AttributeError, TypeError, ValueError):
        return False


def check_prescription(
    db: Session,
    items: list[dict],
    allergy_history: str | None = None,
    patient_context: dict | None = None,
) -> list[dict]:
    """对一组处方明细执行全部启用规则。

    items: [{"name": 药品名, "dosage": 每次剂量(float), "frequency": 频次中文, "number": 数量}, ...]
    返回: [{"severity": 1|2|3, "rule_id": n, "type": ..., "message": ...}]，severity=3 必须拦截
    """
    rules = db.query(PrescriptionReviewRule).filter(PrescriptionReviewRule.status == 1).all()
    findings: list[dict] = []

    freq_per_day = {"qd": 1, "bid": 2, "tid": 3, "qid": 4, "q8h": 3, "q6h": 4, "q12h": 2, "qn": 1, "prn": 1, "st": 1}

    def daily_dose(it: dict) -> float:
        freq = (it.get("frequency") or "").strip().lower()
        per_day = freq_per_day.get(freq)
        if per_day is None:
            digits = re.findall(r"\d+", freq)
            per_day = int(digits[0]) if digits else 1
        return float(it.get("dosage") or 0) * per_day

    for rule in rules:
        today = datetime.date.today()
        if rule.effective_from and today < rule.effective_from:
            continue
        if rule.effective_to and today > rule.effective_to:
            continue
        hit = False
        if rule.rule_type == "interaction":
            names = [it.get("name", "") for it in items]
            hit = any(_match_drug(n, rule.drug_a) for n in names) and any(_match_drug(n, rule.drug_b) for n in names)
        elif rule.rule_type == "contraindication":
            hit = any(_match_drug(it.get("name", ""), rule.drug_a) for it in items)
        elif rule.rule_type == "dose":
            for it in items:
                if not _match_drug(it.get("name", ""), rule.drug_a):
                    continue
                dose = it.get("dosage")
                if dose is None:
                    continue
                if rule.min_dose is not None and dose < float(rule.min_dose):
                    hit = True
                if rule.max_dose is not None and dose > float(rule.max_dose):
                    hit = True
                if rule.max_daily_dose is not None and daily_dose(it) > float(rule.max_daily_dose):
                    hit = True
        elif rule.rule_type == "duplicate":
            names = [it.get("name", "") for it in items]
            hits = sum(1 for n in names if _match_drug(n, rule.drug_a))
            hit = hits >= 2
        elif rule.rule_type == "allergy_key":
            history = (allergy_history or "").strip()
            if history and rule.drug_a:
                hit = _match_drug(history, rule.drug_a) and any(_match_drug(it.get("name", ""), rule.drug_a) for it in items)
        elif rule.rule_type == "context" and patient_context:
            try:
                condition = json.loads(rule.condition_json or "{}")
            except (TypeError, ValueError):
                condition = {}
            hit = (
                any(_match_drug(it.get("name", ""), rule.drug_a) for it in items)
                and _context_matches(condition, patient_context)
            )

        if hit:
            findings.append({
                "severity": rule.severity,
                "rule_id": rule.rule_id,
                "type": rule.rule_type,
                "message": rule.message,
                "source": rule.source,
                "version": rule.version,
            })

    # severity 排序：禁止(3) 在前
    findings.sort(key=lambda f: -f["severity"])
    return findings


def has_blocking(findings: list[dict]) -> bool:
    return any(f["severity"] == 3 for f in findings)
