"""Exact bed task JSON filters with current role and original/current scope checks."""

from fastapi import HTTPException
from sqlalchemy import JSON, String, case, func, type_coerce
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.sql.functions import FunctionElement

from app.ai import bed_facts as facts
from app.ai.bed_series_models import AIBedSeries
from app.ai.models import AIRun
from app.models import Ward


class _JsonScalarKind(FunctionElement):
    """Preserve JSON types; casting an extracted member alone admits strings/bools."""

    type = String()
    inherit_cache = True


@compiles(_JsonScalarKind)
def _mysql_json_kind(element, compiler, **kwargs):
    document, path = list(element.clauses)
    return "JSON_TYPE(JSON_EXTRACT(" + compiler.process(document, **kwargs) + ", " + compiler.process(path, **kwargs) + "))"


@compiles(_JsonScalarKind, "sqlite")
def _sqlite_json_kind(element, compiler, **kwargs):
    return "JSON_TYPE(" + ", ".join(compiler.process(value, **kwargs) for value in element.clauses) + ")"


def _positive(value):
    if type(value) is not int or not 1 <= value <= 2147483647:
        raise HTTPException(422, "床位历史科室和病区标识须为规范正整数")
    return value


def _ward_scope(db, actor, ward_id, *, expected_department=None):
    row = facts.current_query(db.query(Ward.ward_id, Ward.department_id).filter_by(ward_id=ward_id)).one_or_none()
    if expected_department is not None and row is not None and row.department_id is not None and expected_department != row.department_id:
        raise HTTPException(422, "未选择原序列时显式科室与病区当前归属不一致")
    if actor.user_role == "super_admin":
        return row
    if row is None or row.department_id is None:
        raise HTTPException(403, "不能核实该病区当前科室范围，不能读取原床位任务")
    facts.bed_scope(db, actor, row.department_id)
    return row


def filter_history(db, user, query, *, department_id=None, ward_id=None, bed_series_id=None):
    """Apply exact members before LIMIT; do not load or requalify source bodies.

    A series anchors its original department/ward. Ordinary callers must also
    retain permission for the ward's current department after a transfer. With
    no series anchor, an explicit department/ward pair describes today's scope.
    Whole-run currentness and frozen audit remain authorize_run's responsibility.
    """
    actor = facts.current_actor(db, user)
    facts.authorized_departments(db, actor)
    if department_id is not None:
        department_id = _positive(department_id)
    if ward_id is not None:
        ward_id = _positive(ward_id)
    source = None
    if bed_series_id is not None:
        try:
            bed_series_id = facts.canonical_id(bed_series_id)
        except (ValueError, TypeError, AttributeError) as exc:
            raise HTTPException(422, "床位历史序列标识须为规范UUID") from exc
        source = facts.current_query(db.query(AIBedSeries.series_id, AIBedSeries.department_id, AIBedSeries.ward_id).filter_by(series_id=bed_series_id)).one_or_none()
        if source is None:
            raise HTTPException(404, "原床位序列不存在")
        if department_id is not None and department_id != source.department_id or ward_id is not None and ward_id != source.ward_id:
            raise HTTPException(422, "显式科室、病区与原床位序列范围不一致")
        facts.bed_scope(db, actor, source.department_id, allow_missing=actor.user_role == "super_admin")
        _ward_scope(db, actor, source.ward_id)
    else:
        if ward_id is not None:
            _ward_scope(db, actor, ward_id, expected_department=department_id)
    if department_id is not None:
        facts.bed_scope(db, actor, department_id, allow_missing=actor.user_role == "super_admin")
    query = query.filter(AIRun.feature_key == "bed_forecast")
    if actor.user_role != "super_admin":
        query = query.filter(AIRun.requested_by == actor.user_id)
    # Invalid stored JSON is outside an exact scope filter, never a SQL parser
    # failure or a placeholder taking LIMIT slots from valid scoped history.
    document = case((func.json_valid(AIRun.input_json) == 1, AIRun.input_json), else_="{}")
    binding = type_coerce(document, JSON)["payload"]["context"]["bed_binding"]

    def integer_member(key, value):
        return (_JsonScalarKind(document, "$.payload.context.bed_binding." + key).in_(("integer", "INTEGER")), binding[key].as_integer() == value)

    if department_id is not None or ward_id is not None or bed_series_id is not None:
        # A metadata scope must consist of typed JSON identities. Booleans and
        # numeric strings are not identifiers even when a dialect casts them.
        query = query.filter(
            _JsonScalarKind(document, "$.payload.context.bed_binding.department_id").in_(("integer", "INTEGER")),
            _JsonScalarKind(document, "$.payload.context.bed_binding.ward_id").in_(("integer", "INTEGER")),
            _JsonScalarKind(document, "$.payload.context.bed_binding.series_id").in_(("text", "STRING")),
            binding["department_id"].as_integer().between(1, 2147483647),
            binding["ward_id"].as_integer().between(1, 2147483647),
        )
    if department_id is not None:
        query = query.filter(*integer_member("department_id", department_id))
    if ward_id is not None:
        query = query.filter(*integer_member("ward_id", ward_id))
    if bed_series_id is not None:
        # Bind all original scope members, so a forged JSON series UUID cannot
        # match a task that carries another original department or ward.
        query = query.filter(
            _JsonScalarKind(document, "$.payload.context.bed_binding.series_id").in_(("text", "STRING")),
            binding["series_id"].as_string() == bed_series_id,
            *integer_member("department_id", source.department_id),
            *integer_member("ward_id", source.ward_id),
        )
    return query
