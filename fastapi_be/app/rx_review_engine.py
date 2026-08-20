"""审方规则引擎：开方/审方时自动执行的用药安全检查。

规则由药师在系统中维护（rxReviewRule CRUD），不预置数据。
检查类型：
- interaction   两药配伍禁忌（drug_a × drug_b）
- contraindication 单药禁忌关键词（drug_a 命中药品名即触发）
- dose          剂量范围（对药品 drug_a 的每次/每日剂量）
- duplicate     重复用药（同成分 drug_a 关键词的两药同开）
- allergy_key   过敏拦截补充关键词（与 patient.allergy_history 匹配）
"""
import re

from sqlalchemy.orm import Session

from app.models import PrescriptionReviewRule


def _match_drug(name: str, keyword: str | None) -> bool:
    """关键词匹配：空关键词不匹配；支持中英文药名（子串含前缀匹配）。"""
    if not keyword:
        return False
    return keyword.strip().lower() in (name or "").lower()


def check_prescription(db: Session, items: list[dict], allergy_history: str | None = None) -> list[dict]:
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

        if hit:
            findings.append({
                "severity": rule.severity,
                "rule_id": rule.rule_id,
                "type": rule.rule_type,
                "message": rule.message,
            })

    # severity 排序：禁止(3) 在前
    findings.sort(key=lambda f: -f["severity"])
    return findings


def has_blocking(findings: list[dict]) -> bool:
    return any(f["severity"] == 3 for f in findings)
