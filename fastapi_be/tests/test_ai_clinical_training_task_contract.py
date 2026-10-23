"""Pure actual-source draft checks; consistent hashes grant no SQL authority."""

import copy
import hashlib
import json
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.ai import clinical_training_contract as c
from app.ai import clinical_training_task_contract as task
from app.ai.clinical_training_task_prompt import SYSTEM_PROMPT, TASK_PROMPT

FIXTURE = Path(__file__).parent / "fixtures/ai_clinical_training_feedback_source.json"


def source():
    return json.loads(FIXTURE.read_text())


def selection(value):
    return dict(clinical_training_submission_id=value["source_id"], objective="explain_practice_feedback")


def anchors(value):
    return dict(expected_source_hash=c.content_hash(value), expected_feedback_hash=c.content_hash(value["feedback"]), expected_public_hash=c.content_hash(value["lesson"]), expected_submission_hash=c.content_hash(value["submission"]))


def draft(value):
    question = value["feedback"]["questions"][0]
    raw = question["reviewed_rationale"]
    return dict(schema_version="clinical_training_feedback_draft_v1", source_id=value["source_id"], source_sha256=c.content_hash(value), feedback_sha256=c.content_hash(value["feedback"]), objective="explain_practice_feedback", status="education_feedback_draft", grade_policy="server_score_unchanged", explanations=[dict(question_id=question["question_id"], explanation="仅解释本次明确受审解析，固定成绩不改变", evidence=[dict(target="reviewed_rationale", question_id=question["question_id"], document_id=None, start_codepoint=0, end_codepoint=len(raw), quote=raw)])], revision_steps=[], gaps=[])


def test_actual_same_case_source_fixture_and_independent_receipt_hash_interface():
    value = source()
    actual = task.validate_frozen_source(value, **anchors(value))
    assert c.whole(actual) == c.whole(value)
    proof = json.loads(FIXTURE.with_name("ai_clinical_training_feedback_source_provenance.json").read_text())
    assert proof["fixture_sha256"] == hashlib.sha256(FIXTURE.read_bytes()).hexdigest()
    assert proof["fixture_bytes"] == FIXTURE.stat().st_size and "not current SQL permission" in proof["authority_boundary"]
    assert actual.feedback.matching_count == actual.feedback.question_count == 2
    assert task.verify_draft(draft(value), value, selection(value)).explanations[0].evidence[0].quote == value["feedback"]["questions"][0]["reviewed_rationale"]


@pytest.mark.parametrize("fault", ["missing_question", "missing_answer", "missing_feedback", "wrong_count", "wrong_outcome", "wrong_selected", "foreign_key", "duplicate_key", "foreign_reference", "omitted_reference", "changed_literal", "changed_raw_hash", "private_governance", "patient_id"])
def test_whole_source_rejects_omission_corruption_and_foreign_fields(fault):
    value = source()
    if fault == "missing_question":
        value["lesson"]["questions"].pop()
    elif fault == "missing_answer":
        value["submission"]["answers"].pop()
    elif fault == "missing_feedback":
        value["feedback"]["questions"].pop()
    elif fault == "wrong_count":
        value["feedback"]["matching_count"] -= 1
    elif fault == "wrong_outcome":
        value["feedback"]["questions"][0]["outcome"] = "explicitly_unanswered"
    elif fault == "wrong_selected":
        value["feedback"]["questions"][0]["selected_option_ids"] = []
    elif fault == "foreign_key":
        value["feedback"]["questions"][0]["correct_option_ids"] = [str(uuid.uuid4())]
    elif fault == "duplicate_key":
        value["feedback"]["questions"][0]["correct_option_ids"] *= 2
    elif fault == "foreign_reference":
        value["feedback"]["questions"][0]["reference_ids"] = [str(uuid.uuid4())]
    elif fault == "omitted_reference":
        value["references"]["references"].pop()
    elif fault == "changed_literal":
        value["references"]["references"][0]["content"] += " changed"
    elif fault == "changed_raw_hash":
        value["references"]["references"][0]["content_utf8_sha256"] = "0" * 64
    elif fault == "private_governance":
        value["references"]["references"][0]["source_uri"] = "private-origin"
    else:
        value["patient_id"] = 1
    with pytest.raises((ValueError, ValidationError)):
        task.TrainingFeedbackSource.model_validate(value, strict=True)


def test_fully_self_consistent_changed_key_still_fails_independent_actual_feedback_and_source_anchors():
    original = source()
    value = copy.deepcopy(original)
    value["feedback"]["questions"][0]["correct_option_ids"] = [value["lesson"]["questions"][0]["options"][1]["option_id"]]
    value["feedback"]["questions"][0]["outcome"] = "differs_from_reviewed_key"
    value["feedback"]["matching_count"], value["feedback"]["differing_count"] = 1, 1
    # This can be structurally valid. Its recomputed hash is no authority.
    task.TrainingFeedbackSource.model_validate(value, strict=True)
    with pytest.raises(ValueError):
        task.validate_frozen_source(value, **anchors(original))
    changed = anchors(value)
    changed["expected_feedback_hash"] = anchors(original)["expected_feedback_hash"]
    with pytest.raises(ValueError):
        task.validate_frozen_source(value, **changed)


@pytest.mark.parametrize("field,value", [("patient_id", 1), ("question", "free clinical input"), ("preview", True), ("clinical_training_submission_id", True), ("objective", "recommend_treatment")])
def test_task_selection_only_actual_submission_and_finite_objective(field, value):
    with pytest.raises(ValidationError):
        task.TrainingTaskSelection.model_validate({**selection(source()), field: value}, strict=True)


@pytest.mark.parametrize("fault", ["source_id", "source_hash", "feedback_hash", "objective", "changed_grade", "new_score", "foreign_question", "duplicate_question", "invented_quote", "utf16_offset", "foreign_rationale", "foreign_reference", "empty_evidence", "invented_step", "foreign_gap"])
def test_draft_cannot_change_grade_bind_foreign_source_or_invent_quote_or_target(fault):
    value = source()
    result = draft(value)
    if fault == "source_id":
        result["source_id"] = str(uuid.uuid4())
    elif fault == "source_hash":
        result["source_sha256"] = "0" * 64
    elif fault == "feedback_hash":
        result["feedback_sha256"] = "0" * 64
    elif fault == "objective":
        result["objective"] = "review_supplied_material"
    elif fault == "changed_grade":
        result["grade_policy"] = "model_regraded"
    elif fault == "new_score":
        result["matching_count"] = 0
    elif fault == "foreign_question":
        result["explanations"][0]["question_id"] = str(uuid.uuid4())
    elif fault == "duplicate_question":
        result["explanations"] *= 2
    elif fault == "invented_quote":
        result["explanations"][0]["evidence"][0]["quote"] += " changed"
    elif fault == "utf16_offset":
        result["explanations"][0]["evidence"][0]["end_codepoint"] += 1
    elif fault == "foreign_rationale":
        result["explanations"][0]["evidence"][0]["question_id"] = value["feedback"]["questions"][1]["question_id"]
    elif fault == "foreign_reference":
        result["explanations"][0]["evidence"][0] = dict(target="reference_text", question_id=None, document_id=str(uuid.uuid4()), start_codepoint=0, end_codepoint=1, quote="x")
    elif fault == "empty_evidence":
        result["explanations"][0]["evidence"] = []
    elif fault == "invented_step":
        result["revision_steps"] = [dict(question_ids=[result["explanations"][0]["question_id"]], kind="create_new_unreviewed_case", explanation="invented", evidence=result["explanations"][0]["evidence"])]
    else:
        result["gaps"] = [dict(question_ids=[str(uuid.uuid4())], kind="insufficient_reviewed_material", description="foreign scope")]
    with pytest.raises((ValueError, ValidationError)):
        task.verify_draft(result, value, selection(value))


def test_reference_quote_preserves_bom_emoji_crlf_nul_and_exact_question_binding():
    value = source()
    result = draft(value)
    question = value["feedback"]["questions"][0]
    document = next(item for item in value["references"]["references"] if item["document_id"] == question["reference_ids"][0])
    raw = document["content"]
    quote = dict(target="reference_text", question_id=None, document_id=document["document_id"], start_codepoint=0, end_codepoint=len(raw), quote=raw)
    result["explanations"][0]["evidence"] = [quote]
    result["revision_steps"] = [dict(question_ids=[question["question_id"]], kind="reread_selected_reference", explanation="只复习该题当前实际参考", evidence=[quote])]
    assert task.verify_draft(result, value, selection(value)).explanations[0].evidence[0].quote.encode() == raw.encode()
    assert "\ufeff" in raw and "😀" in raw and "\r\n" in raw and "\x00" in raw


def test_whole_source_budget_includes_wrapper_and_all_literals_without_partial_fallback():
    value = source()
    # Both nested packets are individually legal. Their whole wrapper exceeds
    # the budget; declarations here still establish no actual SQL authority.
    value["lesson"]["scenario_text"] = "a" * c.TEXT_BYTES
    raw = "b" * 65535
    references = sorted([dict(document_id=str(uuid.uuid4()), title="合成容量参考", version="synthetic-v1", content=raw, content_utf8_sha256=hashlib.sha256(raw.encode()).hexdigest()) for _ in range(64)], key=lambda item: item["document_id"])
    value["references"]["references"] = references
    for index, question in enumerate(value["feedback"]["questions"]):
        question["reference_ids"] = [item["document_id"] for item in references[index * 32:(index + 1) * 32]]
    public_hash = c.content_hash(value["lesson"])
    value["submission"]["public_source_sha256"] = public_hash
    value["feedback"]["public_source_sha256"] = public_hash
    value["feedback"]["submission_sha256"] = c.content_hash(value["submission"])
    c.PublicTrainingLesson.model_validate(value["lesson"], strict=True)
    task.ModelReferences.model_validate(value["references"], strict=True)
    assert len(c.canonical_json(value).encode()) > c.WHOLE_BYTES
    with pytest.raises(ValidationError, match="complete finite training packet exceeds8MiB"):
        task.TrainingFeedbackSource.model_validate(value, strict=True)


def test_contract_and_fixed_prompt_import_without_settings_database_or_router_dependencies():
    script = '''
import builtins,json
original=builtins.__import__
def checked(name,*a,**kw):
 if name.split('.')[0]in{'sqlalchemy','pydantic_settings','dotenv'}or name in{'app.config','app.database','app.models','app.main'}or name.startswith('app.routers'):raise RuntimeError('Unexpected IO dependency:'+name)
 return original(name,*a,**kw)
builtins.__import__=checked
from app.ai.clinical_training_task_contract import TrainingFeedbackSource,TrainingFeedbackDraft
from app.ai.clinical_training_task_prompt import SYSTEM_PROMPT,TASK_PROMPT
print(json.dumps([TrainingFeedbackSource.model_json_schema()['additionalProperties'],TrainingFeedbackDraft.model_json_schema()['additionalProperties'],len(SYSTEM_PROMPT),len(TASK_PROMPT)]))
'''
    result = subprocess.run([sys.executable, "-c", script], cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, check=True)
    assert json.loads(result.stdout)[:2] == [False, False]
    assert "server_score_unchanged" in SYSTEM_PROMPT and "Unicode标量码点" in SYSTEM_PROMPT
    assert "仅使用模拟病例开展问诊推演，按参考标准反馈推理与遗漏，不引入真实患者身份" in TASK_PROMPT
