"""Bound76 SQL Batch originals and exact audit receipts; no authorization here."""

from fastapi import HTTPException
from pydantic import TypeAdapter

from app.ai.models import AIAuditEvent
from app.ai.research_cohort_contract import SHA, Positive, canonical_json
from app.ai.research_cohort_sources import _governance, _original_json, _verify_governance, hash_content, utc_text
from app.ai.research_cohort_write_guard import current_research_rows
from app.ai.research_variables_dictionary import _audit_clock
from app.ai.research_variables_snapshot import MAX_BYTES, project_variable_snapshot, verify_variable_snapshot


def batch_identity(row):
    return {
        "schema_version": "research_variable_batch_identity_v1",
        "batch_id": row.batch_id,
        "scope_id": row.scope_id,
        "dictionary_id": row.dictionary_id,
        "created_by": row.created_by,
        "created_at": utc_text(row.created_at),
        "created_event_id": row.created_event_id,
    }


def batch_governance_hash(row):
    return hash_content({"batch_id": row.batch_id, "content_hash": row.content_hash, "governance": _governance(row), "last_event_id": row.last_event_id})


def batch_proof(row):
    """Reconstruct original and projection before trusting stored SQL hashes."""
    try:
        snapshot = verify_variable_snapshot(_original_json(row.snapshot_json, MAX_BYTES), identity_key=row.identity_key)
        identity = batch_identity(row)
        if any(snapshot[name] != identity[name] for name in ("batch_id", "scope_id", "dictionary_id", "created_by", "created_at", "created_event_id")):
            raise ValueError("Actual SQL Batch identity differs from its whole original")
        if hash_content(snapshot) != row.content_hash:
            raise ValueError("Whole immutable Batch SHA differs")
        request = snapshot["request"]
        expected = {
            "scope_content_hash": request["scope_content_hash"],
            "scope_governance_hash": request["scope_governance_hash"],
            "dictionary_content_hash": request["dictionary_content_hash"],
            "dictionary_governance_hash": request["dictionary_governance_hash"],
            "collection_digest": snapshot["collection_digest"],
            "member_manifest_hash": snapshot["member_manifest_hash"],
        }
        for name, value in expected.items():
            TypeAdapter(SHA).validate_python(getattr(row, name), strict=True)
            if getattr(row, name) != value:
                raise ValueError("Actual stored parent/member anchor differs")
        TypeAdapter(Positive).validate_python(row.last_event_id, strict=True)
        governance = _governance(row)
        manual = dict(authorization_review_status="unknown", authorization_reviewed_by=None, authorization_reviewed_at=None, authorization_review_basis="")
        _verify_governance(identity, governance, manual)
        governance_hash = batch_governance_hash(row)
        projection = _original_json(row.projection_json, MAX_BYTES)
        if projection != project_variable_snapshot(snapshot, governance_hash, identity_key=row.identity_key) or hash_content(projection) != row.projection_hash:
            raise ValueError("Whole original literal model projection differs")
        return {
            "schema_version": "research_variable_batch_proof_v1",
            "identity": identity,
            "snapshot": snapshot,
            "content_hash": row.content_hash,
            "governance": governance,
            "governance_hash": governance_hash,
            "source": projection,
            "projection_hash": row.projection_hash,
            "last_event_id": row.last_event_id,
        }
    except (HTTPException, ValueError, TypeError, KeyError, AttributeError, UnicodeError) as exc:
        raise HTTPException(409, "变量批次原身份、完整快照、全部绑定、治理或模型投影SHA已损坏") from exc


def batch_creation_detail(proof):
    return {"source_kind": "research_variable_batch", "identity": proof["identity"], "content_hash": proof["content_hash"]}


def batch_transition_detail(proof):
    return {
        "source_kind": "research_variable_batch",
        "content_hash": proof["content_hash"],
        "governance_hash": proof["governance_hash"],
        "projection_hash": proof["projection_hash"],
    }


def verify_batch_audits(db, row, proof):
    """Only the actual two immutable audit PKs, never a broad task/audit scan."""
    created = current_research_rows(db.query(AIAuditEvent).filter_by(event_id=row.created_event_id), shared=True).one_or_none()
    if created is None or (created.actor_id, created.action, created.target, created.detail_json, utc_text(created.create_time)) != (
        row.created_by,
        "research.variable_batch.create",
        row.batch_id,
        canonical_json(batch_creation_detail(proof)),
        utc_text(_audit_clock(row.created_at)),
    ):
        raise HTTPException(409, "变量批次具体创建审计主键、原件或时钟不一致")
    last = current_research_rows(db.query(AIAuditEvent).filter_by(event_id=row.last_event_id), shared=True).one_or_none()
    if last is None or last.target != row.batch_id:
        raise HTTPException(409, "变量批次具体最近审计主键不存在")
    if row.last_event_id == row.created_event_id:
        if row.status != "draft" or row.revision != 1:
            raise HTTPException(409, "变量批次技术治理缺少实际过渡回执")
        return
    action, actor, clock = ("revoke", row.revoked_by, row.revoked_at) if row.status == "revoked" else ("review", row.reviewed_by, row.reviewed_at)
    if (last.actor_id, last.action, last.detail_json, utc_text(last.create_time)) != (
        actor,
        "research.variable_batch." + action,
        canonical_json(batch_transition_detail(proof)),
        utc_text(_audit_clock(clock)),
    ):
        raise HTTPException(409, "变量批次具体治理回执或原签署时钟不一致")
