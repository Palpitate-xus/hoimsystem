"""Pure closed educational feedback drafts, never independent Source authority.

The server must independently prove the actual submission receipt, current
lesson/review/reference/actor and exact deterministic key before constructing a
source. Public hashes or internally consistent declared keys prove none of it.
"""

import hashlib
from typing import Annotated, Literal

from pydantic import AfterValidator, Field, TypeAdapter, model_validator

from app.ai import clinical_training_contract as c
from app.ai import clinical_training_scoring as scoring

OBJECTIVES = {
    "explain_practice_feedback": "解释本次已提交练习与审核答案的相符、不同和明确未作答项",
    "review_supplied_material": "仅用本课程审核解析与所选参考安排原知识点复习",
    "identify_reviewed_gaps": "整理本次练习中现有受审材料尚不足以解释的明确缺口",
}
Objective = Literal["explain_practice_feedback", "review_supplied_material", "identify_reviewed_gaps"]


class TrainingTaskSelection(c.StrictModel):
    clinical_training_submission_id: c.Identifier
    objective: Objective


class ModelReference(c.StrictModel):
    document_id: c.Identifier
    title: Annotated[str, Field(strict=True, min_length=1, max_length=200), AfterValidator(c.scalar)]
    version: Annotated[str, Field(strict=True, min_length=1, max_length=80), AfterValidator(c.scalar)]
    content: str
    content_utf8_sha256: c.Digest

    @model_validator(mode="after")
    def complete_literal(self):
        raw = self.content.encode("utf-8", errors="strict")
        if not 1 <= len(raw) <= 65535 or hashlib.sha256(raw).hexdigest() != self.content_utf8_sha256:
            raise ValueError("The complete literal reference must match its actual raw hash")
        return self


class ModelReferences(c.StrictModel):
    schema_version: Literal["clinical_training_model_references_v1"]
    lesson_id: c.Identifier
    references: Annotated[list[ModelReference], Field(min_length=1, max_length=2048)]

    @model_validator(mode="after")
    def finite_sorted(self):
        ids = [item.document_id for item in self.references]
        if ids != sorted(set(ids)):
            raise ValueError("The whole sorted unique reference selection is required")
        c.whole(self)
        return self


class TrainingFeedbackSource(c.StrictModel):
    schema_version: Literal["clinical_training_feedback_source_v1"]
    source_id: c.Identifier
    lesson: c.PublicTrainingLesson
    submission: scoring.LessonSubmission
    feedback: scoring.PracticeFeedback
    references: ModelReferences
    intended_use: Literal["explain_actual_recorded_practice_not_patient_treatment_or_credentialing"]

    @model_validator(mode="after")
    def complete_declared_consistency_not_authority(self):
        lesson, submitted, feedback = self.lesson, self.submission, self.feedback
        public_hash = c.content_hash(lesson)
        if any(value != lesson.lesson_id for value in (submitted.lesson_id, feedback.lesson_id, self.references.lesson_id)) or submitted.public_source_sha256 != public_hash or feedback.public_source_sha256 != public_hash or feedback.submission_sha256 != c.content_hash(submitted):
            raise ValueError("Every complete packet must bind the actual declared lesson/submission")
        questions = {item.question_id: item for item in lesson.questions}
        answers = {item.question_id: item for item in submitted.answers}
        if set(answers) != set(questions) or [item.question_id for item in feedback.questions] != list(questions) or feedback.question_count != len(questions):
            raise ValueError("Every actual question requires one complete answer/feedback in lesson order")
        reference_ids = {item.document_id for item in self.references.references}
        selected_references, outcomes = set(), []
        for item in feedback.questions:
            question, answer = questions[item.question_id], answers[item.question_id]
            options = {option.option_id for option in question.options}
            correct = set(item.correct_option_ids)
            if not correct.issubset(options) or len(correct) != len(item.correct_option_ids) or question.selection == "single" and len(correct) != 1:
                raise ValueError("Declared key must remain finite and match this exact question")
            selected = set(answer.selected_option_ids)
            if not selected.issubset(options) or question.selection == "single" and len(selected) > 1 or item.selected_option_ids != answer.selected_option_ids:
                raise ValueError("Feedback must retain the actual complete submitted selection")
            outcome = "explicitly_unanswered" if not selected else "matches_reviewed_key" if selected == correct else "differs_from_reviewed_key"
            if item.outcome != outcome or len(set(item.reference_ids)) != len(item.reference_ids) or not set(item.reference_ids).issubset(reference_ids):
                raise ValueError("Declared outcome or exact question reference selection differs")
            selected_references.update(item.reference_ids)
            outcomes.append(outcome)
        if selected_references != reference_ids or any(getattr(feedback, field) != outcomes.count(outcome) for field, outcome in [("matching_count", "matches_reviewed_key"), ("differing_count", "differs_from_reviewed_key"), ("unanswered_count", "explicitly_unanswered")]):
            raise ValueError("No reference or exact deterministic outcome can be silently omitted")
        c.whole(self)
        return self


def validate_frozen_source(value, *, expected_source_hash, expected_feedback_hash, expected_public_hash, expected_submission_hash):
    """Expected hashes must come from independent current SQL/actual receipts."""
    for digest in (expected_source_hash, expected_feedback_hash, expected_public_hash, expected_submission_hash):
        TypeAdapter(c.Digest).validate_python(digest, strict=True)
    source = TrainingFeedbackSource.model_validate(c.parse_packet(value), strict=True)
    if (c.content_hash(source), c.content_hash(source.feedback), c.content_hash(source.lesson), c.content_hash(source.submission)) != (expected_source_hash, expected_feedback_hash, expected_public_hash, expected_submission_hash):
        raise ValueError("A self-consistent edited source cannot replace independent actual receipt hashes")
    return source


class TrainingQuote(c.StrictModel):
    target: Literal["reviewed_rationale", "reference_text"]
    question_id: c.Identifier | None
    document_id: c.Identifier | None
    start_codepoint: Annotated[int, Field(strict=True, ge=0, le=8388608)]
    end_codepoint: Annotated[int, Field(strict=True, ge=1, le=8388608)]
    quote: Annotated[str, Field(strict=True, min_length=1, max_length=65535), AfterValidator(c.scalar)]

    @model_validator(mode="after")
    def explicit_one_target(self):
        if self.end_codepoint <= self.start_codepoint or len(self.quote.encode()) > 65535:
            raise ValueError("An entire nonempty scalar-codepoint quote is required")
        if self.target == "reviewed_rationale" and (self.question_id is None or self.document_id is not None) or self.target == "reference_text" and (self.document_id is None or self.question_id is not None):
            raise ValueError("One exact rationale or reference target is required")
        return self


class QuestionExplanation(c.StrictModel):
    question_id: c.Identifier
    explanation: c.Note
    evidence: Annotated[list[TrainingQuote], Field(min_length=1, max_length=16)]


class RevisionStep(c.StrictModel):
    question_ids: Annotated[list[c.Identifier], Field(min_length=1, max_length=64)]
    kind: Literal["review_supplied_rationale", "reread_selected_reference", "repeat_same_synthetic_question"]
    explanation: c.Note
    evidence: Annotated[list[TrainingQuote], Field(min_length=1, max_length=16)]


class MaterialGap(c.StrictModel):
    question_ids: Annotated[list[c.Identifier], Field(min_length=1, max_length=64)]
    kind: Literal["missing_reviewed_explanation", "reference_not_supporting_request", "insufficient_reviewed_material"]
    description: c.Note


class TrainingFeedbackDraft(c.StrictModel):
    schema_version: Literal["clinical_training_feedback_draft_v1"]
    source_id: c.Identifier
    source_sha256: c.Digest
    feedback_sha256: c.Digest
    objective: Objective
    status: Literal["education_feedback_draft"]
    grade_policy: Literal["server_score_unchanged"]
    explanations: Annotated[list[QuestionExplanation], Field(max_length=64)]
    revision_steps: Annotated[list[RevisionStep], Field(max_length=32)]
    gaps: Annotated[list[MaterialGap], Field(max_length=64)]


def verify_draft(value, source, selection):
    """Caller already needs independently anchored, current authorized Source."""
    source = TrainingFeedbackSource.model_validate(c.parse_packet(source), strict=True)
    selection = TrainingTaskSelection.model_validate(c.parse_packet(selection), strict=True)
    draft = TrainingFeedbackDraft.model_validate(c.parse_packet(value), strict=True)
    if selection.clinical_training_submission_id != source.source_id or draft.source_id != source.source_id or draft.source_sha256 != c.content_hash(source) or draft.feedback_sha256 != c.content_hash(source.feedback) or draft.objective != selection.objective:
        raise ValueError("The draft must bind this exact actual practice and finite objective")
    questions = {item.question_id: item for item in source.feedback.questions}
    documents = {item.document_id: item for item in source.references.references}

    def scope(ids):
        if len(set(ids)) != len(ids) or not set(ids).issubset(questions):
            raise ValueError("Every explicit question must be actual and nonduplicated")

    def quotes(evidence, ids):
        supported = set()
        for item in evidence:
            if item.target == "reviewed_rationale":
                if item.question_id not in ids:
                    raise ValueError("A rationale cannot come from a different question")
                text = questions[item.question_id].reviewed_rationale
                supported.add(item.question_id)
            else:
                if item.document_id not in documents:
                    raise ValueError("No unselected reference can enter feedback")
                members = {key for key in ids if item.document_id in questions[key].reference_ids}
                if not members:
                    raise ValueError("A reference must belong to an explicit target question")
                supported.update(members)
                text = documents[item.document_id].content
            if item.end_codepoint > len(text) or text[item.start_codepoint:item.end_codepoint] != item.quote:
                raise ValueError("Quote must preserve the exact full scalar-codepoint slice")
        if supported != set(ids):
            raise ValueError("Every target question needs actual selected evidence")

    scope([item.question_id for item in draft.explanations])
    for item in draft.explanations:
        quotes(item.evidence, [item.question_id])
    for item in draft.revision_steps:
        scope(item.question_ids)
        quotes(item.evidence, item.question_ids)
    for item in draft.gaps:
        scope(item.question_ids)
    c.whole(draft)
    return draft
