"""Short leaflet task proof and its only model-visible payload; no SQL authority."""

from typing import Literal

from pydantic import Field, model_validator

from app.ai import document_evidence_contract as d
from app.ai.drug_label_draft import bounded_json, checked_source
from app.ai.drug_label_projection import SourceBinding, projection_hash

FEATURE_KEY = "drug_label_extraction"
SCOPE_NOTE = "单件明确绑定药品目录的受审完整说明书；仅生成逐字字段草稿，未验证官方完整性、执业资质、字段语义或临床适用。"
MISSING_DATA = (
    "药品目录仅比较实际药品主键、名称、条码与状态，未从名称推断规格、厂家或批准文号。",
    "原文隐私和原意审核及药师角色签署保留其明确范围，不构成匿名保证或医学验证。",
    "本次字段草稿仍需药师逐项核对原文条件及含义，不自动更新目录、知识或临床规则。",
)


class DrugLabelRequest(d.StrictModel):
    drug_label_source_binding_id: d.UUID
    question: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def question_capacity(self):
        if self.question is not None and len(d.utf8(self.question)) > 8000:
            raise ValueError("The optional unchanged question exceeds 8000 UTF8 bytes")
        return self


class DrugLabelContextBinding(d.StrictModel):
    schema_version: Literal["drug_label_context_binding_v1"]
    source_id: str = Field(max_length=100)
    source: SourceBinding
    source_projection_hash: d.SHA256
    raw_bytes_hash: d.SHA256
    raw_bytes_length: int = Field(strict=True, ge=1, le=d.MAX_ORIGINAL_BYTES)
    codepoint_length: int = Field(strict=True, ge=1, le=d.MAX_ORIGINAL_BYTES)

    @model_validator(mode="after")
    def exact_source_identity(self):
        if self.source_id != f"drug_label_source:{self.source.source_binding_id}:{self.source.content_hash[:12]}":
            raise ValueError("The source identity must match the retained complete release")
        return self


def selection(values):
    return DrugLabelRequest.model_validate(bounded_json(values))


def binding_for_projection(source):
    source = checked_source(source)
    return DrugLabelContextBinding(
        schema_version="drug_label_context_binding_v1",
        source_id=source.source_id,
        source=source.binding,
        source_projection_hash=projection_hash(source),
        raw_bytes_hash=source.raw_bytes_hash,
        raw_bytes_length=source.raw_bytes_length,
        codepoint_length=source.codepoint_length,
    )


def evidence_for_binding(binding):
    value = DrugLabelContextBinding.model_validate(bounded_json(binding))
    return [
        {"source_id": value.source_id, "kind": "drug_label_source", "title": "明确目录身份与受审完整说明书绑定", "content": d.canonical_json({"drug_label_binding": value.model_dump(mode="json")})},
        {
            "source_id": f"document_original:{value.source.original.original_id}:{value.source.original.content_hash[:12]}",
            "kind": "document_original",
            "title": "完整说明书原文与精确字节依据",
            "content": d.canonical_json(
                {
                    "original": value.source.original.model_dump(mode="json"),
                    "raw_bytes_hash": value.raw_bytes_hash,
                    "raw_bytes_length": value.raw_bytes_length,
                    "codepoint_length": value.codepoint_length,
                }
            ),
        },
    ]


def short_context(binding, snapshot_time):
    value = DrugLabelContextBinding.model_validate(bounded_json(binding))
    d.clock(snapshot_time)
    return {
        "scope": "input",
        "source_domain": "released_drug_label_original",
        "selected_sources": {"drug_label_source_binding_id": value.source.source_binding_id},
        "drug_label_binding": value.model_dump(mode="json"),
        "scope_note": SCOPE_NOTE,
        "missing_data": list(MISSING_DATA),
        "truncated_sources": [],
        "snapshot_time": snapshot_time,
    }


def checked_context(context):
    context = bounded_json(context)
    if not isinstance(context, dict):
        raise ValueError("An exact short leaflet context is required")
    binding = DrugLabelContextBinding.model_validate(context["drug_label_binding"])
    expected = short_context(binding, context["snapshot_time"])
    if context != expected:
        raise ValueError("Mixed or altered leaflet task context is not permitted")
    return binding


def expand_public_context(context, source):
    binding = checked_context(context)
    source = checked_source(source)
    if binding_for_projection(source) != binding or context["snapshot_time"] < source.clocks.source_published_at:
        raise ValueError("Complete seeded projection or actual publication clock differs from the task")
    expanded = {**context, "drug_label_source": source.model_dump(mode="json")}
    bounded_json(expanded)
    return expanded


def public_payload(data):
    """Minimize an already SQL-authorized task; never grants live eligibility."""
    data = bounded_json(data)
    if not isinstance(data, dict) or set(data) != {"input", "context", "tools", "evidence"} or data["tools"] != {}:
        raise ValueError("One closed leaflet task and no tools are required")
    context = data["context"]
    if not isinstance(context, dict) or "drug_label_source" not in context:
        raise ValueError("The complete authorized seeded public source is required")
    short = {key: value for key, value in context.items() if key != "drug_label_source"}
    binding = checked_context(short)
    source = checked_source(context["drug_label_source"])
    expected = expand_public_context(short, source)
    request = selection(data["input"])
    if context != expected or request.drug_label_source_binding_id != binding.source.source_binding_id or data["evidence"] != evidence_for_binding(binding):
        raise ValueError("Input, complete evidence and retained projection must describe one identical release")
    return {"drug_label_source": source.model_dump(mode="json"), "question": request.question}
