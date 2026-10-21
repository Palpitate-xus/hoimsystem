"""Pure complete Prompt snapshots, including the packaged version-zero branch.

This proves internal literal consistency only. Services must separately current-
read the actual Prompt FK/config and current project/patient/model authority.
Database Prompt authors/notes are private artifact data, never model evidence.
"""

import datetime as dt
from typing import Annotated, Literal

from pydantic import AfterValidator, Field, model_validator

from app.ai.deidentification_contract import StrictModel
from app.ai.deidentification_prompt import SYSTEM_PROMPT, TASK_VERSION, instructions_digest, prompt_hash
from app.ai.deidentification_spans import canonical, text_digest, utf8
from app.ai.research_cohort_contract import SHA, UUID, Positive, scalar

FEATURE_KEY = "deidentification"
PROMPT_BYTES = 65535


def bounded_prompt(value):
    scalar(value)
    if len(utf8(value)) > PROMPT_BYTES:
        raise ValueError("The actual complete Prompt must fit its stored UTF8 TEXT")
    return value


PromptText = Annotated[str, Field(strict=True, min_length=1, max_length=PROMPT_BYTES), AfterValidator(bounded_prompt)]


class DatabasePromptSnapshot(StrictModel):
    prompt_id: UUID
    feature_key: Literal["deidentification"]
    version: Positive
    task_prompt: PromptText
    change_note: Annotated[str, Field(strict=True, max_length=1000), AfterValidator(scalar)]
    created_by: Positive
    create_time: Annotated[str, Field(strict=True, min_length=19, max_length=26)]

    @model_validator(mode="after")
    def original_naive_clock(self):
        clock = dt.datetime.fromisoformat(self.create_time)
        if clock.tzinfo is not None or str(clock) != self.create_time:
            raise ValueError("Preserve the exact original naive-UTC SQL clock string")
        return self


class DeidentificationFrozenPrompt(StrictModel):
    schema_version: Literal["deidentification_frozen_prompt_v1"]
    origin: Literal["packaged_catalog", "database_version"]
    prompt_version_id: UUID | None
    version: Annotated[int, Field(strict=True, ge=0, le=2147483647)]
    catalog_version: Annotated[str, Field(strict=True, min_length=1, max_length=40), AfterValidator(scalar)]
    native_task_version: Literal["deidentification_literal_candidates_v1"]
    system_prompt: PromptText
    task_prompt: PromptText
    system_hash: SHA
    task_hash: SHA
    prompt_hash: SHA
    instructions_digest: SHA
    database_snapshot: DatabasePromptSnapshot | None

    @model_validator(mode="after")
    def complete_branch_and_literal_hashes(self):
        if self.origin == "packaged_catalog":
            if self.prompt_version_id is not None or self.version != 0 or self.database_snapshot is not None:
                raise ValueError("Packaged version zero has no fabricated saved Prompt row")
        else:
            snapshot = self.database_snapshot
            if self.prompt_version_id is None or self.version <= 0 or snapshot is None:
                raise ValueError("A saved version requires its real FK and complete original record")
            if snapshot.prompt_id != self.prompt_version_id or snapshot.version != self.version or snapshot.task_prompt != self.task_prompt:
                raise ValueError("The original saved Prompt ID/version/full Task differs")
        if self.system_prompt != SYSTEM_PROMPT:
            raise ValueError("This native contract uses its exact fixed System text")
        if self.system_hash != text_digest(self.system_prompt) or self.task_hash != text_digest(self.task_prompt):
            raise ValueError("Full raw UTF8 System/Task hashes differ")
        if self.prompt_hash != prompt_hash(self.task_prompt) or self.instructions_digest != instructions_digest(self.task_prompt):
            raise ValueError("Canonical Prompt hash and raw instructions digest are distinct bindings")
        return self


def verify_frozen_prompt(value):
    # Reparse nested model instances, including adversarial model_construct,
    # rather than relying on Pydantic's default instance revalidation policy.
    if isinstance(value, DeidentificationFrozenPrompt):
        value = value.model_dump(mode="json")
    from app.ai.deidentification_http import parse_json

    value = parse_json(utf8(canonical(value)))
    return DeidentificationFrozenPrompt.model_validate(value, strict=True).model_dump(mode="json")


def freeze_prompt(task_prompt, *, catalog_version, database_snapshot=None):
    """Caller supplies the actual complete selected Task, not a short suffix.

    A non-null database snapshot must come from the service's real current row;
    this pure helper cannot establish that a database row exists or is active.
    """
    if database_snapshot is not None:
        database_snapshot = DatabasePromptSnapshot.model_validate(database_snapshot, strict=True).model_dump(mode="json")
    value = {
        "schema_version": "deidentification_frozen_prompt_v1",
        "origin": "database_version" if database_snapshot is not None else "packaged_catalog",
        "prompt_version_id": database_snapshot["prompt_id"] if database_snapshot is not None else None,
        "version": database_snapshot["version"] if database_snapshot is not None else 0,
        "catalog_version": catalog_version,
        "native_task_version": TASK_VERSION,
        "system_prompt": SYSTEM_PROMPT,
        "task_prompt": task_prompt,
        "system_hash": text_digest(SYSTEM_PROMPT),
        "task_hash": text_digest(task_prompt),
        "prompt_hash": prompt_hash(task_prompt),
        "instructions_digest": instructions_digest(task_prompt),
        "database_snapshot": database_snapshot,
    }
    return verify_frozen_prompt(value)
