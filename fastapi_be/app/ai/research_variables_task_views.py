"""Source-first76 short receipts and independently bounded complete parts.

No aggregate response duplicates Source/private Scope/result. Ordinary reads
need current original purposes; only an explicit Super audit uses frozen proof,
and even that audit retains its own current project/all-patient permissions.
"""

from functools import wraps

from fastapi import HTTPException

from app.ai import research_variables_attempts as attempts
from app.ai import research_variables_receipts as receipts
from app.ai import research_variables_result_storage as results
from app.ai import research_variables_storage as storage
from app.ai import research_variables_task_reader as reader
from app.ai.catalog import FEATURE_BY_KEY
from app.ai.research_variables_run_models import AIResearchVariableRunResult
from app.ai.research_variables_task_binding import binding_reference
from app.ai.research_variables_task_context import wire_parts
from app.ai.research_variables_task_contract import FEATURE_KEY, canonical
from app.ai.research_variables_task_view_contract import VariableTaskAnchorRecord

VIEW_FIELDS = (
    "run_id",
    "feature_key",
    "status",
    "preview",
    "prompt_version",
    "provider_revision",
    "context_digest",
    "patient_id",
    "encounter_ref",
    "requested_by",
    "error_code",
    "error_message",
    "latency_ms",
    "create_time",
    "start_time",
    "finish_time",
)


def checked_view(function):
    @wraps(function)
    def call(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except (ValueError, TypeError, KeyError, AttributeError, UnicodeError) as exc:
            raise HTTPException(409, "变量任务实际短引用、技术锚或回执闭集无法核对，未降级显示") from exc

    return call


def bounded(value):
    try:
        canonical(value)
        return value
    except (ValueError, TypeError, UnicodeError) as exc:
        raise HTTPException(413, "完整变量任务分件含回执超过8MiB或无法编码，未截断或省略原件") from exc


def artifact_record(task):
    return VariableTaskAnchorRecord(**{key: storage._clock(getattr(task.artifact, key)) for key in VariableTaskAnchorRecord.model_fields}).model_dump(mode="json")


def _reference_and_receipt(db, task):
    reference = None
    if task.run.status == "succeeded":
        reference = results.VariableResultReference.model_validate(storage.canonical_value(task.run.result_json))
        actual = results._metadata(db, task)
        if reference != results.reference_for_row(actual):
            raise HTTPException(409, "完整变量结果短引用与实际SQL元数据不同")
        attempts.verify_delivery(db, task)
        recorded = receipts.verify_receipt(db, task, accept_event_id=reference.accept_audit_event_id)
        results._accept_audit(db, task, actual, reference)
        return reference.model_dump(mode="json"), recorded.receipt.model_dump(mode="json"), "recorded"
    if task.run.result_json != "{}" or db.query(AIResearchVariableRunResult.run_id).filter_by(run_id=task.run.run_id).one_or_none() is not None:
        raise HTTPException(409, "非成功变量任务不能保留或显示完整成功结果")
    if task.artifact.usage_event_id is not None:
        if task.run.status not in {"failed", "cancelled"}:
            raise HTTPException(409, "非终态变量任务不能冒充已有最终用量")
        record = receipts.verify_receipt(db, task)
        return None, record.receipt.model_dump(mode="json"), "recorded"
    if task.run.status not in {"queued", "running", "cancelled"}:
        raise HTTPException(409, "变量终态缺具体用量PK，不能以物理0补造回执")
    return None, None, "pending"


@checked_view
def describe_task(db, task, *, include_result=True):
    reference, usage, receipt_status = _reference_and_receipt(db, task)
    if include_result:
        # A full detail validates every literal and actual blob before offering
        # the separate result link, without duplicating its BODY in this DTO.
        results.result_from_task(db, task)
    fields = {key: storage._clock(getattr(task.run, key)) for key in VIEW_FIELDS}
    fields.update(
        feature_name=FEATURE_BY_KEY[FEATURE_KEY].name,
        requires_human_review=True,
        context_metadata=storage.canonical_value(task.run.context_metadata_json),
        research_variable_batch_id=task.artifact.batch_id,
        research_variable_artifact=artifact_record(task),
        research_variable_findings={"binding": binding_reference(task.binding)},
        result=None,
        result_reference=reference,
        usage_receipt=usage,
        usage_receipt_status=receipt_status,
        input_tokens=usage["input_tokens"] if usage is not None else None,
        output_tokens=usage["output_tokens"] if usage is not None else None,
        automatic_clinical_write=False,
        automatic_export=False,
        frozen_audit=task.frozen_audit,
    )
    fields["parts"] = {name: f"/ai/runs/{task.run.run_id}/research-variables/{name}" for name in ("binding", "source", "scope", "result", "receipt")}
    return bounded(fields)


def describe_variable_run(db, user, identifier, include_result=True, *, frozen_audit=False):
    return describe_task(db, reader.load_task(db, user, identifier, frozen_audit=frozen_audit), include_result=include_result)


@checked_view
def read_variable_part(db, user, identifier, part, *, frozen_audit=False):
    if part not in {"binding", "source", "scope", "result", "receipt"}:
        raise HTTPException(422, "变量任务仅提供明确完整分件")
    task = reader.load_task(db, user, identifier, frozen_audit=frozen_audit)
    if part in {"binding", "source", "scope"}:
        value = wire_parts(task.binding, task.source, task.private_scope)[part]
    elif part == "result":
        value = results.result_from_task(db, task)
        if value is None:
            raise HTTPException(409, "本次任务尚无已接受完整变量草稿，未构造空成功结果")
    else:
        _, usage, status = _reference_and_receipt(db, task)
        value = {"schema_version": "research_variable_receipt_part_v1", "binding": binding_reference(task.binding), "receipt_status": status, "usage_receipt": usage}
    return bounded(value)


@checked_view
def trace_variable_run(db, user, identifier):
    task = reader.load_task(db, user, identifier, frozen_audit=True)
    detail = describe_task(db, task)
    value = {
        "schema_version": "research_variable_task_trace_v1",
        "run": detail,
        "frozen_request": task.snapshot.model_dump(mode="json"),
        "frozen_evidence": storage.canonical_value(task.run.evidence_json),
        "frozen_context_metadata": storage.canonical_value(task.run.context_metadata_json),
        "raw_frozen_json": {name: getattr(task.run, name) for name in ("input_json", "evidence_json", "context_metadata_json")},
        "research_variable_artifact": artifact_record(task),
        "request_authorization": task.binding.request_authorization.model_dump(mode="json"),
        "request_authorization_hash": task.binding.request_authorization_hash,
        "result_reference": detail["result_reference"],
        "usage_receipt": detail["usage_receipt"],
        "parts": detail["parts"],
        "frozen_audit": True,
        "execution_current": False,
    }
    return bounded(value)
