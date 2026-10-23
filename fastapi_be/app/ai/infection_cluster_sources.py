"""Complete finite current SQL capture; explicit purpose rights precede clinical BODY.

No diagnosis/model execution is implemented. The SQL-only HMAC key is not an
anonymity guarantee and is never returned by metadata or split part endpoints.
"""

import secrets
import uuid

from fastapi import HTTPException
from sqlalchemy import func, inspect

from app.ai import infection_cluster_contract as c
from app.ai import infection_cluster_input as i
from app.ai import infection_cluster_projection as p
from app.ai import infection_cluster_registry as r
from app.ai.infection_cluster_models import AIInfectionCaseReview, AIInfectionPurposeGrant, AIInfectionSnapshot
from app.ai.infection_cluster_write_guard import current


def _roots(db, req):
    from app.models import InfectionCase

    roots, last, size = [], None, 0
    index_hint = None
    if db.get_bind().dialect.name == "mysql":
        # Discover a real current FK-leading index; do not assume its generated
        # name or let a tiny-table optimizer choose a global PK scan/lock.
        indexes = inspect(db.connection()).get_indexes(InfectionCase.__tablename__)
        names = sorted(item["name"] for item in indexes if item["column_names"] and item["column_names"][0] == "patient_id")
        if not names:
            raise HTTPException(409, "实际Patient前缀索引缺失，无法证明有限范围当前锁")
        quoted = db.get_bind().dialect.identifier_preparer.quote(names[0])
        index_hint = f"FORCE INDEX ({quoted})"
    while True:
        query = db.query(InfectionCase).filter(
            InfectionCase.patient_id.in_(req.patient_ids), InfectionCase.onset_date >= c.day(req.window.date_from), InfectionCase.onset_date <= c.day(req.window.date_to)
        )
        if index_hint is not None:
            query = query.with_hint(InfectionCase, index_hint, "mysql")
        if last is not None:
            query = query.filter(InfectionCase.case_id > last)
        rows = current(query.order_by(InfectionCase.case_id)).limit(128).all()
        for row in rows:
            if len(roots) >= c.MAX_ROOTS:
                raise HTTPException(413, "完整相关原上报集合超过4096根，拒绝截断")
            raw = r.original(row)
            proof = c.OriginalProof(original=raw, content_hash=c.digest(raw))
            size += len(c.utf8(c.canonical(proof)))
            if size > c.MAX_BYTES:
                raise HTTPException(413, "完整相关原件超过8MiB，拒绝截断")
            roots.append(proof)
        if len(rows) < 128:
            break
        last = rows[-1].case_id
    return roots


def _current_grants(db, actor, req):
    result = []
    # Bind the complete applicable permission-root set, including draft,
    # rejected/withdrawn roots and transfer grants not used for this local read.
    for row in r.governed_rows(db, AIInfectionPurposeGrant, AIInfectionPurposeGrant.patient_id.in_(req.patient_ids), AIInfectionPurposeGrant.user_id == actor.user_id):
        full = r.record(db, row, "grant")
        result.append({"record_id": full.record_id, "content_hash": full.content_hash, "governance_hash": full.governance_hash})
        if len(result) > c.MAX_ROOTS or len(c.utf8(c.canonical(result))) > c.MAX_BYTES:
            raise HTTPException(413, "用途根全集超限，拒绝不完整核验")
    return result


def _review_rows(db, req, roots):
    result, by_root = [], {}
    ids = [proof.original.case_id for proof in roots]
    # Bounded PK batches avoid a huge driver IN list. All relevant review
    # versions/states are retained; no latest-row selection is made.
    for offset in range(0, len(ids), 128):
        for row in r.governed_rows(db, AIInfectionCaseReview, AIInfectionCaseReview.definition_id == req.definition_id, AIInfectionCaseReview.case_id.in_(ids[offset : offset + 128])):
            full = r.record(db, row, "review")
            proposal = full.payload
            if (row.case_id, row.patient_id, row.definition_id, row.original_content_hash, row.definition_content_hash, row.definition_governance_hash) != (
                proposal.case_id,
                next(proof.original.patient_id for proof in roots if proof.original.case_id == proposal.case_id),
                proposal.definition_id,
                proposal.original_content_hash,
                proposal.definition_content_hash,
                proposal.definition_governance_hash,
            ):
                raise HTTPException(409, "复核技术定位与完整原件不一致")
            result.append({"record_id": full.record_id, "content_hash": full.content_hash, "governance_hash": full.governance_hash})
            by_root.setdefault(proposal.case_id, []).append(full)
            if len(result) > c.MAX_ROOTS or len(c.utf8(c.canonical(result))) > c.MAX_BYTES:
                raise HTTPException(413, "复核根全集超限，拒绝不完整核验")
    return result, by_root


def _stamp(actor_id, at, basis):
    return c.ReviewStamp(reviewed_by=actor_id, reviewed_at=at, basis_note=basis, basis_hash=c.text_digest(basis))


def pure_review(full):
    proposal, governance = full.payload, full.governance
    mappings = {}
    for field in ("infection_type", "pathogen"):
        raw = getattr(proposal, field)
        mappings[field] = c.TaxonomyReview(
            field=field,
            original_state=raw.original_state,
            original_value_hash=raw.original_value_hash,
            assessment=raw.assessment,
            reviewed_code=raw.reviewed_code,
            review=_stamp(governance.reviewed_by, governance.reviewed_at, raw.basis_note),
        )
    return c.CaseReview(
        case_id=proposal.case_id,
        original_content_hash=proposal.original_content_hash,
        definition_content_hash=proposal.definition_content_hash,
        definition_governance_hash=proposal.definition_governance_hash,
        assessment=proposal.assessment,
        review=_stamp(governance.reviewed_by, governance.reviewed_at, proposal.basis_note),
        **mappings,
    )


def collect_current(db, actor, req, *, external_model=False, require_config=False):
    actor, _ = r.authorize_patients(db, actor, req.patient_ids, external_model=external_model, require_config=require_config)
    # Own staged business changes must participate too. Reauthorize after their
    # flush (including any database triggers), before the first clinical SELECT.
    db.flush()
    actor, _ = r.authorize_patients(db, actor, req.patient_ids, external_model=external_model, require_config=require_config)
    full_definition, definition = r.definition_current(db, req.definition_id)
    roots = _roots(db, req)
    reviews_manifest, by_root = _review_rows(db, req, roots)
    reviews = []
    for proof in roots:
        matches = [
            full
            for full in by_root.get(proof.original.case_id, [])
            if full.eligible
            and (full.payload.original_content_hash, full.payload.definition_content_hash, full.payload.definition_governance_hash)
            == (proof.content_hash, definition.content_hash, definition.governance_hash)
        ]
        if len(matches) != 1:
            raise HTTPException(409, "每一原上报根必须恰好对应一个当前独立发布的精确复核")
        reviews.append(pure_review(matches[0]))
    witness = {
        "schema_version": "infection_current_witness_v1",
        "scope": req.model_dump(mode="json"),
        "actor": {"user_id": actor.user_id, "role": actor.user_role, "token_invalid_before": actor.token_invalid_before.isoformat() if actor.token_invalid_before else None},
        "definition": {"record_id": full_definition.record_id, "content_hash": full_definition.content_hash, "governance_hash": full_definition.governance_hash},
        "originals": [{"case_id": proof.original.case_id, "content_hash": proof.content_hash} for proof in roots],
        "reviews": reviews_manifest,
        "grants": _current_grants(db, actor, req),
    }
    c.canonical(witness)
    return actor, definition, roots, reviews, witness


@r.atomic
def preview_roots(db, user, value):
    """Authorized complete roots for explicit per-case review; no implicit review."""
    req = i.SnapshotCreate.model_validate(value)
    actor = r._start(db, user, patient_ids=req.patient_ids)
    r.authorize_patients(db, actor, req.patient_ids)
    db.flush()
    r.authorize_patients(db, actor, req.patient_ids)
    _, definition = r.definition_current(db, req.definition_id)
    roots = _roots(db, req)
    result = {
        "schema_version": "infection_root_preview_v1",
        "request": req.model_dump(mode="json"),
        "definition": definition.model_dump(mode="json"),
        "originals": [proof.model_dump(mode="json") for proof in roots],
        "complete": True,
        "root_count": len(roots),
        "clinical_interpretation": "recorded_reports_not_diagnoses_or_outbreaks",
        "captured_at": r.utc(r.utcnow()),
    }
    c.canonical(result)
    return result


@r.atomic
def create_snapshot(db, user, value):
    req = i.SnapshotCreate.model_validate(value)
    actor = r._start(db, user, patient_ids=req.patient_ids)
    actor, definition, roots, reviews, witness = collect_current(db, actor, req)
    rid, key = str(uuid.uuid4()), secrets.token_bytes(32)
    private = c.PrivateCollection(
        schema_version="infection_cluster_private_collection_v1",
        collection_id=rid,
        captured_at=r.utc(r.utcnow()),
        patient_ids=req.patient_ids,
        window=req.window,
        definition=definition,
        originals=roots,
        reviews=reviews,
        declared_capture_scope="all_infection_case_rows_for_explicit_patients_and_onset_window_all_statuses",
        completeness_basis="caller_declared_requires_later_server_current_collection_proof",
    )
    public = p.project_source(private, key)
    private_json, public_json, witness_json = c.canonical(private), c.canonical(public), c.canonical(witness)
    anchors = {"scope_hash": c.digest(req), "definition_id": req.definition_id, "captured_at": private.captured_at, "public_hash": c.digest(public), "witness_hash": c.digest(witness)}
    event, expected = r._audit(db, actor, "snapshot", rid, "create", c.digest(private), 1, anchors=anchors)
    row = AIInfectionSnapshot(
        snapshot_id=rid,
        definition_id=req.definition_id,
        created_by=actor.user_id,
        create_event_id=event.event_id,
        schema_version="infection_cluster_snapshot_v1",
        captured_at=r.clock(private.captured_at),
        scope_json=c.canonical(req),
        private_json=private_json,
        private_hash=c.digest(private),
        public_json=public_json,
        public_hash=c.digest(public),
        witness_json=witness_json,
        witness_hash=c.digest(witness),
        mapping_key=key,
    )
    db.add(row)
    r._verify_write(db, row, expected, actor)
    _, _, _, _, actual_witness = collect_current(db, actor, req)
    if witness != actual_witness:
        raise HTTPException(409, "快照写后完整成员/用途/定义/复核已变化")
    return metadata(row)


def metadata(row):
    return {
        "schema_version": "infection_snapshot_metadata_v1",
        "snapshot_id": row.snapshot_id,
        "captured_at": r.utc(row.captured_at),
        "private_hash": row.private_hash,
        "public_hash": row.public_hash,
        "witness_hash": row.witness_hash,
        "detail_required": True,
        "parts_separately_bounded": True,
        "denominator": "not_provided",
        "clinical_parts_require_current_patient_purpose": True,
        "can_execute": False,
    }


def _snapshot_locator(db, rid):
    return current(
        db.query(
            AIInfectionSnapshot.snapshot_id,
            AIInfectionSnapshot.created_by,
            AIInfectionSnapshot.definition_id,
            AIInfectionSnapshot.scope_json,
            AIInfectionSnapshot.create_event_id,
            AIInfectionSnapshot.private_hash,
            AIInfectionSnapshot.public_hash,
            AIInfectionSnapshot.witness_hash,
            AIInfectionSnapshot.captured_at,
        ).filter_by(snapshot_id=rid),
        shared=True,
    ).one_or_none()


@r.atomic
def snapshot_part(db, user, rid, part, *, external_model=False, execution=False):
    from app.models import User

    if part not in {"private", "public"}:
        raise HTTPException(422, "只支持明确的独立private/public整件")
    # Gate + actor precede locator and every clinical Source TEXT column. A
    # revoked purpose has no Super frozen/audit exception.
    actor = r._start(db, user, roles=i.SOURCE_ROLES)
    locator = _snapshot_locator(db, rid)
    if locator is None:
        raise HTTPException(404, "快照不存在")
    req = i.SnapshotCreate.model_validate_json(locator.scope_json)
    if c.canonical(req) != locator.scope_json or locator.definition_id != req.definition_id:
        raise HTTPException(409, "快照技术范围原字节或定义定位不一致")
    anchors = {"scope_hash": c.digest(req), "definition_id": req.definition_id, "captured_at": r.utc(locator.captured_at), "public_hash": locator.public_hash, "witness_hash": locator.witness_hash}
    expected_audit = r.audit_detail("snapshot", rid, "create", locator.private_hash, 1, anchors=anchors)
    audit = r._actual(db, r.AIAuditEvent, locator.create_event_id)
    if audit is None or (audit.actor_id, audit.action, audit.target, audit.detail_json) != (locator.created_by, "infection.snapshot.create", rid, expected_audit):
        raise HTTPException(409, "原始技术范围与具体创建审计PK不一致")
    r.authorize_patients(db, actor, req.patient_ids, external_model=external_model, require_config=execution)
    owner = current(db.query(User).filter_by(user_id=locator.created_by), shared=True).one_or_none()
    if owner is None:
        raise HTTPException(409, "原捕获账户不存在")
    _, _, _, _, witness = collect_current(db, owner, req, external_model=external_model, require_config=False)
    if c.digest(witness) != locator.witness_hash:
        raise HTTPException(409, "当前完整来源集合已变化，未读取快照正文")
    row = current(db.query(AIInfectionSnapshot).filter_by(snapshot_id=rid), shared=True).one()
    if row.definition_id != req.definition_id or c.canonical(req) != row.scope_json or row.witness_json != c.canonical(witness) or row.witness_hash != c.digest(witness):
        raise HTTPException(409, "当前完整来源集合与原快照不一致")
    private = c.verify_private_collection(row.private_json)
    public = p.InfectionClusterSource.model_validate_json(row.public_json)
    if (
        private.collection_id != rid
        or private.captured_at != r.utc(row.captured_at)
        or private.definition.payload.definition_id != row.definition_id
        or private.patient_ids != req.patient_ids
        or private.window != req.window
        or c.digest(private) != row.private_hash
        or c.canonical(public) != row.public_json
        or c.digest(public) != row.public_hash
        or not p.verify_public_source(public, private, row.mapping_key)
    ):
        raise HTTPException(409, "完整来源/投影/SQL私钥锚不一致")
    audit = r._actual(db, r.AIAuditEvent, row.create_event_id)
    if audit is None or audit.actor_id != row.created_by or audit.action != "infection.snapshot.create" or audit.target != rid or audit.detail_json != expected_audit:
        raise HTTPException(409, "实际快照创建审计PK不一致")
    # The immutable private original rows are compared too, not merely a public
    # digest someone could rehash. The fresh capture clock itself is not a
    # currentness key; immutable original captured_at remains unchanged.
    frozen_roots = [{"case_id": proof.original.case_id, "content_hash": proof.content_hash} for proof in private.originals]
    if frozen_roots != witness["originals"]:
        raise HTTPException(409, "原件完整根集合不一致")
    body = private.model_dump(mode="json") if part == "private" else public.model_dump(mode="json")
    result = {"metadata": metadata(row), "part": part, "value": body, "proof_basis": "server_current_sql_and_exact_hashes_private_key_not_disclosed"}
    c.canonical(result)
    return result


def snapshot_directory(db, user, *, page=1, size=20):
    actor = r._start(db, user, roles=i.SOURCE_ROLES)
    if type(page) is not int or page < 1 or type(size) is not int or not 1 <= size <= 100:
        raise HTTPException(422, "需要完整分页参数")
    columns = [getattr(AIInfectionSnapshot, name) for name in ("snapshot_id", "captured_at", "private_hash", "public_hash", "witness_hash")]
    query = db.query(*columns)
    if actor.user_role != "super_admin":
        query = query.filter(AIInfectionSnapshot.created_by == actor.user_id)
    total = current(query.with_entities(func.count(AIInfectionSnapshot.snapshot_id)), shared=True).scalar()
    rows = current(query.order_by(AIInfectionSnapshot.captured_at, AIInfectionSnapshot.snapshot_id), shared=True).offset((page - 1) * size).limit(size).all()
    return {"items": [metadata(row) for row in rows], "total": total, "page": page, "size": size, "clinical_body_included": False}
