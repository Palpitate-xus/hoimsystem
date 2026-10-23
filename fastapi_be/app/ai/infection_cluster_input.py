"""Closed Source requests; these declarations do not establish patient purpose rights."""

from typing import Literal

from pydantic import Field, model_validator

from app.ai import infection_cluster_contract as c

SOURCE_ROLES = frozenset({"super_admin", "admin", "director"})
GOVERNANCE_ROLES = frozenset({"super_admin"})
Purpose = Literal["infection_surveillance_processing", "external_model_transfer"]


class Basis(c.StrictModel):
    basis_note: str = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def explicit_basis(self):
        if not self.basis_note.strip() or len(c.utf8(self.basis_note)) > 4000:
            raise ValueError("An explicit whole basis within1000CP/4000UTF8bytes is required")
        return self


class GrantCreate(Basis):
    patient_id: c.PositiveId
    user_id: c.PositiveId
    purpose: Purpose
    valid_from: str
    valid_to: str

    @model_validator(mode="after")
    def actual_term(self):
        if c.clock(self.valid_to) <= c.clock(self.valid_from):
            raise ValueError("Explicit UTC6 validity must have positive duration")
        return self


class DefinitionCreate(c.StrictModel):
    version_label: str = Field(min_length=1, max_length=100)
    definition_text: str = Field(min_length=1, max_length=c.MAX_BYTES)
    infection_type_codes: list[c.Code] = Field(max_length=c.MAX_ROOTS)
    pathogen_codes: list[c.Code] = Field(max_length=c.MAX_ROOTS)

    @model_validator(mode="after")
    def whole_definition(self):
        if not self.version_label.strip() or not self.definition_text.strip():
            raise ValueError("The definition and its declared version are explicit")
        if len(set(self.infection_type_codes)) != len(self.infection_type_codes) or len(set(self.pathogen_codes)) != len(self.pathogen_codes):
            raise ValueError("Duplicate taxonomy codes are not silently removed")
        c.canonical(self)
        return self


class CAS(Basis):
    expected_revision: c.PositiveId
    expected_content_hash: c.SHA
    expected_governance_hash: c.SHA


class GovernReview(CAS):
    decision: Literal["publish", "reject"]
    privacy_review: Literal["confirmed", "not_confirmed"]
    faithfulness_review: Literal["confirmed", "not_confirmed"]

    @model_validator(mode="after")
    def consistent_decision(self):
        if (self.decision == "publish") != (self.privacy_review == self.faithfulness_review == "confirmed"):
            raise ValueError("Publication requires both actual positive review declarations")
        return self


class TaxonomyProposal(Basis):
    original_state: c.ValueState
    original_value_hash: c.SHA
    assessment: Literal["mapped", "not_mapped", "not_assessed"]
    reviewed_code: c.Code | None

    @model_validator(mode="after")
    def literal_mapping(self):
        if (self.assessment == "mapped") != (self.reviewed_code is not None) or self.assessment == "mapped" and self.original_state != "present":
            raise ValueError("Only explicit present original labels can be mapped")
        return self


class CaseReviewCreate(Basis):
    case_id: c.UUID
    original_content_hash: c.SHA
    definition_id: c.UUID
    definition_content_hash: c.SHA
    definition_governance_hash: c.SHA
    assessment: c.Assessment
    infection_type: TaxonomyProposal
    pathogen: TaxonomyProposal


class SnapshotCreate(c.StrictModel):
    patient_ids: list[c.PositiveId] = Field(min_length=1, max_length=c.MAX_ROOTS)
    window: c.CalendarWindow
    definition_id: c.UUID

    @model_validator(mode="after")
    def explicit_finite_members(self):
        if len(set(self.patient_ids)) != len(self.patient_ids):
            raise ValueError("The explicit patient set cannot contain duplicates")
        return self
