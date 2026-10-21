"""Closed split RCA tasks and literal hypotheses; never live SQL authority.

Only an authorized server Case builder may construct this binding. Public
projection, source, provider wire and each complete response are independently
bounded. A Source that fits does not imply the complete provider request fits.
"""

import hashlib
from typing import Annotated, Literal

from pydantic import Field, model_validator

from app.ai import rca_evidence_contract as c
from app.ai import rca_evidence_input as i

FEATURE_KEY = "incident_rca"
INPUT_MODE = "rca_evidence"
SOURCE_DOMAIN = "published_event_investigation_released_evidence"
MAX_RUN_TEXT_BYTES = 65535
SCOPE_NOTE = "仅本次明确事件的有限受审发布资料；候选假设未经因果或责任核实，不自动修改RCA、PDCA或临床记录。"
MISSING_DATA = (
    "旧上报和分析时间未记录时区或实际发生时刻；不据此补患者就诊或先后因果。",
    "三项人工发布审核和逐字引文核对不证明候选解释正确、调查完整或整改有效。",
    "没有返回假设也不表示没有问题；全部草稿须独立调查，不能自动确认责任。",
)


class RcaTaskSelection(c.StrictModel):
    rca_evidence_case_id: c.OpaqueId
    question: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def whole_question(self):
        if self.question is not None and len(c.utf8(self.question)) > 8000:
            raise ValueError("The optional unchanged question exceeds8000UTF8 bytes")
        return self


class RcaTaskGrant(c.StrictModel):
    grant_id: c.OpaqueId
    event_id: i.PositiveId
    patient_id_at_grant: i.PositiveId | None
    grantee_id: i.PositiveId
    permission_kind: i.PermissionKind
    content_hash: c.SHA
    governance_hash: c.SHA
    issued_at: str
    valid_until: str

    @model_validator(mode="after")
    def clocks(self):
        if c.clock(self.issued_at) >= c.clock(self.valid_until):
            raise ValueError("The real frozen purpose must have an explicit positive validity interval")
        return self


def grant_anchor(record):
    """Retain an already SQL-authorized exact purpose, without its free text."""
    record = i.GrantRecord.model_validate(record)
    if not record.current_scope:
        raise ValueError("A task cannot freeze an ineligible purpose")
    return RcaTaskGrant(
        **{name: getattr(record.identity, name) for name in ("grant_id", "event_id", "patient_id_at_grant", "grantee_id", "permission_kind", "issued_at", "valid_until")},
        content_hash=record.content_hash,
        governance_hash=record.governance_hash,
    )


class RcaTaskBinding(c.StrictModel):
    schema_version: Literal["rca_evidence_context_binding_v1"]
    case_id: c.OpaqueId
    event_id: i.PositiveId
    patient_id_at_capture: i.PositiveId | None
    requested_by: i.PositiveId
    case_content_hash: c.SHA
    case_governance_hash: c.SHA
    collection_hash: c.SHA
    source_id: str = Field(max_length=100)
    source_projection_hash: c.SHA
    source_bytes: Annotated[int, Field(strict=True, ge=1, le=c.MAX_WIRE_BYTES)]
    source_snapshot_time: str
    event_grant: RcaTaskGrant
    patient_grant: RcaTaskGrant | None

    @model_validator(mode="after")
    def actual_scope(self):
        if self.source_id != f"rca_case:{self.case_id}:{self.case_content_hash[:12]}":
            raise ValueError("The actual Case source ID must bind its whole private content")
        c.clock(self.source_snapshot_time)
        if (self.patient_grant is None) != (self.patient_id_at_capture is None):
            raise ValueError("Only actual associated patients require the independent patient-purpose anchor")
        for grant, kind in ((self.event_grant, "event_investigation"), (self.patient_grant, "associated_patient_processing")):
            if grant is not None and (grant.event_id, grant.patient_id_at_grant, grant.grantee_id, grant.permission_kind) != (self.event_id, self.patient_id_at_capture, self.requested_by, kind):
                raise ValueError("Independent purpose anchors must describe this exact actor/event/patient")
        if self.patient_grant is not None and self.patient_grant.grant_id == self.event_grant.grant_id:
            raise ValueError("One grant cannot substitute for independent event and patient purposes")
        return self


def binding_for_source(source, *, event_id, patient_id, requested_by, collection_hash, event_grant, patient_grant):
    source = c.validate_source(source)
    if (source.event_state.patient_association == "recorded_patient") != (patient_id is not None):
        raise ValueError("The released projection and actual private patient association differ")
    return RcaTaskBinding(
        schema_version="rca_evidence_context_binding_v1",
        case_id=source.case_id,
        event_id=event_id,
        patient_id_at_capture=patient_id,
        requested_by=requested_by,
        case_content_hash=source.content_hash,
        case_governance_hash=source.governance_hash,
        collection_hash=collection_hash,
        source_id=source.source_id,
        source_projection_hash=c.digest(source),
        source_bytes=len(c.utf8(c.canonical(source))),
        source_snapshot_time=source.snapshot_time,
        event_grant=event_grant,
        patient_grant=patient_grant,
    )


def evidence_for_binding(binding):
    binding = RcaTaskBinding.model_validate(binding)
    return [{"source_id": binding.source_id, "kind": "rca_evidence_case", "title": "明确事件的受审发布资料及独立用途绑定", "content": c.canonical({"rca_evidence_binding": binding})}]


def short_context(binding, snapshot_time):
    binding = RcaTaskBinding.model_validate(binding)
    when = c.clock(snapshot_time)
    if c.clock(binding.source_snapshot_time) > when:
        raise ValueError("The actual task cannot precede the frozen Case publication")
    for grant in (binding.event_grant, binding.patient_grant):
        if grant is not None and not c.clock(grant.issued_at) <= when < c.clock(grant.valid_until):
            raise ValueError("An independent real purpose was not valid at actual task creation")
    return {
        "schema_version": "rca_evidence_context_v1",
        "scope": "input",
        "source_domain": SOURCE_DOMAIN,
        "selected_sources": {"rca_evidence_case_id": binding.case_id},
        "rca_evidence_binding": binding.model_dump(mode="json"),
        "scope_note": SCOPE_NOTE,
        "missing_data": list(MISSING_DATA),
        "snapshot_time": snapshot_time,
    }


def checked_context(context):
    if not isinstance(context, dict):
        raise ValueError("A closed short RCA task context is required")
    binding = RcaTaskBinding.model_validate(context.get("rca_evidence_binding"))
    if context != short_context(binding, context.get("snapshot_time")):
        raise ValueError("The complete frozen short context is inconsistent or mixed")
    c.canonical(context)
    return binding


def expand_public_context(context, source):
    binding = checked_context(context)
    source = c.validate_source(source)
    expected = (binding.case_id, binding.source_id, binding.case_content_hash, binding.case_governance_hash, binding.source_projection_hash, binding.source_bytes, binding.source_snapshot_time)
    actual = (source.case_id, source.source_id, source.content_hash, source.governance_hash, c.digest(source), len(c.utf8(c.canonical(source))), source.snapshot_time)
    if expected != actual or (source.event_state.patient_association == "recorded_patient") != (binding.patient_id_at_capture is not None):
        raise ValueError("Every retained complete Source anchor must match this exact task")
    expanded = {**context, "rca_evidence_source": source.model_dump(mode="json")}
    c.canonical(expanded)
    return expanded


def public_payload(data):
    """Minimize an already current-authorized split task; not an auth API."""
    if not isinstance(data, dict) or set(data) != {"input", "context", "tools", "evidence"} or data["tools"] != {}:
        raise ValueError("One closed RCA task and no tools are required")
    selection = RcaTaskSelection.model_validate(data["input"])
    context = data["context"]
    if not isinstance(context, dict) or "rca_evidence_source" not in context:
        raise ValueError("The complete authorized public Source is required")
    short = {key: value for key, value in context.items() if key != "rca_evidence_source"}
    binding = checked_context(short)
    source = c.validate_source(context["rca_evidence_source"])
    if selection.rca_evidence_case_id != binding.case_id or context != expand_public_context(short, source) or data["evidence"] != evidence_for_binding(binding):
        raise ValueError("Selected Case, complete Source, evidence and binding differ")
    return {"rca_source": source.model_dump(mode="json"), "question": selection.question}


def instructions_digest(system, task):
    if type(system) is not str or type(task) is not str:
        raise ValueError("Actual complete frozen System and Task strings are required")
    return hashlib.sha256(c.utf8(system + "\n\n" + task)).hexdigest()


def text_json(value):
    raw = c.canonical(value)
    if len(c.utf8(raw)) > MAX_RUN_TEXT_BYTES:
        raise ValueError("The complete existing Run TEXT field exceeds65535UTF8 bytes")
    return raw
