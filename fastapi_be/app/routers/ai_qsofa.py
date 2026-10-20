"""Explicit qSOFA point/applicability sources; governance does not manufacture complete measurements."""

import json
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.ai.governance import audit
from app.ai.models import AIQsofaAssessment, AIRiskRuleProfile, utcnow
from app.ai.observation_windows import snapshot_current
from app.ai.qsofa_sources import (
    ASSESSMENT_ROLES,
    AssessmentCreate,
    AssessmentRevoke,
    actor_current,
    assessment_current,
    authorize_scope,
    clinical_qualification,
    create_assessment,
    gcs_group,
    metadata,
    window_binding,
)
from app.ai.risk_rule_profiles import actual_super, canonical_id, profile_current
from app.database import get_db
from app.dependencies import require_roles
from app.models import User

router = APIRouter(tags=["AI明确qSOFA评估来源"], default_response_class=JSONResponse)


def commit_audit(db, actor, action, target, detail):
    try:
        audit(db, actor.user_id, action, target, detail)
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "qSOFA原资料或版本发生竞争，评估及审计均未覆盖") from exc
    except Exception:
        db.rollback()
        raise


def assessment_row(db, identifier):
    canonical_id(identifier)
    row = db.query(AIQsofaAssessment).filter_by(assessment_id=identifier).populate_existing().one_or_none()
    if row is None:
        raise HTTPException(404, "qSOFA原评估来源不存在")
    return row


def detail(db, user, row):
    actor = actor_current(db, user)
    if actor.user_role != "super_admin":
        authorize_scope(db, actor, row.patient_id, row.admission_id)
    data = {
        **metadata(row),
        "snapshot": None,
        "specialist_source": None,
        "eligible": False,
        "exclusion_reasons": ["source_not_current"],
        "freshness": {"state": "revoked" if row.status == "revoked" else "stale"},
        "eligibility_basis": "source_and_rule_governance_not_clinical_applicability",
    }
    try:
        data.update(assessment_current(db, row, allow_revoked=True, user=actor))
        if not data["eligible"] and actor.user_role != "super_admin":
            data["snapshot"] = data["specialist_source"] = None
    except HTTPException:
        if actor.user_role == "super_admin":
            try:
                data["snapshot"] = json.loads(row.snapshot_json)
            except (ValueError, TypeError, RecursionError):
                pass
    if actor.user_role != "super_admin":
        authorize_scope(db, actor, row.patient_id, row.admission_id)
    return {**data, "can_revoke": row.status == "active" and (actor.user_role == "super_admin" or row.created_by == actor.user_id)}


def scoped_row(db, user, identifier, patient_id, admission_id):
    authorize_scope(db, user, patient_id, admission_id)
    row = assessment_row(db, identifier)
    if row.patient_id != patient_id or row.admission_id != admission_id:
        raise HTTPException(409, "qSOFA来源不属于本次原患者与住院")
    return row


def listing(db, user, patient_id, admission_id, status, page, page_size, window_id=None):
    query = db.query(AIQsofaAssessment)
    if patient_id is not None:
        query = query.filter_by(patient_id=patient_id)
    if admission_id is not None:
        query = query.filter_by(admission_id=canonical_id(admission_id))
    if status is not None:
        query = query.filter_by(status=status)
    if window_id is not None:
        query = query.filter_by(window_id=canonical_id(window_id))
    total = query.count()
    rows = query.order_by(AIQsofaAssessment.created_at.desc(), AIQsofaAssessment.assessment_id).offset((page - 1) * page_size).limit(page_size).all()
    return {"items": [detail(db, user, row) for row in rows], "total": total, "page": page, "page_size": page_size}


@router.get("/ai/qsofa-assessments/candidates")
def candidates(
    patient_id: int = Query(ge=1, le=2147483647),
    admission_id: str = Query(min_length=36, max_length=36),
    window_id: str = Query(min_length=36, max_length=36),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*ASSESSMENT_ROLES)),
):
    from app.inpatient_observations import explicit_utc

    actor = actor_current(db, user)
    authorize_scope(db, actor, patient_id, admission_id)
    window = snapshot_current(db, actor, window_id)
    if window["patient_id"] != patient_id or window["admission_id"] != admission_id:
        raise HTTPException(409, "候选原窗口不属于当前患者及原住院")
    points = [item for item in window["points"] if item["status"] == "active"]
    gcs_items = []
    cutoff = explicit_utc(window["as_of"])
    for point in points:
        for item in gcs_group(db, point["observation_id"], cutoff):
            if item["status"] == "active" and item["anchor_current"] and explicit_utc(window["start_at"]) <= explicit_utc(item["observed_at"]) <= explicit_utc(window["end_at"]):
                gcs_items.append(item)
    profiles = db.query(AIRiskRuleProfile).filter_by(status="published", rule_id="qsofa_sepsis3_2016").order_by(AIRiskRuleProfile.created_at.desc(), AIRiskRuleProfile.rule_profile_id).all()
    authorize_scope(db, actor, patient_id, admission_id)
    return {
        "code": 200,
        "data": {
            "window": {**window_binding(window), "patient_id": patient_id, "admission_id": admission_id},
            "points": points,
            "gcs_observations": gcs_items,
            "rule_profiles": [profile_current(db, row.rule_profile_id) for row in profiles],
            "can_sign_clinical": clinical_qualification(db, actor, patient_id, admission_id) is not None,
            "quality": window["quality"],
            "scope_note": "当前回顾性医生核实原时点成人、实际非ICU及感染状态；声明在现在登记，不是历史预测，不作为单一脓毒症筛查、诊断或排除。",
        },
    }


@router.get("/ai/qsofa-assessments")
def assessments(
    patient_id: int = Query(ge=1, le=2147483647),
    admission_id: str = Query(min_length=36, max_length=36),
    status: Literal["active", "revoked"] | None = None,
    window_id: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*ASSESSMENT_ROLES)),
):
    authorize_scope(db, user, patient_id, admission_id)
    return {"code": 200, "data": listing(db, user, patient_id, admission_id, status, page, page_size, window_id)}


@router.post("/ai/qsofa-assessments")
def post_assessment(req: AssessmentCreate, db: Session = Depends(get_db), user: User = Depends(require_roles(*ASSESSMENT_ROLES))):
    row = create_assessment(db, user, req)
    actor = actor_current(db, user)
    authorize_scope(db, actor, row.patient_id, row.admission_id)
    commit_audit(
        db,
        actor,
        "qsofa_assessment.create",
        row.assessment_id,
        {
            "content_hash": row.content_hash,
            "window_content_hash": row.window_content_hash,
            "point_content_hash": row.point_content_hash,
            "rule_profile_content_hash": row.rule_profile_content_hash,
            "recipe_digest": row.recipe_digest,
        },
    )
    return {"code": 200, "msg": "已冻结当前回顾性临床核实与原床旁量；不是原截止时已知风险，未调用模型或改变临床验证", "data": detail(db, actor, row)}


@router.get("/ai/qsofa-assessments/{assessment_id}")
def get_assessment(
    assessment_id: str,
    patient_id: int = Query(ge=1, le=2147483647),
    admission_id: str = Query(min_length=36, max_length=36),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*ASSESSMENT_ROLES)),
):
    return {"code": 200, "data": detail(db, user, scoped_row(db, user, assessment_id, patient_id, admission_id))}


@router.post("/ai/qsofa-assessments/{assessment_id}/revoke")
def revoke_assessment(assessment_id: str, req: AssessmentRevoke, db: Session = Depends(get_db), user: User = Depends(require_roles(*ASSESSMENT_ROLES))):
    actor = actor_current(db, user)
    if actor.user_role == "super_admin":
        row = assessment_row(db, assessment_id)
        if row.patient_id != req.patient_id or row.admission_id != req.admission_id:
            raise HTTPException(409, "撤销请求不属于冻结原患者与住院")
    else:
        row = scoped_row(db, actor, assessment_id, req.patient_id, req.admission_id)
    if actor.user_role != "super_admin" and row.created_by != actor.user_id:
        raise HTTPException(403, "仅原评估人或超级管理员可撤销来源")
    if row.status != "active" or row.revision != req.expected_revision:
        raise HTTPException(409, "来源已撤销或版本改变，不可恢复")
    count = (
        db.query(AIQsofaAssessment)
        .filter_by(assessment_id=assessment_id, status="active", revision=req.expected_revision)
        .update({"status": "revoked", "revision": 2, "revoked_at": utcnow(), "revoked_by": actor.user_id, "revoke_reason": req.reason}, synchronize_session=False)
    )
    if count != 1:
        db.rollback()
        raise HTTPException(409, "来源发生并发撤销，请刷新")
    commit_audit(db, actor, "qsofa_assessment.revoke", assessment_id, {"content_hash": row.content_hash, "revision": 2})
    return {"code": 200, "data": detail(db, actor, assessment_row(db, assessment_id))}


@router.get("/ai/admin/qsofa-assessments")
def admin_assessments(
    patient_id: int | None = Query(None, ge=1, le=2147483647),
    admission_id: str | None = None,
    status: Literal["active", "revoked"] | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("super_admin")),
):
    user = actual_super(db, user)
    return {"code": 200, "data": listing(db, user, patient_id, admission_id, status, page, page_size)}


@router.get("/ai/admin/qsofa-assessments/{assessment_id}")
def admin_assessment(assessment_id: str, db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin"))):
    user = actual_super(db, user)
    return {"code": 200, "data": detail(db, user, assessment_row(db, assessment_id))}
