"""Exact UTF8 originals and codepoint spans; no clinical or extraction claim."""

import base64
import datetime as dt
import hashlib
import json
import re
import uuid
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

MAX_ORIGINAL_BYTES = 4 * 1024 * 1024
MAX_REQUEST_BYTES = 8 * 1024 * 1024
MAX_METADATA_BYTES = 32768
MAX_KNOWLEDGE_BYTES = 65535
MAX_CANDIDATE_BYTES = 131072
MAX_PUBLICATION_BYTES = 196608
UPLOAD_TIMEOUT_SECONDS = 15
SOURCE_KIND = "document_span"
URI_PREFIX = "hoim://document-evidence/"
DECLARATION = "submitter_declared_not_authority_or_clinical_validation"

SHA256 = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$", strict=True)]
UUID = Annotated[str, Field(pattern=r"^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$", strict=True)]
Positive = Annotated[int, Field(strict=True, ge=1, le=2147483647)]
Revision = Annotated[int, Field(strict=True, ge=1, le=3)]
UtcText = Annotated[str, Field(pattern=r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z$", strict=True)]
Review = Literal["unknown", "confirmed", "not_confirmed"]
DocumentKind = Literal["guideline", "drug_label", "local_protocol", "other"]
Category = Literal["clinical", "drug", "hospital", "operations", "training"]


def utf8(value: str) -> bytes:
    """No normalization, replacement decoding, BOM stripping or newline changes."""
    if not isinstance(value, str):
        raise ValueError("A real Unicode string is required")
    try:
        return value.encode("utf-8", errors="strict")
    except UnicodeError as exc:
        raise ValueError("Unpaired surrogates and invalid UTF8 are not accepted") from exc


def canonical_json(value) -> str:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value) -> str:
    return hashlib.sha256(utf8(canonical_json(value))).hexdigest()


def bytes_hash(text: str) -> str:
    return hashlib.sha256(utf8(text)).hexdigest()


def clock(value: str) -> dt.datetime:
    try:
        result = dt.datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ")
    except (TypeError, ValueError) as exc:
        raise ValueError("A real UTC Gregorian microsecond timestamp is required") from exc
    if utc_text(result) != value:
        raise ValueError("UTC timestamps must use the canonical six-digit format")
    return result


def utc_text(value: dt.datetime) -> str:
    if value.tzinfo is not None:
        value = value.astimezone(dt.UTC).replace(tzinfo=None)
    return f"{value.year:04d}-{value.month:02d}-{value.day:02d}T{value.hour:02d}:{value.minute:02d}:{value.second:02d}.{value.microsecond:06d}Z"


def meaningful(value: str, *, maximum: int = 4000, minimum: int = 10) -> str:
    if len("".join(value.split())) < minimum or len(utf8(value)) > maximum:
        raise ValueError("The explicit basis must be meaningful and within its UTF8 byte limit")
    return value


def unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON keys are not accepted")
        result[key] = value
    return result


def reject_constant(value):
    raise ValueError("Nonfinite JSON numbers are not accepted")


def parse_json(text: str):
    try:
        result = json.loads(text, object_pairs_hook=unique_pairs, parse_constant=reject_constant)
        pending = [result]
        count = 0
        while pending:
            value = pending.pop()
            count += 1
            if count > 20000:
                raise ValueError("JSON structural budget exceeded")
            if isinstance(value, str):
                utf8(value)
            elif isinstance(value, dict):
                for key, child in value.items():
                    utf8(key)
                    pending.append(child)
            elif isinstance(value, list):
                pending.extend(value)
        return result
    except (UnicodeError, RecursionError, OverflowError) as exc:
        raise ValueError("Invalid or excessively nested JSON") from exc


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, validate_default=True)

    @model_validator(mode="before")
    @classmethod
    def valid_strings(cls, value):
        pending = [value]
        while pending:
            item = pending.pop()
            if isinstance(item, str):
                utf8(item)
            elif isinstance(item, dict):
                for key, child in item.items():
                    utf8(key)
                    pending.append(child)
            elif isinstance(item, list):
                pending.extend(item)
        return value


class DocumentMetadata(StrictModel):
    title: str = Field(min_length=2, max_length=200)
    version: str = Field(min_length=1, max_length=80)
    document_kind: DocumentKind
    declared_source_uri: str = Field(min_length=3, max_length=2000)
    declared_publisher: str | None = Field(min_length=1, max_length=200)
    source_available_at: UtcText | None
    applicability_note: str = Field(min_length=10, max_length=4000)
    authorization_note: str = Field(min_length=10, max_length=4000)

    @model_validator(mode="after")
    def explicit_declarations(self):
        for name in ("title", "version", "declared_source_uri"):
            meaningful(getattr(self, name), minimum=1, maximum=8000)
        if self.declared_publisher is not None:
            meaningful(self.declared_publisher, minimum=1, maximum=800)
        for name in ("applicability_note", "authorization_note"):
            meaningful(getattr(self, name))
        if self.source_available_at is not None:
            clock(self.source_available_at)
        if len(utf8(canonical_json(self))) > MAX_METADATA_BYTES:
            raise ValueError("Complete metadata exceeds the UTF8 byte budget")
        return self


class DirectText(StrictModel):
    kind: Literal["direct_text"]
    text: str = Field(min_length=1, max_length=MAX_ORIGINAL_BYTES)
    expected_bytes_hash: SHA256

    @model_validator(mode="after")
    def exact_bytes(self):
        if len(utf8(self.text)) > MAX_ORIGINAL_BYTES or bytes_hash(self.text) != self.expected_bytes_hash:
            raise ValueError("Original UTF8 bytes exceed the limit or differ from the submitted digest")
        return self


class Utf8File(StrictModel):
    kind: Literal["utf8_file"]
    filename: str = Field(min_length=1, max_length=255)
    bytes_base64: str = Field(min_length=4, max_length=((MAX_ORIGINAL_BYTES + 2) // 3) * 4)
    expected_bytes_hash: SHA256

    @model_validator(mode="after")
    def exact_file(self):
        if not self.filename.lower().endswith((".txt", ".md")) or "/" in self.filename or "\\" in self.filename or len(utf8(self.filename)) > 1020:
            raise ValueError("Only a basename ending in .txt or .md is supported")
        self.decoded_text()
        return self

    def decoded_text(self):
        try:
            raw = base64.b64decode(self.bytes_base64, validate=True)
            if not raw or len(raw) > MAX_ORIGINAL_BYTES or base64.b64encode(raw).decode("ascii") != self.bytes_base64:
                raise ValueError("The complete file bytes must be canonical base64 within 4MiB")
            if hashlib.sha256(raw).hexdigest() != self.expected_bytes_hash:
                raise ValueError("File bytes differ from the submitted digest")
            return raw.decode("utf-8", errors="strict")
        except (UnicodeError, ValueError) as exc:
            raise ValueError("Only the exact valid UTF8 file is supported; no decoding fallback") from exc


class OriginalCreate(StrictModel):
    metadata: DocumentMetadata
    content: Annotated[DirectText | Utf8File, Field(discriminator="kind")]


class OriginalImmutable(StrictModel):
    schema_version: Literal["document_original_immutable_v1"]
    original_id: UUID
    created_by: Positive
    recorded_at: UtcText
    metadata: DocumentMetadata
    input_kind: Literal["direct_text", "utf8_file"]
    filename: str | None = Field(min_length=1, max_length=255)
    raw_bytes_hash: SHA256
    raw_bytes_length: int = Field(strict=True, ge=1, le=MAX_ORIGINAL_BYTES)
    codepoint_length: int = Field(strict=True, ge=1, le=MAX_ORIGINAL_BYTES)
    text: str = Field(min_length=1, max_length=MAX_ORIGINAL_BYTES)

    @model_validator(mode="after")
    def exact_original(self):
        clock(self.recorded_at)
        if self.metadata.source_available_at is not None and self.metadata.source_available_at > self.recorded_at:
            raise ValueError("Original availability cannot be after server registration")
        if (self.input_kind == "direct_text") != (self.filename is None):
            raise ValueError("The actual input method and original filename must be preserved")
        if self.raw_bytes_length != len(utf8(self.text)) or self.codepoint_length != len(self.text) or self.raw_bytes_hash != bytes_hash(self.text):
            raise ValueError("Original bytes, codepoints and digest must all match")
        if self.filename is not None and (not self.filename.lower().endswith((".txt", ".md")) or "/" in self.filename or "\\" in self.filename):
            raise ValueError("Unsupported original filename")
        if len(utf8(canonical_json(self))) > MAX_REQUEST_BYTES - MAX_METADATA_BYTES:
            raise ValueError("Complete original JSON exceeds the bounded response budget")
        return self


class GovernedReview(StrictModel):
    status: Literal["draft", "published", "approved", "rejected", "revoked"]
    revision: Revision
    privacy_review: Review
    faithfulness_review: Review
    reviewed_by: Positive | None
    reviewed_at: UtcText | None
    review_basis_note: str = Field(max_length=4000)
    revoked_by: Positive | None
    revoked_at: UtcText | None
    revoke_reason: str = Field(max_length=1000)

    @model_validator(mode="after")
    def actual_governance(self):
        reviewed = self.reviewed_by is not None
        if reviewed != (self.reviewed_at is not None) or reviewed != bool(self.review_basis_note):
            raise ValueError("Review identity, time and basis are one complete signature")
        revoked = self.revoked_by is not None
        if revoked != (self.revoked_at is not None) or revoked != bool(self.revoke_reason):
            raise ValueError("Revocation identity, time and basis are one complete signature")
        if reviewed:
            clock(self.reviewed_at)
            meaningful(self.review_basis_note)
            if "unknown" in (self.privacy_review, self.faithfulness_review):
                raise ValueError("An actual review must record both explicit decisions")
        elif (self.privacy_review, self.faithfulness_review) != ("unknown", "unknown"):
            raise ValueError("No review signature means both reviews remain unknown")
        if revoked:
            clock(self.revoked_at)
            meaningful(self.revoke_reason, maximum=4000)
        if self.status == "draft" and (self.revision != 1 or reviewed or revoked):
            raise ValueError("Draft governance must be revision one without signatures")
        if self.status in {"published", "approved", "rejected"} and (self.revision != 2 or not reviewed or revoked):
            raise ValueError("The first explicit review creates revision two")
        if self.status in {"published", "approved"} and (self.privacy_review, self.faithfulness_review) != ("confirmed", "confirmed"):
            raise ValueError("Publication/approval requires explicit privacy and fidelity confirmation")
        if self.status == "rejected" and (self.privacy_review, self.faithfulness_review) == ("confirmed", "confirmed"):
            raise ValueError("A rejection must record at least one unconfirmed review")
        if self.status == "revoked" and (not revoked or self.revision != (3 if reviewed else 2)):
            raise ValueError("Revocation must preserve the actual previous review")
        return self


class ReviewRequest(StrictModel):
    expected_revision: Revision
    expected_content_hash: SHA256
    expected_governance_hash: SHA256
    decision: Literal["approve", "reject"]
    privacy_review: Literal["confirmed", "not_confirmed"]
    faithfulness_review: Literal["confirmed", "not_confirmed"]
    basis_note: str = Field(min_length=10, max_length=4000)

    @model_validator(mode="after")
    def explicit_decision(self):
        meaningful(self.basis_note)
        if (self.decision == "approve") != ((self.privacy_review, self.faithfulness_review) == ("confirmed", "confirmed")):
            raise ValueError("Approval and the two actual review decisions must agree")
        return self


class RevokeRequest(StrictModel):
    expected_revision: Revision
    expected_content_hash: SHA256
    expected_governance_hash: SHA256
    basis_note: str = Field(min_length=10, max_length=1000)

    @field_validator("basis_note")
    @classmethod
    def explicit_reason(cls, value):
        return meaningful(value)


class OriginalReference(StrictModel):
    original_id: UUID
    content_hash: SHA256
    governance_hash: SHA256


class CandidateCreate(StrictModel):
    original: OriginalReference
    proposed_heading: str = Field(min_length=1, max_length=200)
    clause_kind: Literal["recommendation", "definition", "applicability", "warning", "other"]
    start: int = Field(strict=True, ge=0, le=MAX_ORIGINAL_BYTES)
    end: int = Field(strict=True, ge=1, le=MAX_ORIGINAL_BYTES)
    quote: str = Field(min_length=1, max_length=MAX_KNOWLEDGE_BYTES)
    provenance: Literal["unverified_submission"]

    @model_validator(mode="after")
    def bounded_span(self):
        meaningful(self.proposed_heading, minimum=1, maximum=800)
        if self.start >= self.end or len(self.quote) != self.end - self.start or len(utf8(self.quote)) > MAX_KNOWLEDGE_BYTES:
            raise ValueError("A complete nonempty codepoint [start,end) span within the knowledge byte limit is required")
        return self


class CandidateImmutable(StrictModel):
    schema_version: Literal["document_span_candidate_immutable_v1"]
    candidate_id: UUID
    created_by: Positive
    recorded_at: UtcText
    proposal: CandidateCreate

    @model_validator(mode="after")
    def bounded(self):
        clock(self.recorded_at)
        if len(utf8(canonical_json(self))) > MAX_CANDIDATE_BYTES:
            raise ValueError("The complete candidate exceeds its UTF8 budget")
        return self


class KnowledgeMetadata(StrictModel):
    title: str = Field(min_length=2, max_length=200)
    version: str = Field(min_length=1, max_length=80)
    category: Category
    feature_keys: list[str] = Field(min_length=1, max_length=80)
    department_id: Positive | None
    effective_from: UtcText | None
    effective_to: UtcText | None

    @model_validator(mode="after")
    def explicit_metadata(self):
        for value in (self.title, self.version):
            meaningful(value, minimum=1, maximum=800)
        if len(set(self.feature_keys)) != len(self.feature_keys) or any(not re.fullmatch(r"[a-z][a-z0-9_]{1,79}", key) for key in self.feature_keys):
            raise ValueError("Explicit unique capability keys are required")
        for value in (self.effective_from, self.effective_to):
            if value is not None:
                clock(value)
        if self.effective_from is not None and self.effective_to is not None and self.effective_from >= self.effective_to:
            raise ValueError("Effective times must be an ordered half-open interval")
        return self


class PublishRequest(StrictModel):
    expected_revision: Revision
    expected_content_hash: SHA256
    expected_governance_hash: SHA256
    knowledge: KnowledgeMetadata
    basis_note: str = Field(min_length=10, max_length=4000)

    @field_validator("basis_note")
    @classmethod
    def explicit_basis(cls, value):
        return meaningful(value)


class CandidateReference(StrictModel):
    candidate_id: UUID
    content_hash: SHA256
    governance_hash: SHA256


class PublicationImmutable(StrictModel):
    schema_version: Literal["document_knowledge_publication_immutable_v1"]
    publication_id: UUID
    original: OriginalReference
    candidate: CandidateReference
    published_by: Positive
    published_at: UtcText
    publication_basis_note: str = Field(min_length=10, max_length=4000)
    knowledge_document_id: UUID
    knowledge: KnowledgeMetadata
    quote: str = Field(min_length=1, max_length=MAX_KNOWLEDGE_BYTES)
    quote_bytes_hash: SHA256

    @model_validator(mode="after")
    def exact_quote(self):
        clock(self.published_at)
        meaningful(self.publication_basis_note)
        if len(utf8(self.quote)) > MAX_KNOWLEDGE_BYTES or bytes_hash(self.quote) != self.quote_bytes_hash:
            raise ValueError("The complete exact quote must fit MySQL TEXT; no truncation")
        if len(utf8(canonical_json(self))) > MAX_PUBLICATION_BYTES:
            raise ValueError("The complete publication exceeds its UTF8 budget")
        return self


class PublicationGovernance(StrictModel):
    status: Literal["active", "revoked"]
    revision: Annotated[int, Field(strict=True, ge=1, le=2)]
    revoked_by: Positive | None
    revoked_at: UtcText | None
    revoke_reason: str = Field(max_length=1000)

    @model_validator(mode="after")
    def actual_revocation(self):
        if self.status == "active":
            if self.revision != 1 or self.revoked_by is not None or self.revoked_at is not None or self.revoke_reason:
                raise ValueError("An active publication has no revocation signature")
        else:
            if self.revision != 2 or self.revoked_by is None or self.revoked_at is None:
                raise ValueError("A revoked publication requires the complete actual signature")
            clock(self.revoked_at)
            meaningful(self.revoke_reason)
        return self


Ineligibility = Literal["original_not_published", "original_not_current", "candidate_not_approved", "publication_revoked", "knowledge_not_published", "knowledge_changed"]


class OriginalRecord(StrictModel):
    schema_version: Literal["document_original_record_v1"]
    source_id: str
    snapshot: OriginalImmutable
    content_hash: SHA256
    governance: GovernedReview
    governance_hash: SHA256
    eligible: bool
    ineligibility_reasons: list[Ineligibility]
    declaration_status: Literal["submitter_declared_not_authority_or_clinical_validation"]
    clinical_validation: Literal["not_provided"]

    @model_validator(mode="after")
    def full_binding(self):
        if self.source_id != f"document_original:{self.snapshot.original_id}:{self.content_hash[:12]}" or digest(self.snapshot) != self.content_hash or digest(self.governance) != self.governance_hash:
            raise ValueError("Original record identity and complete hashes must match")
        if self.governance.status == "approved":
            raise ValueError("Original publication and candidate approval are distinct")
        check_review_clocks(self.snapshot.recorded_at, self.governance)
        reasons = [] if self.governance.status == "published" else ["original_not_published"]
        if self.ineligibility_reasons != reasons or self.eligible != (not reasons):
            raise ValueError("Original eligibility must preserve actual publication governance")
        if len(utf8(canonical_json(self))) > MAX_REQUEST_BYTES:
            raise ValueError("Complete response exceeds 8MiB; no original truncation")
        return self


class CandidateRecord(StrictModel):
    schema_version: Literal["document_span_candidate_record_v1"]
    source_id: str
    snapshot: CandidateImmutable
    content_hash: SHA256
    governance: GovernedReview
    governance_hash: SHA256
    original_current: bool
    eligible: bool
    ineligibility_reasons: list[Ineligibility]
    clinical_validation: Literal["not_provided"]

    @model_validator(mode="after")
    def full_binding(self):
        if (
            self.source_id != f"document_candidate:{self.snapshot.candidate_id}:{self.content_hash[:12]}"
            or digest(self.snapshot) != self.content_hash
            or digest(self.governance) != self.governance_hash
        ):
            raise ValueError("Candidate identity and complete hashes must match")
        if self.governance.status == "published":
            raise ValueError("Approval does not itself publish a knowledge document")
        check_review_clocks(self.snapshot.recorded_at, self.governance)
        reasons = ([] if self.original_current else ["original_not_current"]) + ([] if self.governance.status == "approved" else ["candidate_not_approved"])
        if self.ineligibility_reasons != reasons or self.eligible != (not reasons):
            raise ValueError("Candidate eligibility must retain all parent and review gates")
        return self


class PublicationRecord(StrictModel):
    schema_version: Literal["document_knowledge_publication_record_v1"]
    snapshot: PublicationImmutable
    content_hash: SHA256
    governance: PublicationGovernance
    governance_hash: SHA256
    eligible: bool
    ineligibility_reasons: list[Ineligibility]
    clinical_validation: Literal["not_provided"]

    @model_validator(mode="after")
    def full_binding(self):
        if digest(self.snapshot) != self.content_hash or digest(self.governance) != self.governance_hash:
            raise ValueError("Complete publication hashes must match")
        if self.governance.revoked_at is not None and self.governance.revoked_at < self.snapshot.published_at:
            raise ValueError("Publication revocation cannot predate publication")
        if self.eligible != (not self.ineligibility_reasons) or len(self.ineligibility_reasons) != len(set(self.ineligibility_reasons)):
            raise ValueError("Eligibility and all current source gates must agree")
        return self


def check_review_clocks(recorded_at: str, governance: GovernedReview):
    if governance.reviewed_at is not None and governance.reviewed_at < recorded_at:
        raise ValueError("Review cannot predate server registration")
    if governance.revoked_at is not None and governance.revoked_at < (governance.reviewed_at or recorded_at):
        raise ValueError("Revocation cannot predate the actual original or review")


def publication_id_from_uri(uri: str) -> str:
    if not isinstance(uri, str) or not uri.startswith(URI_PREFIX):
        raise ValueError("Not a document-evidence publication URI")
    value = uri[len(URI_PREFIX) :]
    if str(uuid.UUID(value)) != value:
        raise ValueError("A canonical publication UUID is required")
    return value
