"""Deterministic practice matching against a supplied key, never competency certification."""

from typing import Annotated, Literal

from pydantic import Field, model_validator

from app.ai import clinical_training_contract as c


class QuestionAnswer(c.StrictModel):
    question_id: c.Identifier
    selected_option_ids: Annotated[list[c.Identifier], Field(max_length=16)]

    @model_validator(mode="after")
    def explicit_distinct(self):
        if len(set(self.selected_option_ids)) != len(self.selected_option_ids):
            raise ValueError("Repeated selections cannot be silently merged")
        return self


class LessonSubmission(c.StrictModel):
    lesson_id: c.Identifier
    public_source_sha256: c.Digest
    answers: Annotated[list[QuestionAnswer], Field(min_length=1, max_length=64)]

    @model_validator(mode="after")
    def distinct_questions(self):
        if len({answer.question_id for answer in self.answers}) != len(self.answers):
            raise ValueError("Each question must have one explicit answer record")
        c.whole(self)
        return self


class QuestionPracticeFeedback(c.StrictModel):
    question_id: c.Identifier
    selected_option_ids: Annotated[list[c.Identifier], Field(max_length=16)]
    outcome: Literal["matches_reviewed_key", "differs_from_reviewed_key", "explicitly_unanswered"]
    correct_option_ids: Annotated[list[c.Identifier], Field(min_length=1, max_length=16)]
    reviewed_rationale: c.Note
    reference_ids: Annotated[list[c.Identifier], Field(min_length=1, max_length=32)]


class PracticeFeedback(c.StrictModel):
    schema_version: Literal["clinical_training_practice_feedback_v1"]
    lesson_id: c.Identifier
    public_source_sha256: c.Digest
    submission_sha256: c.Digest
    scoring_method: Literal["all_selected_options_exact_set_match_v1"]
    assessment_claim: Literal["practice_record_only_not_clinical_competence_or_credential"]
    question_count: Annotated[int, Field(strict=True, ge=1, le=64)]
    matching_count: Annotated[int, Field(strict=True, ge=0, le=64)]
    differing_count: Annotated[int, Field(strict=True, ge=0, le=64)]
    unanswered_count: Annotated[int, Field(strict=True, ge=0, le=64)]
    questions: Annotated[list[QuestionPracticeFeedback], Field(min_length=1, max_length=64)]


def score_submission(private_lesson, submission):
    private = c.PrivateTrainingLesson.model_validate(c.parse_packet(private_lesson), strict=True)
    source = c.project_lesson(private)
    submission = LessonSubmission.model_validate(c.parse_packet(submission), strict=True)
    if submission.lesson_id != private.lesson_id or submission.public_source_sha256 != c.content_hash(source):
        raise ValueError("Submission must bind this entire immutable public lesson")
    answers = {answer.question_id: answer for answer in submission.answers}
    if set(answers) != {question.question_id for question in private.questions}:
        raise ValueError("Every actual question requires an explicit answer; absent is not unanswered")
    feedback = []
    for question in private.questions:
        answer = answers[question.question_id]
        selected = set(answer.selected_option_ids)
        if not selected.issubset({option.option_id for option in question.options}) or question.selection == "single" and len(selected) > 1:
            raise ValueError("Answer includes a foreign option or invalid selection count")
        outcome = "explicitly_unanswered" if not selected else ("matches_reviewed_key" if selected == set(question.correct_option_ids) else "differs_from_reviewed_key")
        feedback.append(
            QuestionPracticeFeedback(
                question_id=question.question_id,
                selected_option_ids=answer.selected_option_ids,
                outcome=outcome,
                correct_option_ids=question.correct_option_ids,
                reviewed_rationale=question.reviewed_rationale,
                reference_ids=question.reference_ids,
            )
        )
    result = PracticeFeedback(
        schema_version="clinical_training_practice_feedback_v1",
        lesson_id=private.lesson_id,
        public_source_sha256=c.content_hash(source),
        submission_sha256=c.content_hash(submission),
        scoring_method="all_selected_options_exact_set_match_v1",
        assessment_claim="practice_record_only_not_clinical_competence_or_credential",
        question_count=len(feedback),
        matching_count=sum(item.outcome == "matches_reviewed_key" for item in feedback),
        differing_count=sum(item.outcome == "differs_from_reviewed_key" for item in feedback),
        unanswered_count=sum(item.outcome == "explicitly_unanswered" for item in feedback),
        questions=feedback,
    )
    c.whole(result)
    return result


def verify_feedback(value, private_lesson, submission):
    actual = PracticeFeedback.model_validate(c.parse_packet(value), strict=True)
    expected = score_submission(private_lesson, submission)
    if c.whole(actual) != c.whole(expected):
        raise ValueError("Every practice score, answer, rationale and reference must match the complete deterministic record")
    return actual
