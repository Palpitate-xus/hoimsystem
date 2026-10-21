"""Closed original task bytes and durable SQL identity for recorded-ledger runs."""

import hashlib
import json

from fastapi import HTTPException
from pydantic import TypeAdapter

from app.ai import charge_reconciliation_contract as c
from app.ai.charge_reconciliation_context import ChargeContextBinding, charge_evidence, selection, short_context
from app.ai.charge_reconciliation_frozen import ChargeFrozenProvider, ChargeFrozenValidation
from app.ai.charge_reconciliation_prompt import CHARGE_RECONCILIATION_SYSTEM_PROMPT
from app.ai.context import ContextBundle, context_metadata
from app.ai.governance import digest

FEATURE_KEY = "charge_reconciliation"
ARTIFACT_SCHEMA = "charge_run_artifact_v1"
ANCHOR_FIELDS = ("input_hash", "evidence_hash", "metadata_hash", "prompt_hash", "context_digest", "source_binding_hash")


def text_hash(value):
    if type(value) is not str or not 0 < len(c.utf8(value)) <= 65535:
        raise ValueError("The whole retained task must fit its original UTF8 TEXT column")
    return hashlib.sha256(c.utf8(value)).hexdigest()


def _json(value):
    text_hash(value)

    def pairs(items):
        result = {}
        for key, child in items:
            if key in result:
                raise ValueError("Duplicate original JSON member")
            result[key] = child
        return result

    def nonfinite(_value):
        raise ValueError("Nonfinite original JSON number")

    parsed = json.loads(value, object_pairs_hook=pairs, parse_constant=nonfinite)
    if c.canonical_json(parsed) != value:
        raise ValueError("The complete retained task JSON must be canonical and scalar-exact")
    return parsed


def _task(run):
    snapshot, evidence, metadata = _json(run.input_json), _json(run.evidence_json), _json(run.context_metadata_json)
    if not isinstance(snapshot, dict) or set(snapshot) != {"catalog_version", "system_prompt", "task_prompt", "payload", "provider_snapshot", "feature_validation"}:
        raise ValueError("The complete closed recorded-ledger task is required")
    if run.feature_key != FEATURE_KEY or type(run.requested_by) is not int or run.requested_by < 1:
        raise ValueError("The actual task feature and author differ")
    TypeAdapter(c.UUID).validate_python(run.run_id, strict=True)
    if (
        snapshot["system_prompt"] != CHARGE_RECONCILIATION_SYSTEM_PROMPT
        or type(snapshot["task_prompt"]) is not str
        or not snapshot["task_prompt"].strip()
        or type(snapshot["catalog_version"]) is not str
        or not snapshot["catalog_version"]
    ):
        raise ValueError("The complete original fixed System and Task Prompt must remain exact")
    payload = snapshot["payload"]
    if not isinstance(payload, dict) or set(payload) != {"input", "context", "tools", "evidence"} or payload["tools"] != {}:
        raise ValueError("Only one reconstructible recorded-ledger source and no tools are allowed")
    context = payload["context"]
    bound = ChargeContextBinding.model_validate(context["charge_binding"])
    if type(run.patient_id) is not int or run.patient_id != bound.patient_id or type(run.encounter_ref) is not str or run.encounter_ref != bound.admission_id:
        raise ValueError("The whole task must bind the same actual patient and Admission")
    binding = bound.model_dump(mode="json")
    if selection(payload["input"]) != bound.case_snapshot_id or c.canonical_json(context) != c.canonical_json(short_context(binding, context["snapshot_time"])):
        raise ValueError("The short context has a different source, scope, scalar type or private body")
    if payload["evidence"] != evidence or evidence != [charge_evidence(binding)]:
        raise ValueError("The exact one reconstructible original evidence is required")
    provider = ChargeFrozenProvider.model_validate(snapshot["provider_snapshot"])
    validation = ChargeFrozenValidation.model_validate(snapshot["feature_validation"])
    if c.canonical_json(provider) != c.canonical_json(snapshot["provider_snapshot"]) or c.canonical_json(validation) != c.canonical_json(snapshot["feature_validation"]):
        raise ValueError("Original provider/validation types or fields differ")
    if (
        type(run.provider_id) is not int
        or type(run.provider_revision) is not int
        or run.provider_id != provider.provider_id
        or run.provider_revision != provider.revision
        or type(run.prompt_version) is not int
        or run.prompt_version < 0
    ):
        raise ValueError("The retained provider or Prompt identity differs from its actual task")
    if run.prompt_hash != digest([snapshot["system_prompt"], snapshot["task_prompt"]]) or run.context_digest != digest(context):
        raise ValueError("The complete original Prompt or context digest differs")
    expected = {
        **context_metadata(ContextBundle(data=context, evidence=evidence, department_ids=set(bound.department_ids))),
        "feature_revision": validation.feature_revision,
        "validation_status": validation.status,
        "tool_fingerprint": digest({}),
        "instructions_digest": hashlib.sha256(c.utf8(snapshot["system_prompt"] + "\n\n" + snapshot["task_prompt"])).hexdigest(),
        "model_version": provider.model,
    }
    if not isinstance(metadata, dict) or c.canonical_json(metadata) != c.canonical_json(expected):
        raise ValueError("The original complete task metadata differs")
    return snapshot, binding, metadata, evidence


def _anchor_values(run, binding):
    return {
        "input_hash": text_hash(run.input_json),
        "evidence_hash": text_hash(run.evidence_json),
        "metadata_hash": text_hash(run.context_metadata_json),
        "prompt_hash": run.prompt_hash,
        "context_digest": run.context_digest,
        "source_binding_hash": c.digest(binding),
    }


def stage_anchor(db, run):
    from app.ai.charge_reconciliation_run_models import AIChargeRunArtifact
    from app.ai.charge_reconciliation_sources import utcnow

    snapshot, binding, _, _ = _task(run)
    clock = utcnow()
    if c.utc_text(clock) < snapshot["payload"]["context"]["snapshot_time"]:
        raise HTTPException(409, "服务器时钟早于本次完整来源核对，任务未入队")
    db.add(
        AIChargeRunArtifact(
            run_id=run.run_id, case_snapshot_id=binding["case_snapshot_id"], requested_by=run.requested_by, schema_version=ARTIFACT_SCHEMA, created_at=clock, **_anchor_values(run, binding)
        )
    )
    db.flush()
    load_snapshot(db, run)
    return snapshot


def load_snapshot(db, run):
    from app.ai.charge_reconciliation_run_models import AIChargeRunArtifact

    try:
        snapshot, binding, metadata, evidence = _task(run)
        if db is None:
            raise ValueError("An actual retained SQL task anchor is required")
        row = db.query(AIChargeRunArtifact).filter_by(run_id=run.run_id).populate_existing().with_for_update(read=True).one_or_none()
        if row is None or row.schema_version != ARTIFACT_SCHEMA or row.case_snapshot_id != binding["case_snapshot_id"] or row.requested_by != run.requested_by:
            raise ValueError("The durable actual task/source/author binding is unavailable")
        if any(getattr(row, key) != value for key, value in _anchor_values(run, binding).items()) or c.utc_text(row.created_at) < snapshot["payload"]["context"]["snapshot_time"]:
            raise ValueError("The retained whole original task bytes or source binding differ")
        return snapshot, binding, metadata, evidence
    except (ValueError, TypeError, KeyError, AttributeError, UnicodeError, RecursionError) as exc:
        raise HTTPException(409, "完整账目任务、原件、身份或Prompt锚点无效，未降级读取") from exc


def is_charge_run(db, run):
    from app.ai.charge_reconciliation_run_models import AIChargeRunArtifact

    if run.feature_key == FEATURE_KEY:
        return True
    try:
        if isinstance(run.input_json, str):
            snapshot = json.loads(run.input_json)
            payload = snapshot.get("payload") if isinstance(snapshot, dict) else None
            context = payload.get("context") if isinstance(payload, dict) else None
            values = payload.get("input") if isinstance(payload, dict) else None
            if isinstance(context, dict) and {"charge_binding", "charge_source", "charge_case"} & context.keys() or isinstance(values, dict) and "charge_case_id" in values:
                return True
        if isinstance(run.result_json, str):
            result = json.loads(run.result_json)
            if isinstance(result, dict) and (result.get("schema_version") == "charge_result_ref_v1" or "charge_analysis" in result):
                return True
    except (ValueError, TypeError, UnicodeError, RecursionError) as exc:
        raise HTTPException(409, "已存任务JSON无效，不能降级读取") from exc
    if db is None or not run.run_id:
        return False
    with db.no_autoflush:
        # This is only an immutable routing locator. The Artifact is inserted
        # atomically with its Run, so any consistent snapshot that can see the
        # actual Run can also see this identity. Do not take Artifact S before
        # the dedicated caller's Billing Gate; authorization/load_snapshot
        # subsequently lock and verify every current original anchor.
        return db.query(AIChargeRunArtifact.run_id).filter_by(run_id=run.run_id).first() is not None
