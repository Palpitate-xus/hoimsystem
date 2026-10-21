"""Only current independent purposes can build an executable released task.

Each complete Source/private Case is served as its own typed piece. A short
context/evidence packet does not grant access to either body on a later request.
"""

from dataclasses import dataclass

from fastapi import HTTPException
from pydantic import ValidationError

from app.ai import rca_evidence_case_contract as k
from app.ai import rca_evidence_cases as cases
from app.ai import rca_evidence_contract as c
from app.ai import rca_evidence_grants as grants
from app.ai import rca_evidence_input as i
from app.ai import rca_evidence_task_contract as t
from app.ai.rca_evidence_task_views import RcaFrozenCase


@dataclass(frozen=True)
class RcaPreparedContext:
    selection: t.RcaTaskSelection
    data: dict
    evidence: list
    source: c.RcaEvidenceSource
    record: k.CaseRecord
    binding: t.RcaTaskBinding
    frozen_case: RcaFrozenCase
    authorized: grants.AuthorizedEvent


def selection(values):
    try:
        return t.RcaTaskSelection.model_validate(values)
    except (ValueError, TypeError, UnicodeError) as exc:
        raise HTTPException(422, "仅接受一个明确RCA Case UUID和原样可选问题，不接受患者、就诊或额外正文") from exc


def frozen_case(snapshot, governance, content_hash, governance_hash):
    value = RcaFrozenCase(
        schema_version="rca_evidence_frozen_case_v1",
        immutable=snapshot,
        content_hash=content_hash,
        governance=governance,
        governance_hash=governance_hash,
        frozen_task_view=True,
        execution_current=False,
    )
    cases.wire(value)
    return value


def prepare_context(db, user, values):
    chosen = selection(values)
    auth, row = cases._load(db, user, chosen.rca_evidence_case_id)
    try:
        record = cases._record(db, row, cases._capture(db, auth))
        source = cases.project_source(record)
        bound = t.binding_for_source(
            source,
            event_id=auth.identity.event_id,
            patient_id=auth.identity.patient_id,
            requested_by=auth.actor.user_id,
            collection_hash=record.immutable.capture.collection_hash,
            event_grant=t.grant_anchor(auth.event_grant),
            patient_grant=t.grant_anchor(auth.patient_grant) if auth.patient_grant else None,
        )
        short = t.short_context(bound, i.utc_text(grants.utcnow()))
        evidence = t.evidence_for_binding(bound)
        retained = frozen_case(record.immutable, record.governance, record.content_hash, record.governance_hash)
        cases.wire(source)
        t.text_json(short)
        t.text_json(evidence)
        return RcaPreparedContext(chosen, short, evidence, source, record, bound, retained, auth)
    except (ValueError, TypeError, UnicodeError, ValidationError) as exc:
        raise HTTPException(409, "完整当前RCA来源、用途、冻结正文或完整分件容量无法核对，未截断") from exc


def authorize_binding(db, user, value, *, frozen_audit=False):
    """Source/current purpose first, before callers may load any Task TEXT.

    Explicit audit still requires the auditor's current independent event and
    patient purposes. It may inspect the original frozen publication after live
    revocation; this never authorizes re-execution or restores current status.
    """
    binding = t.RcaTaskBinding.model_validate(value)
    auth, row = cases._load(db, user, binding.case_id)
    if not frozen_audit and auth.actor.user_id != binding.requested_by:
        raise HTTPException(403, "普通RCA任务读取须为原请求人；其它Super审计须显式冻结入口")
    if (row.event_id, row.patient_id_at_capture, row.content_hash) != (binding.event_id, binding.patient_id_at_capture, binding.case_content_hash):
        raise HTTPException(409, "任务原事件、患者归属或完整Case身份已改变")
    if frozen_audit:
        snapshot, _current_governance = cases._body(db, row)
        return auth, snapshot
    for anchor in (binding.event_grant, binding.patient_grant):
        if anchor is None:
            continue
        actual = grants.grant_detail(db, auth.actor, anchor.grant_id)
        if not actual.current_scope or t.grant_anchor(actual) != anchor:
            raise HTTPException(403, "任务原独立用途许可已撤销、过期或变化；另一许可不能恢复原任务")
    record = cases._record(db, row, cases._capture(db, auth))
    source = cases.project_source(record)
    expected = t.binding_for_source(
        source,
        event_id=auth.identity.event_id,
        patient_id=auth.identity.patient_id,
        requested_by=binding.requested_by,
        collection_hash=record.immutable.capture.collection_hash,
        event_grant=binding.event_grant,
        patient_grant=binding.patient_grant,
    )
    if expected != binding:
        raise HTTPException(409, "完整当前RCA发布、集合或投影与原任务不一致")
    return auth, record.immutable
