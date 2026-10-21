"""Unverified paired-source questions; literal overlap is never clinical impact.

The server must build DocumentChangeSource from an authorized current published
Scope. This pure module does not authorize SQL, call a provider or mutate targets.
"""

from typing import Literal

from pydantic import Field, field_validator, model_validator

from app.ai import document_change_contract as c
from app.ai.document_change_json import MAX_JSON_BYTES, parse_case_json, require_case_json
from app.ai.document_change_prompt import SYSTEM_PROMPT as SYSTEM_PROMPT
from app.ai.document_change_prompt import TASK_PROMPT as TASK_PROMPT

MAX_CHANGES = 128
MAX_SPANS_PER_SIDE = 16
COVERAGE = "partial_questions_no_completeness_or_automatic_impact_claim"
COVERAGE_NOTE = "未核实版本核对问题；单侧引文不表示另一原文没有相应内容，空结果不表示没有变化，任何结果均不证明全文或院内规则影响覆盖完整。"
OVERLAP_NOTE = "literal_span_overlap_not_confirmed_impact"


class ProposedChange(c.e.StrictModel):
    kind: Literal["paired_wording_question", "baseline_excerpt_question", "candidate_excerpt_question", "insufficient_evidence"]
    baseline_spans: list[c.ExactSpan] = Field(max_length=MAX_SPANS_PER_SIDE)
    candidate_spans: list[c.ExactSpan] = Field(max_length=MAX_SPANS_PER_SIDE)
    review_note: str = Field(min_length=1, max_length=2000)
    clarification_question: str = Field(min_length=1, max_length=2000)

    @model_validator(mode="after")
    def literal_question(self):
        for value in (self.review_note, self.clarification_question):
            c.e.meaningful(value, minimum=1, maximum=8000)
        baseline, candidate = bool(self.baseline_spans), bool(self.candidate_spans)
        if self.kind == "paired_wording_question" and not (baseline and candidate):
            raise ValueError("A paired question requires actual spans on both sides")
        if self.kind == "baseline_excerpt_question" and (not baseline or candidate):
            raise ValueError("A baseline excerpt question contains only actual baseline spans")
        if self.kind == "candidate_excerpt_question" and (baseline or not candidate):
            raise ValueError("A candidate excerpt question contains only actual candidate spans")
        for spans in (self.baseline_spans, self.candidate_spans):
            keys = [(value.start, value.end, value.quote) for value in spans]
            if len(keys) != len(set(keys)):
                raise ValueError("Duplicate literal spans are not extra evidence")
        return self


class ProviderReply(c.e.StrictModel):
    changes: list[ProposedChange] = Field(max_length=MAX_CHANGES)


class DraftBinding(c.e.StrictModel):
    scope_id: c.e.UUID
    scope_content_hash: c.e.SHA256
    scope_governance_hash: c.e.SHA256
    source_projection_hash: c.e.SHA256
    instructions_digest: c.e.SHA256


class LinkOverlap(c.e.StrictModel):
    link: c.PublicRuleLink
    target: c.PublicTarget
    baseline_span_ordinals: list[int] = Field(max_length=MAX_SPANS_PER_SIDE)
    candidate_span_ordinals: list[int] = Field(max_length=MAX_SPANS_PER_SIDE)
    meaning: Literal["literal_span_overlap_not_confirmed_impact"]

    @field_validator("baseline_span_ordinals", "candidate_span_ordinals", mode="before")
    @classmethod
    def actual_ordinals(cls, values):
        if not isinstance(values, list) or any(type(value) is not int or value < 0 or value >= MAX_SPANS_PER_SIDE for value in values):
            raise ValueError("Overlap ordinals must be actual bounded integers")
        if values != sorted(set(values)):
            raise ValueError("Overlap ordinals must be canonical and unique")
        return values

    @model_validator(mode="after")
    def reference_and_intersection(self):
        if self.link.target != self.target.target or self.link.within_declared_scope != self.target.within_declared_scope:
            raise ValueError("An overlap preserves the exact retained target and declared-scope label")
        if bool(self.baseline_span_ordinals) == bool(self.candidate_span_ordinals):
            raise ValueError("A link belongs to exactly one original side and has at least one literal overlap")
        return self


class DraftChange(ProposedChange):
    link_overlaps: list[LinkOverlap] = Field(max_length=c.MAX_MEMBERS)


class DocumentChangeDraft(c.e.StrictModel):
    schema_version: Literal["document_change_draft_v1"]
    binding: DraftBinding
    coverage: Literal["partial_questions_no_completeness_or_automatic_impact_claim"]
    requires_human_review: Literal[True]
    automatic_changes: Literal[False]
    changes: list[DraftChange] = Field(max_length=MAX_CHANGES)

    @field_validator("requires_human_review", "automatic_changes", mode="before")
    @classmethod
    def actual_literal(cls, value, info):
        if value is not (info.field_name == "requires_human_review"):
            raise ValueError("Server-owned review/action flags must be actual booleans")
        return value


def source_id(source):
    return f"document_change_scope:{source.scope.scope_id}:{source.scope.content_hash[:12]}"


def source_binding(source, instructions_digest):
    return DraftBinding(
        scope_id=source.scope.scope_id,
        scope_content_hash=source.scope.content_hash,
        scope_governance_hash=source.scope.governance_hash,
        source_projection_hash=c.e.digest(source),
        instructions_digest=instructions_digest,
    )


def checked_source(value):
    if isinstance(value, str | bytes):
        value = parse_case_json(value)
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    require_case_json(value)
    source = c.DocumentChangeSource.model_validate(value)
    targets = {c.target_key(value.target): value for value in source.targets}
    originals = {value.original.original_id: value for value in (source.baseline, source.candidate)}
    for link in source.rule_links:
        original = originals[link.original.original_id]
        if link.end > original.codepoint_length or c.e.bytes_hash(original.text[link.start : link.end]) != link.quote_bytes_hash:
            raise ValueError("Every retained public link must preserve its exact original CP range and quote-byte hash")
        target = targets[c.target_key(link.target)]
        if link.within_declared_scope != target.within_declared_scope:
            raise ValueError("A retained link cannot silently change the target's declared scope")
        if link.current and (target.state != "current" or target.snapshot_hash != link.target_snapshot_hash):
            raise ValueError("A link cannot claim current when its retained target state/hash differs")
    return source


def _literal_spans(proposal, source):
    for spans, original in ((proposal.baseline_spans, source.baseline), (proposal.candidate_spans, source.candidate)):
        for span in spans:
            if span.end > original.codepoint_length or original.text[span.start : span.end] != span.quote:
                raise ValueError("Every span must equal the exact corresponding original codepoint interval")


def build_draft(reply, source, instructions_digest):
    source = checked_source(source)
    if isinstance(reply, str | bytes):
        reply = parse_case_json(reply)
    if hasattr(reply, "model_dump"):
        reply = reply.model_dump(mode="json")
    require_case_json(reply)
    reply = ProviderReply.model_validate(reply)
    binding = source_binding(source, instructions_digest)
    targets = {c.target_key(value.target): value for value in source.targets}
    # Account incrementally before appending witnesses. No million-reference
    # intermediate can be built before the final 8MiB all-or-refuse check.
    used = len(c.e.utf8(require_case_json(reply))) + len(c.e.utf8(require_case_json(binding))) + 8192
    changes = []
    for proposal in reply.changes:
        _literal_spans(proposal, source)
        overlaps = []
        for link in source.rule_links:
            baseline = link.original.original_id == source.baseline.original.original_id
            spans = proposal.baseline_spans if baseline else proposal.candidate_spans
            ordinals = [index for index, span in enumerate(spans) if span.start < link.end and link.start < span.end]
            if not ordinals:
                continue
            witness = LinkOverlap(
                link=link, target=targets[c.target_key(link.target)], baseline_span_ordinals=ordinals if baseline else [], candidate_span_ordinals=[] if baseline else ordinals, meaning=OVERLAP_NOTE
            )
            used += len(c.e.utf8(require_case_json(witness))) + 2
            if used > MAX_JSON_BYTES:
                raise ValueError("The complete overlap proof exceeds 8MiB; no witness is omitted")
            overlaps.append(witness)
        changes.append(DraftChange(**proposal.model_dump(mode="json"), link_overlaps=overlaps))
    draft = DocumentChangeDraft(schema_version="document_change_draft_v1", binding=binding, coverage=COVERAGE, requires_human_review=True, automatic_changes=False, changes=changes)
    require_case_json(draft)
    return draft


def parse_provider_reply(raw, source, instructions_digest):
    # The wire reply is only proposed changes; identities and digests are never
    # accepted from the model or computed by it.
    if type(raw) not in {str, bytes}:
        raise ValueError("Provider reply must be complete raw UTF8 JSON")
    return build_draft(parse_case_json(raw), source, instructions_digest)


def validate_draft(value, source, instructions_digest):
    if isinstance(value, str | bytes):
        value = parse_case_json(value)
    elif isinstance(value, DocumentChangeDraft):
        value = value.model_dump(mode="json")
    require_case_json(value)
    checked = DocumentChangeDraft.model_validate(value)
    proposed = {"changes": [change.model_dump(mode="json", exclude={"link_overlaps"}) for change in checked.changes]}
    expected = build_draft(proposed, source, instructions_digest)
    if value != expected.model_dump(mode="json") or checked != expected:
        raise ValueError("The complete frozen binding, literal spans and every mechanical overlap must match")
    return checked
