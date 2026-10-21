"""Strict complete-wire/JSON protocol; the caller supplies current DB authority."""

import hashlib
import json

from fastapi import HTTPException

from app.ai.research_cohort_contract import canonical_json
from app.ai.research_cohort_draft import MAX_BYTES, ResearchCohortDraft, checked_source, citation_catalog, digest, validate_draft
from app.ai.research_cohort_prompt import instructions_for


def _object(pairs):
    value = {}
    for key, child in pairs:
        if key in value:
            raise ValueError("Duplicate JSON key")
        value[key] = child
    return value


def _nonfinite(value):
    raise ValueError("Nonfinite JSON scalar is forbidden")


def parse_draft_json(raw, source):
    try:
        if type(raw) is bytes:
            if len(raw) > MAX_BYTES:
                raise HTTPException(413, "完整研究模型回执超过8MiB")
            raw = raw.decode("utf-8", errors="strict")
        if type(raw) is not str or not 0 < len(raw.encode("utf-8")) <= MAX_BYTES:
            raise ValueError("A complete nonempty UTF8 JSON document is required")
        value = json.loads(raw, object_pairs_hook=_object, parse_constant=_nonfinite)
        return validate_draft(value, source)
    except (ValueError, TypeError, UnicodeError, RecursionError) as exc:
        raise HTTPException(409, "研究模型回执不是闭合、唯一键的完整UTF8 JSON") from exc


def model_input(source, question=None):
    source = checked_source(source)
    if source["external_model_use"] != "recorded_permitted":
        raise HTTPException(403, "项目未明确记录模型处理许可；纯协议不替代当前逐患者授权")
    try:
        if question is not None and (type(question) is not str or len(question) > 2000 or len(question.encode("utf-8")) > 8000):
            raise ValueError("A bounded scalar question is required")
    except (ValueError, UnicodeError) as exc:
        raise HTTPException(422, "研究问题须为可空的2000码点/8000UTF8以内原字符串") from exc
    return {"research_source": source, "source_projection_hash": digest(source), "citation_catalog": citation_catalog(source), "question": question}


def model_wire(source, question, task_prompt):
    """Actual complete logical model message, all-or-refuse before HTTP.

    Transport-specific JSON envelopes must be bounded again after construction.
    The exact arbitrary current versioned Task is accepted, never default-only.
    """
    instructions = instructions_for(task_prompt)
    value = {"instructions": instructions, "input": model_input(source, question), "response_schema": ResearchCohortDraft.model_json_schema()}
    encoded = canonical_json(value).encode("utf-8")
    if len(encoded) > MAX_BYTES:
        raise HTTPException(413, "完整研究Source、问题、Prompt与输出schema超过8MiB，未裁剪")
    return value, hashlib.sha256(instructions.encode("utf-8")).hexdigest()
