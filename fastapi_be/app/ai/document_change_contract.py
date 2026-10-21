"""Closed human-governed comparison sources; no model extraction or rule mutation."""

from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator

from app.ai import document_evidence_contract as e

MAX_CASE_BYTES = 8 * 1024 * 1024
MAX_LINK_BYTES = 1024 * 1024
MAX_MEMBERS = 8192
MAX_DECLARED_TARGETS = 256
MAX_BASIS_BYTES = 16000
SCHEMA_VERSION = "document_change_source_v1"
DECLARATION = "declared_relationship_not_authority_or_clinical_validation"

TargetKind = Literal["risk_rule_profile", "clinical_pathway"]
Review = Literal["unknown", "confirmed", "not_confirmed"]


class RiskProfileReference(e.StrictModel):
    kind: Literal["risk_rule_profile"]
    target_id: e.UUID


class PathwayReference(e.StrictModel):
    kind: Literal["clinical_pathway"]
    target_id: e.Positive


TargetReference = Annotated[RiskProfileReference | PathwayReference, Field(discriminator="kind")]


def target_key(value):
    return value.kind, str(value.target_id)


def byte_bound(value, maximum=MAX_CASE_BYTES):
    if len(e.utf8(e.canonical_json(value))) > maximum:
        raise ValueError("The complete UTF8 object exceeds its byte budget; nothing is truncated")


class ExactSpan(e.StrictModel):
    start: int = Field(strict=True, ge=0, le=e.MAX_ORIGINAL_BYTES)
    end: int = Field(strict=True, ge=1, le=e.MAX_ORIGINAL_BYTES)
    quote: str = Field(min_length=1, max_length=e.MAX_KNOWLEDGE_BYTES)

    @model_validator(mode="after")
    def exact_extent(self):
        if self.start >= self.end or len(self.quote) != self.end - self.start or len(e.utf8(self.quote)) > e.MAX_KNOWLEDGE_BYTES:
            raise ValueError("An exact nonempty Unicode codepoint [start,end) span is required")
        return self


class Relationship(e.StrictModel):
    kind: Literal["declared_successor", "comparison_only"]
    same_guideline_family: Review
    basis_note: str = Field(min_length=10, max_length=4000)

    @model_validator(mode="after")
    def explicit(self):
        e.meaningful(self.basis_note)
        if self.kind == "declared_successor" and self.same_guideline_family != "confirmed":
            raise ValueError("An unconfirmed family cannot be declared a successor")
        return self


class LinkCreate(e.StrictModel):
    original: e.OriginalReference
    span: ExactSpan
    target: TargetReference
    expected_target_hash: e.SHA256
    dependency_kind: Literal["declared_support", "declared_implementation", "requires_human_review"]
    basis_note: str = Field(min_length=10, max_length=4000)
    provenance: Literal["unverified_human_submission"]

    @model_validator(mode="after")
    def bounded(self):
        e.meaningful(self.basis_note)
        byte_bound(self, MAX_LINK_BYTES)
        return self


class ScopeCaptureRequest(e.StrictModel):
    baseline_original: e.OriginalReference
    candidate_original: e.OriginalReference
    relationship: Relationship
    declared_targets: list[TargetReference] = Field(max_length=MAX_DECLARED_TARGETS)
    rule_link_coverage: Literal["complete_within_declared_scope", "incomplete", "unknown"]
    declaration_basis_note: str = Field(min_length=10, max_length=4000)

    @model_validator(mode="after")
    def explicit_finite_scope(self):
        if self.baseline_original.original_id == self.candidate_original.original_id:
            raise ValueError("Two different original identities must be explicitly selected")
        keys = [target_key(value) for value in self.declared_targets]
        if keys != sorted(set(keys)):
            raise ValueError("The finite declared target set must be unique and canonically ordered")
        e.meaningful(self.declaration_basis_note)
        byte_bound(self)
        return self


class ScopeCreate(ScopeCaptureRequest):
    expected_inventory_hash: e.SHA256


class ReviewRequest(e.StrictModel):
    expected_revision: e.Revision
    expected_content_hash: e.SHA256
    expected_governance_hash: e.SHA256
    decision: Literal["approve", "reject"]
    privacy_review: Literal["confirmed", "not_confirmed"]
    faithfulness_review: Literal["confirmed", "not_confirmed"]
    dependency_review: Literal["confirmed", "not_confirmed"]
    basis_note: str = Field(min_length=10, max_length=4000)

    @model_validator(mode="after")
    def actual_decision(self):
        e.meaningful(self.basis_note)
        confirmed = (self.privacy_review, self.faithfulness_review, self.dependency_review) == ("confirmed",) * 3
        if (self.decision == "approve") != confirmed:
            raise ValueError("Approval requires three explicit review confirmations")
        return self


class Governance(e.StrictModel):
    status: Literal["draft", "published", "rejected", "revoked"]
    revision: e.Revision
    privacy_review: Review
    faithfulness_review: Review
    dependency_review: Review
    reviewed_by: e.Positive | None
    reviewed_at: e.UtcText | None
    review_basis_note: str = Field(max_length=4000)
    revoked_by: e.Positive | None
    revoked_at: e.UtcText | None
    revoke_reason: str = Field(max_length=1000)

    @model_validator(mode="after")
    def exact_signature(self):
        reviewed = self.reviewed_by is not None
        revoked = self.revoked_by is not None
        decisions = (self.privacy_review, self.faithfulness_review, self.dependency_review)
        if reviewed != (self.reviewed_at is not None) or reviewed != bool(self.review_basis_note):
            raise ValueError("The three review decisions share one actual identity, clock and basis")
        if reviewed:
            e.clock(self.reviewed_at)
            e.meaningful(self.review_basis_note)
            if "unknown" in decisions:
                raise ValueError("An actual review must record all three explicit decisions")
        elif decisions != ("unknown",) * 3:
            raise ValueError("Unreviewed decisions remain unknown")
        if revoked != (self.revoked_at is not None) or revoked != bool(self.revoke_reason):
            raise ValueError("Revocation requires the complete actual signature")
        if revoked:
            e.clock(self.revoked_at)
            e.meaningful(self.revoke_reason, maximum=4000)
        if self.status == "draft" and (self.revision != 1 or reviewed or revoked):
            raise ValueError("A draft is unsigned revision one")
        if self.status in {"published", "rejected"} and (self.revision != 2 or not reviewed or revoked):
            raise ValueError("The first review creates revision two")
        if self.status == "published" and decisions != ("confirmed",) * 3:
            raise ValueError("Publication requires three explicit confirmations")
        if self.status == "rejected" and decisions == ("confirmed",) * 3:
            raise ValueError("A rejection must retain at least one unconfirmed decision")
        if self.status == "revoked" and (not revoked or self.revision != (3 if reviewed else 2)):
            raise ValueError("Revocation preserves the previous actual review")
        if self.reviewed_at is not None and self.revoked_at is not None and self.revoked_at < self.reviewed_at:
            raise ValueError("Revocation cannot predate review")
        return self


# Raw database column names are a closed private whitelist. Legacy naive clock
# strings remain original strings, without declaring an unknown timezone UTC.
RISK_COLUMNS = (
    "rule_profile_id",
    "schema_version",
    "rule_id",
    "recipe_digest",
    "policy_digest",
    "identity_hash",
    "published_key",
    "payload_json",
    "content_hash",
    "created_by",
    "created_at",
    "status",
    "revision",
    "published_at",
    "published_by",
    "review_note",
    "review_evidence_reference",
    "implementation_terms_confirmed",
    "revoked_at",
    "revoked_by",
    "revoke_reason",
)
PATHWAY_COLUMNS = ("pathway_id", "name", "disease_code", "disease_name", "steps", "expected_days", "status", "source_revision", "create_time")
RISK_INTEGER_COLUMNS = {"created_by", "revision", "published_by", "implementation_terms_confirmed", "revoked_by"}
PATHWAY_INTEGER_COLUMNS = {"pathway_id", "expected_days", "status", "source_revision"}


class TargetSnapshot(e.StrictModel):
    schema_version: Literal["document_change_target_snapshot_v1"]
    target: TargetReference
    exists: bool = Field(strict=True)
    columns: dict[str, str | int | None] | None
    state: Literal["current", "inactive", "stale", "unknown", "missing"]
    state_reasons: list[Literal["target_missing", "target_inactive", "target_state_unknown", "profile_implementation_changed"]] = Field(max_length=4)

    @model_validator(mode="after")
    def complete_private_columns(self):
        if not self.exists:
            if self.columns is not None or self.state != "missing" or self.state_reasons != ["target_missing"]:
                raise ValueError("A missing target has no invented column facts")
            return self
        names = RISK_COLUMNS if self.target.kind == "risk_rule_profile" else PATHWAY_COLUMNS
        integers = RISK_INTEGER_COLUMNS if self.target.kind == "risk_rule_profile" else PATHWAY_INTEGER_COLUMNS
        if self.columns is None or set(self.columns) != set(names) or self.state == "missing":
            raise ValueError("Every exact whitelisted private target column is required")
        for name, value in self.columns.items():
            if value is not None and (type(value) is not int if name in integers else type(value) is not str):
                raise ValueError("Private target values preserve their actual stored types")
        identifier = "rule_profile_id" if self.target.kind == "risk_rule_profile" else "pathway_id"
        if self.columns[identifier] != self.target.target_id:
            raise ValueError("The target reference and actual identity differ")
        if len(set(self.state_reasons)) != len(self.state_reasons) or (self.state == "current") != (not self.state_reasons):
            raise ValueError("The target state and closed reasons differ")
        byte_bound(self, MAX_LINK_BYTES)
        return self


class LinkImmutable(e.StrictModel):
    schema_version: Literal["document_rule_link_immutable_v1"]
    link_id: e.UUID
    created_by: e.Positive
    recorded_at: e.UtcText
    proposal: LinkCreate
    target_snapshot: TargetSnapshot

    @model_validator(mode="after")
    def exact_frozen_target(self):
        e.clock(self.recorded_at)
        if self.target_snapshot.target != self.proposal.target or not self.target_snapshot.exists or e.digest(self.target_snapshot) != self.proposal.expected_target_hash:
            raise ValueError("The complete actual target must equal the explicitly reviewed target digest")
        byte_bound(self, MAX_LINK_BYTES)
        return self


class AuditReferences(e.StrictModel):
    created: e.Positive
    reviewed: e.Positive | None
    revoked: e.Positive | None

    @model_validator(mode="after")
    def distinct(self):
        values = [value for value in (self.created, self.reviewed, self.revoked) if value is not None]
        if len(set(values)) != len(values):
            raise ValueError("Each actual mutation has its own exact audit primary key")
        return self


class LinkRecord(e.StrictModel):
    schema_version: Literal["document_rule_link_record_v1"]
    snapshot: LinkImmutable
    content_hash: e.SHA256
    governance: Governance
    governance_hash: e.SHA256
    original_current: bool = Field(strict=True)
    target_current: bool = Field(strict=True)
    audit_event_ids: AuditReferences
    eligible: bool = Field(strict=True)
    ineligibility_reasons: list[Literal["link_not_published", "original_changed", "target_changed"]] = Field(max_length=3)
    declaration_status: Literal["declared_relationship_not_authority_or_clinical_validation"]
    clinical_validation: Literal["not_provided"]

    @model_validator(mode="after")
    def exact_identity(self):
        if (self.audit_event_ids.reviewed is not None) != (self.governance.reviewed_by is not None) or (self.audit_event_ids.revoked is not None) != (self.governance.revoked_by is not None):
            raise ValueError("Exact audit references must match the actual review/revocation signatures")
        if e.digest(self.snapshot) != self.content_hash or e.digest(self.governance) != self.governance_hash:
            raise ValueError("The complete immutable link and governance must match their hashes")
        expected = (
            ([] if self.governance.status == "published" else ["link_not_published"]) + ([] if self.original_current else ["original_changed"]) + ([] if self.target_current else ["target_changed"])
        )
        if self.ineligibility_reasons != expected or self.eligible != (not expected):
            raise ValueError("Link eligibility is structural currentness, never clinical validation")
        check_clocks(self.snapshot.recorded_at, self.governance)
        return self


class PublicationDependency(e.StrictModel):
    candidate: e.CandidateRecord
    publication: e.PublicationRecord

    @model_validator(mode="after")
    def actual_parent(self):
        if self.publication.snapshot.candidate.candidate_id != self.candidate.snapshot.candidate_id:
            raise ValueError("The actual candidate and publication must have the same parent")
        return self


class Inventory(e.StrictModel):
    schema_version: Literal["document_change_inventory_v1"]
    baseline_original: e.OriginalRecord
    candidate_original: e.OriginalRecord
    targets: list[TargetSnapshot] = Field(max_length=MAX_MEMBERS)
    rule_links: list[LinkRecord] = Field(max_length=MAX_MEMBERS)
    publications: list[PublicationDependency] = Field(max_length=MAX_MEMBERS)
    member_count: int = Field(strict=True, ge=2, le=MAX_MEMBERS)

    @model_validator(mode="after")
    def one_shared_budget(self):
        originals = (self.baseline_original.snapshot.original_id, self.candidate_original.snapshot.original_id)
        if originals[0] == originals[1]:
            raise ValueError("Two original identities must remain distinct")
        keys = [("original", value) for value in originals]
        keys.extend(("target:" + value.target.kind, str(value.target.target_id)) for value in self.targets)
        keys.extend(("link", value.snapshot.link_id) for value in self.rule_links)
        for value in self.publications:
            keys.extend(
                (("candidate", value.candidate.snapshot.candidate_id), ("publication", value.publication.snapshot.publication_id), ("knowledge", value.publication.snapshot.knowledge_document_id))
            )
        if len(keys) != len(set(keys)) or self.member_count != len(keys):
            raise ValueError("All originals, targets, links, candidates, publications and knowledge share one exact member cap")
        if [target_key(value.target) for value in self.targets] != sorted(target_key(value.target) for value in self.targets):
            raise ValueError("Current targets must be canonically ordered")
        if [value.snapshot.link_id for value in self.rule_links] != sorted(value.snapshot.link_id for value in self.rule_links):
            raise ValueError("The complete link collection must be canonically ordered")
        if [value.publication.snapshot.publication_id for value in self.publications] != sorted(value.publication.snapshot.publication_id for value in self.publications):
            raise ValueError("The complete publication collection must be canonically ordered")
        targets = {target_key(value.target) for value in self.targets}
        if any(value.snapshot.proposal.original.original_id not in originals or target_key(value.snapshot.proposal.target) not in targets for value in self.rule_links):
            raise ValueError("Every link retains its real original and current target, including outside-scope targets")
        if any(value.publication.snapshot.original.original_id not in originals for value in self.publications):
            raise ValueError("Every publication must belong to one of the two originals")
        byte_bound(self)
        return self


class ScopeImmutable(e.StrictModel):
    schema_version: Literal["document_change_scope_immutable_v1"]
    scope_id: e.UUID
    created_by: e.Positive
    recorded_at: e.UtcText
    request: ScopeCaptureRequest
    inventory_hash: e.SHA256
    inventory: Inventory

    @model_validator(mode="after")
    def exact_capture(self):
        e.clock(self.recorded_at)
        if e.digest(self.inventory) != self.inventory_hash:
            raise ValueError("The complete captured inventory must match its own digest")
        for reference, record in ((self.request.baseline_original, self.inventory.baseline_original), (self.request.candidate_original, self.inventory.candidate_original)):
            if reference != e.OriginalReference(original_id=record.snapshot.original_id, content_hash=record.content_hash, governance_hash=record.governance_hash):
                raise ValueError("The original sides and exact complete capture differ")
        if not {target_key(value) for value in self.request.declared_targets} <= {target_key(value.target) for value in self.inventory.targets if value.exists}:
            raise ValueError("Every explicitly declared target must exist in the captured finite target inventory")
        byte_bound(self)
        return self


class ScopeRecord(e.StrictModel):
    schema_version: Literal["document_change_scope_record_v1"]
    snapshot: ScopeImmutable
    content_hash: e.SHA256
    governance: Governance
    governance_hash: e.SHA256
    inventory_current: bool = Field(strict=True)
    audit_event_ids: AuditReferences
    eligible: bool = Field(strict=True)
    ineligibility_reasons: list[Literal["scope_not_published", "inventory_changed"]] = Field(max_length=2)
    hospital_wide_rule_inventory: Literal["not_provided"]
    automatic_supersession: Literal[False]
    clinical_validation: Literal["not_provided"]

    @field_validator("automatic_supersession", mode="before")
    @classmethod
    def actual_false(cls, value):
        if value is not False:
            raise ValueError("Automatic supersession is the actual boolean false")
        return value

    @model_validator(mode="after")
    def exact_identity(self):
        if (self.audit_event_ids.reviewed is not None) != (self.governance.reviewed_by is not None) or (self.audit_event_ids.revoked is not None) != (self.governance.revoked_by is not None):
            raise ValueError("Exact audit references must match the actual review/revocation signatures")
        if e.digest(self.snapshot) != self.content_hash or e.digest(self.governance) != self.governance_hash:
            raise ValueError("Complete scope and governance hashes must match")
        expected = ([] if self.governance.status == "published" else ["scope_not_published"]) + ([] if self.inventory_current else ["inventory_changed"])
        if self.ineligibility_reasons != expected or self.eligible != (not expected):
            raise ValueError("Scope currentness is not a clinical impact or authority declaration")
        check_clocks(self.snapshot.recorded_at, self.governance)
        byte_bound(self)
        return self


def check_clocks(recorded_at, governance):
    e.clock(recorded_at)
    for value in (governance.reviewed_at, governance.revoked_at):
        if value is not None and value < recorded_at:
            raise ValueError("Review/revocation cannot predate actual registration")


class DocumentChangeOriginal(e.StrictModel):
    schema_version: Literal["document_change_original_source_v1"]
    original: e.OriginalReference
    raw_bytes_hash: e.SHA256
    raw_bytes_length: int = Field(strict=True, ge=1, le=e.MAX_ORIGINAL_BYTES)
    codepoint_length: int = Field(strict=True, ge=1, le=e.MAX_ORIGINAL_BYTES)
    text: str = Field(min_length=1, max_length=e.MAX_ORIGINAL_BYTES)

    @model_validator(mode="after")
    def exact_bytes(self):
        if self.raw_bytes_length != len(e.utf8(self.text)) or self.codepoint_length != len(self.text) or self.raw_bytes_hash != e.bytes_hash(self.text):
            raise ValueError("The complete original UTF8 bytes and codepoint counts must match")
        byte_bound(self)
        return self


class ScopeReference(e.StrictModel):
    scope_id: e.UUID
    content_hash: e.SHA256
    governance_hash: e.SHA256


class PublicTarget(e.StrictModel):
    target: TargetReference
    snapshot_hash: e.SHA256
    state: Literal["current", "inactive", "stale", "unknown", "missing"]
    within_declared_scope: bool = Field(strict=True)


class PublicRuleLink(e.StrictModel):
    link_id: e.UUID
    content_hash: e.SHA256
    governance_hash: e.SHA256
    original: e.OriginalReference
    start: int = Field(strict=True, ge=0, le=e.MAX_ORIGINAL_BYTES)
    end: int = Field(strict=True, ge=1, le=e.MAX_ORIGINAL_BYTES)
    quote_bytes_hash: e.SHA256
    target: TargetReference
    target_snapshot_hash: e.SHA256
    dependency_kind: Literal["declared_support", "declared_implementation", "requires_human_review"]
    current: bool = Field(strict=True)
    within_declared_scope: bool = Field(strict=True)


class PublicPublication(e.StrictModel):
    publication_id: e.UUID
    content_hash: e.SHA256
    governance_hash: e.SHA256
    original: e.OriginalReference
    candidate: e.CandidateReference
    knowledge_document_id: e.UUID
    knowledge_content_hash: e.SHA256
    bound_source_current: bool = Field(strict=True)
    ineligibility_reasons: list[e.Ineligibility] = Field(max_length=6)


class DocumentChangeSource(e.StrictModel):
    schema_version: Literal["document_change_source_v1"]
    scope: ScopeReference
    baseline: DocumentChangeOriginal
    candidate: DocumentChangeOriginal
    relationship_kind: Literal["declared_successor", "comparison_only"]
    same_guideline_family: Review
    rule_link_coverage: Literal["complete_within_declared_scope", "incomplete", "unknown"]
    targets: list[PublicTarget] = Field(max_length=MAX_MEMBERS)
    rule_links: list[PublicRuleLink] = Field(max_length=MAX_MEMBERS)
    publications: list[PublicPublication] = Field(max_length=MAX_MEMBERS)
    member_count: int = Field(strict=True, ge=2, le=MAX_MEMBERS)
    inventory_hash: e.SHA256
    hospital_wide_rule_inventory: Literal["not_provided"]
    clinical_validation: Literal["not_provided"]

    @model_validator(mode="after")
    def complete_originals_and_refs(self):
        baseline = self.baseline
        candidate = self.candidate
        if baseline.original.original_id == candidate.original.original_id:
            raise ValueError("The exact two public original identities must remain distinct")
        originals = {value.original.original_id: value.original for value in (baseline, candidate)}
        targets = [target_key(value.target) for value in self.targets]
        links = [value.link_id for value in self.rule_links]
        publications = [value.publication_id for value in self.publications]
        if targets != sorted(set(targets)) or links != sorted(set(links)) or publications != sorted(set(publications)):
            raise ValueError("The complete public dependency sets are canonical and unique")
        if self.member_count != 2 + len(targets) + len(links) + 3 * len(publications):
            raise ValueError("The public and private dependency member counts must agree")
        if any(
            value.original.original_id not in originals or value.original != originals[value.original.original_id] or target_key(value.target) not in targets or value.start >= value.end
            for value in self.rule_links
        ):
            raise ValueError("Public links may only reference the two exact originals and retained targets")
        if any(value.original.original_id not in originals or value.original != originals[value.original.original_id] for value in self.publications):
            raise ValueError("Publications may only reference the two exact originals")
        byte_bound(self)
        return self
