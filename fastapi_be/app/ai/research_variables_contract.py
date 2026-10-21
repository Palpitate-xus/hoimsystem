"""Pure typed76 variable dictionary and explicit authorized batch references."""

from typing import Annotated, Literal

from pydantic import AfterValidator, Field, model_validator

from app.ai.research_cohort_contract import SHA, UUID, Basis, Family, Label, Positive, RecordWindow, ScopeReference, StrictModel, ordered, scalar
from app.ai.research_variables_fields import MAX_VARIABLES, VARIABLE_FIELDS

Key = Annotated[str, Field(strict=True, pattern=r"^[a-z][a-z0-9_]{0,63}$")]
Kind = Literal["verbatim_text", "original_integer", "original_calendar_date", "original_naive_clock"]
Unit = Annotated[str, Field(strict=True, min_length=1, max_length=64), AfterValidator(scalar)]


class VariableDefinition(StrictModel):
    variable_key: Key
    label: Label
    family: Family
    field: Annotated[str, Field(strict=True, min_length=1, max_length=64)]
    value_kind: Kind
    record_window: RecordWindow | None
    temporal_policy: Literal["explicit_recorded_window_unknown_clock_separate", "static_subject_field_without_event_clock"]
    record_policy: Literal["all_recorded_candidates_no_automatic_winner"]
    unit_policy: Literal["preserve_original_literal_no_conversion"]
    declared_unit: Unit | None
    missingness_policy: Literal["explicit_literal_evidence_else_unknown"]
    extraction_instruction: Basis

    @model_validator(mode="after")
    def exact_recorded_field(self):
        if VARIABLE_FIELDS[self.family].get(self.field) != self.value_kind:
            raise ValueError("An exact supported original column and recorded type are required")
        static = self.family == "patient_demographics"
        if static != (self.record_window is None) or static != (self.temporal_policy == "static_subject_field_without_event_clock"):
            raise ValueError("Static subject fields have no episode clock; other fields require an explicit finite calendar window")
        if self.declared_unit is not None and self.value_kind != "verbatim_text":
            raise ValueError("Unit declarations cannot reinterpret original integer, date or naive-clock fields")
        return self


class DictionaryCreate(ScopeReference):
    title: Label
    purpose: Basis
    variables: Annotated[list[VariableDefinition], Field(min_length=1, max_length=MAX_VARIABLES)]
    basis_note: Basis

    @model_validator(mode="after")
    def finite_distinct_dictionary(self):
        ordered([variable.variable_key for variable in self.variables])
        return self


class BatchCapture(ScopeReference):
    variable_dictionary_id: UUID
    dictionary_content_hash: SHA
    dictionary_governance_hash: SHA
    patient_ids: Annotated[list[Positive], Field(min_length=1, max_length=256), AfterValidator(ordered)]
