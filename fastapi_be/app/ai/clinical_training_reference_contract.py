"""Private full manual-training references, with a separate model projection.

These packets describe captured state only. SQL must independently establish
current publication, role/epoch, validity and absence of a reserved source link.
"""

import hashlib
from typing import Annotated, Literal

from pydantic import Field, model_validator

from app.ai import clinical_training_contract as c


class ReferenceActor(c.StrictModel):
    user_id: c.ActorId
    user_role: Literal["super_admin"]
    token_invalid_before: c.Clock | None


class KnowledgeMetadata(c.StrictModel):
    document_id: c.Identifier
    title: Annotated[str, Field(strict=True, min_length=1, max_length=200)]
    version: Annotated[str, Field(strict=True, min_length=1, max_length=80)]
    source_uri: Annotated[str, Field(strict=True, min_length=3, max_length=2000)]
    source_kind: None
    source_reference_id: None
    source_snapshot_hash: None
    category: Literal["training"]
    content_hash: c.Digest
    feature_keys_json: str
    department_id: None
    status: Literal["published"]
    effective_from: c.Clock | None
    effective_to: c.Clock | None
    reviewed_by: c.ActorId
    reviewed_at: c.Clock
    created_by: c.ActorId
    create_time: c.Clock

    @model_validator(mode="after")
    def explicit_finite_manual_training(self):
        for value in (self.title, self.version, self.source_uri, self.feature_keys_json):
            c.scalar(value)
        if len(self.feature_keys_json.encode()) > 65535:
            raise ValueError("Entire stored feature selection must fit its actual TEXT")
        features = c.parse_packet(self.feature_keys_json)
        if type(features) is not list or not 1 <= len(features) <= 80 or any(type(item) is not str or not item for item in features) or len(set(features)) != len(features) or "clinical_training" not in features:
            raise ValueError("The exact stored feature array must explicitly include training")
        if self.source_uri.lower().startswith(("hoim://clinical-pathway/", "hoim://document-evidence/")):
            raise ValueError("This finite manual reference contract does not replace native source authorization")
        if self.reviewed_at < self.create_time or self.effective_from is not None and self.effective_to is not None and self.effective_from >= self.effective_to:
            raise ValueError("Stored reference clocks must remain explicit and ordered")
        return self


class TrainingReference(c.StrictModel):
    metadata: KnowledgeMetadata
    author: ReferenceActor
    reviewer: ReferenceActor
    content: str
    content_utf8_sha256: c.Digest

    @model_validator(mode="after")
    def exact_complete_body_and_actors(self):
        raw = self.content.encode("utf-8", errors="strict")
        if not 1 <= len(raw) <= 65535 or hashlib.sha256(raw).hexdigest() != self.content_utf8_sha256 or c.content_hash(self.content) != self.metadata.content_hash:
            raise ValueError("The entire literal reference must match its two declared hash encodings")
        if self.author.user_id != self.metadata.created_by or self.reviewer.user_id != self.metadata.reviewed_by:
            raise ValueError("Actual captured author/reviewer identities must match the document")
        return self


class TrainingReferenceSnapshot(c.StrictModel):
    schema_version: Literal["clinical_training_reference_snapshot_v1"]
    lesson_id: c.Identifier
    captured_by: c.ActorId
    captured_at: c.Clock
    selection_basis: Literal["exact_union_of_all_private_question_reference_ids"]
    references: Annotated[list[TrainingReference], Field(min_length=1, max_length=2048)]
    publication_claim: Literal["stored_manual_training_publication_and_current_actors_not_independent_content_truth"]

    @model_validator(mode="after")
    def complete_sorted_union(self):
        identifiers = [reference.metadata.document_id for reference in self.references]
        if identifiers != sorted(set(identifiers)):
            raise ValueError("References must be one explicit sorted unique selection, without implicit loss")
        for reference in self.references:
            metadata = reference.metadata
            if metadata.reviewed_at > self.captured_at or metadata.effective_from is not None and metadata.effective_from > self.captured_at or metadata.effective_to is not None and metadata.effective_to <= self.captured_at:
                raise ValueError("Every captured reference must be effective at the stated capture clock")
        c.whole(self)
        return self


def model_projection(value):
    """Caller still needs current selected lesson/submission and transfer grant."""
    snapshot = TrainingReferenceSnapshot.model_validate(c.parse_packet(value), strict=True)
    result = {
        "schema_version": "clinical_training_model_references_v1",
        "lesson_id": snapshot.lesson_id,
        "references": [dict(document_id=item.metadata.document_id, title=item.metadata.title, version=item.metadata.version, content=item.content, content_utf8_sha256=item.content_utf8_sha256) for item in snapshot.references],
    }
    c.whole(result)
    return result
