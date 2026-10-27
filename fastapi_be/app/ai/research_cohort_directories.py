"""Bounded technical registry references, not a clinical permission directory."""

from fastapi import HTTPException
from sqlalchemy import exists, or_

from app.ai.research_cohort_metadata import install_metadata_functions, registry_hash_expression
from app.ai.research_cohort_models import AIResearchPatientAuthorization, AIResearchProjectACL, AIResearchStudyScope
from app.ai.research_cohort_sources import _registry_authority, utc_text, utcnow
from app.ai.research_cohort_write_guard import current_research_rows, lock_research_write
from app.sql_counts import locked_row_count

COMMON = ("schema_version", "created_by", "created_at", "status", "revision", "reviewed_by", "reviewed_at", "revoked_by", "revoked_at", "valid_from", "valid_until", "content_hash")
MANUAL = ("authorization_review_status", "authorization_reviewed_by", "authorization_reviewed_at")


def list_registry(db, user, kind, *, scope_id=None, page=1, size=20):
    if type(page) is not int or not 1 <= page <= 100000 or type(size) is not int or not 1 <= size <= 100:
        raise HTTPException(422, "科研技术目录页码须为规范有界整数")
    actor = lock_research_write(db, user)
    if kind == "scope":
        model, pk, source_kind = AIResearchStudyScope, "scope_id", "study_scope"
        columns = ("scope_id", *COMMON, *MANUAL)
        if actor.user_role == "super_admin":
            where = []
        else:
            now = utcnow()
            candidate = exists().where(
                AIResearchProjectACL.scope_id == model.scope_id,
                AIResearchProjectACL.user_id == actor.user_id,
                AIResearchProjectACL.status == "published",
                AIResearchProjectACL.valid_from <= now,
                AIResearchProjectACL.valid_until > now,
            )
            where = [or_(model.created_by == actor.user_id, candidate)]
    else:
        if kind not in {"acl", "authorization"} or scope_id is None:
            raise HTTPException(422, "项目ACL/患者授权目录须明确scope_id")
        # Governance directory only. A recorded ACL supplies a narrow Scope
        # candidate header above, not a new permission to browse consent text.
        _registry_authority(db, actor, scope_id)
        model, pk, source_kind = (AIResearchProjectACL, "acl_id", "acl") if kind == "acl" else (AIResearchPatientAuthorization, "authorization_id", "authorization")
        columns = (pk, "scope_id", *COMMON, "user_id", "permission") if kind == "acl" else (pk, "scope_id", *COMMON, "patient_id", "authorization_kind", "access_basis", *MANUAL)
        where = [model.scope_id == scope_id]
    install_metadata_functions(db)
    total = locked_row_count(current_research_rows(db.query(model).filter(*where), shared=True), getattr(model, pk), aggregate=True)
    query = db.query(*(getattr(model, name) for name in columns), registry_hash_expression(model, manual=kind != "acl")).filter(*where).order_by(model.created_at.desc(), getattr(model, pk))
    rows = current_research_rows(query, shared=True).offset((page - 1) * size).limit(size).all()
    items = []
    for row in rows:
        item = {key: utc_text(value) if key.endswith("_at") or key in {"valid_from", "valid_until"} else value for key, value in row._mapping.items()}
        identifier = item[pk]
        item.update(source_kind=source_kind, source_record_id=identifier, source_id=f"research_{kind}:{identifier}:{item['content_hash'][:12]}", detail_required=True, candidate_reference_only=True)
        items.append(item)
    return {"items": items, "page": page, "size": size, "total": total}
