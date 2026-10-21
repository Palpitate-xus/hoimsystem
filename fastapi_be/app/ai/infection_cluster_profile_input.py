"""Recorded local validation scope is distinct from independent publication."""

from typing import Literal

from pydantic import Field, model_validator

from app.ai import infection_cluster_contract as c
from app.ai import infection_cluster_input as source_input
from app.ai import infection_cluster_scenario_input as scenario
from app.ai import infection_cluster_statistics_contract as k

ValidationStatus = Literal["unreviewed", "pilot", "validated", "suspended"]


class InstalledImplementation(c.StrictModel):
    schema_version: Literal["infection_local_implementation_v1"]
    engine: Literal["prediction"]
    execution: Literal["installed_local_exact_integer_statistics_no_external_model"]
    version: Literal["infection_case_set_fisher_v1"]
    recipe_hash: c.SHA
    code_hashes: dict[str, c.SHA]
    local_clinical_validation: Literal["not_provided_by_implementation_identity"]
    automatic_enable: Literal[False]

    @model_validator(mode="after")
    def actual_closed_files(self):
        expected = {"infection_cluster_contract.py", "infection_cluster_projection.py", "infection_cluster_statistics_contract.py", "infection_cluster_statistics.py"}
        if set(self.code_hashes) != expected or self.recipe_hash != c.digest(k.RECIPE):
            raise ValueError("The full fixed arithmetic implementation identity differs")
        return self


class ProfileScope(c.StrictModel):
    definition_id: c.UUID
    definition_content_hash: c.SHA
    definition_governance_hash: c.SHA
    department_ids: list[c.PositiveId] = Field(min_length=1, max_length=k.MAX_COMPARISONS)
    source_window: c.CalendarWindow
    pathogen_codes: list[c.Code] = Field(min_length=1, max_length=c.MAX_ROOTS)
    alpha_decimals: list[str] = Field(min_length=1, max_length=64)
    max_source_records: int = Field(strict=True, ge=1, le=c.MAX_ROOTS)
    max_comparisons: int = Field(strict=True, ge=1, le=k.MAX_COMPARISONS)
    unknown_department_policy: Literal["retain_all_unknown_records_and_exclude_from_inference_not_normal"]
    scope_basis: Literal["only_explicit_source_records_departments_definition_calendar_and_literal_parameters_not_hospital_coverage"]

    @model_validator(mode="after")
    def finite_explicit_scope(self):
        for values in (self.department_ids, self.pathogen_codes, self.alpha_decimals):
            if len(set(values)) != len(values):
                raise ValueError("The reviewed scope is explicit and cannot be silently deduplicated")
        for alpha in self.alpha_decimals:
            k.alpha_fraction(alpha)
        return self


class ProfileCreate(source_input.Basis):
    version_label: str = Field(min_length=1, max_length=100)
    expected_implementation_hash: c.SHA
    scope: ProfileScope
    validation_status: ValidationStatus
    validation_evidence_reference: str | None = Field(max_length=1000)
    validation_basis_note: str = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def validation_is_a_recorded_assertion(self):
        if not self.version_label.strip() or len(c.utf8(self.version_label)) > 400:
            raise ValueError("An explicit bounded version is required")
        source_input.Basis(basis_note=self.validation_basis_note)
        if self.validation_evidence_reference is not None and (not self.validation_evidence_reference.strip() or len(c.utf8(self.validation_evidence_reference)) > 4000):
            raise ValueError("The exact recorded evidence reference is bounded and not empty")
        if self.validation_status in {"pilot", "validated"} and self.validation_evidence_reference is None:
            raise ValueError("Pilot/validated assertions require an explicit recorded evidence reference")
        c.canonical(self)
        return self


class ProfileDepartment(c.StrictModel):
    department_id: c.PositiveId
    recorded_name: str | None = Field(max_length=24)
    directory_hash: c.SHA

    @model_validator(mode="after")
    def narrow_identity(self):
        if self.directory_hash != c.digest({"department_id": self.department_id, "name": self.recorded_name}):
            raise ValueError("The narrow actual Department anchor differs")
        return self


class ProfilePayload(ProfileCreate):
    schema_version: Literal["infection_local_profile_payload_v1"]
    profile_id: c.UUID
    created_by: c.PositiveId
    recorded_at: str
    author_epoch: scenario.ActorEpoch
    implementation_descriptor: InstalledImplementation
    departments: list[ProfileDepartment] = Field(min_length=1, max_length=k.MAX_COMPARISONS)
    directory_hash: c.SHA
    limitations: list[str]
    validation_assertion_basis: Literal["human_recorded_scope_and_evidence_not_code_certification_or_automatic_activation"]

    @model_validator(mode="after")
    def exact_immutable_profile(self):
        c.clock(self.recorded_at)
        if self.created_by != self.author_epoch.user_id or c.digest(self.implementation_descriptor) != self.expected_implementation_hash:
            raise ValueError("The actual author and installed implementation anchors differ")
        if [d.department_id for d in self.departments] != self.scope.department_ids or self.directory_hash != c.digest([d.model_dump(mode="json") for d in self.departments]):
            raise ValueError("Every explicitly selected actual Department is bound in order")
        if self.limitations != k.LIMITATIONS:
            raise ValueError("Method limitations cannot be omitted")
        c.canonical(self)
        return self


class ProfileRecord(c.StrictModel):
    schema_version: Literal["infection_local_profile_record_v1"]
    profile_id: c.UUID
    payload: ProfilePayload
    content_hash: c.SHA
    governance: scenario.ScenarioGovernance
    governance_hash: c.SHA
    eligible: bool = Field(strict=True)
    current_issues: list[Literal["not_published", "author_epoch_changed", "reviewer_epoch_changed", "installed_implementation_changed", "definition_changed", "department_directory_changed"]]
    publication_does_not_enable_execution: Literal[True]
    authority_basis: Literal["current_independent_super_exact_audit_pk_and_installed_identity_not_verified_clinical_validity"]

    @model_validator(mode="after")
    def whole_profile(self):
        if self.profile_id != self.payload.profile_id or self.content_hash != c.digest(self.payload) or self.governance_hash != c.digest(self.governance):
            raise ValueError("The whole immutable profile differs")
        if (self.payload.created_by, self.payload.recorded_at) != (self.governance.created_by, self.governance.recorded_at):
            raise ValueError("Actual author/clock anchors differ")
        if self.eligible != (not self.current_issues) or len(set(self.current_issues)) != len(self.current_issues):
            raise ValueError("Current eligibility and explicit issues differ")
        return self


class LocalConfigWrite(source_input.Basis):
    expected_feature_revision: int = Field(strict=True, ge=0)
    expected_selection_revision: int = Field(strict=True, ge=0)
    profile_id: c.UUID | None
    enabled: bool = Field(strict=True)
    allowed_roles: list[str] = Field(min_length=1, max_length=32)
    validation_status: ValidationStatus
    validation_note: str | None = Field(max_length=5000)
    daily_limit: int = Field(strict=True, ge=1, le=10000)

    @model_validator(mode="after")
    def explicit_activation(self):
        if len(set(self.allowed_roles)) != len(self.allowed_roles):
            raise ValueError("Configured roles cannot be silently deduplicated")
        if self.enabled and (self.profile_id is None or self.validation_status != "validated"):
            raise ValueError("An explicit selected and validated profile is required before activation")
        if self.validation_status in {"pilot", "validated"} and (self.validation_note is None or len(self.validation_note.strip()) < 10):
            raise ValueError("An explicit validation scope and evidence note is required")
        if self.validation_note is not None and len(c.utf8(self.validation_note)) > 20000:
            raise ValueError("The whole original validation note exceeds its UTF8 bound")
        return self
