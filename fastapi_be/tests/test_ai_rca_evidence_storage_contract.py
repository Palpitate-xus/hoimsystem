"""Pure short task/receipt contracts on an actual synthetic published Case."""

import copy

import pytest

from app.ai import rca_evidence_contract as c
from app.ai import rca_evidence_storage_contract as storage
from app.ai import rca_evidence_task_contract as t
from app.ai.rca_evidence_task_prompt import SYSTEM_PROMPT, TASK_PROMPT
from tests.test_ai_rca_evidence_context import prepared
from tests.test_ai_rca_evidence_grants import grant_case as grant_case


def snapshot(value):
    return {
        "schema_version": "rca_evidence_task_snapshot_v1",
        "catalog_version": "synthetic-contract-only",
        "system_prompt": SYSTEM_PROMPT,
        "task_prompt": TASK_PROMPT,
        "payload": {"input": value.selection.model_dump(mode="json"), "context": value.data, "tools": {}, "evidence": value.evidence},
        "provider_snapshot": {
            "provider_id": 1,
            "revision": 1,
            "name": "合成provider元数据并非已配置服务",
            "kind": "chat",
            "api_base": "https://synthetic.invalid/v1",
            "model": "synthetic-contract-model",
            "timeout_seconds": 3,
            "max_output_tokens": 4096,
            "validation_report": "没有效果验证",
            "temperature": 0.0,
            "allows_patient_data": True,
            "effective_output_limit": 4096,
        },
        "feature_validation": {"status": "unreviewed", "note": "仅合同测试，无执行配置", "validated_by": None, "validated_at": None, "feature_revision": 1},
        "source_case_governance": value.record.governance.model_dump(mode="json"),
        "actor_epoch": {"user_role": "super_admin", "token_invalid_before": None},
        "run_clock_basis": "legacy_utc_second_storage",
    }


def test_actual_frozen_publication_is_short_and_independent_of_source_body(grant_case):
    value, _ = prepared(grant_case, "🙂" * 2000)
    raw = snapshot(value)
    saved = storage.RcaTaskSnapshot.model_validate(raw)
    assert saved.payload.input.question == "🙂" * 2000 and saved.source_case_governance == value.record.governance
    assert "rca_evidence_source" not in saved.payload.context
    assert len(t.text_json(saved).encode()) <= 65535
    meta = storage.metadata_for_snapshot(saved)
    assert meta.model_version == "synthetic-contract-model" and meta.source_count == 1
    assert len(storage.RcaTaskMetadata.model_fields) == 11
    assert meta.context_digest == c.digest(value.data)
    assert meta.instructions_digest == t.instructions_digest(SYSTEM_PROMPT, TASK_PROMPT)
    assert saved.provider_snapshot.temperature == 0.0


@pytest.mark.parametrize(
    "axis",
    [
        "foreign_source",
        "tools",
        "question_extra",
        "wrong_fixed_system",
        "unbound_review",
        "review_missing",
        "wrong_role",
        "provider_permission_int",
        "provider_missing",
        "provider_nonfinite",
        "whole_text_wrapper",
    ],
)
def test_complete_snapshot_rejects_cross_source_protocol_change_and_whole_text_overhead(grant_case, axis):
    value, _ = prepared(grant_case)
    raw = snapshot(value)
    if axis == "foreign_source":
        raw["payload"]["context"]["document_source"] = {}
    elif axis == "tools":
        raw["payload"]["tools"]["rca"] = "automatic write"
    elif axis == "question_extra":
        raw["payload"]["input"]["patient_id"] = grant_case["patient_id"]
    elif axis == "wrong_fixed_system":
        raw["system_prompt"] += "替换固定系统"
    elif axis == "unbound_review":
        raw["source_case_governance"]["review_basis_note"] += "未经原签署替换"
    elif axis == "review_missing":
        del raw["source_case_governance"]
    elif axis == "wrong_role":
        raw["actor_epoch"]["user_role"] = "admin"
    elif axis == "provider_permission_int":
        raw["provider_snapshot"]["allows_patient_data"] = 1
    elif axis == "provider_missing":
        del raw["provider_snapshot"]["effective_output_limit"]
    elif axis == "provider_nonfinite":
        raw["provider_snapshot"]["temperature"] = float("nan")
    else:
        raw["task_prompt"] = "x" * 65000
        assert len(raw["task_prompt"].encode()) < 65535
    with pytest.raises(ValueError):
        storage.RcaTaskSnapshot.model_validate(raw)


def receipt(**updates):
    return {
        "schema_version": "rca_evidence_usage_receipt_v1",
        "run_id": "00000000-0000-0000-0000-000000000030",
        "case_id": "00000000-0000-0000-0000-000000000031",
        "claim_event_id": 2,
        "dispatch_event_id": 3,
        "lease_token": "00000000-0000-0000-0000-000000000032",
        "binding_hash": "a" * 64,
        "source_hash": "b" * 64,
        "result_hash": None,
        "terminal_state_hash": "c" * 64,
        "status": "failed",
        "error_code": "BAD_PROVIDER_REPLY",
        "usage": {"input_tokens": 11, "output_tokens": None, "complete": False, "model_call_attempted": True},
        "recorded_at": "2026-10-21T12:00:00.123456Z",
        "run_clock_basis": "legacy_utc_second_storage",
        **updates,
    }


def test_paid_rejected_partial_receipt_and_interrupted_unknown_do_not_create_success():
    paid = storage.RcaUsageEvent.model_validate(receipt())
    assert paid.usage.input_tokens == 11 and paid.usage.output_tokens is None and paid.result_hash is None
    zero = receipt(
        claim_event_id=None,
        dispatch_event_id=None,
        lease_token=None,
        status="cancelled",
        error_code=None,
        usage={"input_tokens": 0, "output_tokens": 0, "complete": True, "model_call_attempted": False},
    )
    assert storage.RcaUsageEvent.model_validate(zero).usage.model_call_attempted is False
    unknown = receipt(error_code="WORKER_INTERRUPTED", usage={"input_tokens": None, "output_tokens": None, "complete": False, "model_call_attempted": None})
    assert storage.RcaUsageEvent.model_validate(unknown).usage.model_call_attempted is None
    succeeded = receipt(status="succeeded", error_code=None, result_hash="d" * 64, usage={"input_tokens": 11, "output_tokens": 13, "complete": True, "model_call_attempted": True})
    assert storage.RcaUsageEvent.model_validate(succeeded).result_hash == "d" * 64
    partial = receipt(status="succeeded", error_code=None, result_hash="d" * 64)
    accepted = storage.RcaUsageEvent.model_validate(partial)
    assert accepted.usage.complete is False and accepted.usage.output_tokens is None and accepted.result_hash == "d" * 64


@pytest.mark.parametrize(
    "updates",
    [
        {"dispatch_event_id": None},
        {"claim_event_id": None},
        {"lease_token": None},
        {"result_hash": "d" * 64},
        {"status": "succeeded"},
        {"usage": {"input_tokens": None, "output_tokens": None, "complete": False, "model_call_attempted": None}},
        {"recorded_at": "2026-10-21T12:00:00Z"},
        {"run_clock_basis": "inferred_utc6"},
    ],
)
def test_terminal_receipt_cannot_invent_claim_dispatch_complete_success_or_known_usage(updates):
    with pytest.raises(ValueError):
        storage.RcaUsageEvent.model_validate(receipt(**updates))


def test_metadata_one_is_actual_int_not_boolean_and_frozen_grant_epochs_do_not_relabel(grant_case):
    value, _ = prepared(grant_case)
    raw = snapshot(value)
    metadata = storage.metadata_for_snapshot(raw).model_dump(mode="json")
    for key, bad in (("source_count", True), ("tool_fingerprint", "e" * 64), ("missing_data", [])):
        changed = copy.deepcopy(metadata)
        changed[key] = bad
        with pytest.raises(ValueError):
            storage.RcaTaskMetadata.model_validate(changed)
    raw["actor_epoch"]["token_invalid_before"] = "2026-10-21T12:00:00"
    with pytest.raises(ValueError):
        storage.RcaTaskSnapshot.model_validate(raw)
