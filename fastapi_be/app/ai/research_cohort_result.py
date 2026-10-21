"""Server-built result: original deterministic outcomes and separate questions."""

from fastapi import HTTPException

from app.ai.research_cohort_contract import canonical_json
from app.ai.research_cohort_draft import MAX_BYTES, checked_source, digest, validate_draft

SUMMARY = "本次只核对明确有限患者集合的原记录谓词；模型提出的部分问题须人工复核，不更改纳排AST、原三值结果或患者集合，不自动导出。"
LIMITATIONS = (
    "模型评论是待核问题，不是研究入组、诊断、因果、临床效果或数据完整性结论。",
    "技术治理和人工授权声明不自动证明伦理审批、同意法律效力、研究资质或匿名。",
    "当前研究权限和模型处理许可须在外发及接受结果时逐项重核；超级管理员没有患者正文旁路。",
)


def result_for_draft(draft, source):
    source = checked_source(source)
    questions = validate_draft(draft, source)
    value = {
        "schema_version": "research_cohort_result_v1",
        "research_source_id": source["source_id"],
        "source_projection_hash": digest(source),
        "summary": SUMMARY,
        "deterministic_evaluation": {
            "rule_id": source["recipe"]["rule_id"],
            "criteria_hash": digest(source["criteria"]),
            "counts": source["counts"],
            "outcomes": [{key: outcome[key] for key in ("patient_token", "truth", "interpretation")} for outcome in source["outcomes"]],
        },
        "question_draft": questions,
        "limitations": [*source["limitations"], *LIMITATIONS],
        "requires_human_review": True,
        "no_business_write": True,
        "no_automatic_export": True,
    }
    if len(canonical_json(value).encode("utf-8")) > MAX_BYTES:
        raise HTTPException(413, "完整研究结果超过8MiB，未截断问题或确定结果")
    return value


def validate_result(value, source):
    try:
        if type(value) is not dict or canonical_json(value) != canonical_json(result_for_draft(value["question_draft"], source)):
            raise ValueError("The server-owned counts, outcomes, limitations or complete draft differ")
        return value
    except (ValueError, KeyError, TypeError, UnicodeError) as exc:
        raise HTTPException(409, "研究完整结果与原确定统计、三值结果及待核草稿不一致") from exc
