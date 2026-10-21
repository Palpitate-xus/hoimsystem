"""75 project/purpose gate then Patient X before optional care-row SHARE.

No clinical text is selected here. This prevents a care/grant predicate from
holding a clinical row SHARE before later acquiring the Patient write lock.
"""

from fastapi import HTTPException

from app.ai.deidentification_contract import SOURCE_ROLES
from app.ai.research_cohort_registry import authorize_patient_research, authorize_project_acl
from app.ai.research_cohort_write_guard import lock_research_write


def authorize_subject(db, user, scope_id, patient_id, *, capture=False, external_model=False):
    actor = lock_research_write(db, user, allowed_roles=SOURCE_ROLES)
    actor, acl = authorize_project_acl(db, actor, scope_id, capture=capture)
    scope = acl["parent_binding"]["scope"]
    if "deidentification_review" not in scope["payload"]["permitted_uses"] or patient_id not in scope["payload"]["patient_ids"]:
        raise HTTPException(403, "当前项目未明确允许本患者的75审阅用途")
    if type(external_model) is not bool or external_model and scope["payload"]["external_model_use"] != "recorded_permitted":
        raise HTTPException(403, "原文模型出站许可未知或未允许")
    lock_research_write(db, actor, allowed_roles=SOURCE_ROLES, scope_ids=(scope_id,), patient_ids=(patient_id,))
    return authorize_patient_research(db, actor, scope_id, patient_id, capture=capture, use="deidentification_review", external_model=external_model)
