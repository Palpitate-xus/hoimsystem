"""Actual whole authorized parts, independent reauthorization and technical views."""

import json
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import update

from app.ai import operations_support_contract as c
from app.ai import operations_support_receipts as receipts
from app.ai import operations_support_registry as registry
from app.ai import operations_support_views as views
from app.ai.models import AIAuditEvent, AIRun
from app.ai.operations_support_run_models import RESULT_SCHEMA, AIOperationsRunResult
from app.ai.operations_support_task_view_contract import OperationsTaskMetadata
from app.ai.operations_support_usage_contract import usage
from tests.test_ai_operations_support_receipts import capture_without_body
from tests.test_ai_operations_support_result_storage import accept
from tests.test_ai_operations_support_result_storage import actors as actors
from tests.test_ai_operations_support_result_storage import claimed as claimed
from tests.test_ai_operations_support_result_storage import configured as configured
from tests.test_ai_operations_support_result_storage import dispatched as dispatched
from tests.test_ai_operations_support_result_storage import queued as queued
from tests.test_ai_operations_support_result_storage import source as source
from tests.test_ai_operations_support_storage import no_body


def test_real_current_queued_metadata_separate_full_parts_and_no_private_original_hashes(queued):
    configured, identifier = queued
    db, registrar, creator, reviewer, admin = configured[0]
    metadata = views.describe_task(db, admin, identifier)
    assert metadata.parts_state == "available" and metadata.binding.operations_case_id == configured[3]["case_id"] and metadata.usage is None
    task = views.read_part(db, admin, identifier, "task")
    source = views.read_part(db, admin, identifier, "source")
    binding = views.read_part(db, admin, identifier, "binding")
    assert task.raw.input_json == db.get(AIRun, identifier).input_json
    assert registry.raw_sha(task.prompt_snapshot_json) == metadata.binding.prompt_snapshot_hash
    assert registry.raw_sha(task.execution_snapshot_json) == metadata.binding.execution_snapshot_hash
    assert c.content_hash(source) == metadata.binding.source_projection_hash
    assert binding.claim_event_id is None and binding.lease_token is None and binding.usage_receipt_json is None
    wire = c.canonical_json([item.model_dump(mode="json") for item in (metadata, task, binding, source)])
    assert configured[1]["original_id"] not in wire and configured[3]["private_hash"] not in wire
    assert not any('"' + field + '"' in wire for field in ("case_private_hash", "case_membership_hash", "review_basis", "origin_note", "api_key_env", "api_key_encrypted"))
    assert views.read_part(db, admin, identifier, "result") is None


def test_super_directory_is_bodyless_even_while_source_is_current(queued):
    configured, identifier = queued
    db, registrar, *_ = configured[0]
    value = capture_without_body(db, lambda: views.technical_metadata(db, registrar, identifier))
    assert value.parts_state == "requires_current_read" and value.binding is None and value.usage is None
    no_body(db, lambda: views.technical_metadata(db, configured[0][-1], identifier), 403)


def test_actual_partial_paid_success_full_binding_receipt_and_exact_result(dispatched):
    configured, claim, dispatch, expected = dispatched
    db = configured[0][0]
    user = configured[0][-1]
    accept(dispatched, usage(11, None, True))
    metadata = views.describe_task(db, user, claim.run_id)
    part = views.read_part(db, user, claim.run_id, "binding")
    receipt = receipts.OperationsUsageEvent.model_validate_json(part.usage_receipt_json, strict=True)
    assert metadata.status == "succeeded" and metadata.usage.model_dump() == usage(11, None, True) and metadata.finish_time == receipt.recorded_at
    assert metadata.finish_clock_basis == "actual_usage_receipt_utc6" and metadata.receipt_pending is False
    assert (part.claim_event_id, part.dispatch_event_id, part.usage_event_id) == (claim.claim_event_id, dispatch.dispatch_event_id, metadata.usage_event_id)
    assert views.read_part(db, user, claim.run_id, "result").model_dump() == expected
    technical = capture_without_body(db, lambda: views.technical_metadata(db, configured[0][1], claim.run_id))
    assert technical.usage == metadata.usage and technical.binding is None and technical.status == "succeeded"


@pytest.mark.parametrize("succeeded", [False, True])
def test_source_withdrawal_retains_only_super_opaque_metadata_not_trace_or_any_part(dispatched, succeeded):
    configured, claim, dispatch, expected = dispatched
    db, registrar, creator, reviewer, admin = configured[0]
    if succeeded:
        accept(dispatched, usage(11, None, True))
    registry.revoke_original(db, registrar, configured[1]["original_id"], {"revision": 1, "reason": "不得复用已撤回Part"})
    if not succeeded:
        receipts.stage_terminal(db, claim, dispatch_event_id=dispatch.dispatch_event_id, usage=usage(11, None, True), status="failed", error_code="SOURCE_NOT_CURRENT", latency_ms=87)
    metadata = capture_without_body(db, lambda: views.describe_task(db, registrar, claim.run_id))
    assert metadata.parts_state == "current_parts_unavailable" and metadata.binding is None and metadata.usage.model_dump() == usage(11, None, True)
    assert metadata.status == ("succeeded" if succeeded else "failed")
    no_body(db, lambda: views.describe_task(db, admin, claim.run_id), 403)
    for part in views.PARTS:
        no_body(db, lambda: views.read_part(db, registrar, claim.run_id, part), 403)
    no_body(db, lambda: views.split_trace(db, registrar, claim.run_id), 403)


def test_an_earlier_task_part_does_not_authorize_later_parts_after_actual_withdrawal(queued):
    configured, identifier = queued
    db, registrar, creator, reviewer, admin = configured[0]
    first = views.read_part(db, admin, identifier, "task")
    assert first.binding.operations_case_id == configured[3]["case_id"]
    registry.revoke_original(db, registrar, configured[1]["original_id"], {"revision": 1, "reason": "独立part每次当前核对"})
    for part in ["source", "binding", "result"]:
        no_body(db, lambda: views.read_part(db, admin, identifier, part), 403)


def test_corrupt_immutable_run_still_has_only_super_incomplete_technical_metadata(queued):
    configured, identifier = queued
    db, registrar, *_ = configured[0]
    db.execute(update(AIRun).where(AIRun.run_id == identifier).values(feature_key="patient_summary"), execution_options={"synchronize_session": False})
    value = capture_without_body(db, lambda: views.describe_task(db, registrar, identifier))
    assert value.parts_state == "incomplete_native_artifact" and value.binding is None and value.usage is None
    no_body(db, lambda: views.read_part(db, registrar, identifier, "task"), 409)


def test_marker_only_legacy_task_is_super_technical_metadata_without_fabricated_usage(configured):
    db, registrar, creator, reviewer, admin = configured[0]
    row = AIRun(feature_key="operations_support", requested_by=admin.user_id, prompt_hash="0" * 64, context_digest="0" * 64, input_json="{}", evidence_json="[]", context_metadata_json="{}", result_json="{}")
    db.add(row)
    db.flush()
    identifier = row.run_id
    value = capture_without_body(db, lambda: views.technical_metadata(db, registrar, identifier))
    assert value.parts_state == "incomplete_native_artifact" and value.binding is None and value.usage is None
    no_body(db, lambda: views.read_part(db, registrar, identifier, "task"), 409)


def test_split_trace_contains_only_metadata_and_four_independent_bare_part_urls(queued):
    configured, identifier = queued
    db, registrar, creator, reviewer, admin = configured[0]
    value = views.split_trace(db, admin, identifier)
    assert value["parts_wire"] == "canonical_json_body_no_envelope" and value["parts_require_independent_current_reads"] is True
    assert set(value["parts"]) == set(views.PARTS) and all(url.endswith("/" + part) for part, url in value["parts"].items())
    assert "prompt_snapshot_json" not in c.canonical_json(value) and "documents" not in c.canonical_json(value)
    OperationsTaskMetadata.model_validate(value["run"], strict=True)


@pytest.mark.parametrize("fault", ["pointer", "unexpected_blob", "queued_terminal_trace"])
def test_non_success_null_never_hides_unexpected_blob_pointer_or_corrupt_phase(queued, fault):
    configured, identifier = queued
    db, registrar, creator, reviewer, admin = configured[0]
    if fault == "pointer":
        db.execute(update(AIRun).where(AIRun.run_id == identifier).values(result_json='{"invented":true}'), execution_options={"synchronize_session": False})
    elif fault == "queued_terminal_trace":
        db.execute(update(AIRun).where(AIRun.run_id == identifier).values(latency_ms=99), execution_options={"synchronize_session": False})
    else:
        from app.ai import operations_support_attempts as attempts

        header = attempts.phase_header(db, identifier)
        audit = AIAuditEvent(actor_id=admin.user_id, action="synthetic_invalid_result_fixture", target=identifier, detail_json="{}")
        db.add(audit)
        db.flush()
        db.add(AIOperationsRunResult(run_id=identifier, schema_version=RESULT_SCHEMA, lease_token=str(uuid.uuid4()), accepted_at=registry.utcnow(), result_json="{}", result_bytes=2, result_hash=registry.raw_sha("{}"), source_binding_hash=header["source_binding_hash"], instructions_digest=header["instructions_digest"], accept_audit_event_id=audit.event_id))
        db.flush()
    with pytest.raises(HTTPException) as error:
        views.read_part(db, admin, identifier, "result")
    assert error.value.status_code == 409


def test_task_view_schema_import_is_pure_and_has_no_database_or_configuration_dependency():
    script = """
import builtins,json
original=builtins.__import__
def checked(name,*a,**kw):
 if name.split('.')[0] in {'sqlalchemy','pydantic_settings','dotenv'} or name in {'app.config','app.database','app.models'}:raise RuntimeError('Unexpected view schema IO dependency:'+name)
 return original(name,*a,**kw)
builtins.__import__=checked
from app.ai.operations_support_task_view_contract import OperationsTaskMetadata,OperationsTaskPart,OperationsBindingPart
print(json.dumps([item.model_json_schema()['additionalProperties'] for item in (OperationsTaskMetadata,OperationsTaskPart,OperationsBindingPart)]))
"""
    result = subprocess.run([sys.executable, "-c", script], cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, check=True)
    assert json.loads(result.stdout) == [False, False, False]
