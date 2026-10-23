"""Finite synthetic teaching governance requests; declarations grant no access."""

from typing import Annotated, Literal

from pydantic import AfterValidator, Field, model_validator

from app.ai import clinical_training_contract as c


class TrainingLessonCreate(c.StrictModel):
    version_label: c.Title
    title: c.Title
    scenario_text: c.Text
    learning_objectives: Annotated[list[c.Title], Field(min_length=1, max_length=32)]
    questions: Annotated[list[c.PrivateQuestion], Field(min_length=1, max_length=64)]
    synthetic_material_declared: bool

    @model_validator(mode="after")
    def finite_declared_material(self):
        if self.synthetic_material_declared is not True:
            raise ValueError("An explicit synthetic-material declaration is required, without treating it as verification")
        c.validate_question_ids(self.questions)
        c.whole(self)
        return self


class TrainingLessonReview(c.StrictModel):
    expected_lesson_revision: Annotated[int, Field(strict=True, ge=1, le=1)]
    expected_private_sha256: c.Digest
    expected_public_sha256: c.Digest
    expected_references_sha256: c.Digest
    decision: Literal["publish", "reject"]
    synthetic_material_checked: bool
    answer_key_checked: bool
    reference_applicability_checked: bool
    model_processing_allowed: bool
    basis: c.Note

    @model_validator(mode="after")
    def explicit_independent_review(self):
        if self.decision == "publish" and any(value is not True for value in (self.synthetic_material_checked, self.answer_key_checked, self.reference_applicability_checked)):
            raise ValueError("Publication requires each explicit independent review assertion")
        if self.decision == "reject" and self.model_processing_allowed:
            raise ValueError("A rejected lesson cannot authorize model processing")
        return self


class TrainingSourceRevoke(c.StrictModel):
    revision: Annotated[int, Field(strict=True, ge=1, le=1)]
    reason: Annotated[str, Field(strict=True, min_length=1, max_length=1000), AfterValidator(c.scalar)]


class TrainingReviewedLesson(c.StrictModel):
    schema_version: Literal["clinical_training_independent_review_v1"]
    review_id: c.Identifier
    lesson_id: c.Identifier
    reviewed_by: c.ActorId
    reviewed_at: c.Clock
    proposal: TrainingLessonReview
