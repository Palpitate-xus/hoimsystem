"""Mechanical minimum projection of a verified finite reported-case collection.

The caller supplies and must privately retain a per-Source32-byte mapping key.
This helper neither manages that key nor grants current patient/model authority.
Opaque hashes cannot be independently rebuilt by a client lacking private roots.
"""

import hashlib
import hmac
from collections import Counter
from typing import Annotated, Literal

from pydantic import Field, model_validator

from app.ai import infection_cluster_contract as c

Count = Annotated[int, Field(strict=True, ge=0, le=c.MAX_ROOTS)]
MissingBasis = Literal[
    "department_not_recorded",
    "infection_type_empty",
    "pathogen_null",
    "pathogen_empty",
    "case_review_not_assessed",
    "case_review_undetermined",
    "case_review_basis_not_provided",
    "infection_type_code_not_mapped",
    "pathogen_code_not_mapped",
    "legacy_event_timezone_unknown",
]
LIMITATIONS = [
    "Only all caller-declared InfectionCase roots for this explicit patient set and onset-date window are represented; no hospital-wide surveillance coverage is established.",
    "Recorded workflow status is not a diagnosis, laboratory finding, independent case classification or resolution of infection.",
    "Case classifications and local taxonomy codes are explicit human declarations against this exact definition; pure hashes and distinct actor IDs do not prove real publication or clinical validity.",
    "Onset is a stored calendar date; legacy create/update clocks have unknown timezone and are not historical availability or UTC event timestamps.",
    "No population denominator was provided; distinct selected or observed subjects must not become a denominator, rate, probability or outbreak determination.",
    "Admission linkage, pathogen laboratory determination and validated signal modelling are not provided by the legacy table.",
    "Multiple reports for the same patient remain distinct records; no duplicate-infection or repeat-event merging is performed.",
    "HMAC tokens are pseudonymous technical references, not an anonymity guarantee; the private mapping key and original rows remain server-side.",
    "This mechanical projection grants no clinical read, model execution, independent review, export or intervention permission.",
]


class DefinitionReference(c.StrictModel):
    definition_token: c.SHA
    version_hash: c.SHA
    content_hash: c.SHA
    governance_hash: c.SHA
    publication_basis_hash: c.SHA
    authority_basis: Literal["local_human_declaration_not_official_or_clinically_validated"]
    verification_basis: Literal["declared_actor_and_clock_structure_only_not_current_authority"]
    taxonomy_basis: Literal["local_reviewed_codes_no_automatic_label_normalization"]


class Scope(c.StrictModel):
    kind: Literal["finite_explicit_patient_set"]
    patient_tokens: list[c.SHA] = Field(min_length=1, max_length=c.MAX_ROOTS)
    window: c.CalendarWindow
    coverage_basis: Literal["caller_declared_requires_later_server_current_collection_proof"]

    @model_validator(mode="after")
    def unique_tokens(self):
        if len(set(self.patient_tokens)) != len(self.patient_tokens):
            raise ValueError("Explicit subject tokens cannot be silently deduplicated")
        return self


class Taxonomy(c.StrictModel):
    original_state: c.ValueState
    assessment: Literal["mapped", "not_mapped", "not_assessed"]
    reviewed_code: c.Code | None
    basis_hash: c.SHA | None
    review_hash: c.SHA

    @model_validator(mode="after")
    def explicit_code(self):
        if (self.assessment == "mapped") != (self.reviewed_code is not None) or self.assessment == "mapped" and (self.original_state != "present" or self.basis_hash is None):
            raise ValueError("Only a literal reviewed present label has an explicit local code")
        if self.assessment == "not_mapped" and self.basis_hash is None:
            raise ValueError("An explicit not-mapped decision retains its actual basis hash")
        return self


class Report(c.StrictModel):
    case_token: c.SHA
    patient_token: c.SHA
    department_token: c.SHA | None
    original_content_hash: c.SHA
    case_review_hash: c.SHA
    onset_date: str
    human_assessment: c.Assessment
    assessment_basis_hash: c.SHA | None
    infection_type: Taxonomy
    pathogen: Taxonomy
    recorded_status: c.RawInt
    recorded_status_meaning: Literal["reported", "investigating", "closed_recorded", "unknown"]
    status_basis: Literal["recorded_workflow_not_diagnosis_or_human_definition_assessment"]
    missing_basis: list[MissingBasis] = Field(max_length=10)

    @model_validator(mode="after")
    def literal_calendar_and_recorded_status(self):
        c.day(self.onset_date)
        meaning = {0: "reported", 1: "investigating", 2: "closed_recorded"}.get(self.recorded_status, "unknown")
        if meaning != self.recorded_status_meaning or len(set(self.missing_basis)) != len(self.missing_basis):
            raise ValueError("Only the known workflow integers are labelled; missing bases are unique")
        if self.human_assessment != "not_assessed" and self.assessment_basis_hash is None:
            raise ValueError("A human assessment requires its independently bound basis")
        return self


class Counts(c.StrictModel):
    distinct_records: Count
    distinct_subjects_with_records: Count
    declared_subjects: Count
    meets_definition: Count
    does_not_meet: Count
    undetermined: Count
    not_assessed: Count
    counting_basis: Literal["separate_report_records_and_distinct_recorded_subjects_neither_is_a_population_denominator"]


class Denominator(c.StrictModel):
    status: Literal["not_provided"]
    reason: Literal["legacy_infection_case_has_no_surveillance_population_denominator"]


class InfectionClusterSource(c.StrictModel):
    schema_version: Literal["infection_cluster_source_v1"]
    source_id: str = Field(pattern=r"^infection_reports:[a-f0-9]{64}:[a-f0-9]{12}$", max_length=95)
    private_collection_hash: c.SHA
    captured_at: str
    scope: Scope
    definition: DefinitionReference
    reports: list[Report] = Field(max_length=c.MAX_ROOTS)
    counts: Counts
    denominator: Denominator
    clinical_interpretation: Literal["not_a_diagnosis_or_outbreak_determination"]
    automatic_actions: bool = Field(strict=True)
    privacy_basis: Literal["technical_tokens_only_private_ids_and_free_original_text_not_projected_not_anonymity_assurance"]
    limitations: list[str] = Field(min_length=len(LIMITATIONS), max_length=len(LIMITATIONS))

    @model_validator(mode="after")
    def exact_counts_and_closed_scope(self):
        c.clock(self.captured_at)
        if self.automatic_actions is not False or self.limitations != LIMITATIONS:
            raise ValueError("No automatic action or replacement of the declared limitations is supported")
        if len({r.case_token for r in self.reports}) != len(self.reports):
            raise ValueError("No report can be silently deduplicated")
        subjects = {r.patient_token for r in self.reports}
        if not subjects.issubset(self.scope.patient_tokens) or any(not self.scope.window.date_from <= r.onset_date <= self.scope.window.date_to for r in self.reports):
            raise ValueError("All public records belong to the exact explicit scope")
        actual = Counter(r.human_assessment for r in self.reports)
        if (
            self.counts.distinct_records != len(self.reports)
            or self.counts.distinct_subjects_with_records != len(subjects)
            or self.counts.declared_subjects != len(self.scope.patient_tokens)
            or any(getattr(self.counts, name) != actual[name] for name in ("meets_definition", "does_not_meet", "undetermined", "not_assessed"))
        ):
            raise ValueError("Record/subject counts and all human classification counts must be exact")
        c.canonical(self)
        return self


def _key(value):
    if type(value) is not bytes or len(value) != 32:
        raise ValueError("The caller must provide exactly32 private bytes; the key is never part of the Source")
    return value


def _token(key, collection, collection_hash, kind, value):
    raw = c.canonical(["infection_cluster_mapping_v1", collection.collection_id, collection_hash, kind, value])
    return hmac.new(key, c.utf8(raw), hashlib.sha256).hexdigest()


def _taxonomy(value):
    return {"original_state": value.original_state, "assessment": value.assessment, "reviewed_code": value.reviewed_code, "basis_hash": value.review.basis_hash, "review_hash": c.digest(value)}


def _missing(row, review):
    values = []
    if row.department_id is None:
        values.append("department_not_recorded")
    if row.infection_type == "":
        values.append("infection_type_empty")
    if row.pathogen is None:
        values.append("pathogen_null")
    elif row.pathogen == "":
        values.append("pathogen_empty")
    if review.assessment == "not_assessed":
        values.append("case_review_not_assessed")
    elif review.assessment == "undetermined":
        values.append("case_review_undetermined")
    if review.review.basis_hash is None:
        values.append("case_review_basis_not_provided")
    for name in ("infection_type", "pathogen"):
        if getattr(review, name).assessment != "mapped":
            values.append(name + "_code_not_mapped")
    values.append("legacy_event_timezone_unknown")
    return values


def project_source(value, private_key: bytes) -> InfectionClusterSource:
    """Project validated private facts mechanically; never imply current authority."""
    key, collection = _key(private_key), c.verify_private_collection(value)
    collection_hash = c.digest(collection)

    def token(kind, value):
        return _token(key, collection, collection_hash, kind, value)

    definition, governance = collection.definition.payload, collection.definition.governance
    reviews = {r.case_id: r for r in collection.reviews}
    reports = []
    for proof in collection.originals:
        row, review = proof.original, reviews[proof.original.case_id]
        reports.append(
            {
                "case_token": token("case", row.case_id),
                "patient_token": token("patient", row.patient_id),
                "department_token": None if row.department_id is None else token("department", row.department_id),
                "original_content_hash": proof.content_hash,
                "case_review_hash": c.digest(review),
                "onset_date": row.onset_date,
                "human_assessment": review.assessment,
                "assessment_basis_hash": review.review.basis_hash,
                "infection_type": _taxonomy(review.infection_type),
                "pathogen": _taxonomy(review.pathogen),
                "recorded_status": row.status,
                "recorded_status_meaning": {0: "reported", 1: "investigating", 2: "closed_recorded"}.get(row.status, "unknown"),
                "status_basis": "recorded_workflow_not_diagnosis_or_human_definition_assessment",
                "missing_basis": _missing(row, review),
            }
        )
    actual = Counter(r.assessment for r in collection.reviews)
    result = InfectionClusterSource.model_validate(
        {
            "schema_version": "infection_cluster_source_v1",
            "source_id": f"infection_reports:{token('collection', collection.collection_id)}:{collection_hash[:12]}",
            "private_collection_hash": collection_hash,
            "captured_at": collection.captured_at,
            "scope": {
                "kind": "finite_explicit_patient_set",
                "patient_tokens": [token("patient", p) for p in collection.patient_ids],
                "window": collection.window.model_dump(mode="json"),
                "coverage_basis": collection.completeness_basis,
            },
            "definition": {
                "definition_token": token("definition", definition.definition_id),
                "version_hash": c.text_digest(definition.version_label),
                "content_hash": collection.definition.content_hash,
                "governance_hash": collection.definition.governance_hash,
                "publication_basis_hash": governance.publication_basis_hash,
                "authority_basis": definition.authority_basis,
                "verification_basis": governance.verification_basis,
                "taxonomy_basis": "local_reviewed_codes_no_automatic_label_normalization",
            },
            "reports": reports,
            "counts": {
                "distinct_records": len(reports),
                "distinct_subjects_with_records": len({p.original.patient_id for p in collection.originals}),
                "declared_subjects": len(collection.patient_ids),
                **{name: actual[name] for name in ("meets_definition", "does_not_meet", "undetermined", "not_assessed")},
                "counting_basis": "separate_report_records_and_distinct_recorded_subjects_neither_is_a_population_denominator",
            },
            "denominator": {"status": "not_provided", "reason": "legacy_infection_case_has_no_surveillance_population_denominator"},
            "clinical_interpretation": "not_a_diagnosis_or_outbreak_determination",
            "automatic_actions": False,
            "privacy_basis": "technical_tokens_only_private_ids_and_free_original_text_not_projected_not_anonymity_assurance",
            "limitations": list(LIMITATIONS),
        },
        strict=True,
    )
    return result


def projection_digest(value) -> str:
    return c.digest(value)


def verify_public_source(value, private_collection, private_key: bytes) -> bool:
    """Exact re-projection requires the actual private roots and retained key."""
    try:
        original = value.model_dump(mode="json") if isinstance(value, InfectionClusterSource) else value
        typed = InfectionClusterSource.model_validate(original, strict=True)
        return c.canonical(original) == c.canonical(typed) == c.canonical(project_source(private_collection, private_key))
    except (ValueError, TypeError, UnicodeError, RecursionError):
        return False
