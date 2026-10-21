"""Public source-registry inputs; actors, clocks and publication are server-owned."""

from typing import Annotated, Literal

from pydantic import AfterValidator, Field, model_validator

from app.ai import operations_support_contract as c

OptionalMetadata = Annotated[str, Field(strict=True, max_length=120), AfterValidator(c._scalar)] | None


class OriginalCreate(c.StrictModel):
    kind: Literal["diagnostic_log", "runbook", "reference_document"]
    title: c.Title
    origin_note: c.Note
    declared_component: OptionalMetadata
    declared_version: OptionalMetadata
    content_text: c.Text


class ReleaseCreate(c.StrictModel):
    original_id: c.Identifier
    original_full_sha256: c.Digest
    released_title: c.Title
    released_component: OptionalMetadata
    released_version: OptionalMetadata
    redactions: Annotated[list[c.Redaction], Field(max_length=4096)]


class ReleaseReview(c.StrictModel):
    revision: Annotated[int, Field(strict=True, ge=1, le=1)]
    decision: Literal["publish", "reject"]
    privacy_reviewed: bool
    faithfulness_reviewed: bool
    applicability_reviewed: bool
    model_processing_allowed: bool
    basis: c.Note

    @model_validator(mode="after")
    def actual_decision(self):
        complete = self.privacy_reviewed and self.faithfulness_reviewed and self.applicability_reviewed
        if (self.decision == "publish") != complete:
            raise ValueError("Publication requires all three explicit reviews; a rejection must record an actual unmet review")
        if self.decision == "reject" and self.model_processing_allowed:
            raise ValueError("Rejected material cannot carry positive model-processing permission")
        return self


class SourceRevoke(c.StrictModel):
    revision: Annotated[int, Field(strict=True, ge=1, le=3)]
    reason: Annotated[str, Field(strict=True, min_length=1, max_length=1000), AfterValidator(c._scalar)]


class CaseCreate(c.StrictModel):
    release_ids: Annotated[list[c.Identifier], Field(min_length=1, max_length=c.MAX_SOURCES)]

    @model_validator(mode="after")
    def distinct_releases(self):
        if len(set(self.release_ids)) != len(self.release_ids):
            raise ValueError("Each selected release must have an explicit distinct identity")
        return self
