"""Explicit AKI source roles and clinical attestations; missing facts remain unknown."""

import json
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.ai.aki_sources import (
    ASSESSMENT_ROLES,
    AssessmentCreate,
    AssessmentRevoke,
    LabReference,
    actor_current,
    assessment_current,
    authorize_scope,
    clinical_qualification,
    create_assessment,
    load_lab,
    metadata,
    window_binding,
)
from app.ai.governance import audit
from app.ai.models import AIAKIAssessment, AIRiskRuleProfile, utcnow
from app.ai.observation_windows import snapshot_current
from app.ai.risk_rule_profiles import actual_super, canonical_id, profile_current
from app.database import get_db
from app.dependencies import require_roles
from app.models import Admission, InpatientLabSource, User

router = APIRouter(tags=["AI明确AKI评估来源"], default_response_class=JSONResponse)


def commit(db):
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "AKI原资料或版本发生竞争，评估及审计均未覆盖") from exc


def assessment_row(db, identifier):
    canonical_id(identifier)
    row = db.query(AIAKIAssessment).filter_by(assessment_id=identifier).populate_existing().one_or_none()
    if row is None:
        raise HTTPException(404, "AKI原评估来源不存在")
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
        raise HTTPException(409, "AKI来源不属于本次原患者与住院")
    return row


def listing(db, user, patient_id, admission_id, status, page, page_size, window_id=None):
    query = db.query(AIAKIAssessment)
    if patient_id is not None:
        query = query.filter_by(patient_id=patient_id)
    if admission_id is not None:
        query = query.filter_by(admission_id=canonical_id(admission_id))
    if status is not None:
        query = query.filter_by(status=status)
    if window_id is not None:
        query = query.filter_by(window_id=canonical_id(window_id))
    total = query.count()
    rows = query.order_by(AIAKIAssessment.created_at.desc(), AIAKIAssessment.assessment_id).offset((page - 1) * page_size).limit(page_size).all()
    return {"items": [detail(db, user, row) for row in rows], "total": total, "page": page, "page_size": page_size}


@router.get("/ai/aki-assessments/candidates")
def candidates(
    patient_id: int = Query(ge=1, le=2147483647),
    admission_id: str = Query(min_length=36, max_length=36),
    window_id: str = Query(min_length=36, max_length=36),
    baseline_admission_id: str | None = None,
    baseline_page: int = Query(1, ge=1),
    baseline_page_size: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*ASSESSMENT_ROLES)),
):
    from app.ai.models import AILabMapping
    from app.inpatient_laboratory import source_current
    from app.inpatient_observations import explicit_utc

    actor = actor_current(db, user)
    authorize_scope(db, actor, patient_id, admission_id)
    window = snapshot_current(db, actor, window_id)
    if window["schema_version"] != "inpatient_window_v2" or window["patient_id"] != patient_id or window["admission_id"] != admission_id:
        raise HTTPException(409, "AKI候选须绑定当前原患者和住院的v2窗口")
    original_admission = canonical_id(baseline_admission_id) if baseline_admission_id is not None else admission_id
    authorize_scope(db, actor, patient_id, original_admission)
    admissions = []
    for row in db.query(Admission).filter_by(patient_id=patient_id).order_by(Admission.admission_id).all():
        try:
            authorize_scope(db, actor, patient_id, row.admission_id)
        except HTTPException:
            continue
        admissions.append({"admission_id": row.admission_id, "admission_no": row.admission_no, "status": row.status})
    cutoff = explicit_utc(window["as_of"])

    def source_view(row):
        return load_lab(db, actor, LabReference(lab_source_id=row.lab_source_id, expected_content_hash=row.content_hash), patient_id, cutoff)

    current = []
    for item in window["lab_observations"]:
        if item["eligible"] is True and item["status"] == "active" and item["snapshot"]["mapping"]["analyte_key"] == "creatinine":
            current.append(source_view(db.get(InpatientLabSource, item["lab_source_id"])))
    baseline = []
    rows = (
        db.query(InpatientLabSource)
        .join(AILabMapping, InpatientLabSource.mapping_id == AILabMapping.mapping_id)
        .filter(
            InpatientLabSource.patient_id == patient_id,
            InpatientLabSource.admission_id == original_admission,
            InpatientLabSource.status == "active",
            InpatientLabSource.registered_at <= cutoff,
            InpatientLabSource.available_at <= cutoff,
            AILabMapping.analyte_key == "creatinine",
        )
        .order_by(InpatientLabSource.collected_at_utc.desc(), InpatientLabSource.lab_source_id)
        .populate_existing()
        .all()
    )
    for row in rows:
        try:
            if source_current(db, row, allow_revoked=True)["eligible"]:
                baseline.append(source_view(row))
        except HTTPException:
            continue
    profiles = db.query(AIRiskRuleProfile).filter_by(status="published", rule_id="kdigo_aki_2012").order_by(AIRiskRuleProfile.created_at.desc(), AIRiskRuleProfile.rule_profile_id).all()
    weights = []
    for item in window["points"]:
        if item["status"] == "active" and "body_weight" in item["payload"]["measurements"]:
            weights.append(
                {
                    **item,
                    "conflict": any(
                        group["observed_at"] == item["observed_at"] and group["measurement_code"] == "body_weight" and group["state"] == "conflicting_values_or_missing_state"
                        for group in window["quality"]["same_time_groups"]
                    ),
                }
            )
    authorize_scope(db, actor, patient_id, admission_id)
    authorize_scope(db, actor, patient_id, original_admission)
    offset = (baseline_page - 1) * baseline_page_size
    return {
        "code": 200,
        "data": {
            "window": {**window_binding(window), "patient_id": patient_id, "admission_id": admission_id},
            "creatinine_sources": current,
            "baseline_sources": baseline[offset : offset + baseline_page_size],
            "baseline_admissions": admissions,
            "baseline_admission_id": original_admission,
            "baseline_page": baseline_page,
            "baseline_page_size": baseline_page_size,
            "baseline_total": len(baseline),
            "weight_points": weights,
            "urine_intervals": [item for item in window["urine_intervals"] if item["status"] == "active"],
            "rule_profiles": [profile_current(db, row.rule_profile_id) for row in profiles],
            "can_sign_clinical": clinical_qualification(db, actor, patient_id, admission_id) is not None,
            "quality": window["quality"],
            "scope_note": "仅明确所选原窗口及另获授权原住院的真实登记来源；未默认选择基线、最近体重或尿量，候选和项目分类不是临床适用性验证。",
        },
    }


@router.get("/ai/aki-assessments")
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


@router.post("/ai/aki-assessments")
def post_assessment(req: AssessmentCreate, db: Session = Depends(get_db), user: User = Depends(require_roles(*ASSESSMENT_ROLES))):
    row = create_assessment(db, user, req)
    authorize_scope(db, user, row.patient_id, row.admission_id)
    audit(
        db,
        user.user_id,
        "aki_assessment.create",
        row.assessment_id,
        {
            "content_hash": row.content_hash,
            "window_content_hash": row.window_content_hash,
            "rule_profile_content_hash": row.rule_profile_content_hash,
            "recipe_digest": row.recipe_digest,
        },
    )
    commit(db)
    return {"code": 200, "msg": "已冻结明确检验、体重、尿量原引用与人工声明；未改变功能开关或临床验证", "data": detail(db, user, row)}


@router.get("/ai/aki-assessments/{assessment_id}")
def get_assessment(
    assessment_id: str,
    patient_id: int = Query(ge=1, le=2147483647),
    admission_id: str = Query(min_length=36, max_length=36),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*ASSESSMENT_ROLES)),
):
    return {"code": 200, "data": detail(db, user, scoped_row(db, user, assessment_id, patient_id, admission_id))}


@router.post("/ai/aki-assessments/{assessment_id}/revoke")
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
        db.query(AIAKIAssessment)
        .filter_by(assessment_id=assessment_id, status="active", revision=req.expected_revision)
        .update({"status": "revoked", "revision": 2, "revoked_at": utcnow(), "revoked_by": actor.user_id, "revoke_reason": req.reason}, synchronize_session=False)
    )
    if count != 1:
        db.rollback()
        raise HTTPException(409, "来源发生并发撤销，请刷新")
    audit(db, actor.user_id, "aki_assessment.revoke", assessment_id, {"content_hash": row.content_hash, "revision": 2})
    commit(db)
    return {"code": 200, "data": detail(db, actor, assessment_row(db, assessment_id))}


@router.get("/ai/admin/aki-assessments")
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


@router.get("/ai/admin/aki-assessments/{assessment_id}")
def admin_assessment(assessment_id: str, db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin"))):
    user = actual_super(db, user)
    return {"code": 200, "data": detail(db, user, assessment_row(db, assessment_id))}
