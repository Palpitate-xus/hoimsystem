"""Current all-root event captures and explicit case publication.

PublicSource and private CaseRecord are separate complete responses, each
8MiB including its actual JSON wrapper. A finite declared case is never a
complete hospital investigation or proof of clinical causation.
"""

import hashlib
import hmac
import secrets
import uuid
from types import SimpleNamespace

from fastapi import HTTPException
from sqlalchemy import select

from app.ai import rca_evidence_case_contract as k
from app.ai import rca_evidence_contract as c
from app.ai import rca_evidence_current as current_keys
from app.ai import rca_evidence_grants as g
from app.ai import rca_evidence_input as i
from app.ai import rca_evidence_sources as originals
from app.ai.models import AIAuditEvent
from app.ai.rca_evidence_models import AIRcaEvidenceCase, AIRcaEvidenceOriginal
from app.ai.rca_evidence_write_guard import current_rows
from app.models import AdverseEventRca

# No original/notes are read for a previous patient association. This exact
# technical projection changes for every supported Source governance writer.
TECH_FIELDS = (
    "original_id",
    "event_id",
    "patient_id_at_capture",
    "content_hash",
    "json_bytes",
    "origin_kind",
    "status",
    "revision",
    "privacy_review",
    "faithfulness_review",
    "provenance_review",
    "created_by",
    "recorded_at",
    "reviewed_by",
    "reviewed_at",
    "revoked_by",
    "revoked_at",
    "created_audit_event_id",
    "reviewed_audit_event_id",
    "revoked_audit_event_id",
)


def wire(value):
    body = value.model_dump(mode="json") if hasattr(value, "model_dump") else value
    result = {"code": 200, "msg": "success", "data": body}
    c.canonical(result)
    return result


def _capture(db, auth):
    event = originals._legacy_snapshot(db, "legacy_event", auth.identity.event_id, auth.identity.event_id)
    # Current locking IDs/byte sizes are necessary even when the caller has an
    # older RR view. Event X serializes the exact three legacy/new writers.
    rca_columns = [column for column in AdverseEventRca.__table__.columns if column.type.python_type is str]
    rca_ids = current_keys.discover(db, AdverseEventRca, "rca_id", event.event_id)
    original_ids = current_keys.discover(db, AIRcaEvidenceOriginal, "original_id", event.event_id)
    if 1 + len(rca_ids) + len(original_ids) > c.MAX_MEMBERS:
        raise HTTPException(413, "完整同事件根件超过合并4096上限，未选赢家或截断")
    rcas = [
        current_keys.current_metadata(
            db, AdverseEventRca, "rca_id", identifier, event.event_id, (AdverseEventRca.rca_id, AdverseEventRca.event_id, *[originals._bytes_expression(db, column) for column in rca_columns])
        )
        for identifier in rca_ids
    ]
    rows = [
        current_keys.current_metadata(
            db,
            AIRcaEvidenceOriginal,
            "original_id",
            identifier,
            event.event_id,
            (*[getattr(AIRcaEvidenceOriginal, key) for key in TECH_FIELDS], originals._bytes_expression(db, AIRcaEvidenceOriginal.original_json)),
        )
        for identifier in original_ids
    ]
    if 1 + len(rcas) + len(rows) > c.MAX_MEMBERS:
        raise HTTPException(413, "完整同事件根件超过合并4096上限，未选赢家或截断")
    if sum(value or 0 for row in rcas for value in row[2:]) + sum(row[-1] or 0 for row in rows if row.patient_id_at_capture == event.patient_id) > c.MAX_WIRE_BYTES:
        raise HTTPException(413, "完整同事件已授权正文超过8MiB，未加载大正文或截断")
    rca_records = [originals._legacy_snapshot(db, "legacy_rca", row.rca_id, event.event_id) for row in rcas]
    members = []
    size = len(c.utf8(c.canonical(event))) + sum(len(c.utf8(c.canonical(row))) for row in rca_records)
    for row in rows:
        if row.patient_id_at_capture != event.patient_id:
            technical = {key: getattr(row, key) for key in TECH_FIELDS}
            for key in ("recorded_at", "reviewed_at", "revoked_at"):
                if technical[key] is not None:
                    technical[key] = i.utc_text(technical[key])
            member = k.RestrictedOriginal(
                **{key: getattr(row, key) for key in ("original_id", "event_id", "content_hash", "json_bytes", "origin_kind", "status", "revision")},
                technical_governance_hash=c.digest(technical),
                patient_association="different_from_current_not_disclosed",
                visibility="association_changed_not_disclosed",
            )
        else:
            if row.json_bytes != row[-1] or not 0 < row[-1] <= c.MAX_WIRE_BYTES:
                raise HTTPException(413, "完整原件字节锚不一致，未载入其正文")
            actual = current_rows(db.query(AIRcaEvidenceOriginal).filter_by(original_id=row.original_id), shared=True).one()
            member = k.VisibleOriginal(record=originals._record(db, actual), visibility="current_patient_purpose_authorized")
        size += len(c.utf8(c.canonical(member)))
        if size > c.MAX_WIRE_BYTES:
            raise HTTPException(413, "构造完整集合时达到8MiB预算，未返回截断集合")
        members.append(member)
    collection_hash = c.digest({"event": event, "rcas": rca_records, "originals": [k.stable_original(item) for item in members]})
    result = k.Capture(event=event, rcas=rca_records, originals=members, collection_hash=collection_hash, coverage="all_current_same_event_roots_finite_not_complete_causality")
    wire(result)
    return result


def capture_event(db, user, event_id):
    return _capture(db, g.authorize_event(db, user, event_id))


def _locator(db, identifier):
    try:
        if str(uuid.UUID(identifier)) != identifier:
            raise ValueError("Noncanonical UUID")
    except (ValueError, TypeError, AttributeError) as exc:
        raise HTTPException(422, "调查Case UUID不规范") from exc
    statement = select(AIRcaEvidenceCase.case_id, AIRcaEvidenceCase.event_id, AIRcaEvidenceCase.patient_id_at_capture).where(AIRcaEvidenceCase.case_id == identifier)
    with db.no_autoflush:
        bind = db.get_bind()
        if bind.dialect.name in {"mysql", "mariadb"}:
            engine = getattr(bind, "engine", bind)
            with engine.connect().execution_options(isolation_level="READ COMMITTED") as connection:
                row = connection.execute(statement).one_or_none()
            if row is not None:
                return tuple(row)
        row = db.execute(statement).one_or_none()
    return tuple(row) if row is not None else None


def _load(db, user, identifier):
    # Writers and reads preserve Actor -> technical locator -> Event parent.
    g.current_actor(db, user, g.SOURCE_ROLES)
    identity = _locator(db, identifier)
    if identity is None:
        raise HTTPException(404, "调查Case不存在")
    auth = g.authorize_event(db, user, identity[1])
    if identity[2] != auth.identity.patient_id:
        raise HTTPException(403, "旧Case所属患者与当前事件不同，新的关联用途不能恢复旧正文")
    metadata = current_rows(
        db.query(
            AIRcaEvidenceCase.case_id, AIRcaEvidenceCase.event_id, AIRcaEvidenceCase.patient_id_at_capture, AIRcaEvidenceCase.json_bytes, originals._bytes_expression(db, AIRcaEvidenceCase.case_json)
        ).filter_by(case_id=identifier)
    ).one_or_none()
    if metadata is None or tuple(metadata[:3]) != identity:
        raise HTTPException(409, "Case实际父件身份已变化")
    if metadata[3] != metadata[4] or not 0 < metadata[4] <= c.MAX_WIRE_BYTES:
        raise HTTPException(413, "完整Case字节预算不一致，未读取私有正文")
    row = current_rows(db.query(AIRcaEvidenceCase).filter_by(case_id=identifier)).one()
    return auth, row


def _detail(row, action, governance=None):
    detail = {"case_id": row.case_id, "event_id": row.event_id, "patient_id_at_capture": row.patient_id_at_capture, "content_hash": row.content_hash, "collection_hash": row.collection_hash}
    if action == "create":
        detail.update({"event_grant_id": row.event_grant_id, "patient_grant_id": row.patient_grant_id})
    elif action == "review":
        detail.update({key: governance[key] for key in ("privacy_review", "faithfulness_review", "provenance_review", "reviewed_by", "reviewed_at", "review_basis_note")})
        detail.update(
            {"revision": 2, "status": row.status if row.status != "revoked" else ("published" if row.privacy_review == row.faithfulness_review == row.provenance_review == "confirmed" else "rejected")}
        )
    else:
        detail.update({key: governance[key] for key in ("revision", "revoked_by", "revoked_at", "revoke_reason")})
    return detail


def _body(db, row):
    snapshot = k.CaseImmutable.model_validate(c._strict_reply(row.case_json))
    if c.canonical(snapshot) != row.case_json or len(c.utf8(row.case_json)) != row.json_bytes or c.digest(snapshot) != row.content_hash:
        raise ValueError("Whole private Case JSON/bytes/SHA differs")
    expected = {
        "case_id": snapshot.case_id,
        "event_id": snapshot.event_id,
        "patient_id_at_capture": snapshot.patient_id_at_capture,
        "event_grant_id": snapshot.event_grant.identity.grant_id,
        "patient_grant_id": snapshot.patient_grant.identity.grant_id if snapshot.patient_grant else None,
        "created_by": snapshot.created_by,
        "recorded_at": c.clock(snapshot.recorded_at).replace(tzinfo=None),
        "collection_hash": snapshot.capture.collection_hash,
        "member_count": 1 + len(snapshot.capture.rcas) + len(snapshot.capture.originals),
    }
    if any(getattr(row, key) != value for key, value in expected.items()):
        raise ValueError("Immutable Case and actual SQL scope/member/grant columns differ")
    governance = originals._governance(row)
    gov = governance.model_dump(mode="json")
    for action, identifier, actor, when in (
        ("create", row.created_audit_event_id, row.created_by, row.recorded_at),
        ("review", row.reviewed_audit_event_id, row.reviewed_by, row.reviewed_at),
        ("revoke", row.revoked_audit_event_id, row.revoked_by, row.revoked_at),
    ):
        if identifier is None:
            continue
        expected = {**_detail(row, action, gov), "recorded_at_utc6": i.utc_text(when), "audit_clock_basis": "legacy_utc_second_storage"}
        audit = current_rows(db.query(AIAuditEvent).filter_by(event_id=identifier), shared=True).one_or_none()
        if audit is None or (audit.actor_id, audit.action, audit.target, audit.detail_json, audit.create_time) != (
            actor,
            f"rca_case.{action}",
            row.case_id,
            c.canonical(expected),
            when.replace(microsecond=0),
        ):
            raise ValueError("The exact Case audit PK does not match the original content/review/scope")
    return snapshot, governance


def _record(db, row, current):
    snapshot, governance = _body(db, row)
    matches = current.collection_hash == snapshot.capture.collection_hash
    result = k.CaseRecord(
        immutable=snapshot,
        content_hash=row.content_hash,
        governance=governance,
        governance_hash=c.digest({"case_id": row.case_id, "content_hash": row.content_hash, "governance": governance}),
        current_collection_hash=current.collection_hash,
        current_collection_matches=matches,
        eligible=row.status == "published" and matches,
        evaluated_at=i.utc_text(g.utcnow()),
        public_source_endpoint="separate_typed_8MiB_response",
        causal_verification="not_provided",
    )
    wire(result)
    return result


def opaque(snapshot, namespace, value):
    digest = hmac.new(bytes.fromhex(snapshot.identity_secret), c.utf8(c.canonical([namespace, value])), hashlib.sha256).hexdigest()
    return str(uuid.UUID(digest[:32]))


def project_source(record):
    """Only released derivatives, never private legacy text or patient IDs."""
    if not record.eligible:
        raise HTTPException(409, "仅当前全集仍匹配且三项明确审核发布的Case可生成执行Source")
    body, members, items, timeline = record.immutable, [], [], []
    event = body.capture.event
    members.append(c.Member(member_id=opaque(body, "legacy_event", event.event_id), kind="legacy_event", content_hash=c.digest(event), governance_hash=None, release_status="not_released"))
    for rca in body.capture.rcas:
        members.append(c.Member(member_id=opaque(body, "legacy_rca", rca.rca_id), kind="legacy_rca", content_hash=c.digest(rca), governance_hash=None, release_status="not_released"))
    size = sum(len(c.utf8(c.canonical(member))) for member in members)
    for member in body.capture.originals:
        stable = k.stable_original(member)
        item_id = opaque(body, "original", stable["original_id"])
        if member.visibility == "association_changed_not_disclosed":
            members.append(
                c.Member(
                    member_id=item_id,
                    kind="manual_evidence" if member.origin_kind != "human_timeline" else "human_timeline",
                    content_hash=member.content_hash,
                    governance_hash=None,
                    release_status="not_released",
                )
            )
            continue
        original = member.record
        kind = "human_timeline" if original.immutable.origin_kind == "human_timeline" else "manual_evidence"
        released = original.eligible
        members.append(c.Member(member_id=item_id, kind=kind, content_hash=original.content_hash, governance_hash=original.governance_hash, release_status="released" if released else "not_released"))
        if not released:
            continue
        if len(items) >= c.MAX_ITEMS:
            raise HTTPException(413, "完整发布原件超过256项，未省略任何已发布成员")
        item = c.ReleasedItem(
            item_id=item_id,
            kind=kind,
            content_hash=original.content_hash,
            governance_hash=original.governance_hash,
            text=original.immutable.text,
            text_hash=original.immutable.text_hash,
            available_at=original.immutable.recorded_at,
            availability_basis="original_registration",
        )
        size += len(c.utf8(c.canonical(item)))
        if size > c.MAX_WIRE_BYTES:
            raise HTTPException(413, "构造全部已审核发布文本时达到8MiB，未截断")
        items.append(item)
        for entry in original.immutable.timeline:
            when = entry.occurred_time.model_dump(mode="json")
            # Pre-hashed human basis is still per-case unlinkable public data.
            when["basis_hash"] = hmac.new(bytes.fromhex(body.identity_secret), c.utf8(c.canonical(["timeline_basis", when["basis_hash"]])), hashlib.sha256).hexdigest()
            projected = c.HumanTimelineEntry(
                entry_id=opaque(body, "timeline", [original.immutable.original_id, entry.entry_id]),
                source_item_id=item_id,
                statement=entry.statement,
                occurred_time=when,
                recorded_at=original.immutable.recorded_at,
                evidence=[c.ExactQuote(item_id=item_id, **quote.model_dump(mode="json")) for quote in entry.evidence],
                assertion_status=entry.assertion_status,
            )
            if len(timeline) >= c.MAX_TIMELINE:
                raise HTTPException(413, "完整人工时间线超过512项，未省略成员")
            size += len(c.utf8(c.canonical(projected)))
            if size > c.MAX_WIRE_BYTES:
                raise HTTPException(413, "构造完整人工时间线时达到8MiB，未截断")
            timeline.append(projected)
    members.sort(key=lambda item: item.member_id)
    items.sort(key=lambda item: item.item_id)
    timeline.sort(key=lambda item: item.entry_id)
    result = c.RcaEvidenceSource(
        schema_version="rca_evidence_source_v1",
        case_id=body.case_id,
        source_id=f"rca_case:{body.case_id}:{record.content_hash[:12]}",
        content_hash=record.content_hash,
        governance_hash=record.governance_hash,
        snapshot_time=record.governance.reviewed_at,
        review_mode="current_retrospective_investigation_not_historical_prediction",
        event_state=c.RecordedEventState(
            recorded_severity=event.severity,
            recorded_status=event.status,
            report_time=event.report_time,
            patient_association="recorded_patient" if event.patient_id is not None else "not_recorded",
            encounter_assignment="not_recorded",
            causal_approval="not_provided",
        ),
        publication=c.SourcePublication(status="published", privacy_review="confirmed", faithfulness_review="confirmed", provenance_review="confirmed", reviewed_at=record.governance.reviewed_at),
        members=members,
        member_manifest_hash=c.digest(members),
        items=items,
        timeline=timeline,
        evidence_coverage="finite_declared_snapshot_not_complete_causality_or_hospital_coverage",
    )
    wire(result)
    return result


def case_detail(db, user, identifier):
    auth, row = _load(db, user, identifier)
    try:
        return _record(db, row, _capture(db, auth))
    except (ValueError, TypeError, UnicodeError) as exc:
        raise HTTPException(409, "完整Case、当前全根集合或独立审计无法核对") from exc


def public_source(db, user, identifier):
    return project_source(case_detail(db, user, identifier))


def _postflush(db, auth, row, expected, audit_id, audit_value, *, require_current):
    db.flush()
    current_keys.remember_flushed(db, row)
    db.expire(row)
    current_auth = g.authorize_event(db, auth.actor, auth.identity.event_id)
    if tuple(current_auth.identity) != tuple(auth.identity):
        raise ValueError("Actual association changed after flush")
    metadata = current_keys.current_metadata(
        db,
        AIRcaEvidenceCase,
        "case_id",
        expected["case_id"],
        expected["event_id"],
        (
            AIRcaEvidenceCase.case_id,
            AIRcaEvidenceCase.event_id,
            AIRcaEvidenceCase.patient_id_at_capture,
            AIRcaEvidenceCase.content_hash,
            AIRcaEvidenceCase.json_bytes,
            originals._bytes_expression(db, AIRcaEvidenceCase.case_json),
        ),
    )
    if tuple(metadata[2:5]) != (expected["patient_id_at_capture"], expected["content_hash"], expected["json_bytes"]) or metadata[5] != expected["json_bytes"]:
        raise ValueError("The actual postflush Case scope/hash/bytes changed before any private body read")
    actual = current_rows(db.query(AIRcaEvidenceCase).filter_by(case_id=expected["case_id"])).one()
    if originals._values(actual) != expected:
        raise ValueError("The exact persisted Case/scope/governance changed")
    g._exact_audit(db, audit_id, audit_value)
    record = _record(db, actual, _capture(db, current_auth))
    if require_current and not record.current_collection_matches:
        raise ValueError("All-root collection changed after write; nothing is accepted")
    if record.eligible:
        project_source(record)
    return record


@g._write
def create_case(db, user, values):
    request = g.typed(k.CaseCreate, values)
    auth = g.authorize_event(db, user, request.event_id)
    capture = _capture(db, auth)
    if (request.expected_event_patient_id, request.expected_collection_hash) != (auth.identity.patient_id, capture.collection_hash):
        raise HTTPException(409, "完整实际同事件根件或关联患者已变化，请重新审阅捕获摘要")
    when = g.utcnow()
    body = k.CaseImmutable(
        schema_version="rca_evidence_case_v1",
        case_id=str(uuid.uuid4()),
        event_id=request.event_id,
        patient_id_at_capture=auth.identity.patient_id,
        identity_secret=secrets.token_hex(32),
        created_by=auth.actor.user_id,
        recorded_at=i.utc_text(when),
        event_grant=auth.event_grant,
        patient_grant=auth.patient_grant,
        basis_note=request.basis_note,
        capture=capture,
        causal_verification="not_provided",
    )
    payload = c.canonical(body)
    row = AIRcaEvidenceCase(
        case_id=body.case_id,
        event_id=body.event_id,
        patient_id_at_capture=body.patient_id_at_capture,
        event_grant_id=body.event_grant.identity.grant_id,
        patient_grant_id=body.patient_grant.identity.grant_id if body.patient_grant else None,
        case_json=payload,
        json_bytes=len(c.utf8(payload)),
        member_count=1 + len(capture.rcas) + len(capture.originals),
        collection_hash=capture.collection_hash,
        content_hash=c.digest(body),
        created_by=body.created_by,
        recorded_at=when,
    )
    originals._initial(row)
    audit_id, audit_value = g._audit(db, auth.actor, "rca_case.create", row.case_id, _detail(row, "create"), when)
    row.created_audit_event_id = audit_id
    expected = originals._values(row)
    db.add(row)
    return _postflush(db, auth, row, expected, audit_id, audit_value, require_current=True)


def _cas(row, request, before):
    if (row.revision, row.content_hash, before.governance_hash) != (request.expected_revision, request.expected_content_hash, request.expected_governance_hash):
        raise HTTPException(409, "完整Case正文或三项签署治理已变化")


@g._write
def review_case(db, user, identifier, values):
    request = g.typed(i.SourceReview, values)
    auth, row = _load(db, user, identifier)
    before = _record(db, row, _capture(db, auth))
    _cas(row, request, before)
    if row.status != "draft" or not before.current_collection_matches:
        raise HTTPException(409, "只有全部当前根件仍匹配的草稿Case可明确审核")
    when = g.utcnow()
    updates = {
        "status": "published" if request.decision == "publish" else "rejected",
        "revision": 2,
        "privacy_review": request.privacy_review,
        "faithfulness_review": request.faithfulness_review,
        "provenance_review": request.provenance_review,
        "reviewed_by": auth.actor.user_id,
        "reviewed_at": when,
        "review_basis_note": request.basis_note,
    }
    draft = SimpleNamespace(**{**originals._values(row), **updates})
    detail = _detail(draft, "review", {**{key: getattr(draft, key) for key in originals.REVIEW_FIELDS}, "reviewed_at": i.utc_text(when)})
    audit_id, audit_value = g._audit(db, auth.actor, "rca_case.review", row.case_id, detail, when)
    for key, value in updates.items():
        setattr(row, key, value)
    row.reviewed_audit_event_id = audit_id
    return _postflush(db, auth, row, originals._values(row), audit_id, audit_value, require_current=True)


@g._write
def revoke_case(db, user, identifier, values):
    request = g.typed(i.Revoke, values)
    auth, row = _load(db, user, identifier)
    before = _record(db, row, _capture(db, auth))
    _cas(row, request, before)
    if row.status == "revoked":
        raise HTTPException(409, "不可重复撤销旧Case")
    when = g.utcnow()
    updates = {"status": "revoked", "revision": row.revision + 1, "revoked_by": auth.actor.user_id, "revoked_at": when, "revoke_reason": request.basis_note}
    draft = SimpleNamespace(**{**originals._values(row), **updates})
    detail = _detail(draft, "revoke", {**{key: getattr(draft, key) for key in originals.REVIEW_FIELDS}, "revoked_at": i.utc_text(when)})
    audit_id, audit_value = g._audit(db, auth.actor, "rca_case.revoke", row.case_id, detail, when)
    for key, value in updates.items():
        setattr(row, key, value)
    row.revoked_audit_event_id = audit_id
    return _postflush(db, auth, row, originals._values(row), audit_id, audit_value, require_current=False)
