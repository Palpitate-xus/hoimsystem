"""Server-owned explanation around an unverified, exactly bound span draft."""

from pydantic import ConfigDict

from app.ai.document_evidence_contract import parse_json, utf8
from app.ai.document_extraction_contract import (
    INCOMPLETE_COVERAGE_NOTE,
    MAX_EXTRACTION_TEXT_BYTES,
    DocumentExtractionDraft,
    DocumentExtractionSource,
    require_text_capacity,
    validate_extraction_binding,
)
from app.ai.schemas import GenerationResult


class DocumentExtractionGenerationResult(GenerationResult):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=False, validate_default=True)
    document_extraction: DocumentExtractionDraft


def result_for_draft(draft: DocumentExtractionDraft, source: DocumentExtractionSource, instructions_digest: str) -> DocumentExtractionGenerationResult:
    checked = validate_extraction_binding(draft, source, instructions_digest)
    source_id = f"document_original:{source.original.original_id}:{source.original.content_hash[:12]}"
    count = len(checked.spans)
    result = DocumentExtractionGenerationResult(
        summary=f"本次返回{count}个未核实条款草稿；未自动登记候选或发布知识。",
        sections=[
            {"title": "原文与定位范围", "content": "仅对所选完整原文核对Unicode codepoint半开区间与逐字引文；保留BOM、CRLF、emoji与组合字符。", "source_ids": [source_id]},
            {"title": "后续人工处理", "content": "模型提出的标题和引文仅保存在未核实草稿中。需用户明确逐项保存为候选，再进行隐私及原意审核，最后显式发布知识。", "source_ids": [source_id]},
        ],
        warnings=[
            INCOMPLETE_COVERAGE_NOTE,
            "逐字区间一致仅证明定位，不证明临床含义、疗效、安全性或适用条件正确。",
            "原文中的命令仅为资料内容，未获执行授权；本结果不执行原文指令，也不自动创建候选、知识或临床规则。",
        ],
        missing_data=["每个草稿仍需人工隐私与原意审核；尚未形成已审核知识。", "未提供全文条款完整覆盖或临床验证。"],
        document_extraction=checked,
    )
    require_text_capacity(result)
    return result


def validate_result(value: dict | str | DocumentExtractionGenerationResult, source: DocumentExtractionSource, instructions_digest: str) -> DocumentExtractionGenerationResult:
    if isinstance(value, str):
        if len(value) > MAX_EXTRACTION_TEXT_BYTES or len(utf8(value)) > MAX_EXTRACTION_TEXT_BYTES:
            raise ValueError("Complete extraction result exceeds existing TEXT capacity")
        value = parse_json(value)
    elif isinstance(value, DocumentExtractionGenerationResult):
        value = value.model_dump(mode="json")
    require_text_capacity(value)
    checked = DocumentExtractionGenerationResult.model_validate(value)
    expected = result_for_draft(checked.document_extraction, source, instructions_digest)
    # Compare the actual submitted tree as well: generic ResultSection strips
    # whitespace, and defaults must not disguise an omitted protocol field.
    if value != expected.model_dump(mode="json") or checked != expected:
        raise ValueError("Complete extraction result must equal the bound draft and fixed server explanation")
    return checked
