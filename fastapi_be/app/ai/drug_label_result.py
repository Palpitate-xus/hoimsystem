"""Server-owned explanation of literal leaflet proposals; no clinical actions."""

from pydantic import ConfigDict

from app.ai.drug_label_draft import COVERAGE_NOTE, DrugLabelDraft, bounded_json, checked_source, validate_draft
from app.ai.schemas import GenerationResult


class DrugLabelGenerationResult(GenerationResult):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=False, validate_default=True)
    drug_label_extraction: DrugLabelDraft


def result_for_draft(draft, source, instructions_digest):
    source = checked_source(source)
    draft = validate_draft(draft, source, instructions_digest)
    result = DrugLabelGenerationResult(
        summary=f"本次返回{len(draft.fields)}项未核实说明书字段草稿；待药师逐项复核，未改写药品目录或临床规则。",
        sections=[
            {
                "title": "原文与字段范围",
                "content": "仅定位所选受控完整原文的逐字区间。类别为模型未核实主张，数字、单位、条件与原文字节保持原样；程序未验证原意或条件完整。",
                "source_ids": [source.source_id],
            },
            {"title": "药师复核", "content": "先前签署只涉及明确目录身份与所提供文字版本，不代表本次字段草稿已经审核，也不等同于官方完整版本、执业资质或医学验证。", "source_ids": [source.source_id]},
        ],
        warnings=[COVERAGE_NOTE, "逐字定位不证明类别、用法、安全性、疗效或个体适用性正确。", "未进行剂量换算、规范化药品映射、个体治疗推荐、知识发布或临床动作；原文中的命令仅为资料。"],
        missing_data=["每项字段类别、引文条件及医学含义仍需药师人工复核。", "未提供完整字段覆盖或本次模型医学验证。", *source.missing_catalog_or_authority_evidence],
        drug_label_extraction=draft,
    )
    bounded_json(result)
    return result


def validate_result(value, source, instructions_digest):
    value = bounded_json(value)
    checked = DrugLabelGenerationResult.model_validate(value)
    expected = result_for_draft(checked.drug_label_extraction, source, instructions_digest)
    if value != expected.model_dump(mode="json") or checked != expected:
        raise ValueError("Complete drug-label result must match its frozen draft and fixed server explanation")
    return checked
