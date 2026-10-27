"""Typed original surgery scope filters before LIMIT; full authority is separate."""

from fastapi import HTTPException
from sqlalchemy import JSON, String, case, type_coerce
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.sql.functions import FunctionElement

from app.ai import surgery_facts as facts
from app.ai.models import AIRun
from app.ai.surgery_models import AISurgeryPool
from app.ai.surgery_scenario_models import AISurgeryScenario
from app.models import Department, Doctor
from app.sql_json import json_integer, json_string, json_type, json_valid


class _JsonScalarKind(FunctionElement):
    type = String()
    inherit_cache = True


@compiles(_JsonScalarKind)
def _mysql_kind(element, compiler, **kwargs):
    document, path = list(element.clauses)
    return "JSON_TYPE(JSON_EXTRACT(" + compiler.process(document, **kwargs) + ", " + compiler.process(path, **kwargs) + "))"


@compiles(_JsonScalarKind, "sqlite")
def _sqlite_kind(element, compiler, **kwargs):
    return "JSON_TYPE(" + ", ".join(compiler.process(value, **kwargs) for value in element.clauses) + ")"


@compiles(_JsonScalarKind, "postgresql")
def _postgresql_json_kind(element, compiler, **kwargs):
    return compiler.process(json_type(*tuple(element.clauses)), **kwargs)


def _uuid(value):
    try:
        return facts.canonical_id(value)
    except (ValueError, TypeError, AttributeError) as exc:
        raise HTTPException(422, "手术历史资源池或场景标识须为规范UUID") from exc


def _pool_scope(db, actor, pool_id):
    row = facts.current_query(db.query(AISurgeryPool.pool_id, AISurgeryPool.department_id).filter_by(pool_id=pool_id)).one_or_none()
    if row is None:
        raise HTTPException(404, "原手术资源池不存在")
    if actor.user_role != "super_admin":
        facts.pool_scope(db, actor, pool_id, require_published=False)
    return row


def _department_scope(db, actor, department_id):
    if type(department_id) is not int or not 1 <= department_id <= 2147483647:
        raise HTTPException(422, "手术历史科室标识须为规范正整数")
    if actor.user_role == "super_admin":
        return
    if facts.current_query(db.query(Department.department_id).filter_by(department_id=department_id)).one_or_none() is None:
        raise HTTPException(403, "不能核实该原手术科室的当前范围")
    if facts.current_query(db.query(Doctor.doctor_id).filter_by(user_id=actor.user_id, department_id=department_id)).first() is not None:
        return
    for pool in facts.current_query(db.query(AISurgeryPool.pool_id).filter_by(department_id=department_id)).all():
        try:
            facts.pool_scope(db, actor, pool.pool_id, require_published=False)
            return
        except HTTPException as exc:
            if exc.status_code not in {403, 404, 409}:
                raise
    raise HTTPException(403, "没有此手术科室的当前实际资源池范围")


def filter_history(db, user, query, *, department_id=None, surgery_pool_id=None, surgery_scenario_id=None):
    """Filter native scope, preserving legacy unfiltered feature65 history.

    Neither body reconstruction nor current-source qualification occurs here.
    Every returned run still requires authorize_run and its complete frozen
    binding; Super keeps original pool/department filtering after revocation.
    """
    actor = facts.current_actor(db, user)
    source = None
    if surgery_scenario_id is not None:
        surgery_scenario_id = _uuid(surgery_scenario_id)
        source = facts.current_query(db.query(AISurgeryScenario.scenario_id, AISurgeryScenario.pool_id, AISurgeryScenario.department_id).filter_by(scenario_id=surgery_scenario_id)).one_or_none()
        if source is None:
            raise HTTPException(404, "原手术场景不存在")
        if department_id is not None and department_id != source.department_id or surgery_pool_id is not None and surgery_pool_id != source.pool_id:
            raise HTTPException(422, "手术历史显式范围与原场景的科室或资源池不同")
        surgery_pool_id = source.pool_id
    if surgery_pool_id is not None:
        surgery_pool_id = _uuid(surgery_pool_id)
        pool = _pool_scope(db, actor, surgery_pool_id)
        if source is not None and source.department_id != pool.department_id and actor.user_role != "super_admin":
            raise HTTPException(403, "原手术资源池当前科室归属已经变化")
        if source is None and department_id is not None and department_id != pool.department_id:
            raise HTTPException(422, "手术历史显式科室与当前资源池不同")
    if department_id is not None:
        _department_scope(db, actor, department_id)
    query = query.filter(AIRun.feature_key == "surgery_scheduling")
    if actor.user_role != "super_admin":
        query = query.filter(AIRun.requested_by == actor.user_id)
    document = case((json_valid(AIRun.input_json) == 1, AIRun.input_json), else_="{}")
    binding = type_coerce(document, JSON)["payload"]["context"]["surgery_binding"]

    def integer_member(key, value):
        return _JsonScalarKind(document, "$.payload.context.surgery_binding." + key).in_(("integer", "INTEGER")), json_integer(binding[key].as_integer(), document, "$.payload.context.surgery_binding." + key) == value

    query = query.filter(
        _JsonScalarKind(document, "$.payload.context.surgery_binding.department_id").in_(("integer", "INTEGER")),
        json_integer(binding["department_id"].as_integer(), document, "$.payload.context.surgery_binding.department_id").between(1, 2147483647),
        *(_JsonScalarKind(document, "$.payload.context.surgery_binding." + key).in_(("text", "STRING")) for key in ("pool_id", "scenario_id")),
    )
    if department_id is not None:
        query = query.filter(*integer_member("department_id", department_id))
    if surgery_pool_id is not None:
        query = query.filter(json_string(binding["pool_id"].as_string(), document, "$.payload.context.surgery_binding.pool_id") == surgery_pool_id)
    if source is not None:
        query = query.filter(json_string(binding["scenario_id"].as_string(), document, "$.payload.context.surgery_binding.scenario_id") == surgery_scenario_id, json_string(binding["pool_id"].as_string(), document, "$.payload.context.surgery_binding.pool_id") == source.pool_id, *integer_member("department_id", source.department_id))
    return query
