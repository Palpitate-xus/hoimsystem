"""Actual split DTOs and independent closed-wire negative controls."""

# ruff: noqa: F811 -- actual Source/config/Task fixture imports register fixtures.

import copy

import pytest
from pydantic import ValidationError

from app.ai import infection_cluster_contract as c
from app.ai import infection_cluster_task_view_contract as wire
from app.ai import infection_cluster_task_views as views
from tests.test_ai_infection_cluster_task_storage import finish, profile_case, stage, task_case  # noqa: F401


def test_actual_complete_split_fields_use_source_sha_and_success_actual_receipt(task_case):
    case = task_case
    rid = stage(case)
    queued = views.metadata(case["db"], case["author"], rid)
    assert queued["usage"] is None and queued["result_hash"] is queued["result_bytes"] is None
    assert queued["created_at"].endswith(".123456Z") and not queued["run_created_at"].endswith("Z")
    expected = finish(case, rid)
    metadata = views.metadata(case["db"], case["author"], rid)
    parts = {name: views.part(case["db"], case["author"], rid, name) for name in ["task", "source", "result"]}
    assert parts["source"]["value_hash"] == metadata["source_hash"] == parts["task"]["value"]["source_hash"]
    assert parts["result"]["value"] == expected.model_dump(mode="json") and parts["result"]["value_hash"] == metadata["result_hash"]
    assert metadata["receipt_event_id"] is not None and metadata["usage"]["model_call_attempted"] is False
    assert not metadata["clinical_body_included"] and metadata["protected_hashes_are_opaque"]
    assert "mapping_key" not in c.canonical(parts)


def test_success_metadata_cannot_erase_receipt_restore_false_zero_or_change_clock_basis(task_case):
    case = task_case
    rid = stage(case)
    finish(case, rid)
    raw = views.metadata(case["db"], case["author"], rid)
    attacks = [
        dict(usage=None),
        dict(receipt_event_id=None),
        dict(result_available=False),
        dict(result_hash=None),
        dict(result_bytes=None),
        dict(run_created_at=raw["created_at"]),
        dict(status="normal"),
    ]
    for change in attacks:
        with pytest.raises(ValidationError):
            wire.TaskMetadata.model_validate({**raw, **change})
    paid = copy.deepcopy(raw)
    paid["usage"]["input_tokens"] = 1
    with pytest.raises(ValidationError):
        wire.TaskMetadata.model_validate(paid)


def test_self_rehashed_part_is_still_typed_closed_and_wrong_run_frozen_task_is_rejected(task_case):
    case = task_case
    rid = stage(case)
    task = views.part(case["db"], case["author"], rid, "task")
    changed = copy.deepcopy(task)
    changed["value"]["external_model_transfer"] = True
    changed.update(value_hash=c.digest(changed["value"]), value_bytes=len(c.utf8(c.canonical(changed["value"]))))
    with pytest.raises(ValidationError):
        wire.TaskPart.model_validate(changed)
    with pytest.raises(ValidationError):
        wire.TaskPart.model_validate({**task, "run_id": "00000000-0000-0000-0000-000000009999"})
    with pytest.raises(ValidationError):
        wire.TaskPart.model_validate({**task, "unexpected_private_key": "no"})


def test_directory_preserves_exact_total_page_and_cannot_duplicate_or_fake_complete_members(task_case):
    case = task_case
    first, second = stage(case), stage(case)
    page = views.directory(case["db"], case["author"], page=1, size=1)
    assert page["total"] == 2 and len(page["items"]) == 1 and page["native_artifacts_only"]
    whole = views.directory(case["db"], case["author"], page=1, size=20)
    assert {r["run_id"] for r in whole["items"]} == {first, second}
    bad = copy.deepcopy(whole)
    bad["items"][1] = bad["items"][0]
    with pytest.raises(ValidationError):
        wire.TaskDirectory.model_validate(bad)
    with pytest.raises(ValidationError):
        wire.TaskDirectory.model_validate({**page, "total": 0})
