"""Pure bounded questions about one already authorized, fixed research Case.

This module establishes shape and exact public citations, never DB authority.
Dispatch and acceptance must each authorize the actual project, purpose, ACL,
every patient, external-model permission and provider through current services.
"""

import hashlib
from typing import Annotated, Literal

from fastapi import HTTPException
from pydantic import AfterValidator, Field, model_validator

from app.ai.research_cohort_contract import SHA, ResearchCohortSource, StrictModel, canonical_json, scalar

MAX_BYTES = 8 * 1024 * 1024
MAX_TARGETS = 8192
COVERAGE = "partial_review_questions_only_no_eligibility_or_population_claim"


def digest(value):
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _meaningful(value):
    scalar(value)
    if not value.replace("\ufeff", "").strip():
        raise ValueError("An actual nonempty scalar question is required")
    return value


QuestionText = Annotated[str, Field(strict=True, min_length=4, max_length=2000), AfterValidator(_meaningful)]
Title = Annotated[str, Field(strict=True, min_length=4, max_length=200), AfterValidator(_meaningful)]
Quote = Annotated[str, Field(strict=True, min_length=1, max_length=4000), AfterValidator(scalar)]
Offset = Annotated[int, Field(strict=True, ge=0, le=MAX_BYTES)]


class ResearchCitation(StrictModel):
    target_token: SHA
    text_hash: SHA
    start: Offset
    end: Offset
    quote: Quote

    @model_validator(mode="after")
    def actual_positive_slice(self):
        if self.end <= self.start:
            raise ValueError("An exact positive Unicode-codepoint slice is required")
        return self


class ResearchQuestion(StrictModel):
    category: Literal["standard_question", "recorded_evidence_question", "unknown_condition_question"]
    title: Title
    observation: QuestionText
    clarification_question: QuestionText
    citations: Annotated[list[ResearchCitation], Field(min_length=1, max_length=16)]

    @model_validator(mode="after")
    def distinct_citations(self):
        keys = [(c.target_token, c.text_hash, c.start, c.end, c.quote) for c in self.citations]
        if len(set(keys)) != len(keys):
            raise ValueError("Repeated citations do not add evidence")
        return self


class ResearchCohortDraft(StrictModel):
    schema_version: Literal["research_cohort_questions_v1"]
    research_source_id: Annotated[str, Field(strict=True, min_length=1, max_length=100), AfterValidator(scalar)]
    source_projection_hash: SHA
    coverage: Literal["partial_review_questions_only_no_eligibility_or_population_claim"]
    questions: Annotated[list[ResearchQuestion], Field(max_length=128)]


def checked_source(value):
    try:
        if type(value) is not dict or len(canonical_json(value).encode("utf-8")) > MAX_BYTES:
            raise ValueError("One complete public source must fit 8MiB")
        checked = ResearchCohortSource.model_validate(value).model_dump()
        if checked != value:
            raise ValueError("The public source must preserve exact original scalars")
        return checked
    except (ValueError, TypeError, UnicodeError, RecursionError) as exc:
        raise HTTPException(409, "完整研究公开Case的闭集、日历或集合证明无效") from exc


def citation_catalog(value):
    """Only existing public strings, with their exact path and CP coordinate.

    A clinical target is the already disclosed evidence.quote string; its CP
    offsets are relative to that string, not a claim that the full raw clinical
    field was disclosed. Criteria and technical reasons remain separate types.
    No raw Scope/ACL/Patient IDs, hidden text or derived statistics are added.
    """
    source = checked_source(value)
    projection = digest(source)
    targets = []
    total = 0

    def add(path, text, category):
        nonlocal total
        if type(text) is not str or not text:
            return
        target = {
            "target_token": digest([source["source_id"], projection, path]),
            "category": category,
            "source_path": path,
            "text_hash": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "text": text,
        }
        total += len(canonical_json(target).encode("utf-8"))
        if len(targets) >= MAX_TARGETS or total > MAX_BYTES:
            raise HTTPException(413, "完整研究引用目录超过8192项或8MiB，未截断可选证据")
        targets.append(target)

    def criteria_strings(node, path):
        if type(node) is str:
            add(path, node, "criteria_declaration")
        elif type(node) is dict:
            for key in sorted(node):
                criteria_strings(node[key], path + "/" + key)
        elif type(node) is list:
            for index, child in enumerate(node):
                criteria_strings(child, path + "/" + str(index))

    criteria_strings(source["criteria"], "/criteria")
    for i, outcome in enumerate(source["outcomes"]):
        for j, leaf in enumerate(outcome["leaves"]):
            path = f"/outcomes/{i}/leaves/{j}"
            add(path + "/reason", leaf["reason"], "record_scope_reason")
            for k, evidence in enumerate(leaf["evidence"]):
                add(path + f"/evidence/{k}/quote", evidence["quote"], "recorded_evidence_quote")
                add(path + f"/evidence/{k}/reason", evidence["reason"], "record_scope_reason")
    for i, limitation in enumerate(source["limitations"]):
        add(f"/limitations/{i}", limitation, "source_limitation")
    return {"schema_version": "research_public_citation_catalog_v1", "source_projection_hash": projection, "targets": targets}


def validate_draft(value, source):
    """Exact source anchor and quotes; no automatic clinical truth checking."""
    try:
        if type(value) is not dict or len(canonical_json(value).encode("utf-8")) > MAX_BYTES:
            raise ValueError("One whole draft must fit 8MiB")
        draft = ResearchCohortDraft.model_validate(value)
        source = checked_source(source)
        if draft.research_source_id != source["source_id"] or draft.source_projection_hash != digest(source):
            raise ValueError("The draft belongs to another complete public Case")
        targets = {target["target_token"]: target for target in citation_catalog(source)["targets"]}
        for question in draft.questions:
            kinds = set()
            for citation in question.citations:
                target = targets.get(citation.target_token)
                if target is None or citation.text_hash != target["text_hash"] or citation.end > len(target["text"]) or target["text"][citation.start : citation.end] != citation.quote:
                    raise ValueError("The CP quote is not in the current complete public citation catalog")
                kinds.add(target["category"])
            if question.category == "recorded_evidence_question" and "recorded_evidence_quote" not in kinds:
                raise ValueError("A criteria declaration is not recorded clinical evidence")
            if question.category == "standard_question" and "criteria_declaration" not in kinds:
                raise ValueError("A standard question must refer to the fixed declared criteria")
        return draft.model_dump()
    except (ValueError, TypeError, KeyError, UnicodeError, RecursionError) as exc:
        raise HTTPException(409, "研究待核问题的完整Case锚、闭集或逐字CP引文不一致") from exc
