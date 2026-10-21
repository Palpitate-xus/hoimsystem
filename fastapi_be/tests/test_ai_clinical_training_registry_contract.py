"""Finite governance input, without assuming declaration or hashes grant access."""

import pytest
from pydantic import ValidationError

from app.ai.clinical_training_registry_contract import TrainingLessonCreate, TrainingLessonReview, TrainingSourceRevoke
from tests.test_ai_clinical_training_contract import lesson


def request():
    value = lesson()
    return {**{key: value[key] for key in ("version_label", "title", "scenario_text", "learning_objectives", "questions")}, "synthetic_material_declared": True}


def review():
    return dict(expected_lesson_revision=1, expected_private_sha256="1" * 64, expected_public_sha256="2" * 64, expected_references_sha256="3" * 64, decision="publish", synthetic_material_checked=True, answer_key_checked=True, reference_applicability_checked=True, model_processing_allowed=False, basis="明确合成教学、答案与当前参考材料适用性人工审核声明。")


def test_creation_has_no_client_supplied_author_clock_identity_or_fake_publication():
    value = request()
    parsed = TrainingLessonCreate.model_validate(value, strict=True)
    assert parsed.scenario_text == value["scenario_text"] and parsed.questions[0].correct_option_ids
    for key, injected in {"created_by": 1, "created_at": "2026-10-21T00:00:00.000001Z", "lesson_id": lesson()["lesson_id"], "status": "published", "patient_id": 1, "encounter_ref": "1"}.items():
        with pytest.raises(ValidationError):
            TrainingLessonCreate.model_validate({**value, key: injected}, strict=True)


@pytest.mark.parametrize("value", [False, 1, "true", None])
def test_synthetic_declaration_must_be_an_explicit_true_boolean(value):
    with pytest.raises(ValidationError):
        TrainingLessonCreate.model_validate({**request(), "synthetic_material_declared": value}, strict=True)


@pytest.mark.parametrize("field", ["synthetic_material_checked", "answer_key_checked", "reference_applicability_checked"])
def test_publication_requires_each_independent_checked_assertion(field):
    with pytest.raises(ValidationError):
        TrainingLessonReview.model_validate({**review(), field: False}, strict=True)


def test_internal_publication_is_separate_from_model_processing_and_rejection_never_transfers():
    assert TrainingLessonReview.model_validate(review(), strict=True).model_processing_allowed is False
    rejected = {**review(), "decision": "reject", "synthetic_material_checked": False}
    assert TrainingLessonReview.model_validate(rejected, strict=True).decision == "reject"
    with pytest.raises(ValidationError):
        TrainingLessonReview.model_validate({**rejected, "model_processing_allowed": True}, strict=True)


@pytest.mark.parametrize("revision", [0, 2, True, "1"])
def test_revoke_uses_an_explicit_original_revision_without_republication(revision):
    with pytest.raises(ValidationError):
        TrainingSourceRevoke.model_validate(dict(revision=revision, reason="明确教学来源撤回"), strict=True)
