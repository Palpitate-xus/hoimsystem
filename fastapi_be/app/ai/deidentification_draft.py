"""Pure literal model candidates; never applied edits or a privacy certificate.

The public-source checker verifies visible shape and literal hashes only. It
provides no SQL/current authorization proof. Callers must first obtain the
current75 Source with the explicit purpose and external-model permission.
"""

from typing import Annotated, Literal

from pydantic import AfterValidator, BeforeValidator, Field, TypeAdapter, model_validator

from app.ai.deidentification_contract import LIMITATIONS, MAX_BYTES, MAX_DOCUMENTS, StrictModel
from app.ai.deidentification_http import parse_json
from app.ai.deidentification_spans import canonical, digest, utf8, verify_document
from app.ai.research_cohort_contract import SHA, UUID, scalar

MAX_CANDIDATES = 128
CATEGORIES = ("direct_identifier", "quasi_identifier", "possible_identifier", "uncertain")
PARTIAL_NOTICE = "模型仅给出部分待核对候选；零候选不代表没有身份信息，未选文字和组合识别风险仍须人工核查。"


def false_only(value):
    if type(value) is not bool or value is not False:
        raise ValueError("The actual false flag must not become numeric zero")
    return value


FalseFlag = Annotated[Literal[False], BeforeValidator(false_only)]
Text = Annotated[str, Field(strict=True, max_length=MAX_BYTES), AfterValidator(scalar)]
Key = Annotated[str, Field(strict=True, min_length=1, max_length=160), AfterValidator(scalar)]
Nonnegative = Annotated[int, Field(strict=True, ge=0, le=MAX_BYTES)]


def review_note(value):
    scalar(value)
    if not value.strip() or len(utf8(value)) > 4000:
        raise ValueError("A bounded meaningful model review note is required")
    return value


class SourceDocument(StrictModel):
    source_id: Key
    field: Annotated[str, Field(strict=True, min_length=1, max_length=100), AfterValidator(scalar)]
    text: Text | None
    text_hash: SHA | None
    utf8_bytes: Nonnegative | None
    codepoint_length: Nonnegative | None
    absent_reason: Literal["not_recorded"] | None

    @model_validator(mode="after")
    def literal_document(self):
        if not verify_document(self.model_dump()):
            raise ValueError("The full visible original text/hash/CP/UTF8/null state differs")
        return self


class DeidentificationPublicSource(StrictModel):
    schema_version: Literal["deidentification_public_source_v1"]
    source_id: Key
    source_content_hash: SHA
    source_governance_hash: SHA
    documents: Annotated[list[SourceDocument], Field(min_length=1, max_length=MAX_DOCUMENTS)]
    coverage: Literal["complete_selected_fields_only"]
    original_time_basis: Literal["legacy_naive_calendar_dates_timezone_unknown"]
    limitations: Annotated[list[str], Field(min_length=len(LIMITATIONS), max_length=len(LIMITATIONS))]
    anonymity_guaranteed: FalseFlag

    @model_validator(mode="after")
    def exact_selected_field_identity(self):
        prefix, case_id, suffix = self.source_id.split(":")
        TypeAdapter(UUID).validate_python(case_id, strict=True)
        if prefix != "deidentification_case" or suffix != self.source_content_hash[:12] or self.limitations != list(LIMITATIONS):
            raise ValueError("The visible Source ID, hash prefix and limitations differ")
        if [item.source_id for item in self.documents] != ["deid_document:" + case_id + ":" + str(index) for index in range(len(self.documents))]:
            raise ValueError("The complete ordered selected-field identifiers differ")
        bounded_json(self.model_dump())
        return self


class SpanCandidate(StrictModel):
    document_source_id: Key
    text_hash: SHA
    start: Nonnegative
    end: Annotated[int, Field(strict=True, ge=1, le=MAX_BYTES)]
    quote: Annotated[str, Field(strict=True, min_length=1, max_length=MAX_BYTES), AfterValidator(scalar)]
    category: Literal["direct_identifier", "quasi_identifier", "possible_identifier", "uncertain"]
    review_note: Annotated[str, Field(strict=True, min_length=1, max_length=1000), AfterValidator(review_note)]

    @model_validator(mode="after")
    def nonempty_interval(self):
        if self.start >= self.end:
            raise ValueError("A candidate must cover an explicit nonempty original interval")
        return self


class DeidentificationDraft(StrictModel):
    schema_version: Literal["deidentification_draft_v1"]
    source_id: Key
    source_projection_hash: SHA
    coverage: Literal["partial_candidates_only"]
    candidates: Annotated[list[SpanCandidate], Field(max_length=MAX_CANDIDATES)]


def bounded_json(value):
    raw = canonical(value)
    if len(utf8(raw)) > MAX_BYTES:
        raise ValueError("The whole object exceeds8MiB; no truncation is permitted")
    return raw


def checked_source(value):
    # model_validate on a dict, rather than accepting arbitrary already-built
    # model instances, also closes crafted model_construct objects.
    if isinstance(value, DeidentificationPublicSource):
        value = value.model_dump()
    value = parse_json(utf8(bounded_json(value)))
    source = DeidentificationPublicSource.model_validate(value, strict=True)
    bounded_json(source.model_dump())
    return source.model_dump()


def validate_draft(source, value):
    source = checked_source(source)
    if isinstance(value, DeidentificationDraft):
        value = value.model_dump()
    value = parse_json(utf8(bounded_json(value)))
    draft = DeidentificationDraft.model_validate(value, strict=True).model_dump()
    if (draft["source_id"], draft["source_projection_hash"]) != (source["source_id"], digest(source)):
        raise ValueError("The exact full model-visible Source projection must match")
    by_id = {item["source_id"]: item for item in source["documents"]}
    seen = set()
    for candidate in draft["candidates"]:
        document = by_id.get(candidate["document_source_id"])
        if document is None or document["text"] is None or candidate["text_hash"] != document["text_hash"]:
            raise ValueError("A candidate must bind a recorded actual original field")
        if candidate["end"] > len(document["text"]) or document["text"][candidate["start"] : candidate["end"]] != candidate["quote"]:
            raise ValueError("Literal original Unicode codepoint quote differs")
        key = (candidate["document_source_id"], candidate["start"], candidate["end"], candidate["category"])
        if key in seen:
            raise ValueError("Duplicate candidates are not separate evidence")
        seen.add(key)
    bounded_json(draft)
    return draft


def parse_provider_reply(raw, source):
    if type(raw) is not str or len(utf8(raw)) > MAX_BYTES:
        raise ValueError("Whole bounded assistant JSON text required")
    return validate_draft(source, parse_json(utf8(raw)))
