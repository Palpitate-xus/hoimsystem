"""Current SQL purpose grants/definitions/reviews, distinct from pure declarations.

All authority is checked on current SQL rows. The pure recipe proves literal
bindings only; actual independent Super actors and exact audit PKs live here.
"""

import datetime as dt
import functools
import json
import uuid
from typing import Literal

from fastapi import HTTPException
from pydantic import model_validator
from sqlalchemy import func
from sqlalchemy import inspect as sa_inspect

from app.ai import infection_cluster_contract as c
from app.ai import infection_cluster_input as i
from app.ai.infection_cluster_models import AIInfectionCaseReview, AIInfectionDefinition, AIInfectionPurposeGrant
from app.ai.infection_cluster_write_guard import current, identity, lock_gate, lock_infection_write
from app.ai.models import AIAuditEvent

MODELS = {"grant": AIInfectionPurposeGrant, "definition": AIInfectionDefinition, "review": AIInfectionCaseReview}
KEYS = {"grant": "grant_id", "definition": "definition_id", "review": "review_id"}


def utcnow():
    return dt.datetime.now(dt.UTC).replace(tzinfo=None)


def utc(value):
    return value.strftime("%Y-%m-%dT%H:%M:%S.%fZ") if value is not None else None


def clock(value):
    return c.clock(value).replace(tzinfo=None)


def atomic(function):
    @functools.wraps(function)
    def call(db, *args, **kwargs):
        try:
            return function(db, *args, **kwargs)
        except Exception:
            db.rollback()
            raise

    return call


class GrantPayload(i.GrantCreate):
    grant_id: c.UUID
    created_by: c.PositiveId
    recorded_at: str


class ReviewPayload(i.CaseReviewCreate):
    review_id: c.UUID
    created_by: c.PositiveId
    recorded_at: str


class Governance(c.StrictModel):
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

    @model_validator(mode="after")
    def real_state(self):
        c.clock(self.recorded_at)
        if self.reviewed_by is None:
            if self.reviewed_at is not None or self.review_event_id is not None or self.review_basis != "" or self.privacy_review != "unknown" or self.faithfulness_review != "unknown":
                raise ValueError("Incomplete review declaration")
        else:
            if (
                self.reviewed_by == self.created_by
                or self.review_event_id is None
                or not self.review_basis.strip()
                or self.reviewed_at is None
                or c.clock(self.reviewed_at) < c.clock(self.recorded_at)
                or self.privacy_review == "unknown"
                or self.faithfulness_review == "unknown"
            ):
                raise ValueError("Independent complete current review required")
        if self.status == "draft" and (self.revision != 1 or self.reviewed_by is not None or self.revoked_by is not None):
            raise ValueError("Invalid draft governance")
        if self.status in {"published", "rejected"} and (self.revision != 2 or self.reviewed_by is None or self.revoked_by is not None):
            raise ValueError("Invalid reviewed governance")
        if self.status == "published" and (self.privacy_review, self.faithfulness_review) != ("confirmed", "confirmed"):
            raise ValueError("Publication requires both confirmations")
        if self.status == "rejected" and self.privacy_review == self.faithfulness_review == "confirmed":
            raise ValueError("Rejection cannot claim both confirmations")
        if self.revoked_by is None:
            if self.revoked_at is not None or self.revoke_event_id is not None or self.revoke_basis != "":
                raise ValueError("Incomplete withdrawal")
        elif (
            self.status != "revoked"
            or self.revoke_event_id is None
            or not self.revoke_basis.strip()
            or self.revoked_at is None
            or c.clock(self.revoked_at) < c.clock(self.reviewed_at or self.recorded_at)
            or self.revision != (3 if self.reviewed_by is not None else 2)
        ):
            raise ValueError("Invalid withdrawal governance")
        if self.status == "revoked" and self.revoked_by is None:
            raise ValueError("Withdrawal signature missing")
        if len(c.utf8(self.review_basis)) > 4000 or len(c.utf8(self.revoke_basis)) > 4000:
            raise ValueError("Basis exceeds exact UTF8 bound")
        return self


class RegistryRecord(c.StrictModel):
    schema_version: Literal["infection_registry_record_v1"]
    kind: Literal["grant", "definition", "review"]
    record_id: c.UUID
    payload: GrantPayload | c.DefinitionPayload | ReviewPayload
    content_hash: c.SHA
    governance: Governance
    governance_hash: c.SHA
    eligible: bool
    authority_basis: Literal["actual_current_sql_super_and_exact_audit_pk_not_professional_qualification"]

    @model_validator(mode="after")
    def exact_kind(self):
        typ = {"grant": GrantPayload, "definition": c.DefinitionPayload, "review": ReviewPayload}[self.kind]
        if (
            type(self.payload) is not typ
            or getattr(self.payload, KEYS[self.kind]) != self.record_id
            or c.digest(self.payload) != self.content_hash
            or c.digest(self.governance) != self.governance_hash
        ):
            raise ValueError("Registry proof differs")
        author = self.payload.authored_by if self.kind == "definition" else self.payload.created_by
        if author != self.governance.created_by or self.payload.recorded_at != self.governance.recorded_at:
            raise ValueError("Actual author/recording anchors differ")
        return self


def _start(db, user, *, patient_ids=(), roles=i.GOVERNANCE_ROLES, related_user_ids=()):
    """Gate → sorted related User SHARE → sorted Patient X → source/root rows.

    The preliminary queries contain technical author IDs only, never clinical
    body columns. A shared domain Gate serializes all supported source writers.
    """
    lock_gate(db)
    uid = identity(user)
    users = {uid, *related_user_ids}
    # All governance actors are locked before Patients. No privilege is inferred
    # from these opaque locators; every full object and audit is verified later.
    for model in MODELS.values():
        query = db.query(model.created_by, model.reviewed_by, model.revoked_by)
        if model is AIInfectionPurposeGrant:
            query = query.filter(model.patient_id.in_(patient_ids), model.user_id == uid)
        elif model is AIInfectionCaseReview:
            query = query.filter(model.patient_id.in_(patient_ids))
        for row in current(query, shared=True).all():
            users.update(value for value in row if value is not None)
    return lock_infection_write(db, user, allowed_roles=roles, patient_ids=patient_ids, related_user_ids=users)


def _current_sup(db, uid):
    from app.models import User

    row = current(db.query(User.user_id, User.user_role).filter_by(user_id=uid), shared=True).one_or_none()
    return row is not None and row.user_role == "super_admin"


def _state(row):
    return {column.name: getattr(row, column.name) for column in row.__table__.columns}


def _actual(db, model, key):
    primary = sa_inspect(model).primary_key[0]
    return current(db.query(*model.__table__.columns).filter(primary == key), shared=True).one_or_none()


def audit_detail(kind, rid, action, content_hash, revision, *, anchors=None):
    value = {"schema_version": "infection_registry_audit_v1", "kind": kind, "record_id": rid, "action": action, "content_hash": content_hash, "revision": revision}
    if anchors is not None:
        value["anchors"] = anchors
    return c.canonical(value)


def _audit(db, actor, kind, rid, action, content_hash, revision, *, anchors=None):
    detail = audit_detail(kind, rid, action, content_hash, revision, anchors=anchors)
    event = AIAuditEvent(actor_id=actor.user_id, action=f"infection.{kind}.{action}", target=rid, detail_json=detail, create_time=utcnow().replace(microsecond=0))
    db.add(event)
    db.flush()
    expected = _state(event)
    return event, expected


def _verify_audit(db, expected):
    actual = _actual(db, AIAuditEvent, expected["event_id"])
    if actual is None or dict(actual._mapping) != expected:
        raise HTTPException(409, "具体审核审计原件缺失或已改变")


def _verify_write(db, row, event_state, actor):
    expected = _state(row)
    db.flush()
    actual = _actual(db, type(row), expected[sa_inspect(type(row)).primary_key[0].name])
    if actual is None or dict(actual._mapping) != expected or not _current_sup(db, actor.user_id) or not _current_sup(db, expected["created_by"]):
        raise HTTPException(409, "来源写后实际SQL或当前审核身份不一致")
    _verify_audit(db, event_state)


def _audit_current(db, row, kind):
    rid = getattr(row, KEYS[kind])
    for action, event_id, actor_id, revision in [
        ("create", row.create_event_id, row.created_by, 1),
        ("review", row.review_event_id, row.reviewed_by, 2),
        ("revoke", row.revoke_event_id, row.revoked_by, row.revision),
    ]:
        if event_id is None:
            continue
        actual = _actual(db, AIAuditEvent, event_id)
        if (
            actual is None
            or actual.actor_id != actor_id
            or actual.action != f"infection.{kind}.{action}"
            or actual.target != rid
            or actual.detail_json != audit_detail(kind, rid, action, row.content_hash, revision)
        ):
            raise HTTPException(409, "来源具体审计PK闭合失败")


def record(db, row, kind, *, require_current=False):
    payload_type = {"grant": GrantPayload, "definition": c.DefinitionPayload, "review": ReviewPayload}[kind]
    payload = payload_type.model_validate_json(row.payload_json)
    if c.canonical(payload) != row.payload_json:
        raise HTTPException(409, "原件JSON不是完整规范字节")
    gov = Governance.model_validate({field: utc(getattr(row, field)) if field.endswith("_at") else getattr(row, field) for field in Governance.model_fields})
    _audit_current(db, row, kind)
    eligible = row.status == "published" and _current_sup(db, row.created_by) and _current_sup(db, row.reviewed_by)
    result = RegistryRecord(
        schema_version="infection_registry_record_v1",
        kind=kind,
        record_id=getattr(row, KEYS[kind]),
        payload=payload,
        content_hash=row.content_hash,
        governance=gov,
        governance_hash=c.digest(gov),
        eligible=eligible,
        authority_basis="actual_current_sql_super_and_exact_audit_pk_not_professional_qualification",
    )
    c.canonical(result)
    if require_current and not result.eligible:
        raise HTTPException(409, "来源未由当前独立审核身份有效发布")
    return result


def _authorize_record_patient(db, actor, kind, rid):
    if kind == "review":
        from app.models import InfectionCase

        locator = current(db.query(AIInfectionCaseReview.patient_id, AIInfectionCaseReview.case_id).filter_by(review_id=rid), shared=True).one_or_none()
        if locator is None:
            raise HTTPException(404, "复核不存在")
        root = current(db.query(InfectionCase.patient_id).filter_by(case_id=locator.case_id), shared=True).one_or_none()
        if root is None or root.patient_id != locator.patient_id:
            raise HTTPException(409, "复核与实际原上报患者绑定已改变")
        authorize_patients(db, actor, [root.patient_id])


def _row(db, kind, rid, *, shared=False):
    model = MODELS[kind]
    row = current(db.query(model).filter(getattr(model, KEYS[kind]) == rid), shared=shared).one_or_none()
    if row is None:
        raise HTTPException(404, "来源记录不存在")
    return row


def _create(db, actor, kind, rid, payload, **headers):
    serialized = c.canonical(payload)
    content_hash = c.digest(payload)
    event, expected = _audit(db, actor, kind, rid, "create", content_hash, 1)
    row = MODELS[kind](
        **{KEYS[kind]: rid},
        **headers,
        payload_json=serialized,
        content_hash=content_hash,
        status="draft",
        revision=1,
        recorded_at=clock(payload.recorded_at),
        created_by=actor.user_id,
        create_event_id=event.event_id,
        privacy_review="unknown",
        faithfulness_review="unknown",
        review_basis="",
        revoke_basis="",
    )
    db.add(row)
    _verify_write(db, row, expected, actor)
    return row


@atomic
def create_grant(db, user, value):
    from app.models import User

    req = i.GrantCreate.model_validate(value)
    actor = _start(db, user, patient_ids=[req.patient_id], related_user_ids=[req.user_id])
    if current(db.query(User.user_id).filter_by(user_id=req.user_id), shared=True).one_or_none() is None:
        raise HTTPException(409, "明确被许可账户不存在")
    rid = str(uuid.uuid4())
    payload = GrantPayload(**req.model_dump(), grant_id=rid, created_by=actor.user_id, recorded_at=utc(utcnow()))
    row = _create(db, actor, "grant", rid, payload, patient_id=req.patient_id, user_id=req.user_id, purpose=req.purpose, valid_from=clock(req.valid_from), valid_to=clock(req.valid_to))
    return record(db, row, "grant")


@atomic
def create_definition(db, user, value):
    req = i.DefinitionCreate.model_validate(value)
    actor = _start(db, user)
    rid = str(uuid.uuid4())
    payload = c.DefinitionPayload(
        **req.model_dump(), definition_id=rid, authored_by=actor.user_id, recorded_at=utc(utcnow()), authority_basis="local_human_declaration_not_official_or_clinically_validated"
    )
    return record(db, _create(db, actor, "definition", rid, payload), "definition")


def _cas(req, full):
    if (req.expected_revision, req.expected_content_hash, req.expected_governance_hash) != (full.governance.revision, full.content_hash, full.governance_hash):
        raise HTTPException(409, "来源版本/完整内容/治理CAS不一致")


@atomic
def review_record(db, user, kind, rid, value):
    req = i.GovernReview.model_validate(value)
    actor = _start(db, user)
    _authorize_record_patient(db, actor, kind, rid)
    row = _row(db, kind, rid)
    full = record(db, row, kind)
    _cas(req, full)
    if row.status != "draft" or row.created_by == actor.user_id or not _current_sup(db, row.created_by):
        raise HTTPException(409, "仅当前不同Super可审核有效提出者的草稿")
    if kind == "review":
        _review_parent(db, actor, full.payload)
    event, expected = _audit(db, actor, kind, rid, "review", row.content_hash, 2)
    row.status = "published" if req.decision == "publish" else "rejected"
    row.revision = 2
    row.reviewed_by = actor.user_id
    row.reviewed_at = utcnow()
    row.review_event_id = event.event_id
    row.review_basis = req.basis_note
    row.privacy_review = req.privacy_review
    row.faithfulness_review = req.faithfulness_review
    _verify_write(db, row, expected, actor)
    result = record(db, row, kind)
    if kind == "review":
        _review_parent(db, actor, result.payload)
    return result


@atomic
def revoke_record(db, user, kind, rid, value):
    req = i.CAS.model_validate(value)
    actor = _start(db, user)
    _authorize_record_patient(db, actor, kind, rid)
    row = _row(db, kind, rid)
    _cas(req, record(db, row, kind))
    if row.status == "revoked":
        raise HTTPException(409, "来源已撤销")
    revision = row.revision + 1
    event, expected = _audit(db, actor, kind, rid, "revoke", row.content_hash, revision)
    row.status, row.revision = "revoked", revision
    row.revoked_by, row.revoked_at = actor.user_id, utcnow()
    row.revoke_event_id, row.revoke_basis = event.event_id, req.basis_note
    _verify_write(db, row, expected, actor)
    return record(db, row, kind)


def governed_rows(db, model, *filters):
    """Small PK batches + cumulative whole-row budget, never an unbounded BODY all()."""
    primary = sa_inspect(model).primary_key[0]
    last, count, size = None, 0, 0
    while True:
        query = db.query(model).filter(*filters)
        if last is not None:
            query = query.filter(primary > last)
        batch = current(query.order_by(primary), shared=True).limit(8).all()
        for row in batch:
            count += 1
            size += len(c.utf8(row.payload_json)) + len(c.utf8(row.review_basis)) + len(c.utf8(row.revoke_basis))
            if count > c.MAX_ROOTS or size > c.MAX_BYTES:
                raise HTTPException(413, "完整治理原件集合超限，拒绝截断")
            yield row
        if len(batch) < 8:
            break
        last = getattr(batch[-1], primary.name)


def authorize_patients(db, user, patient_ids, *, external_model=False, require_config=False):
    from app.ai.models import AIFeatureConfig
    from app.dependencies import VALID_USER_ROLES

    actor = _start(db, user, patient_ids=patient_ids, roles=i.SOURCE_ROLES)
    if require_config:
        config = current(db.query(AIFeatureConfig.allowed_roles_json).filter_by(feature_key="infection_cluster"), shared=True).one_or_none()
        try:
            roles = json.loads(config.allowed_roles_json) if config else None
        except (ValueError, TypeError) as exc:
            raise HTTPException(409, "当前配置角色不可核对") from exc
        if type(roles) is not list or any(type(role) is not str or role not in VALID_USER_ROLES for role in roles) or len(set(roles)) != len(roles):
            raise HTTPException(409, "当前配置角色不是完整合法闭集")
        if actor.user_role not in roles:
            raise HTTPException(403, "当前角色未获本项执行配置许可")
    proofs = []
    purposes = ["infection_surveillance_processing"] + (["external_model_transfer"] if external_model else [])
    now = utcnow()
    for pid in patient_ids:
        for purpose in purposes:
            rows = governed_rows(db, AIInfectionPurposeGrant, AIInfectionPurposeGrant.patient_id == pid, AIInfectionPurposeGrant.user_id == actor.user_id, AIInfectionPurposeGrant.purpose == purpose)
            eligible = []
            for row in rows:
                full = record(db, row, "grant")
                payload = full.payload
                if (payload.patient_id, payload.user_id, payload.purpose, clock(payload.valid_from), clock(payload.valid_to)) != (
                    row.patient_id,
                    row.user_id,
                    row.purpose,
                    row.valid_from,
                    row.valid_to,
                ):
                    raise HTTPException(409, "用途许可技术定位与完整原件不一致")
                proofs.append({"grant_id": row.grant_id, "content_hash": full.content_hash, "governance_hash": full.governance_hash})
                if full.eligible and row.valid_from <= now < row.valid_to:
                    eligible.append(full)
            if not eligible:
                raise HTTPException(403, "每位明确患者均需当前独立发布的本用途许可")
    return actor, proofs


def definition_current(db, definition_id):
    full = record(db, _row(db, "definition", definition_id, shared=True), "definition", require_current=True)
    gov = c.DefinitionGovernance(
        status="published",
        revision=2,
        definition_content_hash=full.content_hash,
        published_by=full.governance.reviewed_by,
        published_at=full.governance.reviewed_at,
        publication_basis_note=full.governance.review_basis,
        publication_basis_hash=c.text_digest(full.governance.review_basis),
        verification_basis="declared_actor_and_clock_structure_only_not_current_authority",
    )
    pure = c.PublishedDefinition(payload=full.payload, content_hash=full.content_hash, governance=gov, governance_hash=c.digest(gov))
    return full, pure


def original(row):
    values = {key: getattr(row, key) for key in c.InfectionCaseOriginal.model_fields}
    for field in ("create_time", "update_time"):
        value = values[field]
        values[field] = {"text": value.isoformat(), "basis": "stored_naive_timezone_unknown"}
    values["onset_date"] = values["onset_date"].isoformat()
    return c.InfectionCaseOriginal.model_validate(values)


def _review_parent(db, actor, req):
    from app.models import InfectionCase

    locator = current(db.query(InfectionCase.patient_id).filter_by(case_id=req.case_id), shared=True).one_or_none()
    if locator is None:
        raise HTTPException(409, "原上报记录已不存在")
    authorize_patients(db, actor, [locator.patient_id])
    _, definition = definition_current(db, req.definition_id)
    if (definition.content_hash, definition.governance_hash) != (req.definition_content_hash, req.definition_governance_hash):
        raise HTTPException(409, "定义内容/发布治理锚已改变")
    row = current(db.query(InfectionCase).filter_by(case_id=req.case_id), shared=True).one()
    raw = original(row)
    if c.digest(raw) != req.original_content_hash:
        raise HTTPException(409, "完整原上报12列已改变")
    for field, codes in [("infection_type", definition.payload.infection_type_codes), ("pathogen", definition.payload.pathogen_codes)]:
        proposal = getattr(req, field)
        value = getattr(raw, field)
        if (proposal.original_state, proposal.original_value_hash) != (c.value_state(value), c.digest(value)) or proposal.reviewed_code is not None and proposal.reviewed_code not in codes:
            raise HTTPException(409, "原始分类文字/NULL空串/已审代码不一致")
    return raw


@atomic
def create_case_review(db, user, value):
    req = i.CaseReviewCreate.model_validate(value)
    actor = _start(db, user)
    raw = _review_parent(db, actor, req)
    exists = current(
        db.query(AIInfectionCaseReview.review_id).filter_by(
            case_id=req.case_id, original_content_hash=req.original_content_hash, definition_content_hash=req.definition_content_hash, definition_governance_hash=req.definition_governance_hash
        ),
        shared=True,
    ).first()
    if exists:
        raise HTTPException(409, "此原件与定义锚已有独立复核，不允许最后者获胜")
    rid = str(uuid.uuid4())
    payload = ReviewPayload(**req.model_dump(), review_id=rid, created_by=actor.user_id, recorded_at=utc(utcnow()))
    row = _create(
        db,
        actor,
        "review",
        rid,
        payload,
        case_id=req.case_id,
        patient_id=raw.patient_id,
        definition_id=req.definition_id,
        original_content_hash=req.original_content_hash,
        definition_content_hash=req.definition_content_hash,
        definition_governance_hash=req.definition_governance_hash,
    )
    _review_parent(db, actor, payload)
    return record(db, row, "review")


def detail(db, user, kind, rid):
    actor = _start(db, user)
    _authorize_record_patient(db, actor, kind, rid)
    row = _row(db, kind, rid, shared=True)
    if kind == "review":
        authorize_patients(db, actor, [row.patient_id])
    return record(db, row, kind)


def directory(db, user, kind, *, page=1, size=20):
    _start(db, user)
    if kind not in MODELS or type(page) is not int or page < 1 or type(size) is not int or not 1 <= size <= 100:
        raise HTTPException(422, "需要明确来源类型和完整分页参数")
    model = MODELS[kind]
    # Explicit columns, never ORM entities: no payload_json or basis TEXT.
    columns = [getattr(model, key) for key in (KEYS[kind], "content_hash", "status", "revision", "recorded_at", "create_event_id", "review_event_id", "revoke_event_id")]
    query = db.query(*columns)
    total = current(query.with_entities(func.count(getattr(model, KEYS[kind]))), shared=True).scalar()
    rows = current(query.order_by(model.recorded_at, getattr(model, KEYS[kind])), shared=True).offset((page - 1) * size).limit(size).all()
    return {
        "schema_version": "infection_registry_directory_v1",
        "kind": kind,
        "items": [
            {
                "record_id": row[0],
                "content_hash": row.content_hash,
                "status": row.status,
                "revision": row.revision,
                "recorded_at": utc(row.recorded_at),
                "create_event_id": row.create_event_id,
                "review_event_id": row.review_event_id,
                "revoke_event_id": row.revoke_event_id,
                "detail_required": True,
            }
            for row in rows
        ],
        "total": total,
        "page": page,
        "size": size,
        "clinical_parts_available_in_directory": False,
    }
