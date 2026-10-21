"""Precise opaque headers and audit-PK acceptance for75 child originals.

All entry points acquire the research Gate before these helpers. They never
select a private JSON body merely to discover a parent or stop an original.
"""

from types import SimpleNamespace

from fastapi import HTTPException

from app.ai import deidentification_collection as collection
from app.ai import deidentification_sources as sources
from app.ai.deidentification_contract import MAX_BYTES, SOURCE_ROLES
from app.ai.deidentification_spans import canonical, digest, text_digest, utf8
from app.ai.models import AIAuditEvent
from app.ai.research_cohort_sources import _original_json, utc_text, utcnow
from app.ai.research_cohort_write_guard import current_actor, current_research_rows

PRIVATE_COLUMNS = frozenset({"review_json", "output_json", "release_json", "artifact_json", "manual_review_json", "review_basis_note", "revoke_reason"})


def opaque(db, model, key, identifier, *, writing=False):
    columns = [column for column in model.__table__.columns if column.name not in PRIVATE_COLUMNS]
    bodies = [column.name for column in model.__table__.columns if column.name in PRIVATE_COLUMNS]
    query = db.query(*columns, *(collection._sql_hash(db, getattr(model, name)).label(name + "_hash") for name in bodies)).filter(getattr(model, key) == sources._key(identifier))
    row = current_research_rows(query, shared=not writing).one_or_none()
    if row is None:
        raise HTTPException(404, "明确75复核或放行原件不存在")
    return dict(row._mapping)


def expected(row):
    result = {}
    for column in row.__table__.columns:
        value = getattr(row, column.name)
        result[column.name + "_hash" if column.name in PRIVATE_COLUMNS else column.name] = (None if value is None else text_digest(value)) if column.name in PRIVATE_COLUMNS else value
    return result


def governance(header):
    keys = (
        "status",
        "revision",
        "created_by",
        "created_at",
        "reviewed_by",
        "reviewed_at",
        "revoked_by",
        "revoked_at",
        "review_basis_note_hash",
        "revoke_reason_hash",
        "manual_status",
        "manual_reviewed_by",
        "manual_reviewed_at",
        "manual_review_json_hash",
    )
    return {key: utc_text(header[key]) if key.endswith("_at") else header[key] for key in keys}


def metadata(header, kind):
    key = "review_id" if kind == "review" else "release_id"
    value = {
        "schema_version": "deidentification_" + kind + "_metadata_v1",
        key: header[key],
        "content_hash": header["content_hash"],
        "governance_hash": digest(governance(header)),
        "status": header["status"],
        "revision": header["revision"],
        "recorded_at": utc_text(header["created_at"]),
        "manual_status": header["manual_status"],
        "detail_required": True,
    }
    value["case_id" if kind == "review" else "review_id"] = header["case_id" if kind == "review" else "review_id"]
    return value


def bounded(value):
    raw = canonical(value)
    if len(utf8(raw)) > MAX_BYTES:
        raise HTTPException(413, "完整75对象超8MiB，未截断或写入")
    return raw


def original_json(raw):
    return _original_json(raw, MAX_BYTES)


def initialise():
    return dict(
        status="draft",
        revision=1,
        reviewed_by=None,
        reviewed_at=None,
        review_basis_note="",
        revoked_by=None,
        revoked_at=None,
        revoke_reason="",
        manual_status="unknown",
        manual_reviewed_by=None,
        manual_reviewed_at=None,
        manual_review_json=None,
    )


def verify_manual(row):
    if row.manual_status == "unknown":
        if any(getattr(row, key) is not None for key in ("manual_reviewed_by", "manual_reviewed_at", "manual_review_json")):
            raise HTTPException(409, "未确认人工复核不得带有伪造签署")
        return None
    from app.ai.deidentification_contract import ResidualReview
    from app.ai.research_cohort_sources import _typed

    value = _original_json(row.manual_review_json, 65535)
    if type(value) is not dict or set(value) != {"request", "actor", "recorded_at"}:
        raise HTTPException(409, "完整人工复核签署须闭合")
    if (
        type(value["actor"]) is not dict
        or set(value["actor"]) != {"user_id", "user_role", "token_invalid_before"}
        or type(value["actor"]["user_id"]) is not int
        or value["actor"]["user_role"] not in SOURCE_ROLES
    ):
        raise HTTPException(409, "明确原签署身份锚缺失")
    request = _typed(ResidualReview, value["request"])
    if (request.expected_content_hash, request.expected_revision, request.decision, value["actor"]["user_id"], value["recorded_at"]) != (
        row.content_hash,
        1,
        row.manual_status,
        row.manual_reviewed_by,
        utc_text(row.manual_reviewed_at),
    ) or row.manual_reviewed_by == row.created_by:
        raise HTTPException(409, "人工复核与原件/独立当前签署不符")
    return value


def actor_signature(actor):
    return {"user_id": actor.user_id, "user_role": actor.user_role, "token_invalid_before": utc_text(actor.token_invalid_before)}


def manual_current(db, row, source):
    from app.ai.deidentification_access import authorize_subject

    value = verify_manual(row)
    if value is None or row.manual_status != "reviewed_residual_risk_remains":
        return False
    actor, _, _ = authorize_subject(db, SimpleNamespace(user_id=row.manual_reviewed_by), source["scope_id"], source["patient_id"])
    return actor_signature(actor) == value["actor"]


def manual_updates(actor, header, request):
    if (
        header["status"] != "draft"
        or header["revision"] != 1
        or header["manual_status"] != "unknown"
        or header["content_hash"] != request.expected_content_hash
        or header["created_by"] == actor.user_id
    ):
        raise HTTPException(409, "须另一位已获当前项目与患者权限的人独立复核，且仅接受本件首次明确CAS")
    now = utcnow()
    value = {"request": request.model_dump(), "actor": actor_signature(actor), "recorded_at": utc_text(now)}
    raw = canonical(value)
    if len(utf8(raw)) > 65535:
        raise HTTPException(413, "完整人工复核说明超65535 UTF8字节")
    return dict(manual_status=request.decision, manual_reviewed_by=actor.user_id, manual_reviewed_at=now, manual_review_json=raw)


def governance_updates(actor, header, request, *, revoke):
    if actor.user_role != "super_admin" and not (revoke and actor.user_id == header["created_by"]):
        raise HTTPException(403, "仅当前Super技术治理或原作者停止，不构成临床或导出许可")
    if header["revision"] != request.expected_revision or header["content_hash"] != request.expected_content_hash or header["status"] not in ({"draft", "published"} if revoke else {"draft"}):
        raise HTTPException(409, "明确技术CAS或原件状态已改变")
    if revoke:
        return dict(status="revoked", revision=header["revision"] + 1, revoked_by=actor.user_id, revoked_at=utcnow(), revoke_reason=request.basis_note)
    if request.decision == "publish" and header["manual_status"] != "reviewed_residual_risk_remains":
        raise HTTPException(409, "独立残余风险复核未知或未确认，技术发布不能代替")
    return dict(status="published" if request.decision == "publish" else "rejected", revision=2, reviewed_by=actor.user_id, reviewed_at=utcnow(), review_basis_note=request.basis_note)


def finish(db, actor, row, key, kind, action, validate):
    """Capture all columns before flush, then check actual rows and one Audit PK."""
    before = expected(row)
    identifier = before[key]
    db.flush()
    detail = canonical({key: identifier, "content_hash": before["content_hash"], "governance_hash": digest(governance(before))})
    event = AIAuditEvent(actor_id=actor.user_id, action=action, target=identifier, detail_json=detail)
    db.add(event)
    db.flush()
    actor = current_actor(db, actor, allowed_roles=SOURCE_ROLES)
    actual = opaque(db, type(row), key, identifier, writing=True)
    audit = current_research_rows(db.query(AIAuditEvent).filter_by(event_id=event.event_id), shared=True).one_or_none()
    if actual != before or audit is None or (audit.actor_id, audit.action, audit.target, audit.detail_json) != (actor.user_id, action, identifier, detail):
        raise HTTPException(409, "原件完整列/正文SHA或精确审计PK写后核验失败")
    validate(actor)
    db.commit()
    return metadata(actual, kind)


def stop(db, actor, model, key, identifier, header, updates, kind):
    """An opaque stop needs no clinical purpose or body, and never grants one."""
    target = dict(header)
    for name, value in updates.items():
        target[name + "_hash" if name in PRIVATE_COLUMNS else name] = text_digest(value) if name in PRIVATE_COLUMNS else value
    db.query(model).filter(getattr(model, key) == identifier, model.revision == header["revision"]).update(updates, synchronize_session=False)
    action = "deidentification." + kind + ".revoke"
    detail = canonical({key: identifier, "content_hash": target["content_hash"], "governance_hash": digest(governance(target))})
    event = AIAuditEvent(actor_id=actor.user_id, action=action, target=identifier, detail_json=detail)
    db.add(event)
    db.flush()
    current_actor(db, actor, allowed_roles=SOURCE_ROLES)
    audit = current_research_rows(db.query(AIAuditEvent).filter_by(event_id=event.event_id), shared=True).one_or_none()
    if opaque(db, model, key, identifier, writing=True) != target or audit is None or (audit.actor_id, audit.action, audit.target, audit.detail_json) != (actor.user_id, action, identifier, detail):
        raise HTTPException(409, "opaque停止或具体审计PK写后核验失败")
    db.commit()
    return metadata(target, kind)
