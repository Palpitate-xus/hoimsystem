"""Pure synthetic teaching records; no publication/permission/clinical validation proof."""

import copy
import uuid

import pytest
from pydantic import ValidationError

from app.ai import clinical_training_contract as c
from app.ai import clinical_training_scoring as s


def uid():
    return str(uuid.uuid4())


def question(selection="single", option_count=3):
    options = [dict(option_id=uid(), text="合成选项" + str(index)) for index in range(option_count)]
    return dict(
        question_id=uid(),
        selection=selection,
        stem="合成教学问题，不含真实医学判断",
        options=options,
        correct_option_ids=[option["option_id"] for option in options[: (1 if selection == "single" else 2)]],
        reviewed_rationale="PRIVATE_REVIEWED_RATIONALE_SENTINEL",
        reference_ids=[uid()],
    )


def lesson(questions=None):
    return dict(
        schema_version="clinical_training_private_lesson_v1",
        lesson_id=uid(),
        version_label="合成教学版本v1",
        title="有限教学练习",
        scenario_text="\ufeff合成病例 😀\r\n\x00 尾部  ",
        learning_objectives=["练习明确知识点"],
        questions=questions if questions is not None else [question(), question("multiple")],
        created_by=7,
        created_at="2026-10-21T18:00:00.123456Z",
        material_basis="author_declared_synthetic_not_independently_verified_by_contract",
        intended_use="education_only_not_patient_treatment_or_credentialing",
    )


def submission(private, choices=None):
    public = c.project_lesson(private)
    answers = [dict(question_id=q["question_id"], selected_option_ids=copy.deepcopy(q["correct_option_ids"])) for q in private["questions"]]
    if choices is not None:
        for answer, selected in zip(answers, choices, strict=True):
            answer["selected_option_ids"] = selected
    return dict(lesson_id=private["lesson_id"], public_source_sha256=c.content_hash(public), answers=answers)


def test_public_lesson_preserves_complete_literal_material_but_not_key_rationale_author_or_private_hash():
    private = lesson()
    public = c.project_lesson(private)
    wire = c.canonical_json(public)
    assert public.scenario_text.encode() == private["scenario_text"].encode()
    assert len(public.questions) == 2 and all(len(question.options) == 3 for question in public.questions)
    assert c.verify_projection(public, private)
    assert not {"correct_option_ids", "reviewed_rationale", "reference_ids", "created_by", "created_at", "private_hash", "private_sha256"}.intersection(public.model_dump())
    assert "PRIVATE_REVIEWED_RATIONALE_SENTINEL" not in wire and "correct_option_ids" not in wire
    assert public.answer_visibility == "released_feedback_only_after_server_authorized_submission"


def test_secret_key_digest_is_not_exposed_or_implicitly_used_as_low_entropy_answer_proof():
    private = lesson()
    public = c.project_lesson(private)
    changed = copy.deepcopy(private)
    changed["questions"][0]["correct_option_ids"] = [changed["questions"][0]["options"][1]["option_id"]]
    assert c.content_hash(private) != c.content_hash(changed)
    assert c.canonical_json(public) == c.canonical_json(c.project_lesson(changed))
    # Server publication must separately bind an immutable private version and
    # actual receipt; public SHA deliberately grants no such proof.
    assert c.content_hash(private) not in c.canonical_json(public)


@pytest.mark.parametrize(
    "field,value", [("patient_id", 1), ("encounter_ref", "unreviewed"), ("is_published", True), ("created_by", True), ("created_at", "2026-10-21T18:00:00Z"), ("intended_use", "patient_treatment")]
)
def test_private_declarations_reject_foreign_context_fake_publication_and_wrong_scalars(field, value):
    value = {**lesson(), field: value}
    with pytest.raises(ValidationError):
        c.PrivateTrainingLesson.model_validate(value, strict=True)


@pytest.mark.parametrize(
    "change", ["missing_key", "unknown_key", "duplicate_key", "single_two_keys", "missing_reference", "duplicate_reference", "duplicate_option", "duplicate_question", "cross_question_option_alias"]
)
def test_incomplete_or_ambiguous_author_keys_are_rejected_as_entire_lesson(change):
    value = lesson()
    q = value["questions"][0]
    if change == "missing_key":
        q["correct_option_ids"] = []
    elif change == "unknown_key":
        q["correct_option_ids"] = [uid()]
    elif change == "duplicate_key":
        q["correct_option_ids"] *= 2
    elif change == "single_two_keys":
        q["correct_option_ids"] = [option["option_id"] for option in q["options"][:2]]
    elif change == "missing_reference":
        q["reference_ids"] = []
    elif change == "duplicate_reference":
        q["reference_ids"] *= 2
    elif change == "duplicate_option":
        q["options"][1]["option_id"] = q["options"][0]["option_id"]
    elif change == "duplicate_question":
        value["questions"][1] = copy.deepcopy(q)
    else:
        value["questions"][1]["options"][0]["option_id"] = q["options"][0]["option_id"]
    with pytest.raises(ValueError):
        c.PrivateTrainingLesson.model_validate(value, strict=True)


def test_full64_questions_and16_options_each_are_retained_then65_or17_rejected():
    value = lesson([question("multiple", 16) for _ in range(64)])
    public = c.project_lesson(value)
    assert len(public.questions) == 64 and sum(len(q.options) for q in public.questions) == 1024
    assert s.score_submission(value, submission(value)).matching_count == 64
    extra = copy.deepcopy(value)
    extra["questions"].append(question())
    with pytest.raises(ValueError):
        c.project_lesson(extra)
    extra = lesson([question("multiple", 17)])
    with pytest.raises(ValueError):
        c.project_lesson(extra)


def test_matching_differing_and_explicit_unanswered_are_separate_complete_states():
    value = lesson([question(), question("multiple"), question()])
    choices = [value["questions"][0]["correct_option_ids"], [value["questions"][1]["options"][0]["option_id"]], []]
    actual = s.score_submission(value, submission(value, choices))
    assert (actual.question_count, actual.matching_count, actual.differing_count, actual.unanswered_count) == (3, 1, 1, 1)
    assert [q.outcome for q in actual.questions] == ["matches_reviewed_key", "differs_from_reviewed_key", "explicitly_unanswered"]
    assert actual.questions[2].selected_option_ids == []
    assert actual.assessment_claim == "practice_record_only_not_clinical_competence_or_credential"


def test_multiple_choice_requires_exact_set_match_without_order_or_partial_credit():
    value = lesson([question("multiple")])
    answer = submission(value)
    answer["answers"][0]["selected_option_ids"].reverse()
    assert s.score_submission(value, answer).matching_count == 1
    answer["answers"][0]["selected_option_ids"].append(value["questions"][0]["options"][-1]["option_id"])
    assert s.score_submission(value, answer).differing_count == 1


@pytest.mark.parametrize(
    "change",
    ["missing_question", "extra_question", "duplicate_question", "foreign_option", "cross_question_option", "duplicate_option", "single_many", "wrong_source", "wrong_lesson", "unreviewed_text"],
)
def test_incomplete_forged_or_unreviewed_submissions_cannot_be_scored_as_zero_or_partial(change):
    value = lesson()
    answer = submission(value)
    if change == "missing_question":
        answer["answers"].pop()
    elif change == "extra_question":
        answer["answers"].append(dict(question_id=uid(), selected_option_ids=[]))
    elif change == "duplicate_question":
        answer["answers"].append(copy.deepcopy(answer["answers"][0]))
    elif change == "foreign_option":
        answer["answers"][0]["selected_option_ids"] = [uid()]
    elif change == "cross_question_option":
        answer["answers"][0]["selected_option_ids"] = [value["questions"][1]["options"][0]["option_id"]]
    elif change == "duplicate_option":
        answer["answers"][0]["selected_option_ids"] *= 2
    elif change == "single_many":
        answer["answers"][0]["selected_option_ids"] = [option["option_id"] for option in value["questions"][0]["options"][:2]]
    elif change == "wrong_source":
        answer["public_source_sha256"] = "0" * 64
    elif change == "wrong_lesson":
        answer["lesson_id"] = uid()
    else:
        answer["free_text_patient_story"] = "未审核新内容"
    with pytest.raises(ValueError):
        s.score_submission(value, answer)


@pytest.mark.parametrize("field", ["matching_count", "unanswered_count", "assessment_claim", "questions", "submission_sha256"])
def test_feedback_is_rebuilt_from_entire_actual_record_instead_of_trusting_claimed_grade(field):
    private = lesson()
    answer = submission(private)
    feedback = s.score_submission(private, answer).model_dump()
    if field == "matching_count":
        feedback[field] = 0
    elif field == "unanswered_count":
        feedback[field] = 1
    elif field == "assessment_claim":
        feedback[field] = "clinical_competence_certified"
    elif field == "questions":
        feedback[field][0]["reviewed_rationale"] = "invented explanation"
    else:
        feedback[field] = "0" * 64
    with pytest.raises(ValueError):
        s.verify_feedback(feedback, private, answer)


def test_copied_typed_private_and_submission_instances_are_revalidated_with_nested_fields():
    private = c.PrivateTrainingLesson.model_validate(lesson())
    answer = s.LessonSubmission.model_validate(submission(private.model_dump()))
    bad_private = private.model_copy(update={"created_by": True})
    with pytest.raises(ValueError):
        s.score_submission(bad_private, answer)
    bad_answer = answer.model_copy(update={"answers": [answer.answers[0].model_copy(update={"selected_option_ids": [True]})]})
    with pytest.raises(ValueError):
        s.score_submission(private, bad_answer)


@pytest.mark.parametrize("raw", [b'{"lesson_id":"a","lesson_id":"b"}', b'{"created_by":NaN}', b'{"created_by":1.0}', b'{"title":"\xff"}'])
def test_raw_json_rejects_duplicate_nonfinite_fractional_and_invalid_utf8(raw):
    with pytest.raises(ValueError):
        c.project_lesson(raw)


def test_real4m_non_bmp_scenario_boundary_is_byte_based_and_preserves_every_character():
    value = lesson()
    value["scenario_text"] = "😀" * (c.TEXT_BYTES // 4)
    actual = c.project_lesson(value)
    assert len(actual.scenario_text.encode()) == c.TEXT_BYTES
    value["scenario_text"] += "a"
    with pytest.raises(ValueError):
        c.project_lesson(value)


def test_real_complete_private8m_boundary_then_plus_one_rejects_without_first_n_clipping():
    value = lesson([question("multiple", 16) for _ in range(32)])
    for q in value["questions"]:
        for option in q["options"]:
            option["text"] = "汉" * 4000
    value["scenario_text"] = "a"
    available = c.WHOLE_BYTES - len(c.canonical_json(value).encode()) + 1
    assert 0 < available < c.TEXT_BYTES
    value["scenario_text"] = "a" * available
    assert len(c.canonical_json(value).encode()) == c.WHOLE_BYTES
    private = c.PrivateTrainingLesson.model_validate(value, strict=True)
    assert len(c.project_lesson(private).questions) == 32
    value["scenario_text"] += "a"
    with pytest.raises(ValueError):
        c.project_lesson(value)


def test_public_projection_and_all_scores_are_stable_for_original_utf8_wire():
    private = lesson()
    answer = submission(private)
    raw = c.canonical_json(private).encode()
    submission_raw = c.canonical_json(answer).encode()
    public = c.project_lesson(raw)
    feedback = s.score_submission(raw, submission_raw)
    assert c.verify_projection(c.canonical_json(public), raw)
    assert s.verify_feedback(c.canonical_json(feedback), raw, submission_raw) == feedback
