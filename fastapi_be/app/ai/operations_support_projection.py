"""Complete public derivatives of an explicit finite operations collection.

The projection neither proves actual authorization nor scans for credentials.
Only an actual registry can establish current publication and independent actors.
"""

import hashlib
import json
from typing import Annotated, Literal

from pydantic import AfterValidator, Field, model_validator

from app.ai import operations_support_contract as c


class ReviewedMember(c.StrictModel):
    original: c.OperationsOriginal
    review: c.DeclaredOperationsReview

    @model_validator(mode="after")
    def entire_binding(self):
        c.verify_declared_review(self.original, self.review)
        return self


class PrivateOperationsCollection(c.StrictModel):
    schema_version: Literal["operations_support_collection_v1"]
    collection_id: c.Identifier
    assembled_at: c.Clock
    requested_by: c.ActorId
    members: Annotated[list[ReviewedMember], Field(min_length=1, max_length=c.MAX_SOURCES)]

    @model_validator(mode="after")
    def finite_whole(self):
        originals, reviews = set(), set()
        for member in self.members:
            if member.original.original_id in originals or member.review.review_id in reviews:
                raise ValueError("Repeated original or review identities cannot be silently merged")
            originals.add(member.original.original_id)
            reviews.add(member.review.review_id)
            if member.review.reviewed_at > self.assembled_at:
                raise ValueError("The assembly cannot precede any selected review")
        _whole_budget(self)
        return self


class ReleasedOperationsDocument(c.StrictModel):
    source_id: c.Identifier
    kind: Literal["diagnostic_log", "runbook", "reference_document"]
    title: c.Title
    declared_component: Annotated[str, Field(strict=True, max_length=120), AfterValidator(c._scalar)] | None
    declared_version: Annotated[str, Field(strict=True, max_length=120), AfterValidator(c._scalar)] | None
    text: c.Text
    text_sha256: c.Digest

    @model_validator(mode="after")
    def exact_text(self):
        if hashlib.sha256(self.text.encode("utf-8")).hexdigest() != self.text_sha256:
            raise ValueError("Released text must match its whole UTF8 digest")
        return self


class OperationsDocumentCounts(c.StrictModel):
    documents: Annotated[int, Field(strict=True, ge=1, le=c.MAX_SOURCES)]
    diagnostic_logs: Annotated[int, Field(strict=True, ge=0, le=c.MAX_SOURCES)]
    runbooks: Annotated[int, Field(strict=True, ge=0, le=c.MAX_SOURCES)]
    reference_documents: Annotated[int, Field(strict=True, ge=0, le=c.MAX_SOURCES)]


class OperationsSupportSource(c.StrictModel):
    schema_version: Literal["operations_support_source_v1"]
    source_id: c.Identifier
    assembled_at: c.Clock
    coverage: Literal["explicit_reviewed_derivatives_only_not_live_system_inventory"]
    applicability: Literal["manual_declarations_not_independent_live_compatibility_proof"]
    action_basis: Literal["reviewed_runbook_reference_only", "missing_reviewed_runbook"]
    counts: OperationsDocumentCounts
    documents: Annotated[list[ReleasedOperationsDocument], Field(min_length=1, max_length=c.MAX_SOURCES)]

    @model_validator(mode="after")
    def closed_projection(self):
        ids = [d.source_id for d in self.documents]
        if ids != sorted(ids) or len(ids) != len(set(ids)):
            raise ValueError("All released documents must have distinct sorted source identities")
        actual = {
            "documents": len(self.documents),
            "diagnostic_logs": sum(d.kind == "diagnostic_log" for d in self.documents),
            "runbooks": sum(d.kind == "runbook" for d in self.documents),
            "reference_documents": sum(d.kind == "reference_document" for d in self.documents),
        }
        if self.counts.model_dump() != actual:
            raise ValueError("Counts must describe every actual selected document")
        expected = "reviewed_runbook_reference_only" if actual["runbooks"] else "missing_reviewed_runbook"
        if self.action_basis != expected:
            raise ValueError("A diagnostic log cannot become an action runbook")
        _whole_budget(self)
        return self


def _whole_budget(value):
    text = c.canonical_json(value)
    if len(text.encode("utf-8")) > c.MAX_WHOLE_BYTES:
        raise ValueError("The complete operations collection or Source exceeds its whole UTF8 budget")
    return text


def _pairs(rows):
    result = {}
    for key, value in rows:
        if key in result:
            raise ValueError("Duplicate JSON member names cannot be silently resolved")
        result[key] = value
    return result


def _invalid_number(value):
    raise ValueError("Nonfinite and fractional JSON numbers are not part of this Source contract")


def _value(value):
    if type(value) is bytes:
        if len(value) > c.MAX_WHOLE_BYTES:
            raise ValueError("The entire UTF8 packet exceeds the operations whole budget")
        value = value.decode("utf-8", errors="strict")
    if type(value) is str:
        if len(value.encode("utf-8", errors="strict")) > c.MAX_WHOLE_BYTES:
            raise ValueError("The entire UTF8 packet exceeds the operations whole budget")
        return json.loads(value, object_pairs_hook=_pairs, parse_constant=_invalid_number, parse_float=_invalid_number)
    return value


def verify_private_collection(value) -> PrivateOperationsCollection:
    return PrivateOperationsCollection.model_validate(_value(value), strict=True)


def project_source(value) -> OperationsSupportSource:
    private = verify_private_collection(value)
    documents = [
        ReleasedOperationsDocument(
            source_id=member.review.review_id,
            kind=member.original.kind,
            title=member.review.released_title,
            declared_component=member.review.released_component,
            declared_version=member.review.released_version,
            text=member.review.released_text,
            text_sha256=hashlib.sha256(member.review.released_text.encode("utf-8")).hexdigest(),
        )
        for member in private.members
    ]
    documents.sort(key=lambda d: d.source_id)
    runbooks = sum(d.kind == "runbook" for d in documents)
    return OperationsSupportSource(
        schema_version="operations_support_source_v1",
        source_id=private.collection_id,
        assembled_at=private.assembled_at,
        coverage="explicit_reviewed_derivatives_only_not_live_system_inventory",
        applicability="manual_declarations_not_independent_live_compatibility_proof",
        action_basis="reviewed_runbook_reference_only" if runbooks else "missing_reviewed_runbook",
        counts=OperationsDocumentCounts(
            documents=len(documents),
            diagnostic_logs=sum(d.kind == "diagnostic_log" for d in documents),
            runbooks=runbooks,
            reference_documents=sum(d.kind == "reference_document" for d in documents),
        ),
        documents=documents,
    )


def projection_digest(value) -> str:
    source = OperationsSupportSource.model_validate(_value(value), strict=True)
    return c.content_hash(source)


def verify_public_source(value, private_collection) -> bool:
    source = OperationsSupportSource.model_validate(_value(value), strict=True)
    expected = project_source(private_collection)
    return _whole_budget(source) == _whole_budget(expected)
