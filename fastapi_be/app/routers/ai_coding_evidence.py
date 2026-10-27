"""Authorized current coding evidence and independent local-prefix governance."""

from types import SimpleNamespace

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.ai import coding_evidence_sources as s
from app.ai.coding_evidence_guard import current_coding_rows
from app.ai.coding_evidence_input import SOURCE_ROLES, CaptureRequest, CaseCreate, RulePackageCreate, SourceReview, SourceRevoke
from app.ai.coding_evidence_models import AICodingCaseSnapshot, AICodingRulePackage
from app.database import get_db
from app.dependencies import User, require_roles
from app.models import DrgRule, MedicalRecordHome
from app.sql_counts import locked_row_count

router = APIRouter(prefix="/ai/coding-evidence", default_response_class=JSONResponse)


def response(data):
    return {"code": 200, "msg": "success", "data": data}


def run_mutation(db, callback):
    try:
        value = callback()
        db.commit()
        return response(value)
    except BaseException:
        db.rollback()
        raise


def directory(db, model, query, page, page_size):
    primary = model.case_snapshot_id if model is AICodingCaseSnapshot else model.package_id
    count = locked_row_count(current_coding_rows(query, shared=True), primary)
    identifiers = [x[0] for x in current_coding_rows(query.with_entities(primary).order_by(model.created_at.desc(), primary), shared=True).offset((page - 1) * page_size).limit(page_size).all()]
    fields = (*s.IDENTITY, *s.GOVERNANCE, "content_hash") if model is AICodingCaseSnapshot else (*s.PACKAGE_IDENTITY, *s.GOVERNANCE, "content_hash")
    result = []
    for identifier in identifiers:
        raw = current_coding_rows(db.query(*(getattr(model, k) for k in fields)).filter(primary == identifier), shared=True).one()
        # Full private JSON never loads for a metadata directory. Governance
        # notes are hashed into an opaque anchor, then omitted from the result.
        value = s.metadata(SimpleNamespace(**dict(raw._mapping))) if model is AICodingCaseSnapshot else package_metadata(raw)
        result.append({k: v for k, v in value.items() if k not in {"review_basis_note", "revoke_reason"}})
    return {"items": result, "total": count, "page": page, "page_size": page_size, "detail_required": True}


def package_metadata(row):
    value = {k: s.json_value(v) for k, v in row._mapping.items()}
    value["created_at"] = s.utc_text(row.created_at)
    for key in ("reviewed_at", "revoked_at"):
        value[key] = s.utc_text(getattr(row, key)) if getattr(row, key) is not None else None
    value["source_id"] = "coding_package:" + row.package_id + ":" + row.content_hash[:12]
    value["governance_hash"] = s.hash_content({k: value[k] for k in s.GOVERNANCE})
    return value


@router.get("/options")
def options(current_user: User = Depends(require_roles(*SOURCE_ROLES)), db: Session = Depends(get_db)):
    actor = s.current_actor(db, current_user)
    return response(
        {
            "scope": "one_actual_home_and_admission",
            "can_record": True,
            "can_review": actor.user_role == "super_admin",
            "can_manage_rule_packages": actor.user_role == "super_admin",
            "professional_qualification": "not_provided",
            "official_grouper": "not_provided",
            "historical_capture_supported": False,
            "case_rows_require_patient_and_admission": True,
            "max_bindings": 4096,
            "max_groups": 256,
            "max_linked_rules": 4096,
            "max_bytes": 8388608,
        }
    )


@router.get("/homes")
def homes(patient_id: int, admission_id: str, current_user: User = Depends(require_roles(*SOURCE_ROLES)), db: Session = Depends(get_db)):
    actor, admission, _ = s.authorize_admission(db, current_user, patient_id, admission_id)
    rows = (
        current_coding_rows(
            db.query(MedicalRecordHome.home_id, MedicalRecordHome.patient_id, MedicalRecordHome.admission_id, MedicalRecordHome.status, MedicalRecordHome.update_time)
            .filter_by(patient_id=patient_id, admission_id=admission_id)
            .order_by(MedicalRecordHome.home_id),
            shared=True,
        )
        .limit(2)
        .all()
    )
    if len(rows) > 1:
        raise HTTPException(409, "同一真实住院出现多件首页，不自动择取")
    return response(
        {"items": [{k: s.json_value(v) for k, v in row._mapping.items()} for row in rows], "total": len(rows), "patient_id": patient_id, "admission_id": admission.admission_id, "can_record": True}
    )


@router.get("/rules")
def rules(page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100), current_user: User = Depends(require_roles("super_admin")), db: Session = Depends(get_db)):
    s.current_actor(db, current_user, {"super_admin"})
    query = db.query(DrgRule)
    total = locked_row_count(current_coding_rows(query, shared=True), DrgRule.rule_id)
    ids = [x[0] for x in current_coding_rows(query.with_entities(DrgRule.rule_id).order_by(DrgRule.rule_id), shared=True).offset((page - 1) * page_size).limit(page_size).all()]
    items = []
    for identifier in ids:
        row = current_coding_rows(db.query(DrgRule).filter_by(rule_id=identifier), shared=True).one()
        full = s.row_value(row)
        items.append(
            {
                **{
                    k: full[k]
                    for k in (
                        "rule_id",
                        "payment_method",
                        "group_code",
                        "group_name",
                        "diagnosis_prefix",
                        "procedure_prefix",
                        "priority",
                        "version",
                        "effective_from",
                        "effective_to",
                        "status",
                        "update_time",
                    )
                },
                "original_content_hash": s.hash_content(full),
                "rule_scope": "current_local_prefix_rule_not_official_grouper",
            }
        )
    return response({"items": items, "total": total, "page": page, "page_size": page_size, "official_rules_seeded": False})


@router.post("/cases/preview")
def preview(req: CaptureRequest, current_user: User = Depends(require_roles(*SOURCE_ROLES)), db: Session = Depends(get_db)):
    return response(s.capture_case(db, current_user, req))


@router.get("/cases")
def cases(
    patient_id: int | None = None,
    admission_id: str | None = None,
    home_id: str | None = None,
    audit_only: bool = False,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: User = Depends(require_roles(*SOURCE_ROLES)),
    db: Session = Depends(get_db),
):
    s.current_actor(db, current_user, {"super_admin"} if audit_only else s.SOURCE_ROLES)
    if not audit_only:
        if patient_id is None or admission_id is None:
            raise HTTPException(422, "普通目录必须明确真实患者和住院")
        s.authorize_admission(db, current_user, patient_id, admission_id)
    query = db.query(AICodingCaseSnapshot)
    for key, value in [("patient_id", patient_id), ("admission_id", admission_id), ("home_id", home_id)]:
        if value is not None:
            query = query.filter(getattr(AICodingCaseSnapshot, key) == value)
    return response(directory(db, AICodingCaseSnapshot, query, page, page_size))


@router.post("/cases")
def create(req: CaseCreate, current_user: User = Depends(require_roles(*SOURCE_ROLES)), db: Session = Depends(get_db)):
    def callback():
        row = s.create_case(db, current_user, req)
        return s.case_current(db, current_user, row.case_snapshot_id, audit_only=False)

    return run_mutation(db, callback)


@router.get("/cases/{identifier}")
def detail(identifier: str, audit_only: bool = False, current_user: User = Depends(require_roles(*SOURCE_ROLES)), db: Session = Depends(get_db)):
    return response(s.case_current(db, current_user, identifier, audit_only=audit_only))


@router.post("/cases/{identifier}/review")
def review_case(identifier: str, req: SourceReview, current_user: User = Depends(require_roles("super_admin")), db: Session = Depends(get_db)):
    def callback():
        s.review(db, current_user, "case", identifier, req)
        return s.case_current(db, current_user, identifier, audit_only=True)

    return run_mutation(db, callback)


@router.post("/cases/{identifier}/revoke")
def revoke_case(identifier: str, req: SourceRevoke, current_user: User = Depends(require_roles(*SOURCE_ROLES)), db: Session = Depends(get_db)):
    def callback():
        s.review(db, current_user, "case", identifier, req, revoke=True)
        actor = s.current_actor(db, current_user)
        return s.case_current(db, actor, identifier, audit_only=actor.user_role == "super_admin")

    return run_mutation(db, callback)


@router.get("/packages")
def packages(audit_only: bool = False, page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100), current_user: User = Depends(require_roles(*SOURCE_ROLES)), db: Session = Depends(get_db)):
    s.current_actor(db, current_user, {"super_admin"} if audit_only else s.SOURCE_ROLES)
    query = db.query(AICodingRulePackage)
    if not audit_only:
        query = query.filter(AICodingRulePackage.status == "published")
    return response(directory(db, AICodingRulePackage, query, page, page_size))


@router.post("/packages")
def create_package(req: RulePackageCreate, current_user: User = Depends(require_roles("super_admin")), db: Session = Depends(get_db)):
    def callback():
        row = s.create_package(db, current_user, req)
        return s.package_current(db, current_user, row.package_id, audit_only=True)

    return run_mutation(db, callback)


@router.get("/packages/{identifier}")
def package(identifier: str, audit_only: bool = False, current_user: User = Depends(require_roles(*SOURCE_ROLES)), db: Session = Depends(get_db)):
    return response(s.package_current(db, current_user, identifier, audit_only=audit_only))


@router.post("/packages/{identifier}/review")
def review_package(identifier: str, req: SourceReview, current_user: User = Depends(require_roles("super_admin")), db: Session = Depends(get_db)):
    def callback():
        s.review(db, current_user, "package", identifier, req)
        return s.package_current(db, current_user, identifier, audit_only=True)

    return run_mutation(db, callback)


@router.post("/packages/{identifier}/revoke")
def revoke_package(identifier: str, req: SourceRevoke, current_user: User = Depends(require_roles("super_admin")), db: Session = Depends(get_db)):
    def callback():
        s.review(db, current_user, "package", identifier, req, revoke=True)
        return s.package_current(db, current_user, identifier, audit_only=True)

    return run_mutation(db, callback)
