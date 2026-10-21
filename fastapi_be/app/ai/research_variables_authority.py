"""Current76 project/patient authority before any dictionary or clinical body."""

from fastapi import HTTPException

from app.ai.research_cohort_contract import ScopeReference
from app.ai.research_cohort_registry import authorize_patient_research, authorize_project_acl
from app.ai.research_cohort_sources import _typed, scope_proof, scope_row
from app.ai.research_cohort_write_guard import current_actor, lock_research_write
from app.ai.research_variables_contract import DictionaryCreate
from app.ai.research_variables_fields import VARIABLE_USE


def authorize_variable_scope(db, user, values, *, patient_ids=None, capture=False, external_model=False):
    """A locator, role, prior74/75 grant or technical publication grants none.

    Authorize the entire explicit finite member set, take canonical parents,
    then repeat each original proof. This function reads registry declarations
    and opaque clinical parent IDs only. Callers retain the same transaction.
    """
    request = _typed(ScopeReference, values)
    if type(capture) is not bool or type(external_model) is not bool:
        raise HTTPException(422, "明确捕获和模型处理开关须为布尔值")
    actor = lock_research_write(db, user)
    original_epoch = (actor.user_id, actor.user_role, actor.token_invalid_before)
    actor, acl = authorize_project_acl(db, actor, request.scope_id, capture=capture)
    scope = acl["parent_binding"]["scope"]
    if (scope["content_hash"], scope["governance_hash"]) != (request.scope_content_hash, request.scope_governance_hash):
        raise HTTPException(409, "变量抽取项目三锚已变化，未自动采用当前项目")
    if VARIABLE_USE not in scope["payload"]["permitted_uses"]:
        raise HTTPException(403, "项目未明确允许科研变量抽取，其他研究用途不能代授")
    declared = scope["payload"]["patient_ids"]
    if patient_ids is None:
        selected = list(declared)
    else:
        if type(patient_ids) is not list or not 1 <= len(patient_ids) <= 256 or any(type(p) is not int or p <= 0 for p in patient_ids):
            raise HTTPException(422, "变量批次须明确有限的原患者标识集合")
        if patient_ids != sorted(set(patient_ids)):
            raise HTTPException(422, "批次患者集合须有序且无重复，未静默合并")
        if not set(patient_ids).issubset(declared):
            raise HTTPException(403, "变量批次不能扩展原项目患者集合")
        selected = list(patient_ids)
    permissions = []
    for patient_id in selected:
        actor, fresh_acl, permission = authorize_patient_research(db, actor, request.scope_id, patient_id, capture=capture, use=VARIABLE_USE, external_model=external_model)
        if fresh_acl != acl:
            raise HTTPException(409, "完整变量批次逐患者核验期间项目访问原件变化")
        permissions.append(permission)
    actor = lock_research_write(db, actor, scope_ids=(request.scope_id,), patient_ids=selected)
    if scope_proof(scope_row(db, request.scope_id)) != scope:
        raise HTTPException(409, "变量项目在当前父锁后变化")
    for index, patient_id in enumerate(selected):
        actor, fresh_acl, fresh_permission = authorize_patient_research(db, actor, request.scope_id, patient_id, capture=capture, use=VARIABLE_USE, external_model=external_model)
        if fresh_acl != acl or fresh_permission != permissions[index]:
            raise HTTPException(409, "变量批次当前父锁后逐患者研究授权变化")
    actor = current_actor(db, actor)
    if (actor.user_id, actor.user_role, actor.token_invalid_before) != original_epoch:
        raise HTTPException(403, "变量来源操作原请求角色或登录授权已变化")
    return actor, scope, acl, permissions


def validate_dictionary_scope(values, scope):
    """Validate a supplied full dictionary against a separately current proof."""
    request = _typed(DictionaryCreate, values)
    if (request.scope_id, request.scope_content_hash, request.scope_governance_hash) != (scope["identity"]["scope_id"], scope["content_hash"], scope["governance_hash"]):
        raise HTTPException(409, "变量字典原项目三锚不匹配")
    payload = scope["payload"]
    if VARIABLE_USE not in payload["permitted_uses"]:
        raise HTTPException(403, "变量字典需要项目明确的变量抽取用途")
    window = payload["record_window"]
    for variable in request.variables:
        if variable.family not in payload["data_families"]:
            raise HTTPException(403, "变量字典不能扩展项目声明的记录族")
        if variable.record_window is not None and not (window["date_from"] <= variable.record_window.date_from <= variable.record_window.date_to <= window["date_to"]):
            raise HTTPException(403, "变量各自时间窗须完全位于项目明确时间窗内")
    return request
