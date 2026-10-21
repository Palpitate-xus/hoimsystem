"""Closed private requests; local rule snapshots are never official groupers."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.ai.supply_source_input import SourceReview, SourceRevoke, check_basis

UUID = Annotated[str, Field(pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")]
SHA = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Positive = Annotated[int, Field(strict=True, gt=0, le=2147483647)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class CaptureRequest(StrictModel):
    patient_id: Positive
    admission_id: UUID
    home_id: UUID
    rule_package_id: UUID | None
    expected_rule_package_content_hash: SHA | None
    expected_rule_package_governance_hash: SHA | None

    @model_validator(mode="after")
    def package_binding(self):
        if len({self.rule_package_id is None, self.expected_rule_package_content_hash is None, self.expected_rule_package_governance_hash is None}) != 1:
            raise ValueError("An optional package requires all immutable and governance anchors")
        return self


class CaseCreate(StrictModel):
    request: CaptureRequest
    expected_collection_digest: SHA
    note: str = Field(max_length=4000)

    @model_validator(mode="after")
    def note_bytes(self):
        if len(self.note.encode()) > 4000:
            raise ValueError("Private note exceeds4000UTF8bytes")
        return self


class RulePackageCreate(StrictModel):
    package_kind: Literal["local_prefix_snapshot"]
    rule_ids: list[Positive] = Field(min_length=1, max_length=4096)
    basis_note: str = Field(min_length=20, max_length=4000)

    @model_validator(mode="after")
    def original_rules(self):
        check_basis(self.basis_note)
        if len(set(self.rule_ids)) != len(self.rule_ids):
            raise ValueError("Explicit original rule identifiers cannot repeat")
        return self


SOURCE_ROLES = frozenset({"admin", "super_admin", "doctor", "director"})
__all__ = ["CaptureRequest", "CaseCreate", "RulePackageCreate", "SourceReview", "SourceRevoke", "SOURCE_ROLES"]
