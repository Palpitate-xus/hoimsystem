"""Closed explicit comparison declarations; these types grant no Source authority."""

from typing import Literal

from pydantic import Field, model_validator

from app.ai import infection_cluster_contract as c
from app.ai import infection_cluster_input as i
from app.ai import infection_cluster_statistics_contract as k


class ActorEpoch(c.StrictModel):
    user_id: c.PositiveId
    user_role: Literal["super_admin"]
    token_invalid_before: str | None


class ScenarioCreate(i.Basis):
    source_binding: k.SourceBinding
    department_ids: list[c.PositiveId] = Field(min_length=1, max_length=k.MAX_COMPARISONS)
    windows: list[c.CalendarWindow] = Field(min_length=1, max_length=k.MAX_COMPARISONS)
    pathogen_code: c.Code
    alpha_decimal: str

    @model_validator(mode="after")
    def complete_family(self):
        k.alpha_fraction(self.alpha_decimal)
        if len(set(self.department_ids)) != len(self.department_ids):
            raise ValueError("Explicit Department PKs cannot be silently deduplicated")
        windows = [(w.date_from, w.date_to) for w in self.windows]
        if len(set(windows)) != len(windows) or len(self.department_ids) * len(windows) > k.MAX_COMPARISONS:
            raise ValueError("The complete declared Cartesian family must fit256")
        c.canonical(self)
        return self


class DepartmentBinding(c.StrictModel):
    department_id: c.PositiveId
    recorded_name: str | None = Field(max_length=24)
    directory_hash: c.SHA
    department_token: c.SHA
    identity_fields: Literal["actual_department_id_and_recorded_name_only_not_full_directory_or_active_status"]

    @model_validator(mode="after")
    def literal_directory(self):
        if self.directory_hash != c.digest({"department_id": self.department_id, "name": self.recorded_name}):
            raise ValueError("The actual narrow directory anchor differs")
        return self


class ScenarioPayload(c.StrictModel):
    schema_version: Literal["infection_comparison_scenario_payload_v1"]
    scenario_id: c.UUID
    created_by: c.PositiveId
    recorded_at: str
    author_epoch: ActorEpoch
    source_binding: k.SourceBinding
    departments: list[DepartmentBinding] = Field(min_length=1, max_length=k.MAX_COMPARISONS)
    directory_hash: c.SHA
    plan: k.ScenarioPlan
    plan_hash: c.SHA
    recipe_hash: c.SHA
    basis_note: str
    limitations: list[str]

    @model_validator(mode="after")
    def exact_declaration(self):
        c.clock(self.recorded_at)
        ids = [d.department_id for d in self.departments]
        if len(set(ids)) != len(ids) or self.created_by != self.author_epoch.user_id:
            raise ValueError("The exact author and unique Department declarations differ")
        if self.plan.scenario_id != self.scenario_id or self.plan.source_binding != self.source_binding or self.plan.department_tokens != [d.department_token for d in self.departments]:
            raise ValueError("The full public family and private Department bindings differ")
        if self.directory_hash != c.digest(self.departments) or self.plan_hash != c.digest(self.plan) or self.recipe_hash != c.digest(k.RECIPE):
            raise ValueError("Whole directory/plan/installed recipe anchors differ")
        if self.limitations != k.LIMITATIONS:
            raise ValueError("The fixed method limitations cannot be dropped")
        i.Basis(basis_note=self.basis_note)
        c.canonical(self)
        return self


class ScenarioReview(i.CAS):
    decision: Literal["publish", "reject"]
    privacy_review: Literal["confirmed", "not_confirmed"]
    faithfulness_review: Literal["confirmed", "not_confirmed"]
    parameters_review: Literal["confirmed", "not_confirmed"]

    @model_validator(mode="after")
    def complete_review(self):
        if (self.decision == "publish") != (self.privacy_review == self.faithfulness_review == self.parameters_review == "confirmed"):
            raise ValueError("Publication requires all three explicit independent review declarations")
        return self


class ScenarioGovernance(c.StrictModel):
    status: Literal["draft", "published", "rejected", "revoked"]
    revision: c.PositiveId
    recorded_at: str
    created_by: c.PositiveId
    create_event_id: c.PositiveId
    reviewed_at: str | None
    reviewed_by: c.PositiveId | None
    review_event_id: c.PositiveId | None
    review_basis: str
    privacy_review: Literal["unknown", "confirmed", "not_confirmed"]
    faithfulness_review: Literal["unknown", "confirmed", "not_confirmed"]
    revoked_at: str | None
    revoked_by: c.PositiveId | None
    revoke_event_id: c.PositiveId | None
    revoke_basis: str
    parameters_review: Literal["unknown", "confirmed", "not_confirmed"]
    reviewer_epoch_hash: c.SHA | None

    @model_validator(mode="after")
    def parameter_review(self):
        c.clock(self.recorded_at)
        if (self.reviewed_by is None) != (self.parameters_review == "unknown") or (self.reviewed_by is None) != (self.reviewer_epoch_hash is None):
            raise ValueError("The exact parameter review and actual reviewer epoch are required together")
        flags = (self.privacy_review, self.faithfulness_review, self.parameters_review)
        if self.reviewed_by is None:
            if flags != ("unknown",) * 3 or self.reviewed_at is not None or self.review_event_id is not None or self.review_basis != "":
                raise ValueError("Incomplete review fields")
        elif self.reviewed_by == self.created_by or self.reviewed_at is None or self.review_event_id is None or "unknown" in flags or c.clock(self.reviewed_at) < c.clock(self.recorded_at):
            raise ValueError("An independent complete review is required")
        else:
            i.Basis(basis_note=self.review_basis)
        if self.status == "draft" and (self.revision != 1 or self.reviewed_by is not None or self.revoked_by is not None):
            raise ValueError("Invalid draft governance")
        if self.status in {"published", "rejected"} and (self.revision != 2 or self.reviewed_by is None or self.revoked_by is not None):
            raise ValueError("Invalid reviewed governance")
        if self.status == "published" and self.parameters_review != "confirmed":
            raise ValueError("Published parameters require explicit review")
        if self.status == "published" and flags != ("confirmed",) * 3 or self.status == "rejected" and "not_confirmed" not in flags:
            raise ValueError("The recorded decision and all review flags differ")
        if self.revoked_by is None:
            if self.revoked_at is not None or self.revoke_event_id is not None or self.revoke_basis != "" or self.status == "revoked":
                raise ValueError("Incomplete withdrawal")
        elif (
            self.status != "revoked"
            or self.revoked_at is None
            or self.revoke_event_id is None
            or self.revision != (3 if self.reviewed_by is not None else 2)
            or c.clock(self.revoked_at) < c.clock(self.reviewed_at or self.recorded_at)
        ):
            raise ValueError("Invalid withdrawal governance")
        else:
            i.Basis(basis_note=self.revoke_basis)
        return self


class ScenarioRecord(c.StrictModel):
    schema_version: Literal["infection_comparison_scenario_record_v1"]
    scenario_id: c.UUID
    payload: ScenarioPayload
    content_hash: c.SHA
    governance: ScenarioGovernance
    governance_hash: c.SHA
    eligible: bool = Field(strict=True)
    authority_basis: Literal["current_source_patient_purpose_directory_super_and_exact_audit_pk_not_clinical_validation"]
    publication_does_not_enable_execution: Literal[True]

    @model_validator(mode="after")
    def whole_record(self):
        if self.payload.scenario_id != self.scenario_id or self.content_hash != c.digest(self.payload) or self.governance_hash != c.digest(self.governance):
            raise ValueError("The immutable complete Scenario record differs")
        if (self.payload.created_by, self.payload.recorded_at) != (self.governance.created_by, self.governance.recorded_at):
            raise ValueError("Actual author/recording anchors differ")
        return self
