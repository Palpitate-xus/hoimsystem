"""Whole wire and actual nullable counters, with no DB/config/network imports."""

import hashlib
import uuid

import pytest

from app.ai import clinical_training_contract as c
from app.ai import clinical_training_protocol as p
from app.ai.clinical_training_task_prompt import SYSTEM_PROMPT
from app.ai.clinical_training_usage_contract import TrainingUsage, usage
from tests.test_ai_clinical_training_task_contract import draft, selection, source


def test_complete_wire_retains_every_literal_and_original_key_feedback():
    value = source()
    task = "\ufeff完整自定义Task😀\r\n\x00  尾部 "
    wire, digest = p.model_wire(value, selection(value), task)
    assert wire["input"]["source"] == value
    assert wire["instructions"].encode() == (SYSTEM_PROMPT + "\n\n" + task).encode()
    assert digest == hashlib.sha256(wire["instructions"].encode()).hexdigest()
    assert wire["response_schema"]["additionalProperties"] is False
    actual = p.parse_draft(c.whole(draft(value)), value, selection(value))
    assert actual.grade_policy == "server_score_unchanged"
    assert actual.feedback_sha256 == c.content_hash(value["feedback"])


@pytest.mark.parametrize("fault", ["source_id", "foreign_question", "patient_id", "question", "objective", "missing_objective", "missing_source"])
def test_wire_refuses_foreign_or_implicit_task_scope(fault):
    value = source()
    chosen = selection(value)
    if fault == "source_id":
        chosen["clinical_training_submission_id"] = str(uuid.uuid4())
    elif fault == "objective":
        chosen["objective"] = "recommend_treatment"
    elif fault in {"missing_objective", "missing_source"}:
        chosen.pop("objective" if fault == "missing_objective" else "clinical_training_submission_id")
    else:
        chosen[fault] = "foreign"
    with pytest.raises(ValueError):
        p.model_wire(value, chosen)


@pytest.mark.parametrize("task", [None, 1, "", "x" * 65536, "\ud800"])
def test_complete_task_text_is_never_silently_trimmed_or_clipped(task):
    value = source()
    with pytest.raises((ValueError, TypeError, UnicodeError)):
        p.model_wire(value, selection(value), task)


def test_whole_wire_overhead_can_refuse_a_separately_valid_full_source():
    value = source()
    value["lesson"]["scenario_text"] = "A" * (4 * 1024 * 1024)
    value["submission"]["public_source_sha256"] = c.content_hash(value["lesson"])
    value["feedback"]["public_source_sha256"] = c.content_hash(value["lesson"])
    value["feedback"]["submission_sha256"] = c.content_hash(value["submission"])
    from app.ai.clinical_training_task_contract import TrainingFeedbackSource

    raw = "B" * 65535
    references = sorted([dict(document_id=str(uuid.uuid4()), title="合成容量参考", version="synthetic-v1", content=raw, content_utf8_sha256=hashlib.sha256(raw.encode()).hexdigest()) for _ in range(64)], key=lambda item: item["document_id"])
    value["references"]["references"] = references
    for index, item in enumerate(value["feedback"]["questions"]):
        item["reference_ids"] = [reference["document_id"] for reference in references[index * 32:(index + 1) * 32]]
    excess = len(c.canonical_json(value).encode()) - (c.WHOLE_BYTES - 1000)
    assert excess > 0
    value["lesson"]["scenario_text"] = value["lesson"]["scenario_text"][:-excess]
    value["submission"]["public_source_sha256"] = c.content_hash(value["lesson"])
    value["feedback"]["public_source_sha256"] = c.content_hash(value["lesson"])
    value["feedback"]["submission_sha256"] = c.content_hash(value["submission"])
    TrainingFeedbackSource.model_validate(value, strict=True)
    assert len(c.whole(value).encode()) == c.WHOLE_BYTES - 1000
    with pytest.raises(ValueError, match="complete Source, System, Task"):
        p.model_wire(value, selection(value), "T" * 65535)


@pytest.mark.parametrize("inputs,outputs", [(0, 0), (11, None), (None, 7), (None, None), (2147483647, 2147483647)])
def test_attempted_usage_keeps_every_independently_known_counter(inputs, outputs):
    actual = usage(inputs, outputs, True)
    assert actual == dict(input_tokens=inputs, output_tokens=outputs, complete=inputs is not None and outputs is not None, model_call_attempted=True)


def test_not_attempted_and_recovered_unknown_are_distinct():
    assert usage(0, 0, False)["complete"] is True
    assert usage(None, None, None) == dict(input_tokens=None, output_tokens=None, complete=False, model_call_attempted=None)


@pytest.mark.parametrize("value", [True, -1, 2147483648, 1.0, "1"])
def test_malformed_counter_is_not_normalized_to_unknown(value):
    with pytest.raises(ValueError):
        usage(value, 7, True)


@pytest.mark.parametrize("patch", [dict(complete=True), dict(model_call_attempted=False), dict(model_call_attempted=None), dict(cost=0)])
def test_unknown_usage_cannot_become_complete_unattempted_or_zero_cost(patch):
    value = usage(11, None, True)
    with pytest.raises(ValueError):
        TrainingUsage.model_validate({**value, **patch}, strict=True)
