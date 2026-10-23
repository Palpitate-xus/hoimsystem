"""76-specific scope selection after full project/patient-purpose authority."""

from fastapi import HTTPException
from pydantic import TypeAdapter, ValidationError
from sqlalchemy import inspect

from app.ai.research_cohort_contract import UUID
from app.ai.research_cohort_models import AIResearchStudyScope
from app.ai.research_cohort_registry import authorize_project_acl
from app.ai.research_cohort_write_guard import current_actor, current_research_rows, lock_research_write
from app.ai.research_variables_authority import authorize_variable_scope
from app.ai.research_variables_fields import VARIABLE_SOURCE_ROLES


def _original_subject(user):
    state = inspect(user, raiseerr=False)
    return tuple((key, state.dict[key]) for key in ("username", "user_role", "token_invalid_before") if state is not None and key in state.dict)


def _same_subject(actor, original):
    if any(getattr(actor, key) != value for key, value in original):
        raise HTTPException(403, "原登录身份已变化，请重新读取授权变量项目")


def scope_context(db, user, identifier):
    """Resolve an explicit scope; no clinical rows, capture or outbound grant.

    Existing74 public registry/role contracts are unchanged. This separate76
    reader requires the caller's actual ACL and every declared patient's current
    variable-purpose permission, including Super, before exposing declarations.
    """
    try:
        TypeAdapter(UUID).validate_python(identifier, strict=True)
    except ValidationError as exc:
        raise HTTPException(422, "须提供规范的明确科研项目标识") from exc
    original = _original_subject(user)
    actor = lock_research_write(db, user, allowed_roles=VARIABLE_SOURCE_ROLES)
    _same_subject(actor, original)
    with db.no_autoflush:
        found = current_research_rows(db.query(AIResearchStudyScope.scope_id).filter_by(scope_id=identifier), shared=True).scalar()
    if found is None:
        raise HTTPException(404, "明确科研项目不存在")
    actor, locator = authorize_project_acl(db, actor, identifier)
    declared = locator["parent_binding"]["scope"]
    reference = {"scope_id": identifier, "scope_content_hash": declared["content_hash"], "scope_governance_hash": declared["governance_hash"]}
    actor, scope, acl, _ = authorize_variable_scope(db, actor, reference)
    if scope != declared or acl != locator:
        raise HTTPException(409, "项目声明或访问原件变化，请重新明确读取")
    actor = current_actor(db, actor, allowed_roles=VARIABLE_SOURCE_ROLES)
    _same_subject(actor, original)
    # The original reviewed proof supplies every value. No clinical fields or
    # separate Source governance command is added to this selection endpoint.
    return {
        **scope["identity"],
        "source_id": f"research_scope:{identifier}:{scope['content_hash'][:12]}",
        "content_hash": scope["content_hash"],
        **scope["governance"],
        **scope["authorization_review"],
        "governance_hash": scope["governance_hash"],
        "original": scope,
        "parent_current": True,
        "authorization_reviewer_current": True,
        "eligible": True,
        "exclusion_reasons": [],
        "can_record": False,
        "can_authorization_review": False,
        "can_review": False,
        "can_revoke": False,
        "audit_only": False,
        "eligibility_basis": "project_registry_only_not_patient_collection_permission",
    }
