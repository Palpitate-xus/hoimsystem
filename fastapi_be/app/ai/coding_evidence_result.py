"""Server-owned explanation around an explicitly unreviewed model draft."""

from pydantic import ConfigDict

from app.ai.coding_evidence_contract import CodingEvidenceDraft, structural_counts, validate_draft
from app.ai.schemas import GenerationResult

WARNINGS = [
    "以下逐项意见均为待人工复核的模型主张；逐字引文一致不代表医学解释、编码适用性或主诊断已确认。",
    "本功能没有执行官方DRG/DIP分组、测算支付金额、增加诊断或修改业务编码。",
]
MISSING = [
    "当前字典发行版本未提供。",
    "已记录分组所采用的完整历史规则依据未提供；当前本地前缀规则不是官方分组器。",
    "患者直接标识最小化不保证匿名；引文位置对应本次模型可见投影，不对应私有原文位置。",
]


class CodingGenerationResult(GenerationResult):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=False)
    coding_analysis: CodingEvidenceDraft


def result_for_draft(source, draft, projection_hash):
    validate_draft(source, draft, projection_hash)
    counts = structural_counts(source)
    assessed = {key: 0 for key in ("support_claim", "conflict_claim", "insufficient_evidence", "clarification_requested")}
    for claim in draft.claims:
        assessed[claim.model_assessment] += 1
    return CodingGenerationResult(
        summary=f"已形成{counts['binding_count']}项已记录编码的待复核模型意见，尚未作临床或编码确认。",
        sections=[
            {
                "title": "完整记录结构",
                "content": (
                    f"本件共有{counts['binding_count']}项绑定；其中明确记录的主诊断标记{counts['observed_primary_diagnosis_binding_count']}项，"
                    f"未知或无效主诊断标记{counts['unknown_primary_flag_count']}项，未知编码类型{counts['unknown_binding_kind_count']}项。"
                    "记录数量和标记不证明编码正确或文书支持。"
                ),
                "source_ids": [source["source_id"]],
            },
            {
                "title": "模型主张分布，均待人工核实",
                "content": (
                    f"模型主张支持{assessed['support_claim']}项、冲突{assessed['conflict_claim']}项、证据不足{assessed['insufficient_evidence']}项、"
                    f"需澄清{assessed['clarification_requested']}项。请逐项查看原文投影引文及待核实问题。"
                ),
                "source_ids": [source["source_id"]],
            },
        ],
        warnings=list(WARNINGS),
        missing_data=[*MISSING, *["病案文书字段未记录：" + key for key in source.get("missing_document_fields", [])]],
        coding_analysis=draft,
    )


def validate_result(value, source, projection_hash):
    checked = CodingGenerationResult.model_validate(value)
    expected = result_for_draft(source, checked.coding_analysis, projection_hash)
    if checked.model_dump(mode="json") != expected.model_dump(mode="json"):
        raise ValueError("The fixed server explanation differs from the complete draft and recorded structure")
    return checked
