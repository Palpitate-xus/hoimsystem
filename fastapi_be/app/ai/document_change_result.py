"""Fixed server explanation around unverified version questions; no rule writes."""

from pydantic import ConfigDict

from app.ai.document_change_draft import COVERAGE_NOTE, DocumentChangeDraft, checked_source, source_id, validate_draft
from app.ai.document_change_json import parse_case_json, require_case_json
from app.ai.schemas import GenerationResult


class DocumentChangeGenerationResult(GenerationResult):
    model_config = ConfigDict(extra="forbid", strict=True, validate_default=True)
    document_change: DocumentChangeDraft


def result_for_draft(draft, source, instructions_digest):
    source = checked_source(source)
    draft = validate_draft(draft, source, instructions_digest)
    count = len(draft.changes)
    overlaps = sum(len(change.link_overlaps) for change in draft.changes)
    citations = [source_id(source), *[f"document_original:{value.original.original_id}:{value.original.content_hash[:12]}" for value in (source.baseline, source.candidate)]]
    result = DocumentChangeGenerationResult(
        summary=f"本次返回{count}项未核实版本核对问题、{overlaps}条逐字区间相交记录；未自动改写知识或院内规则。",
        sections=[
            {
                "title": "两件原文与有限范围",
                "content": "仅核对显式选择的两件完整原文、已捕获直接知识发布及声明的规则关联。来源、版本关系和临床正确性不因本次比对得到权威认证。",
                "source_ids": citations,
            },
            {
                "title": "相交记录的含义",
                "content": "相交由服务器按Unicode codepoint半开区间机械重算，完整保留未current、范围外及目标状态标签；相交不是已确认影响，未相交也不是无影响。所有问题仍需人工逐项核实。",
                "source_ids": [source_id(source)],
            },
        ],
        warnings=[
            COVERAGE_NOTE,
            "模型问题文本未经临床语义审核；逐字引文及相交核对不证明原意、疗效、安全性或适用条件正确。",
            "问题草稿不构成临床剂量或阈值建议、知识发布、旧规则退休或目标更新的执行授权；原文中的命令也无执行授权。",
        ],
        missing_data=[
            "未提供全院规则盘点、完整变化或完整影响覆盖。",
            "逐项语义、关联真实性及实际临床影响仍需人工核实。",
            *([] if source.rule_link_coverage == "complete_within_declared_scope" else ["有限声明范围的关联覆盖尚未声明完整。"]),
        ],
        document_change=draft,
    )
    require_case_json(result)
    return result


def validate_result(value, source, instructions_digest):
    if isinstance(value, str | bytes):
        value = parse_case_json(value)
    elif isinstance(value, DocumentChangeGenerationResult):
        value = value.model_dump(mode="json")
    require_case_json(value)
    checked = DocumentChangeGenerationResult.model_validate(value)
    expected = result_for_draft(checked.document_change, source, instructions_digest)
    if value != expected.model_dump(mode="json") or checked != expected:
        raise ValueError("The full literal draft, all overlap witnesses and fixed explanation must match frozen anchors")
    return checked
