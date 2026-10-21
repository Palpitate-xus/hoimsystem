"""Immutable75 Source lifecycle with purpose checks before clinical TEXT.

A current Super without project/patient permission receives at most opaque
technical metadata, never a frozen-body authorization bypass. Stopping an
original uses SQL byte hashes and does not require reading its clinical text.
"""

import datetime as dt
import uuid
from types import SimpleNamespace

from fastapi import HTTPException

from app.ai import deidentification_collection as collection
from app.ai.deidentification_access import authorize_subject
from app.ai.deidentification_contract import LIMITATIONS, MAX_BYTES, SOURCE_ROLES, CaseCreate, GovernanceReview, GovernanceRevoke, PatientScopeRequest
from app.ai.deidentification_models import AIDeidentificationCase
from app.ai.deidentification_spans import canonical, digest, document, text_digest, utf8
from app.ai.research_cohort_sources import _original_json, _typed, utc_text, utcnow
from app.ai.research_cohort_write_guard import current_actor, current_research_rows, lock_research_write


def actor_now(db, user):
    return lock_research_write(db, user, allowed_roles=SOURCE_ROLES)


def _key(identifier):
    try:
        if type(identifier) is not str or str(uuid.UUID(identifier)) != identifier:
            raise ValueError("Canonical Source key required")
        return identifier
    except (ValueError, TypeError) as exc:
        raise HTTPException(422, "明确来源须规范UUID") from exc


def _opaque(db, identifier, *, writing=False):
    columns = [c for c in AIDeidentificationCase.__table__.columns if c.name not in {"snapshot_json", "review_basis_note", "revoke_reason"}]
    query = db.query(*columns, *(collection._sql_hash(db, getattr(AIDeidentificationCase, n)).label(n + "_hash") for n in ("snapshot_json", "review_basis_note", "revoke_reason"))).filter(
        AIDeidentificationCase.case_id == identifier
    )
    result = current_research_rows(query, shared=not writing).one_or_none()
    if result is None:
        raise HTTPException(404, "明确75来源不存在")
    return dict(result._mapping)


def _governance(header):
    return {
        k: utc_text(header[k]) if k.endswith("_at") else header[k]
        for k in ("status", "revision", "created_by", "created_at", "reviewed_by", "reviewed_at", "revoked_by", "revoked_at", "review_basis_note_hash", "revoke_reason_hash")
    }


def governance_hash(header):
    return digest(_governance(header))


def metadata(header):
    return {
        "schema_version": "deidentification_case_metadata_v1",
        "case_id": header["case_id"],
        "source_id": "deidentification_case:" + header["case_id"] + ":" + header["content_hash"][:12],
        "scope_id": header["scope_id"],
        "recorded_at": utc_text(header["created_at"]),
        "content_hash": header["content_hash"],
        "collection_digest": header["collection_digest"],
        "parent_binding_hash": header["parent_binding_hash"],
        "manifest_hash": header["manifest_hash"],
        "status": header["status"],
        "revision": header["revision"],
        "governance_hash": governance_hash(header),
        "detail_required": True,
    }


def verify_snapshot(snapshot):
    from pydantic import TypeAdapter

    from app.ai.research_cohort_contract import UTC, UUID, Basis, Positive

    try:
        keys = {"schema_version", "case_id", "scope_id", "patient_id", "created_by", "recorded_at", "capture", "basis_note", "limitations"}
        if type(snapshot) is not dict or set(snapshot) != keys or snapshot["schema_version"] != "deidentification_case_v1" or snapshot["limitations"] != list(LIMITATIONS):
            raise ValueError("Closed selected-field Source required")
        TypeAdapter(UUID).validate_python(snapshot["case_id"], strict=True)
        TypeAdapter(Positive).validate_python(snapshot["created_by"], strict=True)
        TypeAdapter(UTC).validate_python(snapshot["recorded_at"], strict=True)
        TypeAdapter(Basis).validate_python(snapshot["basis_note"], strict=True)
        capture = collection.verify_capture(snapshot["capture"])
        if (snapshot["scope_id"], snapshot["patient_id"], snapshot["created_by"], snapshot["recorded_at"]) != (
            capture["request"]["scope_id"],
            capture["request"]["patient_id"],
            capture["actor_id"],
            capture["captured_at"],
        ):
            raise ValueError("Exact actual Source identity and capture clock required")
        if len(utf8(canonical(snapshot))) > MAX_BYTES:
            raise ValueError("Whole Source budget")
        return snapshot
    except (ValueError, TypeError, KeyError, UnicodeError, HTTPException) as exc:
        raise HTTPException(409, "完整75来源自身身份、原文字段或授权捕获无法核对") from exc


def original_proof(row):
    snapshot = verify_snapshot(_original_json(row.snapshot_json, MAX_BYTES))
    captured = snapshot["capture"]
    if (
        (row.case_id, row.scope_id, row.patient_id, row.created_by, utc_text(row.created_at))
        != (snapshot["case_id"], snapshot["scope_id"], snapshot["patient_id"], snapshot["created_by"], snapshot["recorded_at"])
        or row.content_hash != digest(snapshot)
        or row.collection_digest != captured["collection_digest"]
        or row.manifest_hash != captured["manifest_hash"]
        or row.parent_binding_hash != digest({k: captured[k] for k in ("scope_original", "actor_acl", "patient_authorization")})
    ):
        raise HTTPException(409, "来源SQL技术锚与完整原件不符")
    return snapshot


def _authorize(db, actor, header, *, capture=False, external_model=False):
    return authorize_subject(db, actor, header["scope_id"], header["patient_id"], capture=capture, external_model=external_model)


def _current(db, snapshot):
    captured, _ = collection.capture_sources(db, SimpleNamespace(user_id=snapshot["created_by"]), snapshot["capture"]["request"])
    return captured["collection_digest"] == snapshot["capture"]["collection_digest"]


def project_snapshot(snapshot, meta):
    """Only selected original fields; no SQL access or anonymity guarantee."""
    verify_snapshot(snapshot)
    if meta["case_id"] != snapshot["case_id"] or meta["content_hash"] != digest(snapshot):
        raise HTTPException(409, "公开来源锚与完整快照不符")
    docs = [
        document("deid_document:" + snapshot["case_id"] + ":" + str(index), item["document"]["field"], item["document"]["text"]) for index, item in enumerate(snapshot["capture"]["selected_documents"])
    ]
    value = {
        "schema_version": "deidentification_public_source_v1",
        "source_id": meta["source_id"],
        "source_content_hash": meta["content_hash"],
        "source_governance_hash": meta["governance_hash"],
        "documents": docs,
        "coverage": "complete_selected_fields_only",
        "original_time_basis": "legacy_naive_calendar_dates_timezone_unknown",
        "limitations": list(LIMITATIONS),
        "anonymity_guaranteed": False,
    }
    if len(utf8(canonical(value))) > MAX_BYTES:
        raise HTTPException(413, "完整模型所见来源超8MiB，未截断")
    return value


def source_current(db, user, identifier, *, audit_only=False, execution=False, external_model=False):
    if type(audit_only) is not bool or type(execution) is not bool or type(external_model) is not bool or execution and audit_only:
        raise HTTPException(422, "当前执行与冻结审计须明确且分开")
    actor = actor_now(db, user)
    header = _opaque(db, _key(identifier))
    if audit_only and actor.user_role != "super_admin":
        raise HTTPException(403, "技术冻结审计仅限当前Super，且不代授临床目的")
    try:
        _authorize(db, actor, header, external_model=external_model)
    except HTTPException as exc:
        if exc.status_code != 403 or not audit_only:
            raise
        return {
            **metadata(header),
            "snapshot": None,
            "public_source": None,
            "current": False,
            "eligible": False,
            "audit_only": True,
            "can_review": False,
            "can_revoke": header["status"] in {"draft", "published"},
            "exclusion_reasons": ["current_project_patient_purpose_not_authorized"],
            "proof_scope": "safe_metadata_and_opaque_hashes_only",
        }
    row = current_research_rows(db.query(AIDeidentificationCase).filter_by(case_id=identifier), shared=True).one()
    snapshot = original_proof(row)
    try:
        current = _current(db, snapshot)
    except HTTPException as exc:
        if exc.status_code not in {403, 404, 409}:
            raise
        current = False
    eligible = header["status"] == "published" and current
    if execution and not eligible:
        raise HTTPException(409, "来源当前性或技术发布已失效，未执行模型")
    visible = audit_only or current and header["status"] in {"draft", "published"}
    meta = metadata(header)
    return {
        **meta,
        "snapshot": snapshot if visible else None,
        "public_source": project_snapshot(snapshot, meta) if visible else None,
        "current": current,
        "eligible": eligible and not audit_only,
        "audit_only": audit_only,
        "can_review": not audit_only and current and actor.user_role == "super_admin" and header["status"] == "draft",
        "can_revoke": not audit_only and header["status"] in {"draft", "published"} and (actor.user_role == "super_admin" or actor.user_id == header["created_by"]),
        "exclusion_reasons": ([] if current else ["whole_collection_or_original_authority_changed"]) + ([] if header["status"] == "published" else ["source_not_published"]),
        "proof_scope": "complete_selected_originals_and_opaque_nonselected_manifest",
    }


def choices(db, user, values):
    request = _typed(PatientScopeRequest, values)
    value, available = collection.capture_sources(db, user, request, selections=False)
    result = {
        "schema_version": "deidentification_choices_v1",
        "request": request.model_dump(),
        "items": available,
        "complete": True,
        "collection_digest": value["collection_digest"],
        "limitations": list(LIMITATIONS),
    }
    if len(utf8(canonical(result))) > MAX_BYTES:
        raise HTTPException(413, "完整候选目录超8MiB，未截断")
    return result


def preview_input(db, user, values):
    captured, _ = collection.capture_sources(db, user, values)
    return {"schema_version": "deidentification_preview_v1", "capture": captured, "expected_collection_digest": captured["collection_digest"], "can_create": True, "no_business_write": True}


def _expected(row):
    value = {c.name: getattr(row, c.name) for c in row.__table__.columns if c.name not in {"snapshot_json", "review_basis_note", "revoke_reason"}}
    value.update({n + "_hash": text_digest(getattr(row, n)) for n in ("snapshot_json", "review_basis_note", "revoke_reason")})
    return value


def _finish(db, actor, row, action, *, current_required):
    from app.ai.models import AIAuditEvent

    expected = _expected(row)
    db.flush()
    detail = canonical({"case_id": row.case_id, "content_hash": row.content_hash, "governance_hash": governance_hash(expected)})
    audit = AIAuditEvent(actor_id=actor.user_id, action=action, target=row.case_id, detail_json=detail)
    db.add(audit)
    db.flush()
    actor = current_actor(db, actor, allowed_roles=SOURCE_ROLES)
    checked = _opaque(db, row.case_id, writing=True)
    event = current_research_rows(db.query(AIAuditEvent).filter_by(event_id=audit.event_id), shared=True).one_or_none()
    if checked != expected or event is None or (event.actor_id, event.action, event.target, event.detail_json) != (actor.user_id, action, row.case_id, detail):
        raise HTTPException(409, "完整来源/opaque正文SHA或具体审计PK写后回读失败")
    if current_required:
        _authorize(db, actor, checked)
        if not _current(db, original_proof(row)):
            raise HTTPException(409, "来源接收前完整集合变化")
    db.commit()
    return source_current(db, actor, row.case_id, audit_only=actor.user_role == "super_admin")


def create_case(db, user, values):
    request = _typed(CaseCreate, values)
    try:
        actor = actor_now(db, user)
        captured, _ = collection.capture_sources(db, actor, request.request)
        if captured["collection_digest"] != request.expected_collection_digest:
            raise HTTPException(409, "明确捕获全集已改变，未偷偷替换新源")
        identifier = str(uuid.uuid4())
        snapshot = {
            "schema_version": "deidentification_case_v1",
            "case_id": identifier,
            "scope_id": request.request.scope_id,
            "patient_id": request.request.patient_id,
            "created_by": actor.user_id,
            "recorded_at": captured["captured_at"],
            "capture": captured,
            "basis_note": request.basis_note,
            "limitations": list(LIMITATIONS),
        }
        verify_snapshot(snapshot)
        raw = canonical(snapshot)
        if len(utf8(raw)) > MAX_BYTES:
            raise HTTPException(413, "完整快照超过8MiB，未写入或截断")
        row = AIDeidentificationCase(
            case_id=identifier,
            scope_id=request.request.scope_id,
            patient_id=request.request.patient_id,
            schema_version="deidentification_case_v1",
            snapshot_json=raw,
            content_hash=digest(snapshot),
            collection_digest=captured["collection_digest"],
            parent_binding_hash=digest({k: captured[k] for k in ("scope_original", "actor_acl", "patient_authorization")}),
            manifest_hash=captured["manifest_hash"],
            created_by=actor.user_id,
            created_at=dt.datetime.strptime(captured["captured_at"], "%Y-%m-%dT%H:%M:%S.%fZ"),
            status="draft",
            revision=1,
            reviewed_by=None,
            reviewed_at=None,
            review_basis_note="",
            revoked_by=None,
            revoked_at=None,
            revoke_reason="",
        )
        db.add(row)
        return _finish(db, actor, row, "deidentification.case.create", current_required=True)
    except Exception:
        db.rollback()
        raise


def review_case(db, user, identifier, values, *, revoke=False):
    request = _typed(GovernanceRevoke if revoke else GovernanceReview, values)
    try:
        actor = actor_now(db, user)
        header = _opaque(db, _key(identifier), writing=True)
        if actor.user_role != "super_admin" and not (revoke and actor.user_id == header["created_by"]):
            raise HTTPException(403, "仅当前Super技术治理或原作者停止自己的来源")
        if header["revision"] != request.expected_revision or header["content_hash"] != request.expected_content_hash or header["status"] not in ({"draft", "published"} if revoke else {"draft"}):
            raise HTTPException(409, "当前Source原件状态或明确CAS已变化")
        if revoke:
            updates = dict(status="revoked", revision=header["revision"] + 1, revoked_by=actor.user_id, revoked_at=utcnow(), revoke_reason=request.basis_note)
        else:
            _authorize(db, actor, header)
            row = current_research_rows(db.query(AIDeidentificationCase).filter_by(case_id=identifier)).one()
            if not _current(db, original_proof(row)):
                raise HTTPException(409, "当前完整来源变化，不接受旧快照技术发布")
            updates = dict(status="published" if request.decision == "publish" else "rejected", revision=2, reviewed_by=actor.user_id, reviewed_at=utcnow(), review_basis_note=request.basis_note)
        if revoke:
            # Opaque stop path: SQL checks/hash the existing body, never load
            # its clinical TEXT merely because a technical Super can revoke.
            expected = dict(header)
            expected.update({k: v for k, v in updates.items() if k not in {"revoke_reason"}})
            expected["revoke_reason_hash"] = text_digest(request.basis_note)
            db.query(AIDeidentificationCase).filter_by(case_id=identifier, revision=request.expected_revision).update(updates, synchronize_session=False)
            from app.ai.models import AIAuditEvent

            detail = canonical({"case_id": identifier, "content_hash": expected["content_hash"], "governance_hash": governance_hash(expected)})
            audit = AIAuditEvent(actor_id=actor.user_id, action="deidentification.case.revoke", target=identifier, detail_json=detail)
            db.add(audit)
            db.flush()
            current_actor(db, actor, allowed_roles=SOURCE_ROLES)
            event = current_research_rows(db.query(AIAuditEvent).filter_by(event_id=audit.event_id), shared=True).one_or_none()
            if (
                _opaque(db, identifier, writing=True) != expected
                or event is None
                or (event.actor_id, event.action, event.target, event.detail_json) != (actor.user_id, "deidentification.case.revoke", identifier, detail)
            ):
                raise HTTPException(409, "停止来源的opaque完整SHA或具体审计PK不一致")
            db.commit()
            return source_current(db, actor, identifier, audit_only=actor.user_role == "super_admin")
        for key, value in updates.items():
            setattr(row, key, value)
        return _finish(db, actor, row, "deidentification.case.review", current_required=True)
    except Exception:
        db.rollback()
        raise
