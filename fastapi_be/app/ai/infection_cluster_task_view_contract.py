"""Closed split-wire views; structural proof never grants clinical authority."""

import datetime as dt
from typing import Any, Literal

from pydantic import Field, model_validator

from app.ai import infection_cluster_contract as c
from app.ai import infection_cluster_statistics_contract as k
from app.ai import infection_cluster_task_contract as t


class TaskAcknowledgement(c.StrictModel):
    run_id: c.UUID
    feature_key: Literal["infection_cluster"]
    status: Literal["queued"]
    result_available: Literal[False]


class TaskMetadata(c.StrictModel):
    schema_version: Literal["infection_local_task_metadata_v1"]
    run_id: c.UUID
    feature_key: Literal["infection_cluster"]
    engine: Literal["prediction"]
    status: Literal["queued", "running", "succeeded", "failed", "cancelled"]
    preview: bool = Field(strict=True)
    scenario_id: c.UUID
    snapshot_id: c.UUID
    profile_id: c.UUID
    created_at: str
    run_created_at: str
    run_finish_at: str | None
    source_hash: c.SHA
    source_bytes: int = Field(strict=True, ge=1, le=c.MAX_BYTES)
    result_hash: c.SHA | None
    result_bytes: int | None = Field(strict=True, ge=1, le=c.MAX_BYTES)
    result_available: bool = Field(strict=True)
    receipt_event_id: c.PositiveId | None
    usage: t.LocalUsage | None
    usage_receipt_status: Literal["pending", "recorded"]
    protected_hashes_are_opaque: Literal[True]
    clinical_parts_require_current_patient_purpose: Literal[True]
    clinical_body_included: Literal[False]
    parts_separately_bounded: Literal[True]
    automatic_actions: Literal[False]

    @model_validator(mode="after")
    def closed_clocks_and_result(self):
        c.clock(self.created_at)
        for value in [self.run_created_at, self.run_finish_at]:
            if value is not None:
                stamp = dt.datetime.fromisoformat(value)
                if stamp.tzinfo is not None or stamp.microsecond != 0 or stamp.isoformat() != value:
                    raise ValueError("Legacy Run clocks are exact naive second values, not UTC6 Source clocks")
        success = self.status == "succeeded"
        if self.result_available != success or (self.result_hash is not None) != success or (self.result_bytes is not None) != success:
            raise ValueError("Only actual successful complete results have a result hash/size")
        recorded = self.usage is not None
        if (self.receipt_event_id is not None) != recorded or self.usage_receipt_status != ("recorded" if recorded else "pending"):
            raise ValueError("Usage is paired to an exact real receipt PK")
        if self.status in {"failed", "succeeded"} and not recorded:
            raise ValueError("A completed terminal status cannot omit the real local receipt")
        if self.usage is not None and (self.usage.run_id, self.usage.terminal_status, self.usage.result_hash) != (self.run_id, self.status, self.result_hash):
            raise ValueError("The actual usage receipt belongs to this run and result")
        c.canonical(self)
        return self


class TaskPart(c.StrictModel):
    schema_version: Literal["infection_local_task_part_v1"]
    run_id: c.UUID
    part: Literal["task", "source", "result"]
    value: Any
    value_hash: c.SHA
    value_bytes: int = Field(strict=True, ge=1, le=c.MAX_BYTES)
    authority: Literal["current_patient_processing_and_local_profile_not_anonymity_or_clinical_validation"]

    @model_validator(mode="after")
    def complete_exact_part(self):
        if self.part == "task":
            value = t.FrozenTask.model_validate(self.value)
            if value.run_id != self.run_id:
                raise ValueError("The complete frozen task belongs to another run")
        elif self.part == "source":
            value = k.StatisticsInput.model_validate(self.value)
        else:
            value = k.Analysis.model_validate(self.value) if self.value is not None else None
        if c.canonical(value) != c.canonical(self.value) or self.value_hash != c.digest(value) or self.value_bytes != len(c.utf8(c.canonical(value))):
            raise ValueError("The whole split part typed value/hash/UTF8 bytes differ")
        c.canonical(self)
        return self


class TaskDirectory(c.StrictModel):
    schema_version: Literal["infection_local_task_directory_v1"]
    items: list[TaskMetadata] = Field(max_length=100)
    total: int = Field(strict=True, ge=0)
    page: int = Field(strict=True, ge=1)
    size: int = Field(strict=True, ge=1, le=100)
    native_artifacts_only: Literal[True]
    clinical_body_included: Literal[False]

    @model_validator(mode="after")
    def complete_page(self):
        if len(self.items) != min(self.size, max(0, self.total - (self.page - 1) * self.size)) or len({item.run_id for item in self.items}) != len(self.items):
            raise ValueError("The declared native directory count/page is inconsistent")
        c.canonical(self)
        return self
