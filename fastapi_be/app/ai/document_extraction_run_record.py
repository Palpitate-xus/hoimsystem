"""Closed complete TEXT record with exact receipt and saved-candidate audit IDs."""

from typing import Literal

from pydantic import Field, model_validator

from app.ai import document_evidence_contract as c
from app.ai.document_extraction_result import DocumentExtractionGenerationResult

RUN_RECORD_SCHEMA = "document_extraction_run_record_v1"


class SavedCandidateReference(c.StrictModel):
    candidate_id: c.UUID
    audit_event_id: c.Positive


class DocumentExtractionRunRecord(c.StrictModel):
    schema_version: Literal["document_extraction_run_record_v1"]
    receipt_event_id: c.Positive
    result: DocumentExtractionGenerationResult | None
    saved_candidates: dict[str, SavedCandidateReference] = Field(max_length=64)

    @model_validator(mode="after")
    def exact_saved_ordinals(self):
        count = len(self.result.document_extraction.spans) if self.result is not None else 0
        allowed = {str(index) for index in range(count)}
        if not set(self.saved_candidates) <= allowed:
            raise ValueError("Saved ordinals must identify actual draft spans")
        references = list(self.saved_candidates.values())
        audit_ids = [item.audit_event_id for item in references]
        if self.receipt_event_id in audit_ids or len(set(audit_ids)) != len(audit_ids) or len({item.candidate_id for item in references}) != len(references):
            raise ValueError("Receipt and per-ordinal audit/candidate identities must be distinct")
        return self


def record_marker(value):
    return isinstance(value, dict) and (value.get("schema_version") == RUN_RECORD_SCHEMA or bool({"receipt_event_id", "saved_candidates"} & value.keys()))


def parse_record(value):
    if type(value) is not str or len(c.utf8(value)) > 65535:
        raise ValueError("The whole task record must fit UTF8 TEXT")
    parsed = c.parse_json(value)
    record = DocumentExtractionRunRecord.model_validate(parsed)
    if c.canonical_json(record) != value:
        raise ValueError("The complete record and all scalar types must remain canonical")
    return record


def encode_record(result, receipt_event_id, saved_candidates=None):
    record = DocumentExtractionRunRecord(
        schema_version=RUN_RECORD_SCHEMA,
        receipt_event_id=receipt_event_id,
        result=result,
        saved_candidates={} if saved_candidates is None else saved_candidates,
    )
    value = c.canonical_json(record)
    parse_record(value)
    return value
