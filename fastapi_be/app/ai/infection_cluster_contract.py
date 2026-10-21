"""Pure finite infection-report records and explicit human review declarations.

These types prove only closed structure, literal bytes and mechanical bindings.
They do not authorize clinical reads, prove real independent publication, validate
surveillance definitions, establish diagnoses, or supply a population denominator.
"""

import datetime as dt
import hashlib
import json
import re
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

MAX_BYTES = 8 * 1024 * 1024
MAX_ROOTS = 4096
MAX_JSON_DEPTH = 32
MAX_JSON_TOKENS = 2000000
SHA = Annotated[str, Field(strict=True, min_length=64, max_length=64, pattern=r"^[a-f0-9]{64}$")]
UUID = Annotated[str, Field(strict=True, min_length=36, max_length=36, pattern=r"^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$")]
PositiveId = Annotated[int, Field(strict=True, ge=1, le=2147483647)]
RawInt = Annotated[int, Field(strict=True, ge=-2147483648, le=2147483647)]
Code = Annotated[str, Field(strict=True, pattern=r"^[A-Z][A-Z0-9_]{0,31}$")]
Assessment = Literal["meets_definition", "does_not_meet", "undetermined", "not_assessed"]
ValueState = Literal["null", "empty", "present"]


def utf8(value: str) -> bytes:
    return value.encode("utf-8", errors="strict")


def clock(value: str) -> dt.datetime:
    if type(value) is not str or re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z", value) is None:
        raise ValueError("An explicit real UTC6 capture/review clock is required")
    return dt.datetime.fromisoformat(value[:-1] + "+00:00")


def day(value: str) -> dt.date:
    if type(value) is not str or re.fullmatch(r"\d{4}-\d{2}-\d{2}", value) is None or dt.date.fromisoformat(value).isoformat() != value:
        raise ValueError("An actual Gregorian date without an invented timezone is required")
    return dt.date.fromisoformat(value)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, revalidate_instances="always")

    @field_validator("*", mode="after")
    @classmethod
    def actual_unicode(cls, value):
        if isinstance(value, str):
            utf8(value)
        return value


def canonical(value) -> str:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    encoder = json.JSONEncoder(ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    chunks, size = [], 0
    for chunk in encoder.iterencode(value):
        size += len(utf8(chunk))
        if size > MAX_BYTES:
            raise ValueError("The complete canonical object exceeds8MiB; no clipping is permitted")
        chunks.append(chunk)
    return "".join(chunks)


def digest(value) -> str:
    return hashlib.sha256(utf8(canonical(value))).hexdigest()


def text_digest(value: str) -> str:
    return hashlib.sha256(utf8(value)).hexdigest()


def value_state(value: str | None) -> str:
    return "null" if value is None else "empty" if value == "" else "present"


class LegacyClock(StrictModel):
    text: str
    basis: Literal["stored_naive_timezone_unknown"]

    @field_validator("text")
    @classmethod
    def retain_naive(cls, value):
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?", value) is None or dt.datetime.fromisoformat(value).tzinfo is not None:
            raise ValueError("Retain the stored naive datetime text without adding UTC")
        return value


class InfectionCaseOriginal(StrictModel):
    case_id: UUID
    patient_id: PositiveId
    department_id: PositiveId | None
    infection_type: str = Field(max_length=100)
    pathogen: str | None = Field(max_length=100)
    onset_date: str
    severity: RawInt
    status: RawInt
    description: str | None = Field(max_length=500)
    reporter_id: PositiveId
    create_time: LegacyClock
    update_time: LegacyClock

    @field_validator("onset_date")
    @classmethod
    def actual_onset_day(cls, value):
        day(value)
        return value


class OriginalProof(StrictModel):
    original: InfectionCaseOriginal
    content_hash: SHA

    @model_validator(mode="after")
    def complete_hash(self):
        if digest(self.original) != self.content_hash:
            raise ValueError("The complete original row canonical hash differs")
        return self


class DefinitionPayload(StrictModel):
    definition_id: UUID
    version_label: str = Field(min_length=1, max_length=100)
    definition_text: str = Field(min_length=1, max_length=MAX_BYTES)
    infection_type_codes: list[Code] = Field(max_length=MAX_ROOTS)
    pathogen_codes: list[Code] = Field(max_length=MAX_ROOTS)
    authored_by: PositiveId
    recorded_at: str
    authority_basis: Literal["local_human_declaration_not_official_or_clinically_validated"]

    @model_validator(mode="after")
    def declared_version(self):
        clock(self.recorded_at)
        if not self.version_label.strip() or not self.definition_text.strip():
            raise ValueError("A declared version and whole definition text are explicit, never defaulted")
        for values in (self.infection_type_codes, self.pathogen_codes):
            if len(set(values)) != len(values):
                raise ValueError("Declared taxonomy codes cannot be silently deduplicated")
        canonical(self)
        return self


class DefinitionGovernance(StrictModel):
    status: Literal["published"]
    revision: Annotated[int, Field(strict=True, ge=2, le=2)]
    definition_content_hash: SHA
    published_by: PositiveId
    published_at: str
    publication_basis_note: str = Field(min_length=1, max_length=4000)
    publication_basis_hash: SHA
    verification_basis: Literal["declared_actor_and_clock_structure_only_not_current_authority"]

    @model_validator(mode="after")
    def complete_basis(self):
        clock(self.published_at)
        if not self.publication_basis_note.strip() or len(utf8(self.publication_basis_note)) > 16000 or text_digest(self.publication_basis_note) != self.publication_basis_hash:
            raise ValueError("The whole explicit publication basis UTF8 hash differs")
        return self


class PublishedDefinition(StrictModel):
    payload: DefinitionPayload
    content_hash: SHA
    governance: DefinitionGovernance
    governance_hash: SHA

    @model_validator(mode="after")
    def declared_independent_publication(self):
        if self.governance.definition_content_hash != self.content_hash:
            raise ValueError("The publication declaration binds the exact complete definition content hash")
        if digest(self.payload) != self.content_hash or digest(self.governance) != self.governance_hash:
            raise ValueError("The complete definition/version or governance hash differs")
        if self.payload.authored_by == self.governance.published_by or clock(self.governance.published_at) < clock(self.payload.recorded_at):
            raise ValueError("Declared distinct actors and ordered clocks are required, not proof of actual authority")
        return self


class ReviewStamp(StrictModel):
    reviewed_by: PositiveId | None
    reviewed_at: str | None
    basis_note: str | None = Field(max_length=4000)
    basis_hash: SHA | None

    @model_validator(mode="after")
    def exact_optional_basis(self):
        fields = (self.reviewed_by, self.reviewed_at, self.basis_note, self.basis_hash)
        if all(value is None for value in fields):
            return self
        if any(value is None for value in fields) or not self.basis_note.strip() or len(utf8(self.basis_note)) > 16000 or text_digest(self.basis_note) != self.basis_hash:
            raise ValueError("A recorded review retains all actor/clock/whole private basis/hash fields")
        clock(self.reviewed_at)
        return self


class TaxonomyReview(StrictModel):
    field: Literal["infection_type", "pathogen"]
    original_state: ValueState
    original_value_hash: SHA
    assessment: Literal["mapped", "not_mapped", "not_assessed"]
    reviewed_code: Code | None
    review: ReviewStamp

    @model_validator(mode="after")
    def explicit_mapping(self):
        if (self.assessment == "mapped") != (self.reviewed_code is not None):
            raise ValueError("Only an explicit reviewed mapping may carry a declared local code")
        if self.assessment == "mapped" and self.original_state != "present":
            raise ValueError("NULL or empty original labels must not become a pathogen or infection code")
        if self.assessment != "not_assessed" and self.review.reviewed_by is None:
            raise ValueError("A mapping decision needs its own explicit recorded basis")
        return self


class CaseReview(StrictModel):
    case_id: UUID
    original_content_hash: SHA
    definition_content_hash: SHA
    definition_governance_hash: SHA
    assessment: Assessment
    review: ReviewStamp
    infection_type: TaxonomyReview
    pathogen: TaxonomyReview

    @model_validator(mode="after")
    def explicit_assessment(self):
        if self.assessment != "not_assessed" and self.review.reviewed_by is None:
            raise ValueError("Human case classification cannot be inferred without its explicit review basis")
        if self.infection_type.field != "infection_type" or self.pathogen.field != "pathogen":
            raise ValueError("Each original label has exactly its own taxonomy review")
        return self


class CalendarWindow(StrictModel):
    date_from: str
    date_to: str
    coordinate_basis: Literal["recorded_onset_date_inclusive_no_event_timezone"]

    @model_validator(mode="after")
    def ordered(self):
        if day(self.date_from) > day(self.date_to):
            raise ValueError("The finite explicit onset-date window is inclusive and ordered")
        return self


class PrivateCollection(StrictModel):
    schema_version: Literal["infection_cluster_private_collection_v1"]
    collection_id: UUID
    captured_at: str
    patient_ids: list[PositiveId] = Field(min_length=1, max_length=MAX_ROOTS)
    window: CalendarWindow
    definition: PublishedDefinition
    originals: list[OriginalProof] = Field(max_length=MAX_ROOTS)
    reviews: list[CaseReview] = Field(max_length=MAX_ROOTS)
    declared_capture_scope: Literal["all_infection_case_rows_for_explicit_patients_and_onset_window_all_statuses"]
    completeness_basis: Literal["caller_declared_requires_later_server_current_collection_proof"]

    @model_validator(mode="after")
    def complete_mechanical_binding(self):
        captured = clock(self.captured_at)
        if len(set(self.patient_ids)) != len(self.patient_ids):
            raise ValueError("The declared patient list must not silently deduplicate")
        ids = [item.original.case_id for item in self.originals]
        reviewed_ids = [item.case_id for item in self.reviews]
        if len(set(ids)) != len(ids) or len(set(reviewed_ids)) != len(reviewed_ids) or set(ids) != set(reviewed_ids):
            raise ValueError("Every original root needs exactly one review, including explicit not_assessed")
        if clock(self.definition.governance.published_at) > captured:
            raise ValueError("A captured definition declaration cannot be published after capture")
        reviews = {item.case_id: item for item in self.reviews}
        patients = set(self.patient_ids)
        for proof in self.originals:
            row, review = proof.original, reviews[proof.original.case_id]
            if row.patient_id not in patients or not self.window.date_from <= row.onset_date <= self.window.date_to:
                raise ValueError("No root may escape the explicit patient/calendar scope")
            if (
                review.original_content_hash != proof.content_hash
                or review.definition_content_hash != self.definition.content_hash
                or review.definition_governance_hash != self.definition.governance_hash
            ):
                raise ValueError("Every case review binds the complete original and exact published definition")
            for name in ("infection_type", "pathogen"):
                mapping = getattr(review, name)
                raw = getattr(row, name)
                if mapping.original_state != value_state(raw) or mapping.original_value_hash != digest(raw):
                    raise ValueError("Taxonomy reviews retain exact NULL/empty/literal labels without normalization")
                codes = self.definition.payload.infection_type_codes if name == "infection_type" else self.definition.payload.pathogen_codes
                if mapping.reviewed_code is not None and mapping.reviewed_code not in codes:
                    raise ValueError("A mapped code must belong to the explicit published local taxonomy")
            for stamp in (review.review, review.infection_type.review, review.pathogen.review):
                if stamp.reviewed_at is not None and (clock(stamp.reviewed_at) < clock(self.definition.governance.published_at) or clock(stamp.reviewed_at) > captured):
                    raise ValueError("A recorded case/mapping review must follow its declared definition and precede capture")
        canonical(self)
        return self


def _pairs(values):
    result = {}
    for key, value in values:
        if key in result:
            raise ValueError("Duplicate JSON keys are not a complete immutable original")
        result[key] = value
    return result


def _nonfinite(value):
    raise ValueError("Nonfinite JSON scalars are not original SQL integer fields")


def _lexical_budget(raw: str):
    depth = tokens = 0
    string = escaped = False
    for char in raw:
        if string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                string = False
        elif char == '"':
            tokens += 1
            string = True
        elif char in "[{":
            depth += 1
            tokens += 1
            if depth > MAX_JSON_DEPTH:
                raise ValueError("Whole JSON nesting exceeds the declared pure budget")
        elif char in "]}":
            depth -= 1
        elif char in ":,":
            tokens += 1
        if tokens > MAX_JSON_TOKENS:
            raise ValueError("Whole JSON lexical work exceeds the declared pure budget")


def verify_private_collection(value) -> PrivateCollection:
    """Mechanical verification only; no current SQL, completeness or permission claim."""
    if isinstance(value, (str, bytes)):
        if isinstance(value, bytes):
            if not 0 < len(value) <= MAX_BYTES:
                raise ValueError("The complete original JSON bytes exceed8MiB")
            value = value.decode("utf-8", errors="strict")
        if not 0 < len(utf8(value)) <= MAX_BYTES:
            raise ValueError("The complete original JSON bytes exceed8MiB")
        _lexical_budget(value)
        value = json.loads(value, object_pairs_hook=_pairs, parse_constant=_nonfinite)
    elif isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    canonical(value)
    return PrivateCollection.model_validate(value, strict=True)
