"""Exact usage-event accounting, without Source or result-content validation.

This reader validates the concrete FK, Audit header, closed domain receipt,
owner, lease, counters and opaque artifact identities. It deliberately does
not certify clinical content or recompute hashes over private Run/Source text.
All statements run in the caller's coherent, unlocked administrative snapshot.
"""

import importlib
import json
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import BigInteger, case, cast, func, literal, select

from app.ai.charge_reconciliation_view_contract import ChargeUsage
from app.ai.document_evidence_contract import SHA256, UUID
from app.ai.models import AIAuditEvent, AIRun
from app.ai.rca_evidence_storage_contract import RcaUsageEvent
from app.sql_json import json_extract, json_integer, json_type, json_valid
from app.sql_text import UTF8Bytes

MAX_RECEIPT_BYTES = 65535


class DocumentUsageEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    schema_version: Literal["document_extraction_receipt_v1"]
    lease_token: UUID | None
    usage: ChargeUsage
    result_hash: SHA256 | None
    error_code: str | None = Field(max_length=80)


class DeidentificationUsageEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    schema_version: Literal["deidentification_usage_receipt_v1"]
    run_id: UUID
    lease: UUID | None
    status: Literal["succeeded", "failed", "cancelled"]
    usage: ChargeUsage
    result_hash: SHA256 | None
    error_code: str | None = Field(max_length=80)


class RcaAccountingEvent(RcaUsageEvent):
    recorded_at_utc6: str = Field(max_length=40)
    audit_clock_basis: Literal["legacy_utc_second_storage"]

    @model_validator(mode="after")
    def original_audit_clock(self):
        if self.recorded_at_utc6 != self.recorded_at:
            raise ValueError("RCA usage and original UTC6 Audit clock differ")
        return self


@dataclass(frozen=True)
class ReceiptSpec:
    model_module: str
    model_name: str
    schema: str
    action: str | dict
    columns: tuple
    fk: str = "usage_event_id"
    result_model: str | None = None
    result_columns: tuple = ()

    def parser(self):
        return getattr(importlib.import_module(self.model_module), self.model_name)


SPECS = {
    "charge": ReceiptSpec(
        "app.ai.charge_reconciliation_view_contract",
        "ChargeReceiptEvent",
        "charge_reconciliation_receipt_v1",
        {"succeeded": "run.charge_reconciliation.accept", "failed": "run.charge_reconciliation.fail", "cancelled": "run.charge_reconciliation.cancel"},
        ("receipt_event_id", "accepted_lease", "result_hash", "source_binding_hash"),
        fk="receipt_event_id",
    ),
    "satisfaction": ReceiptSpec(
        "app.ai.satisfaction_receipts",
        "SatisfactionUsageEvent",
        "satisfaction_usage_receipt_v1",
        {"succeeded": "run.satisfaction.usage.accept", "failed": "run.satisfaction.usage.fail", "cancelled": "run.satisfaction.usage.cancel"},
        ("usage_event_id", "accepted_lease", "result_hash", "source_binding_hash"),
    ),
    "document": ReceiptSpec(
        __name__,
        "DocumentUsageEvent",
        "document_extraction_receipt_v1",
        {"succeeded": "run.document_extraction.accept", "failed": "run.document_extraction.fail", "cancelled": "run.document_extraction.cancel"},
        (),
    ),
    "drug_label": ReceiptSpec(
        "app.ai.drug_label_run_contract",
        "DrugLabelUsageReceipt",
        "drug_label_usage_receipt_v1",
        "run.drug_label.usage",
        ("receipt_event_id", "accepted_lease", "result_hash", "source_binding_hash", "input_hash", "evidence_hash", "metadata_hash"),
        fk="receipt_event_id",
    ),
    "document_change": ReceiptSpec(
        "app.ai.document_change_result_storage",
        "Receipt",
        "document_change_usage_v2",
        "run.document_change.usage",
        ("usage_event_id",),
        result_model="AIDocumentChangeRunResult",
        result_columns=("content_hash", "lease_token"),
    ),
    "research_cohort": ReceiptSpec(
        "app.ai.research_cohort_receipts",
        "ResearchUsageEvent",
        "research_usage_event_v1",
        "research.task.usage",
        ("usage_event_id", "dispatch_event_id", "source_binding_hash"),
        result_model="AIResearchCohortRunResult",
        result_columns=("content_hash", "lease_token"),
    ),
    "deidentification": ReceiptSpec(
        __name__,
        "DeidentificationUsageEvent",
        "deidentification_usage_receipt_v1",
        "deidentification.task.usage",
        ("source_binding_hash",),
        result_model="AIDeidentificationRunResult",
        result_columns=("usage_event_id", "accepted_lease", "result_hash"),
    ),
    "operations_support": ReceiptSpec(
        "app.ai.operations_support_receipts",
        "OperationsUsageEvent",
        "operations_support_usage_event_v1",
        "operations.task.usage",
        ("usage_event_id", "case_id", "created_audit_event_id", "claim_event_id", "dispatch_event_id", "source_projection_hash", "source_binding_hash", "instructions_digest"),
        result_model="AIOperationsRunResult",
        result_columns=("result_hash", "lease_token"),
    ),
    "clinical_training": ReceiptSpec(
        "app.ai.clinical_training_receipts",
        "TrainingUsageEvent",
        "clinical_training_usage_event_v1",
        "training.task.usage",
        ("usage_event_id", "submission_id", "created_audit_event_id", "claim_event_id", "dispatch_event_id", "lease_token", "source_projection_hash", "source_binding_hash", "instructions_digest"),
        result_model="AITrainingRunResult",
        result_columns=("result_hash", "lease_token"),
    ),
    "rca": ReceiptSpec(
        __name__,
        "RcaAccountingEvent",
        "rca_evidence_usage_receipt_v1",
        "rca_run.usage",
        ("usage_event_id", "case_id", "claim_event_id", "dispatch_event_id", "claim_lease", "binding_hash", "source_hash"),
        result_model="AIRcaEvidenceRunResult",
        result_columns=("result_hash", "accepted_lease"),
    ),
    "infection": ReceiptSpec("app.ai.infection_cluster_task_contract", "LocalUsage", "infection_local_usage_v1", "run.infection_cluster.usage", ("usage_event_id", "accepted_lease", "result_hash")),
    "research_variables": ReceiptSpec(
        "app.ai.research_variables_receipts",
        "VariableReceiptRecord",
        "research_variable_usage_event_v1",
        "research_variable_run.usage",
        ("usage_event_id", "batch_id", "create_event_id", "claim_event_id", "dispatch_event_id", "claim_lease", "source_hash", "instructions_digest"),
        result_model="AIResearchVariableRunResult",
        result_columns=("accept_audit_event_id",),
    ),
}


def json_scalar(snapshot, column, path):
    # CASE makes malformed historical TEXT harmless before JSON functions run.
    safe = case((json_valid(column) == 1, column), else_=literal("{}"))
    value = json_extract(safe, path)
    if snapshot._connection.dialect.name in {"mysql", "mariadb"}:
        value = func.json_unquote(value)
    return value


def _document_fk(snapshot):
    safe = case((json_valid(AIRun.result_json) == 1, AIRun.result_json), else_=literal("{}"))
    extracted = json_extract(safe, "$.receipt_event_id")
    mysql = snapshot._connection.dialect.name in {"mysql", "mariadb"}
    kind = json_type(extracted) if mysql else json_type(safe, "$.receipt_event_id")
    scalar = func.json_unquote(extracted) if mysql else extracted
    identifier = json_integer(cast(scalar, BigInteger), safe, "$.receipt_event_id")
    return case(
        (
            (json_scalar(snapshot, AIRun.result_json, "$.schema_version") == "document_extraction_run_record_v1")
            & (kind == ("INTEGER" if mysql else "integer"))
            & (func.length(scalar) <= 10)
            & (identifier > 0)
            & (identifier <= 2147483647),
            identifier,
        ),
        else_=None,
    ).label("usage_event_id")


def artifact_headers(snapshot, ids, domains):
    if {name for name, _, _ in domains} != set(SPECS):
        raise RuntimeError("Every native domain needs an explicit usage-event adapter")
    headers = {}
    for domain, model, _ in domains:
        spec = SPECS[domain]
        columns = [AIRun.run_id.label("parent_id"), model.run_id, model.requested_by, *(getattr(model, name) for name in spec.columns)]
        if domain == "document":
            columns.append(_document_fk(snapshot))
        for row in snapshot.execute(select(*columns).select_from(AIRun).join(model, model.run_id == AIRun.run_id).where(AIRun.run_id.in_(ids))).mappings():
            header = dict(row)
            headers.setdefault(row["parent_id"], []).append((domain, header))
        if spec.result_model:
            result = getattr(importlib.import_module(model.__module__), spec.result_model)
            rows = snapshot.execute(
                select(AIRun.run_id.label("parent_id"), result.run_id, *(getattr(result, name) for name in spec.result_columns))
                .select_from(AIRun)
                .join(result, result.run_id == AIRun.run_id)
                .where(AIRun.run_id.in_(ids))
            ).mappings()
            for row in rows:
                for name, header in headers.get(row["parent_id"], []):
                    if name == domain:
                        header["result"] = dict(row)
    return headers


def receipt_fk(domain, artifact):
    spec = SPECS[domain]
    source = artifact.get("result", {}) if domain == "deidentification" else artifact
    return source.get(spec.fk)


def action_for(domain, status):
    action = SPECS[domain].action
    return action.get(status) if isinstance(action, dict) else action


def receipt_bodies(snapshot, candidates):
    """A wrong FK/action/actor/target/schema never projects its Audit body."""
    ids = {receipt_fk(domain, artifact) for run, domain, artifact in candidates}
    ids = {identifier for identifier in ids if type(identifier) is int and identifier > 0}
    if not ids:
        return {}
    byte_size = func.octet_length(AIAuditEvent.detail_json) if snapshot._connection.dialect.name in {"mysql", "mariadb"} else UTF8Bytes(AIAuditEvent.detail_json)
    headers = {
        row.event_id: row
        for row in snapshot.execute(
            select(
                AIAuditEvent.event_id,
                AIAuditEvent.actor_id,
                AIAuditEvent.action,
                AIAuditEvent.target,
                byte_size.label("bytes"),
                json_scalar(snapshot, AIAuditEvent.detail_json, "$.schema_version").label("schema"),
            ).where(AIAuditEvent.event_id.in_(ids))
        )
    }
    allowed = {}
    for run, domain, artifact in candidates:
        identifier = receipt_fk(domain, artifact)
        header = headers.get(identifier)
        if (
            header is not None
            and (header.actor_id, header.action, header.target, header.schema) == (run["requested_by"], action_for(domain, run["status"]), run["run_id"], SPECS[domain].schema)
            and type(header.bytes) is int
            and 0 < header.bytes <= MAX_RECEIPT_BYTES
        ):
            allowed[(run["run_id"], domain)] = identifier
    bodies = dict(snapshot.execute(select(AIAuditEvent.event_id, AIAuditEvent.detail_json).where(AIAuditEvent.event_id.in_(set(allowed.values())))).all()) if allowed else {}
    return {key: bodies[identifier] for key, identifier in allowed.items() if identifier in bodies}


def _closed_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate receipt key")
        result[key] = value
    return result


def checked_usage(run, domain, artifact, raw):
    """Return only counts/attempts, never the event or private result."""
    if run["status"] not in {"succeeded", "failed", "cancelled"}:
        raise ValueError("Only terminal tasks can have settled usage events")
    if type(run["latency_ms"]) is not int or run["latency_ms"] < 0 or run["finish_time"] is None:
        raise ValueError("A settled usage event requires its actual terminal clocks")
    value = json.loads(raw, object_pairs_hook=_closed_object, parse_constant=lambda _: (_ for _ in ()).throw(ValueError("Nonfinite receipt")))
    record = SPECS[domain].parser().model_validate(value).model_dump(mode="json")
    if record["schema_version"] != SPECS[domain].schema:
        raise ValueError("Wrong domain receipt schema")
    for key in ("run_id", "requested_by", "status", "error_code", "latency_ms"):
        if key in record and record[key] != run[key]:
            raise ValueError("Usage event differs from actual task header")
    if "terminal_status" in record and record["terminal_status"] != run["status"]:
        raise ValueError("Local usage differs from terminal task status")
    for key in ("lease_token", "lease", "claim_lease"):
        if key in record and record[key] != run["lease_token"]:
            raise ValueError("Usage belongs to a different execution lease")
    for key in (
        "case_id",
        "submission_id",
        "batch_id",
        "create_event_id",
        "created_audit_event_id",
        "claim_event_id",
        "dispatch_event_id",
        "claim_lease",
        "source_projection_hash",
        "source_binding_hash",
        "binding_hash",
        "source_hash",
        "instructions_digest",
        "input_hash",
        "evidence_hash",
        "metadata_hash",
    ):
        if key in record and key in artifact and record[key] != artifact[key]:
            raise ValueError("Usage differs from its immutable artifact identity")
    if "usage_event_id" in record and record["usage_event_id"] != receipt_fk(domain, artifact):
        raise ValueError("Usage event self-reference differs")
    result = artifact.get("result", {})
    if result and result["run_id"] != run["run_id"]:
        raise ValueError("Result anchor uses a different canonical task PK")
    if "accept_audit_event_id" in record and record["accept_audit_event_id"] != result.get("accept_audit_event_id"):
        raise ValueError("Usage acceptance identity differs")
    if "result_hash" in record and domain != "document":
        expected_hash = artifact.get("result_hash") if "result_hash" in artifact else result.get("result_hash", result.get("content_hash"))
        if record["result_hash"] != expected_hash or (record["result_hash"] is not None) != (run["status"] == "succeeded"):
            raise ValueError("Usage differs from opaque accepted-result identity")
    usage = record.get("usage", record.get("receipt", record))
    for key in ("input_tokens", "output_tokens"):
        number = usage[key]
        if type(run[key]) is not int or run[key] != (number if number is not None else 0):
            raise ValueError("Legacy counters conflict with this specific usage event")
    if domain == "document" and (type(usage["model_call_attempted"]) is not bool or run["status"] == "succeeded" and usage["model_call_attempted"] is not True):
        raise ValueError("Document extraction requires its original explicit call state")
    if domain == "document" and (record["result_hash"] is not None) != (run["status"] == "succeeded"):
        raise ValueError("The document usage event differs from terminal acceptance state")
    return {key: usage[key] for key in ("input_tokens", "output_tokens", "model_call_attempted")} | (
        {key: record[key] for key in ("calculation_attempted", "calculation_completed", "calculation_ms")} if domain == "infection" else {}
    )
