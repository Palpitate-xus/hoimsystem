"""Pure, finite declarations for reviewed operations documents.

These values establish content bindings only. Real current reviewers, publication,
permissions and revocation require the eventual server-side source registry.
No file, process, environment, network or application settings are accessed here.
"""

import datetime as dt
import hashlib
import json
import re
import uuid
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, field_validator, model_validator

MAX_TEXT_BYTES = 4 * 1024 * 1024
MAX_WHOLE_BYTES = 8 * 1024 * 1024
MAX_SOURCES = 128
MASK_TEXT = "[已遮盖]"


def _scalar(value: str) -> str:
    if type(value) is not str:
        raise ValueError("An actual scalar string is required")
    value.encode("utf-8", errors="strict")
    return value


def _text(value: str) -> str:
    if len(_scalar(value).encode("utf-8")) > MAX_TEXT_BYTES:
        raise ValueError("The complete original or derivative exceeds its UTF8 budget")
    return value


def _uuid(value: str) -> str:
    if str(uuid.UUID(value)) != value:
        raise ValueError("A canonical lowercase UUID is required")
    return value


def _clock(value: str) -> str:
    if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{6}Z", value):
        raise ValueError("An explicit UTC microsecond capture or review clock is required")
    dt.datetime.fromisoformat(value[:-1] + "+00:00")
    return value


Identifier = Annotated[str, Field(strict=True, min_length=36, max_length=36), AfterValidator(_uuid)]
Clock = Annotated[str, Field(strict=True, min_length=27, max_length=27), AfterValidator(_clock)]
Digest = Annotated[str, Field(strict=True, min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")]
Title = Annotated[str, Field(strict=True, min_length=1, max_length=300), AfterValidator(_scalar)]
Note = Annotated[str, Field(strict=True, min_length=1, max_length=4000), AfterValidator(_scalar)]
Text = Annotated[str, Field(strict=True, min_length=1), AfterValidator(_text)]
ActorId = Annotated[int, Field(strict=True, ge=1, le=2147483647)]
Position = Annotated[int, Field(strict=True, ge=0, le=MAX_TEXT_BYTES)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=False, frozen=True, revalidate_instances="always")


def canonical_json(value: BaseModel | dict) -> str:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    text = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    text.encode("utf-8", errors="strict")
    return text


def content_hash(value: BaseModel | dict) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


class OperationsOriginal(StrictModel):
    schema_version: Literal["operations_support_original_v1"]
    original_id: Identifier
    kind: Literal["diagnostic_log", "runbook", "reference_document"]
    title: Title
    origin_note: Note
    declared_component: Annotated[str, Field(strict=True, max_length=120), AfterValidator(_scalar)] | None
    declared_version: Annotated[str, Field(strict=True, max_length=120), AfterValidator(_scalar)] | None
    content_text: Text
    captured_at: Clock
    captured_by: ActorId
    clock_basis: Literal["capture_only_not_verified_incident_occurrence"]


class Redaction(StrictModel):
    start_codepoint: Position
    end_codepoint: Position
    method: Literal["remove", "mask"]

    @model_validator(mode="after")
    def positive_span(self):
        if self.end_codepoint <= self.start_codepoint:
            raise ValueError("A manual redaction must cover an actual nonempty codepoint span")
        return self


def apply_redactions(original: str, spans: list[Redaction]) -> str:
    """Apply all explicitly selected scalar-codepoint spans, preserving every other byte."""
    _text(original)
    if type(spans) is not list or len(spans) > 4096 or any(not isinstance(s, Redaction) for s in spans):
        raise ValueError("A bounded explicit list of typed redactions is required")
    result, previous_end = [], 0
    for span in spans:
        span = Redaction.model_validate(span, strict=True)
        if span.start_codepoint < previous_end or span.end_codepoint > len(original):
            raise ValueError("Redactions must be ordered, disjoint and within the complete original")
        result.extend([original[previous_end : span.start_codepoint], "" if span.method == "remove" else MASK_TEXT])
        previous_end = span.end_codepoint
    result.append(original[previous_end:])
    return "".join(result)


class DeclaredOperationsReview(StrictModel):
    schema_version: Literal["operations_support_declared_review_v1"]
    review_id: Identifier
    original_id: Identifier
    original_full_sha256: Digest
    released_title: Title
    released_component: Annotated[str, Field(strict=True, max_length=120), AfterValidator(_scalar)] | None
    released_version: Annotated[str, Field(strict=True, max_length=120), AfterValidator(_scalar)] | None
    redactions: Annotated[list[Redaction], Field(max_length=4096)]
    released_text: Text
    privacy_reviewed: Literal[True]
    faithfulness_reviewed: Literal[True]
    applicability_declaration_reviewed: Literal[True]
    review_basis: Note
    reviewed_at: Clock
    reviewed_by: ActorId

    @field_validator("privacy_reviewed", "faithfulness_reviewed", "applicability_declaration_reviewed", mode="before")
    @classmethod
    def actual_true(cls, value):
        if type(value) is not bool or value is not True:
            raise ValueError("An explicit true declaration is required; it is not server authorization")
        return value


def verify_declared_review(original: OperationsOriginal, review: DeclaredOperationsReview) -> None:
    original = OperationsOriginal.model_validate(original, strict=True)
    review = DeclaredOperationsReview.model_validate(review, strict=True)
    if review.original_id != original.original_id or review.original_full_sha256 != content_hash(original):
        raise ValueError("The declaration must bind the entire exact original and its metadata")
    if review.reviewed_by == original.captured_by:
        raise ValueError("The declared reviewer must be independent of the original registrar")
    if review.reviewed_at < original.captured_at:
        raise ValueError("The declared review cannot precede the capture")
    if apply_redactions(original.content_text, review.redactions) != review.released_text:
        raise ValueError("The entire derivative must equal the explicit original codepoint transformation")
    if len(canonical_json({"original": original.model_dump(mode="json"), "review": review.model_dump(mode="json")}).encode("utf-8")) > MAX_WHOLE_BYTES:
        raise ValueError("The complete source and declaration exceed the whole-source UTF8 budget")
