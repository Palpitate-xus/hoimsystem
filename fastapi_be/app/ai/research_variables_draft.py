"""Pure literal76 proposals against already authorized, provenanced documents.

This module grants no Source access. The caller must first validate the whole
Source and current purpose/ACL/patient/model authority, then pass every document.
"""

import datetime as dt
import json
from typing import Annotated, Literal

from pydantic import AfterValidator, Field, model_validator

from app.ai.research_cohort_contract import StrictModel, canonical_json, scalar
from app.ai.research_variables_contract import Key, Kind

MAX_BYTES = 8 * 1024 * 1024
MemberToken = Annotated[str, Field(strict=True, pattern=r"^rv_member:[a-f0-9]{64}$")]
RecordToken = Annotated[str, Field(strict=True, pattern=r"^rv_record:[a-f0-9]{64}$")]
FieldToken = Annotated[str, Field(strict=True, pattern=r"^rv_field:[a-f0-9]{64}$")]
Offset = Annotated[int, Field(strict=True, ge=0, le=MAX_BYTES)]


def text(value):
    scalar(value)
    if len(value.encode("utf-8")) > MAX_BYTES:
        raise ValueError("Whole literal exceeds complete bounded Source")
    return value


def quote(value):
    text(value)
    if not value.replace("\ufeff", "").strip():
        raise ValueError("A candidate quote must contain an explicit literal")
    return value


class LiteralDocument(StrictModel):
    member_token: MemberToken
    record_token: RecordToken
    field_token: FieldToken
    variable_key: Key
    value_kind: Kind
    literal: Annotated[str, AfterValidator(text)] | None

    @model_validator(mode="after")
    def exact_original_scalar(self):
        value = self.literal
        if value is None or self.value_kind == "verbatim_text":
            return self
        if self.value_kind == "original_integer":
            if not value or len(value) > 21 or str(int(value)) != value or not -(2**63) <= int(value) < 2**63:
                raise ValueError("Exact original SQL integer literal required")
        elif self.value_kind == "original_calendar_date":
            if dt.date.fromisoformat(value).isoformat() != value:
                raise ValueError("Exact original calendar date required")
        else:
            stamp = dt.datetime.fromisoformat(value)
            if stamp.tzinfo is not None or stamp.isoformat(timespec="microseconds") != value:
                raise ValueError("Exact naive original clock with its stored microseconds required")
        return self


class Candidate(StrictModel):
    member_token: MemberToken
    record_token: RecordToken
    field_token: FieldToken
    variable_key: Key
    value_kind: Kind
    classification: Literal["value_quote_candidate", "not_measured_quote_candidate", "not_applicable_quote_candidate", "conflict_quote_candidate"]
    start: Offset
    end: Offset
    quote: Annotated[str, Field(strict=True, min_length=1, max_length=4000), AfterValidator(quote)]


class VariableDraft(StrictModel):
    schema_version: Literal["research_variable_draft_v1"]
    coverage: Literal["partial_candidates_only"]
    candidates: Annotated[list[Candidate], Field(max_length=128)]


def validate_draft(values, documents):
    if type(documents) is not list or len(documents) > 8192:
        raise ValueError("Complete explicit document list must fit8192 fields without clipping")
    docs, size = [], 2
    for value in documents:
        document = LiteralDocument.model_validate(value).model_dump()
        size += len(canonical_json(document).encode("utf-8")) + int(bool(docs))
        if size > MAX_BYTES:
            raise ValueError("Whole document set exceeds8MiB; it cannot be clipped")
        docs.append(document)
    by_token = {document["field_token"]: document for document in docs}
    if len(by_token) != len(docs):
        raise ValueError("Duplicate opaque field identities cannot choose a winner")
    result = VariableDraft.model_validate(values).model_dump()
    used = {}
    for row in result["candidates"]:
        original = by_token.get(row["field_token"])
        if original is None or any(original[key] != row[key] for key in ("member_token", "record_token", "variable_key", "value_kind")):
            raise ValueError("Candidate must bind the exact declared original field")
        literal = original["literal"]
        start, end = row["start"], row["end"]
        if literal is None or not 0 <= start < end <= len(literal) or literal[start:end] != row["quote"]:
            raise ValueError("Exact complete original Unicode-codepoint quote required")
        if row["value_kind"] != "verbatim_text" and (start != 0 or end != len(literal) or row["classification"] != "value_quote_candidate"):
            raise ValueError("Original scalar/date/clock must remain whole and uninterpreted")
        spans = used.setdefault(row["field_token"], [])
        if any(start < previous_end and previous_start < end for previous_start, previous_end in spans):
            raise ValueError("Repeated or overlapping field proposals cannot be counted twice")
        spans.append((start, end))
    if len(canonical_json(result).encode("utf-8")) > MAX_BYTES:
        raise ValueError("Whole draft budget; no truncated result")
    return result


def parse_draft_json(raw, documents):
    text(raw)

    def closed_pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate JSON keys refused")
            result[key] = value
        return result

    def no_float(value):
        raise ValueError("Only exact integer offsets and literal text, not JSON float/constants")

    return validate_draft(json.loads(raw, object_pairs_hook=closed_pairs, parse_float=no_float, parse_constant=no_float), documents)
