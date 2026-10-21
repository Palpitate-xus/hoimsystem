"""Pure finite synthetic lessons; declarations do not establish server publication."""

import datetime as dt
import hashlib
import json
import re
import uuid
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

WHOLE_BYTES = 8 * 1024 * 1024
TEXT_BYTES = 4 * 1024 * 1024


def scalar(value):
    value.encode("utf-8", errors="strict")
    return value


def identifier(value):
    if str(uuid.UUID(value)) != value:
        raise ValueError("A canonical UUID is required")
    return value


def clock(value):
    if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{6}Z", value):
        raise ValueError("An explicit UTC microsecond declaration clock is required")
    dt.datetime.fromisoformat(value[:-1] + "+00:00")
    return value


def whole_text(value):
    if len(scalar(value).encode()) > TEXT_BYTES:
        raise ValueError("The whole scenario exceeds its UTF8 byte budget")
    return value


Identifier = Annotated[str, Field(strict=True, min_length=36, max_length=36), AfterValidator(identifier)]
Clock = Annotated[str, Field(strict=True, min_length=27, max_length=27), AfterValidator(clock)]
Title = Annotated[str, Field(strict=True, min_length=1, max_length=300), AfterValidator(scalar)]
Note = Annotated[str, Field(strict=True, min_length=1, max_length=4000), AfterValidator(scalar)]
Text = Annotated[str, Field(strict=True, min_length=1), AfterValidator(whole_text)]
Digest = Annotated[str, Field(strict=True, min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")]
ActorId = Annotated[int, Field(strict=True, ge=1, le=2147483647)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True, revalidate_instances="always", str_strip_whitespace=False)


def canonical_json(value):
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    result = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    result.encode("utf-8", errors="strict")
    return result


def content_hash(value):
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def whole(value):
    result = canonical_json(value)
    if len(result.encode()) > WHOLE_BYTES:
        raise ValueError("The complete finite training packet exceeds8MiB; no partial lesson is accepted")
    return result


class Option(StrictModel):
    option_id: Identifier
    text: Note


class PublicQuestion(StrictModel):
    question_id: Identifier
    selection: Literal["single", "multiple"]
    stem: Note
    options: Annotated[list[Option], Field(min_length=2, max_length=16)]

    @model_validator(mode="after")
    def distinct_options(self):
        if len({option.option_id for option in self.options}) != len(self.options):
            raise ValueError("Every option must retain an explicit distinct identity")
        return self


class PrivateQuestion(PublicQuestion):
    correct_option_ids: Annotated[list[Identifier], Field(min_length=1, max_length=16)]
    reviewed_rationale: Note
    reference_ids: Annotated[list[Identifier], Field(min_length=1, max_length=32)]

    @model_validator(mode="after")
    def actual_answer_key(self):
        answers = set(self.correct_option_ids)
        if len(answers) != len(self.correct_option_ids) or not answers.issubset({option.option_id for option in self.options}):
            raise ValueError("The explicit complete key must refer only to actual options")
        if self.selection == "single" and len(answers) != 1:
            raise ValueError("A single-choice question has exactly one declared correct option")
        if len(set(self.reference_ids)) != len(self.reference_ids):
            raise ValueError("Reference identities cannot be silently deduplicated")
        return self


class PrivateTrainingLesson(StrictModel):
    schema_version: Literal["clinical_training_private_lesson_v1"]
    lesson_id: Identifier
    version_label: Title
    title: Title
    scenario_text: Text
    learning_objectives: Annotated[list[Title], Field(min_length=1, max_length=32)]
    questions: Annotated[list[PrivateQuestion], Field(min_length=1, max_length=64)]
    created_by: ActorId
    created_at: Clock
    material_basis: Literal["author_declared_synthetic_not_independently_verified_by_contract"]
    intended_use: Literal["education_only_not_patient_treatment_or_credentialing"]

    @model_validator(mode="after")
    def finite_complete(self):
        validate_question_ids(self.questions)
        whole(self)
        return self


def validate_question_ids(questions):
    ids = [question.question_id for question in questions]
    option_ids = [option.option_id for question in questions for option in question.options]
    if len(set(ids)) != len(ids) or len(set(option_ids)) != len(option_ids):
        raise ValueError("Question/option identities must remain distinct across this complete lesson")


class PublicTrainingLesson(StrictModel):
    schema_version: Literal["clinical_training_public_lesson_v1"]
    lesson_id: Identifier
    version_label: Title
    title: Title
    scenario_text: Text
    learning_objectives: Annotated[list[Title], Field(min_length=1, max_length=32)]
    questions: Annotated[list[PublicQuestion], Field(min_length=1, max_length=64)]
    intended_use: Literal["education_only_not_patient_treatment_or_credentialing"]
    answer_visibility: Literal["released_feedback_only_after_server_authorized_submission"]

    @model_validator(mode="after")
    def complete_public(self):
        validate_question_ids(self.questions)
        whole(self)
        return self


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError("Repeated JSON keys cannot be silently resolved")
        result[key] = value
    return result


def _bad_number(value):
    raise ValueError("Fractional and nonfinite JSON numbers are outside the training contract")


def parse_packet(value):
    if type(value) is bytes:
        if len(value) > WHOLE_BYTES:
            raise ValueError("Complete raw packet exceeds8MiB")
        value = value.decode("utf-8", errors="strict")
    if type(value) is str:
        if len(value.encode("utf-8", errors="strict")) > WHOLE_BYTES:
            raise ValueError("Complete raw packet exceeds8MiB")
        return json.loads(value, object_pairs_hook=_pairs, parse_constant=_bad_number, parse_float=_bad_number)
    return value


def project_lesson(value):
    private = PrivateTrainingLesson.model_validate(parse_packet(value), strict=True)
    # No answer key, rationale, private digest, author or capture metadata is
    # exposed. Hashing a low-entropy answer key is not answer-key secrecy.
    return PublicTrainingLesson(
        schema_version="clinical_training_public_lesson_v1",
        lesson_id=private.lesson_id,
        version_label=private.version_label,
        title=private.title,
        scenario_text=private.scenario_text,
        learning_objectives=private.learning_objectives,
        questions=[PublicQuestion.model_validate(question.model_dump(exclude={"correct_option_ids", "reviewed_rationale", "reference_ids"}), strict=True) for question in private.questions],
        intended_use=private.intended_use,
        answer_visibility="released_feedback_only_after_server_authorized_submission",
    )


def verify_projection(public, private):
    actual = PublicTrainingLesson.model_validate(parse_packet(public), strict=True)
    return whole(actual) == whole(project_lesson(private))
