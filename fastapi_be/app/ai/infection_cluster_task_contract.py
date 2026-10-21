"""Closed local-statistics tasks; no model endpoint, prompt generation or authority."""

import datetime as dt
from typing import Literal

from pydantic import Field, model_validator

from app.ai import infection_cluster_contract as c
from app.ai import infection_cluster_statistics_contract as k

FEATURE_KEY = "infection_cluster"
TEXT_BYTES = 65535
LOCAL_TASK_TEXT = c.canonical({"origin": "local_fixed_recipe", "engine": "prediction", "recipe": k.RECIPE, "limitations": k.LIMITATIONS})
LOCAL_PROMPT_HASH = c.digest(["", LOCAL_TASK_TEXT])
RAW_FIELDS = ("input_json", "evidence_json", "context_metadata_json", "result_json")


def task_json(value):
    text = c.canonical(value)
    if len(c.utf8(text)) > TEXT_BYTES:
        raise ValueError("A complete legacy Task TEXT field exceeds65535UTF8 bytes; no truncation")
    return text


class TaskCreate(c.StrictModel):
    infection_cluster_scenario_id: c.UUID
    preview: bool = Field(strict=True)


class RequesterEpoch(c.StrictModel):
    user_id: c.PositiveId
    user_role: Literal["super_admin", "admin", "director"]
    token_invalid_before: str | None

    @model_validator(mode="after")
    def original_clock(self):
        if self.token_invalid_before is not None:
            stamp = dt.datetime.fromisoformat(self.token_invalid_before)
            if stamp.tzinfo is not None or stamp.isoformat() != self.token_invalid_before:
                raise ValueError("The exact stored token epoch is a naive ISO value, not an invented UTC clock")
        return self


class FrozenTask(c.StrictModel):
    schema_version: Literal["infection_local_frozen_task_v1"]
    feature_key: Literal["infection_cluster"]
    engine: Literal["prediction"]
    execution: Literal["installed_local_exact_integer_statistics_no_external_model"]
    run_id: c.UUID
    requester_epoch: RequesterEpoch
    preview: bool = Field(strict=True)
    created_at: str
    scenario_id: c.UUID
    scenario_content_hash: c.SHA
    scenario_governance_hash: c.SHA
    source_binding: k.SourceBinding
    profile_id: c.UUID
    profile_content_hash: c.SHA
    profile_governance_hash: c.SHA
    feature_revision: int = Field(strict=True, ge=1)
    selection_revision: int = Field(strict=True, ge=1)
    configuration_hash: c.SHA
    recipe_hash: c.SHA
    implementation_hash: c.SHA
    source_hash: c.SHA
    prompt_origin: Literal["local_fixed_recipe"]
    prompt_version: int = Field(strict=True, ge=0, le=0)
    system_prompt: Literal[""]
    task_prompt: str
    prompt_hash: c.SHA
    external_model_transfer: Literal[False]

    @model_validator(mode="after")
    def fixed_local_task(self):
        c.clock(self.created_at)
        if self.recipe_hash != c.digest(k.RECIPE) or self.task_prompt != LOCAL_TASK_TEXT or self.prompt_hash != LOCAL_PROMPT_HASH:
            raise ValueError("Local fixed recipe and the canonical[empty system,complete recipe]Task hash differ")
        task_json(self)
        return self


class ResultPointer(c.StrictModel):
    schema_version: Literal["infection_statistics_result_pointer_v1"]
    run_id: c.UUID
    source_hash: c.SHA
    result_hash: c.SHA
    result_bytes: int = Field(strict=True, ge=1, le=c.MAX_BYTES)


class LocalUsage(c.StrictModel):
    schema_version: Literal["infection_local_usage_v1"]
    run_id: c.UUID
    lease: c.UUID | None
    terminal_status: Literal["succeeded", "failed", "cancelled"]
    input_tokens: int = Field(strict=True, ge=0, le=0)
    output_tokens: int = Field(strict=True, ge=0, le=0)
    model_call_attempted: Literal[False]
    accounting_basis: Literal["installed_local_calculation_without_external_model_call_not_a_cpu_cost_estimate"]
    calculation_attempted: bool | None = Field(strict=True)
    calculation_completed: bool | None = Field(strict=True)
    calculation_ms: int | None = Field(strict=True, ge=0)
    result_hash: c.SHA | None

    @model_validator(mode="after")
    def observed_not_reserved(self):
        if self.calculation_completed is True and self.calculation_attempted is not True:
            raise ValueError("A completed calculation was actually attempted")
        if self.calculation_attempted is False and (self.calculation_completed is not False or self.calculation_ms is not None):
            raise ValueError("A known unattempted calculation has no invented elapsed CPU estimate")
        if (self.terminal_status == "succeeded") != (self.result_hash is not None):
            raise ValueError("Only an accepted success has a complete result hash")
        if self.terminal_status == "succeeded" and self.calculation_completed is not True:
            raise ValueError("Success requires actual completed local calculation")
        return self
