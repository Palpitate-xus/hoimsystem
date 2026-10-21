"""Pure operations task/result bindings to full reviewed public documents."""

from typing import Annotated, Literal

from pydantic import Field, model_validator

from app.ai import operations_support_contract as c
from app.ai import operations_support_projection as p

Objective = Literal["explain_observations", "prepare_reviewed_checks", "compare_declared_versions"]
MAX_RESULT_BYTES = 8 * 1024 * 1024


class OperationsTaskSelection(c.StrictModel):
    operations_case_id: c.Identifier
    objective: Objective


class EvidenceSpan(c.StrictModel):
    source_id: c.Identifier
    start_codepoint: c.Position
    end_codepoint: c.Position
    quote: c.Text

    @model_validator(mode="after")
    def nonempty(self):
        if self.end_codepoint <= self.start_codepoint:
            raise ValueError("Evidence must quote an actual nonempty scalar-codepoint span")
        return self


class Observation(c.StrictModel):
    title: c.Title
    explanation: c.Note
    evidence: Annotated[list[EvidenceSpan], Field(min_length=1, max_length=32)]


class Hypothesis(Observation):
    status: Literal["unverified_hypothesis_requires_admin_review"]


class ManualCheck(c.StrictModel):
    purpose: c.Note
    instruction_reference: EvidenceSpan
    applicability: Literal["requires_current_environment_and_admin_review"]
    impact: Literal["not_established_by_this_draft"]
    execution: Literal["reference_only_no_automatic_execution"]


class Gap(c.StrictModel):
    kind: Literal["missing_reviewed_runbook", "component_unknown", "version_unknown", "environment_not_observed", "source_conflict", "insufficient_evidence"]
    explanation: c.Note


class OperationsDraft(c.StrictModel):
    schema_version: Literal["operations_support_draft_v1"]
    source_id: c.Identifier
    source_sha256: c.Digest
    objective: Objective
    status: Literal["unverified_operations_draft"]
    environment_status: Literal["not_observed_by_this_task"]
    compatibility_status: Literal["not_verified_from_reviewed_text"]
    observations: Annotated[list[Observation], Field(max_length=64)]
    hypotheses: Annotated[list[Hypothesis], Field(max_length=64)]
    manual_checks: Annotated[list[ManualCheck], Field(max_length=64)]
    gaps: Annotated[list[Gap], Field(max_length=64)]


def _whole(value):
    text = c.canonical_json(value)
    if len(text.encode("utf-8")) > MAX_RESULT_BYTES:
        raise ValueError("The entire operations draft exceeds its UTF8 budget; no partial result is accepted")
    return text


def verify_result(value, source, selection) -> OperationsDraft:
    source = p.OperationsSupportSource.model_validate(p._value(source), strict=True)
    selection = OperationsTaskSelection.model_validate(selection, strict=True)
    result = OperationsDraft.model_validate(p._value(value), strict=True)
    if selection.operations_case_id != source.source_id or result.source_id != source.source_id or result.source_sha256 != c.content_hash(source) or result.objective != selection.objective:
        raise ValueError("The result must bind this complete public source and exact selected objective")
    documents = {document.source_id: document for document in source.documents}

    def verify_span(span, *, runbook=False):
        document = documents.get(span.source_id)
        if document is None or span.end_codepoint > len(document.text) or document.text[span.start_codepoint : span.end_codepoint] != span.quote:
            raise ValueError("Evidence must equal the entire explicit original scalar-codepoint slice")
        if runbook and document.kind != "runbook":
            raise ValueError("A diagnostic log or reference document cannot supply an action instruction")

    for finding in [*result.observations, *result.hypotheses]:
        seen = set()
        for span in finding.evidence:
            verify_span(span)
            identity = (span.source_id, span.start_codepoint, span.end_codepoint)
            if identity in seen:
                raise ValueError("Repeated identical references cannot inflate one finding")
            seen.add(identity)
    if result.manual_checks and selection.objective != "prepare_reviewed_checks":
        raise ValueError("Only the explicit reviewed-checks objective requests instruction references")
    if result.manual_checks and source.action_basis != "reviewed_runbook_reference_only":
        raise ValueError("No reviewed runbook is present; no action instruction may be invented")
    for check in result.manual_checks:
        verify_span(check.instruction_reference, runbook=True)
    if source.action_basis == "missing_reviewed_runbook" and not any(gap.kind == "missing_reviewed_runbook" for gap in result.gaps):
        raise ValueError("Missing reviewed action documentation must stay explicit")
    _whole(result)
    return result
