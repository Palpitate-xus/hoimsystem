"""Explicit clinical originals and Super governance through fixed domain definitions."""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic_core import core_schema
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import require_roles
from app.inpatient_observations import canonical_uuid
from app.inpatient_support_common import (
    SUPPORT_ROLES,
    SourceCreate,
    SourceKind,
    SourceRevoke,
    authorize_scope,
    can_record,
    commit_audit,
    create_source,
    current_actor,
    definition,
    definitions,
    revoke_source,
    row_by_id,
    source_current,
)
from app.models import User

router = APIRouter(tags=["原住院器官支持资料"], default_response_class=JSONResponse)
LABELS = {"map": "原MAP测量", "respiratory_support": "实际呼吸支持区间", "arterial_pair": "血气与FiO₂明确配对", "vasoactive": "实际连续给药区段", "infection_episode": "医生感染发作核实"}


def canonical_query_integer(value):
    if type(value) is int:
        return value
    if not isinstance(value, str) or not value or len(value) > 10 or not value.isascii() or not value.isdigit() or value[0] == "0":
        raise ValueError("查询整数须为规范正整数字符，不接受布尔、浮点或指数词法")
    return int(value)


class QueryPositiveInteger(int):
    @classmethod
    def __get_pydantic_core_schema__(cls, source_type, handler):
        # FastAPI rebuilds Query fields and drops alias Annotated metadata; keep
        # raw lexical validation on the actual scalar type's core schema.
        return core_schema.no_info_before_validator_function(canonical_query_integer, core_schema.int_schema())


def actual_super(db, user):
    actor = current_actor(db, user)
    if actor.user_role != "super_admin":
        raise HTTPException(403, "仅超级管理员可全院管理原器官支持资料")
    return actor


def detail(db, user, kind, row):
    actor = current_actor(db, user)
    if actor.user_role != "super_admin":
        authorize_scope(db, actor, row.patient_id, row.admission_id)
    source = source_current(db, row, kind, allow_revoked=True, audit_only=actor.user_role == "super_admin")
    return {
        **source,
        "can_record": can_record(db, actor, row.patient_id, row.admission_id, definition(kind)),
        "can_revoke": row.status == "active" and (actor.user_role == "super_admin" or row.created_by == actor.user_id),
    }


def listing(db, actor, kind, patient_id, admission_id, status, page, page_size):
    spec = definition(kind)
    query = db.query(spec.model)
    if patient_id is not None:
        query = query.filter_by(patient_id=patient_id)
    if admission_id is not None:
        try:
            canonical_uuid(admission_id)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        query = query.filter_by(admission_id=admission_id)
    if status is not None:
        query = query.filter_by(status=status)
    total = query.count()
    rows = query.order_by(spec.model.recorded_at.desc(), spec.model.support_source_id).offset((page - 1) * page_size).limit(page_size).all()
    return {"items": [detail(db, actor, kind, row) for row in rows], "total": total, "page": page, "page_size": page_size}


@router.get("/inpatient-support/options")
def source_options(
    patient_id: QueryPositiveInteger = Query(ge=1, le=2147483647),
    admission_id: str = Query(min_length=36, max_length=36),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*SUPPORT_ROLES)),
):
    actor = authorize_scope(db, user, patient_id, admission_id)
    items = [{"kind": kind, "label": LABELS[kind], "schema_version": spec.schema_version, "can_record": can_record(db, actor, patient_id, admission_id, spec)} for kind, spec in definitions().items()]
    authorize_scope(db, actor, patient_id, admission_id)
    return {"code": 200, "data": {"kinds": items, "clinical_mappings_seeded": False, "scope_note": "原始资料和医生明确核实；未提供完整SOFA、脓毒症诊断、概率或自动治疗。原缺项和实际登记时刻保留。"}}


@router.get("/inpatient-support/infection-evidence")
def infection_evidence(
    patient_id: QueryPositiveInteger = Query(ge=1, le=2147483647),
    admission_id: str = Query(min_length=36, max_length=36),
    kind: Literal["lab_source", "diagnosis_review"] = "lab_source",
    page: QueryPositiveInteger = Query(1, ge=1),
    page_size: QueryPositiveInteger = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*SUPPORT_ROLES)),
):
    from app.inpatient_infection_episodes import evidence_candidates

    actor = authorize_scope(db, user, patient_id, admission_id)
    data = evidence_candidates(db, patient_id, admission_id, kind, page, page_size)
    authorize_scope(db, actor, patient_id, admission_id)
    return {"code": 200, "data": data}


@router.get("/inpatient-support/vasoactive/origin-candidates")
def vasoactive_origins(
    patient_id: QueryPositiveInteger = Query(ge=1, le=2147483647),
    admission_id: str = Query(min_length=36, max_length=36),
    mapping_id: str | None = Query(None, min_length=36, max_length=36),
    page: QueryPositiveInteger = Query(1, ge=1),
    page_size: QueryPositiveInteger = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*SUPPORT_ROLES)),
):
    from app.inpatient_vasoactive import origin_candidates

    actor = authorize_scope(db, user, patient_id, admission_id)
    data = origin_candidates(db, patient_id, admission_id, mapping_id, page, page_size)
    authorize_scope(db, actor, patient_id, admission_id)
    return {"code": 200, "data": data}


@router.get("/inpatient-support/vasoactive/mapping-candidates")
def vasoactive_mappings(
    patient_id: QueryPositiveInteger = Query(ge=1, le=2147483647),
    admission_id: str = Query(min_length=36, max_length=36),
    page: QueryPositiveInteger = Query(1, ge=1),
    page_size: QueryPositiveInteger = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*SUPPORT_ROLES)),
):
    from app.inpatient_vasoactive import mapping_current
    from app.inpatient_vasoactive_models import AIVasoactiveDrugMapping

    actor = authorize_scope(db, user, patient_id, admission_id)
    query = db.query(AIVasoactiveDrugMapping).filter_by(status="published").order_by(AIVasoactiveDrugMapping.created_at.desc(), AIVasoactiveDrugMapping.mapping_id)
    total = query.count()
    items = []
    for row in query.offset((page - 1) * page_size).limit(page_size).all():
        try:
            items.append({**mapping_current(db, row.mapping_id), "eligible": True})
        except HTTPException:
            items.append({"mapping_id": row.mapping_id, "eligible": False, "exclusion_reasons": ["mapping_original_not_current"]})
    authorize_scope(db, actor, patient_id, admission_id)
    return {"code": 200, "data": {"items": items, "total": total, "page": page, "page_size": page_size}}


@router.get("/inpatient-support/{kind}")
def sources(
    kind: SourceKind,
    patient_id: QueryPositiveInteger = Query(ge=1, le=2147483647),
    admission_id: str = Query(min_length=36, max_length=36),
    status: Literal["active", "revoked"] | None = None,
    page: QueryPositiveInteger = Query(1, ge=1),
    page_size: QueryPositiveInteger = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*SUPPORT_ROLES)),
):
    actor = authorize_scope(db, user, patient_id, admission_id)
    data = {**listing(db, actor, kind, patient_id, admission_id, status, page, page_size), "can_record": can_record(db, actor, patient_id, admission_id, definition(kind))}
    authorize_scope(db, actor, patient_id, admission_id)
    return {"code": 200, "data": data}


@router.post("/inpatient-support/{kind}")
def create(kind: SourceKind, values: SourceCreate, db: Session = Depends(get_db), user: User = Depends(require_roles(*SUPPORT_ROLES))):
    try:
        row = create_source(db, user, kind, values)
        actor = authorize_scope(db, user, values.patient_id, values.admission_id, creating=True, doctor_required=definition(kind).doctor_required)
        commit_audit(
            db, actor, "support_source.create", row.support_source_id, {"kind": kind, "content_hash": row.content_hash, "source_verification": "explicit_human_record_not_independently_verified"}
        )
        return {"code": 200, "data": detail(db, actor, kind, row)}
    except Exception:
        db.rollback()
        raise


@router.get("/inpatient-support/{kind}/{identifier}")
def source(
    kind: SourceKind,
    identifier: str,
    patient_id: QueryPositiveInteger = Query(ge=1, le=2147483647),
    admission_id: str = Query(min_length=36, max_length=36),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*SUPPORT_ROLES)),
):
    actor = authorize_scope(db, user, patient_id, admission_id)
    row = row_by_id(db, definition(kind), identifier)
    if row.patient_id != patient_id or row.admission_id != admission_id:
        raise HTTPException(409, "所选原支持资料不属于明确患者和原住院")
    data = detail(db, actor, kind, row)
    authorize_scope(db, actor, patient_id, admission_id)
    return {"code": 200, "data": data}


@router.post("/inpatient-support/{kind}/{identifier}/revoke")
def revoke(kind: SourceKind, identifier: str, values: SourceRevoke, db: Session = Depends(get_db), user: User = Depends(require_roles(*SUPPORT_ROLES))):
    try:
        actor, row = revoke_source(db, user, kind, identifier, values)
        actor = current_actor(db, actor)
        commit_audit(db, actor, "support_source.revoke", row.support_source_id, {"kind": kind, "expected_revision": values.expected_revision, "reason": values.reason})
        return {"code": 200, "data": detail(db, actor, kind, row)}
    except Exception:
        db.rollback()
        raise


@router.get("/ai/admin/support-sources/{kind}")
def admin_sources(
    kind: SourceKind,
    patient_id: QueryPositiveInteger | None = Query(None, ge=1, le=2147483647),
    admission_id: str | None = Query(None, min_length=36, max_length=36),
    status: Literal["active", "revoked"] | None = None,
    page: QueryPositiveInteger = Query(1, ge=1),
    page_size: QueryPositiveInteger = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("super_admin")),
):
    actor = actual_super(db, user)
    data = listing(db, actor, kind, patient_id, admission_id, status, page, page_size)
    actual_super(db, actor)
    return {"code": 200, "data": data}


@router.get("/ai/admin/support-sources/{kind}/{identifier}")
def admin_source(kind: SourceKind, identifier: str, db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin"))):
    actor = actual_super(db, user)
    row = row_by_id(db, definition(kind), identifier)
    data = detail(db, actor, kind, row)
    actual_super(db, actor)
    return {"code": 200, "data": data}
