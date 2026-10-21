"""Opaque current locator and research authorization before any task body."""

import json
from types import SimpleNamespace

from fastapi import HTTPException
from sqlalchemy import inspect

from app.ai.deidentification_access import authorize_subject
from app.ai.deidentification_contract import SOURCE_ROLES
from app.ai.deidentification_run_models import AIDeidentificationRunSource
from app.ai.deidentification_sources import actor_now
from app.ai.research_cohort_write_guard import current_research_rows, lock_research_gate


def run_identifier(value):
    if type(value) is str:
        return value
    state = inspect(value, raiseerr=False)
    return state.identity[0] if state is not None and state.identity else getattr(value, "run_id", None)


def opaque_locator(db, run_id):
    """Gate before current SHARE; no UUID rejection of unrelated legacy IDs."""
    with db.no_autoflush:
        lock_research_gate(db)
        row = current_research_rows(
            db.query(
                AIDeidentificationRunSource.run_id,
                AIDeidentificationRunSource.case_id,
                AIDeidentificationRunSource.scope_id,
                AIDeidentificationRunSource.patient_id,
                AIDeidentificationRunSource.requested_by,
            ).filter_by(run_id=run_id),
            shared=True,
        ).one_or_none()
    return dict(row._mapping) if row is not None else None


def is_deidentification_run(db, run):
    if db is not None and opaque_locator(db, run_identifier(run)) is not None:
        return True
    state = inspect(run, raiseerr=False)
    loaded = state.dict if state is not None else getattr(run, "__dict__", {})
    if loaded.get("feature_key") == "deidentification":
        return True
    for field in ("input_json", "result_json"):
        try:
            value = json.loads(loaded.get(field, "{}"))
            if isinstance(value, dict) and (str(value.get("schema_version", "")).startswith("deidentification_") or "deidentification_case_id" in value or "deidentification_result" in value):
                return True
        except (ValueError, TypeError):
            pass
    return False


def role_configuration(db, actor):
    from app.ai.models import AIFeatureConfig

    config = current_research_rows(db.query(AIFeatureConfig).filter_by(feature_key="deidentification"), shared=True).one_or_none()
    try:
        roles = json.loads(config.allowed_roles_json) if config is not None else None
        if type(roles) is not list or not roles or any(type(role) is not str or role not in SOURCE_ROLES for role in roles) or len(set(roles)) != len(roles):
            raise ValueError("Explicit complete fixed-role intersection required")
    except (ValueError, TypeError) as exc:
        raise HTTPException(409, "75当前功能角色配置无效，未读取任务正文") from exc
    if actor.user_role not in roles:
        raise HTTPException(403, "75当前功能角色已撤回，未读取任务正文")
    return config, sorted(roles)


def authorize_locator(db, user, run_id, *, audit_only=False, external_model=False):
    locator = opaque_locator(db, run_id)
    if locator is None:
        raise HTTPException(404, "明确75任务锚不存在")
    actor = actor_now(db, user)
    if type(audit_only) is not bool or audit_only and actor.user_role != "super_admin":
        raise HTTPException(403, "明确冻结审计须当前Super且仍有项目和逐患者用途")
    if not audit_only and actor.user_id != locator["requested_by"]:
        raise HTTPException(403, "普通任务只允许当前原请求人读取")
    # Even technical Super must pass current project/per-patient purpose rights.
    actor, _, _ = authorize_subject(db, actor, locator["scope_id"], locator["patient_id"], external_model=external_model)
    if not audit_only:
        role_configuration(db, actor)
    return actor, locator


def safe_task_metadata(db, user, run_id):
    """No clinical body, raw Prompt/question or provider endpoint is selected."""
    from app.ai.models import AIRun

    locator = opaque_locator(db, run_id)
    if locator is None:
        raise HTTPException(404, "任务不存在")
    actor = actor_now(db, user)
    if actor.user_role != "super_admin" and actor.user_id != locator["requested_by"]:
        raise HTTPException(403, "不能读取他人技术任务状态")
    fields = ("run_id", "status", "create_time", "finish_time", "error_code")
    row = current_research_rows(db.query(*(getattr(AIRun, key) for key in fields)).filter_by(run_id=run_id), shared=True).one_or_none()
    if row is None:
        raise HTTPException(404, "任务不存在")
    values = dict(row._mapping)
    for field in ("create_time", "finish_time"):
        values[field] = str(values[field]) if values[field] is not None else None
    return {
        "schema_version": "deidentification_safe_task_v1",
        **values,
        "source": None,
        "result": None,
        "raw_frozen_json": None,
        "proof_scope": "technical_metadata_and_opaque_hashes_only",
    }


def actor_for_lease(db, locator):
    """ID-only is allowed for locating, never for bypassing frozen execution epoch."""
    return actor_now(db, SimpleNamespace(user_id=locator["requested_by"]))
