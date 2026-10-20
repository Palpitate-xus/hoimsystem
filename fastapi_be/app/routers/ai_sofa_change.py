"""Separate observed SOFA change review and Super governance of complete originals."""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.ai import sofa_change_sources as sources
from app.ai.risk_rule_profiles import actual_super, canonical_id
from app.ai.sofa_models import AISofaChangeAssessment
from app.ai.sofa_sources import ASSESSMENT_ROLES
from app.database import get_db
from app.dependencies import require_roles
from app.inpatient_support_common import commit_audit
from app.models import User
from app.routers.inpatient_support import QueryPositiveInteger

router = APIRouter(tags=["AI独立SOFA变化与感染归因核实"], default_response_class=JSONResponse)


def assessment_row(db, identifier):
    identifier = canonical_id(identifier)
    row = db.query(AISofaChangeAssessment).filter_by(change_assessment_id=identifier).populate_existing().one_or_none()
    if row is None:
        raise HTTPException(404, "完整SOFA原始临床核实不存在")
    return row


def scoped_row(db, actor, identifier, patient_id, admission_id):
    sources.authorize_scope(db, actor, patient_id, admission_id)
    row = assessment_row(db, identifier)
    if row.patient_id != patient_id or row.admission_id != admission_id:
        raise HTTPException(409, "完整SOFA来源不属于明确原患者及住院")
    return row


def detail(db, user, row, *, summary=False):
    actor = sources.actor_current(db, user)
    is_super = actor.user_role == "super_admin"
    if not is_super:
        sources.authorize_scope(db, actor, row.patient_id, row.admission_id)
    try:
        data = sources.change_detail(db, row, audit_only=is_super)
    except HTTPException as exc:
        if is_super or exc.status_code != 409:
            raise
        # Ordinary readers can see governance metadata, never stale private facts.
        data = {
            **sources.metadata(row),
            "snapshot": None,
            "specialist_source": None,
            "eligible": False,
            "exclusion_reasons": ["source_not_current"],
            "freshness": {"state": "revoked" if row.status == "revoked" else "stale"},
            "eligibility_basis": "source_and_rule_governance_not_clinical_applicability",
        }
    if not is_super:
        sources.authorize_scope(db, actor, row.patient_id, row.admission_id)
    data["can_revoke"] = row.status == "active" and (is_super or row.created_by == actor.user_id)
    if summary:
        data.pop("snapshot", None)
        data.pop("specialist_source", None)
    return data


def listing(db, actor, patient_id, admission_id, status, page, page_size):
    query = db.query(AISofaChangeAssessment)
    if patient_id is not None:
        query = query.filter_by(patient_id=patient_id)
    if admission_id is not None:
        query = query.filter_by(admission_id=canonical_id(admission_id))
    if status is not None:
        query = query.filter_by(status=status)
    total = query.count()
    rows = query.order_by(AISofaChangeAssessment.created_at.desc(), AISofaChangeAssessment.change_assessment_id).offset((page - 1) * page_size).limit(page_size).all()
    return {"items": [detail(db, actor, row, summary=True) for row in rows], "total": total, "page": page, "page_size": page_size}


@router.post("/ai/sofa-change-assessments/candidates")
def candidates(req: sources.ChangeCandidatesRequest, db: Session = Depends(get_db), user: User = Depends(require_roles(*ASSESSMENT_ROLES))):
    actor = sources.actor_current(db, user)
    data = sources.candidates(db, actor, req)
    sources.authorize_scope(db, actor, req.patient_id, req.admission_id)
    return {"code": 200, "data": data}


@router.get("/ai/sofa-change-assessments")
def assessments(
    patient_id: QueryPositiveInteger = Query(ge=1, le=2147483647),
    admission_id: str = Query(min_length=36, max_length=36),
    status: Literal["active", "revoked"] | None = None,
    page: QueryPositiveInteger = Query(1, ge=1),
    page_size: QueryPositiveInteger = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*ASSESSMENT_ROLES)),
):
    actor = sources.actor_current(db, user)
    sources.authorize_scope(db, actor, patient_id, admission_id)
    data = listing(db, actor, patient_id, admission_id, status, page, page_size)
    sources.authorize_scope(db, actor, patient_id, admission_id)
    return {"code": 200, "data": data}


@router.post("/ai/sofa-change-assessments")
def create(req: sources.ChangeCreate, db: Session = Depends(get_db), user: User = Depends(require_roles(*ASSESSMENT_ROLES))):
    try:
        row = sources.create_change_assessment(db, user, req)
        actor = sources.actor_current(db, user)
        sources.authorize_scope(db, actor, row.patient_id, row.admission_id)
        # Materialize the validated response before committing source and audit together.
        db.flush()
        data = detail(db, actor, row)
        commit_audit(
            db,
            actor,
            "sofa_change_assessment.create",
            row.change_assessment_id,
            {
                "content_hash": row.content_hash,
                "projection_hash": row.projection_hash,
                "current_assessment_id": row.current_assessment_id,
                "baseline_assessment_id": row.baseline_assessment_id,
                "infection_source_id": row.infection_source_id,
            },
        )
        return {"code": 200, "data": data}
    except Exception:
        db.rollback()
        raise


@router.get("/ai/sofa-change-assessments/{change_assessment_id}")
def assessment(
    change_assessment_id: str,
    patient_id: QueryPositiveInteger = Query(ge=1, le=2147483647),
    admission_id: str = Query(min_length=36, max_length=36),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*ASSESSMENT_ROLES)),
):
    actor = sources.actor_current(db, user)
    return {"code": 200, "data": detail(db, actor, scoped_row(db, actor, change_assessment_id, patient_id, admission_id))}


@router.post("/ai/sofa-change-assessments/{change_assessment_id}/revoke")
def revoke(change_assessment_id: str, req: sources.ChangeRevoke, db: Session = Depends(get_db), user: User = Depends(require_roles(*ASSESSMENT_ROLES))):
    try:
        actor = sources.actor_current(db, user)
        row = assessment_row(db, change_assessment_id) if actor.user_role == "super_admin" else scoped_row(db, actor, change_assessment_id, req.patient_id, req.admission_id)
        if row.patient_id != req.patient_id or row.admission_id != req.admission_id:
            raise HTTPException(409, "撤销请求不属于冻结原患者及住院")
        row = sources.revoke_change(db, actor, row, req.expected_revision, req.reason)
        data = detail(db, actor, row)
        commit_audit(
            db,
            actor,
            "sofa_change_assessment.revoke",
            row.change_assessment_id,
            {"content_hash": row.content_hash, "expected_revision": req.expected_revision, "revision": row.revision, "reason": req.reason},
        )
        return {"code": 200, "data": data}
    except Exception:
        db.rollback()
        raise


@router.get("/ai/admin/sofa-change-assessments")
def admin_assessments(
    patient_id: QueryPositiveInteger | None = Query(None, ge=1, le=2147483647),
    admission_id: str | None = Query(None, min_length=36, max_length=36),
    status: Literal["active", "revoked"] | None = None,
    page: QueryPositiveInteger = Query(1, ge=1),
    page_size: QueryPositiveInteger = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("super_admin")),
):
    return {"code": 200, "data": listing(db, actual_super(db, user), patient_id, admission_id, status, page, page_size)}


@router.get("/ai/admin/sofa-change-assessments/{change_assessment_id}")
def admin_assessment(change_assessment_id: str, db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin"))):
    return {"code": 200, "data": detail(db, actual_super(db, user), assessment_row(db, change_assessment_id))}
