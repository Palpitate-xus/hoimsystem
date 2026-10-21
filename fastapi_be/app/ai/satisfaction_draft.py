"""Literal themes from selected manual excerpts, separate from exact ratings.

These pure checks validate the complete safe projection and literal references.
They do not authorize a Case or reconstruct its protected raw content hash.
"""

import datetime as dt
import hashlib
import json
import math
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.ai.satisfaction_contract import SHA, SatisfactionSource

MAX_BYTES = 8 * 1024 * 1024
MAX_THEMES = 64
Offset = Annotated[int, Field(strict=True, ge=0, le=MAX_BYTES)]


def canonical_json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def text_hash(value):
    return hashlib.sha256(value.encode("utf-8", errors="strict")).hexdigest()


def source_hash(value):
    return text_hash(canonical_json(value))


class Closed(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False, str_strip_whitespace=False)


class ExcerptCitation(Closed):
    excerpt_token: SHA
    text_hash: SHA
    start: Offset
    end: Offset
    quote: str = Field(min_length=1, max_length=4000)

    @field_validator("quote")
    @classmethod
    def literal_scalar_text(cls, value):
        if len(value.encode("utf-8", errors="strict")) > 16000:
            raise ValueError("A literal quote exceeds its UTF8 budget")
        return value

    @model_validator(mode="after")
    def nonempty_codepoint_span(self):
        if self.end <= self.start:
            raise ValueError("A nonempty Unicode codepoint span is required")
        return self


class SatisfactionTheme(Closed):
    title: str = Field(min_length=4, max_length=200)
    observation: str = Field(min_length=4, max_length=2000)
    clarification_question: str = Field(min_length=4, max_length=2000)
    cited_excerpt_tokens: list[SHA] = Field(min_length=1, max_length=16)
    citations: list[ExcerptCitation] = Field(min_length=1, max_length=16)

    @field_validator("title", "observation", "clarification_question")
    @classmethod
    def meaningful_scalar_text(cls, value):
        if len(value.strip()) < 4 or len(value.encode("utf-8", errors="strict")) > 8000:
            raise ValueError("An explicit UTF8 theme or clarification is required")
        return value

    @model_validator(mode="after")
    def closed_literal_references(self):
        refs = set(self.cited_excerpt_tokens)
        if len(refs) != len(self.cited_excerpt_tokens) or refs != {row.excerpt_token for row in self.citations}:
            raise ValueError("Distinct cited excerpt tokens must exactly match the literal references")
        spans = {(row.excerpt_token, row.start, row.end) for row in self.citations}
        if len(spans) != len(self.citations):
            raise ValueError("A theme cannot repeat the same literal excerpt span")
        return self


class SatisfactionEvidenceDraft(Closed):
    schema_version: Literal["satisfaction_evidence_draft_v1"]
    satisfaction_source_id: str = Field(pattern=r"^satisfaction_case:[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}:[a-f0-9]{12}$")
    safe_projection_hash: SHA
    coverage: Literal["partial_themes_no_population_or_causality_claim"]
    themes: list[SatisfactionTheme] = Field(max_length=MAX_THEMES)


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON member")
        result[key] = value
    return result


def parse_draft(text):
    if type(text) is not str or len(text) > MAX_BYTES or len(text.encode("utf-8", errors="strict")) > MAX_BYTES:
        raise ValueError("The complete theme draft exceeds its UTF8 budget")

    def nonfinite(_value):
        raise ValueError("Nonfinite JSON number")

    return SatisfactionEvidenceDraft.model_validate(json.loads(text, object_pairs_hook=_object, parse_constant=nonfinite))


def _statistics(rows):
    histogram = {str(score): 0 for score in range(1, 6)}
    null_count = invalid_count = 0
    for row in rows:
        if row["score_status"] == "valid_1_to_5":
            histogram[str(row["recorded_score"])] += 1
        elif row["score_status"] == "null":
            null_count += 1
        else:
            invalid_count += 1
    valid = sum(histogram.values())
    total = sum(int(score) * count for score, count in histogram.items())
    divisor = math.gcd(total, valid) if valid else 1
    return {
        "record_count": len(rows),
        "valid_score_count": valid,
        "null_score_count": null_count,
        "invalid_score_count": invalid_count,
        "histogram": histogram,
        "mean_valid_score": {"numerator": total // divisor, "denominator": valid // divisor} if valid else None,
    }


def validate_source(source):
    """Verify safe facts only; current permissions and protected origin are external."""
    value = source.model_dump(mode="json") if isinstance(source, SatisfactionSource) else source
    if len(canonical_json(value).encode("utf-8", errors="strict")) > MAX_BYTES:
        raise ValueError("The complete safe source exceeds its UTF8 budget")
    checked = SatisfactionSource.model_validate(value).model_dump(mode="json")
    safe = checked["safe_snapshot"]
    days = (dt.date.fromisoformat(safe["date_to"]) - dt.date.fromisoformat(safe["date_from"])).days + 1
    if not 1 <= days <= 366 or (safe["scope_kind"] == "hospital_reviews" and safe["doctor_cohort_size"] is not None):
        raise ValueError("The recorded scope or calendar interval differs")
    if safe["scope_kind"] == "explicit_doctor_cohort" and (type(safe["doctor_cohort_size"]) is not int or not 1 <= safe["doctor_cohort_size"] <= 256):
        raise ValueError("An explicit finite Doctor cohort size is required")
    manifest = safe["member_manifest"]
    if source_hash(manifest) != safe["member_manifest_hash"] or len({row["member_token"] for row in manifest}) != len(manifest):
        raise ValueError("The whole distinct member manifest differs")
    reviews = {row["review_token"]: row for row in safe["reviews"]}
    if len(reviews) != len(safe["reviews"]):
        raise ValueError("A recorded Review cannot be duplicated")
    review_roots, excerpt_roots = {}, {}
    for row in manifest:
        if row["review_token"] not in reviews:
            raise ValueError("A root refers to an unavailable recorded Review")
        if row["kind"] == "review":
            if (
                row["member_token"] != row["review_token"]
                or row["review_token"] in review_roots
                or row["content_hash"] != reviews[row["review_token"]]["content_hash"]
                or row["governance_hash"] is not None
                or row["status"] != "not_applicable"
                or row["version"] is not None
                or row["revision"] is not None
                or row["selected"]
                or row["eligibility"] != "original_record"
                or row["exclusion_reasons"]
            ):
                raise ValueError("A Review manifest root differs from its actual safe record")
            review_roots[row["review_token"]] = row
        else:
            if row["status"] == "not_applicable" or row["governance_hash"] is None or row["eligibility"] == "original_record":
                raise ValueError("An excerpt manifest root requires its own governance and explicit eligibility")
            if row["eligibility"] == "eligible_manual_claim" and (row["status"] != "published" or row["exclusion_reasons"]):
                raise ValueError("An eligible manual claim cannot carry an excluded governance state")
            excerpt_roots[row["member_token"]] = row
    if set(review_roots) != set(reviews):
        raise ValueError("The complete Review roots do not equal the safe Review collection")
    unknown_dates = unresolved = 0
    for row in reviews.values():
        if row["date_status"] == "unknown_legacy_clock":
            unknown_dates += 1
            if row["recorded_date"] is not None:
                raise ValueError("An unknown original clock cannot acquire a fabricated date")
        elif row["recorded_date"] is None or not safe["date_from"] <= row["recorded_date"] <= safe["date_to"]:
            raise ValueError("A known calendar member must belong to the declared recorded dates")
        if (row["score_status"] == "valid_1_to_5") != (row["recorded_score"] is not None):
            raise ValueError("Invalid or NULL scores cannot be replaced with a valid score")
        unresolved += row["parent_status"] == "unresolved_actual_links"
    if unknown_dates != safe["unknown_date_member_count"] or unresolved != safe["unresolved_parent_count"]:
        raise ValueError("Unknown-clock and unresolved-parent counts must cover the complete safe records")
    if safe["all_member_statistics"] != _statistics(list(reviews.values())) or safe["known_period_statistics"] != _statistics(
        [row for row in reviews.values() if row["date_status"] == "in_period_legacy_naive"]
    ):
        raise ValueError("Exact recorded rating statistics differ from the complete safe records")
    selected, selected_reviews = {}, set()
    eligible_counts = {}
    for root in excerpt_roots.values():
        if root["eligibility"] == "eligible_manual_claim":
            eligible_counts[root["review_token"]] = eligible_counts.get(root["review_token"], 0) + 1
    for row in safe["selected_excerpts"]:
        root = excerpt_roots.get(row["excerpt_token"])
        if (
            row["excerpt_token"] in selected
            or row["review_token"] in selected_reviews
            or root is None
            or not root["selected"]
            or root["eligibility"] != "eligible_manual_claim"
            or eligible_counts.get(row["review_token"]) != 1
            or root["status"] != "published"
            or root["version"] != row["version"]
            or type(row["version"]) is not int
            or row["version"] < 1
            or type(root["revision"]) is not int
            or root["revision"] < 2
            or row["review_token"] != root["review_token"]
            or row["original_content_hash"] != root["content_hash"]
            or row["original_governance_hash"] != root["governance_hash"]
            or text_hash(row["text"]) != row["text_hash"]
        ):
            raise ValueError("A selected manual excerpt differs from its exact published root or original text")
        selected[row["excerpt_token"]] = row
        selected_reviews.add(row["review_token"])
    if set(selected) != {key for key, row in excerpt_roots.items() if row["selected"]}:
        raise ValueError("All and only explicitly selected manual excerpts must remain present")
    return checked


def validate_draft(source, draft):
    checked_source = validate_source(source)
    value = draft.model_dump(mode="json") if isinstance(draft, SatisfactionEvidenceDraft) else draft
    checked = SatisfactionEvidenceDraft.model_validate(value)
    if len(canonical_json(checked.model_dump(mode="json")).encode("utf-8")) > MAX_BYTES:
        raise ValueError("The complete theme draft exceeds its UTF8 budget")
    if checked.satisfaction_source_id != checked_source["source_id"] or checked.safe_projection_hash != checked_source["safe_projection_hash"]:
        raise ValueError("The draft belongs to another complete safe source projection")
    excerpts = {row["excerpt_token"]: row for row in checked_source["safe_snapshot"]["selected_excerpts"]}
    identities = set()
    for theme in checked.themes:
        if not set(theme.cited_excerpt_tokens) <= excerpts.keys():
            raise ValueError("A theme cannot cite unselected, unavailable or foreign excerpts")
        identity = canonical_json(theme.model_dump(mode="json"))
        if identity in identities:
            raise ValueError("A complete theme cannot be repeated")
        identities.add(identity)
        for citation in theme.citations:
            original = excerpts[citation.excerpt_token]
            if citation.text_hash != original["text_hash"] or citation.end > len(original["text"]) or original["text"][citation.start : citation.end] != citation.quote:
                raise ValueError("A quotation must be the exact selected excerpt Unicode codepoint span")
    return checked
