"""Request-local patient data restrictions for configurable clinical roles.

The existing endpoint ownership checks still apply.  This layer can only narrow
them: SQL reads and bulk mutations receive patient predicates, and unit-of-work
writes validate both their stored and proposed patient ownership.
"""

from dataclasses import dataclass
from functools import cached_property, lru_cache

from fastapi import HTTPException
from sqlalchemy import Column, Table, and_, event, false, inspect, or_, select, union
from sqlalchemy.orm import Session, with_loader_criteria
from sqlalchemy.orm.interfaces import MANYTOONE
from sqlalchemy.sql import visitors
from sqlalchemy.sql.elements import TextClause

from app.ai.models import AIRun
from app.database import Base
from app.models import Admission, Appointment, Doctor, MedicalRecord, Patient, Prescription, Registration

_SCOPE_KEY = "hoim_patient_access_scope"
_CARE_MODELS = (Appointment, Registration, MedicalRecord, Prescription, Admission)
_DENIED = "患者资料超出当前账号的数据范围"
# A run without a patient binding is a supported nonpatient AI task.  Its
# existing requester/feature authorization remains in force, also for children.
_UNBOUND_PATIENT_MODELS = frozenset({AIRun})


@dataclass(frozen=True)
class _PatientScope:
    user_id: int
    doctor_ids: tuple[int, ...]
    models: dict

    @cached_property
    def criteria(self):
        return tuple(with_loader_criteria(model, _predicate(self, model), include_aliases=True) for model in self.models)

    def patients(self):
        if not self.doctor_ids:
            return select(Patient.__table__.c.patient_id).where(false())
        return union(*(
            select(model.__table__.c.patient_id).where(model.__table__.c.doctor_id.in_(self.doctor_ids))
            for model in _CARE_MODELS
        ))


@lru_cache(maxsize=4)
def _patient_models(mapped_classes):
    """Follow foreign keys toward patients, retaining shortest acyclic paths.

    This also protects prescription lines and other children without patient_id.
    Multiple direct patient foreign keys (for example family links) must all be
    authorized; a permitted owner cannot expose a different patient's record.
    """
    by_table = {model.__table__: model for model in mapped_classes}
    links = {}
    for table, model in by_table.items():
        parents = {(fk.parent, fk.column) for fk in table.foreign_keys}
        # A few legacy relationships declare foreign_keys in the mapper rather
        # than a database ForeignKey (notably prescription medication lines).
        for relationship in inspect(model).relationships:
            if relationship.direction is MANYTOONE:
                parents.update(relationship.local_remote_pairs)
        links[table] = parents
    distances = {Patient.__table__: 0}
    edges = {}
    while True:
        additions = {}
        for table in by_table:
            if table in distances:
                continue
            parents = [(local, target) for local, target in links[table] if target.table in distances]
            if not parents:
                continue
            distance = min(distances[target.table] for _, target in parents)
            additions[table] = distance + 1
            edges[table] = tuple((local, target) for local, target in parents if distances[target.table] == distance)
        if not additions:
            break
        distances.update(additions)
    return {by_table[table]: edges.get(table, ()) for table in distances}


def _predicate(scope, model, *, table_only=False):
    table = model.__table__
    column = (lambda name: table.c[name]) if table_only else (lambda name: getattr(model, name))
    if model is Patient:
        return column("patient_id").in_(scope.patients())
    parents = scope.models[model]
    checks = []
    present = []
    by_table = {item.__table__: item for item in scope.models}
    for local, target in parents:
        source = column(local.key)
        parent = by_table[target.table]
        allowed = select(target).where(_predicate(scope, parent, table_only=True))
        # Optional links may be absent, but every present link must be in scope.
        checks.append(or_(source.is_(None), source.in_(allowed)))
        present.append(source.is_not(None))
    if model in _UNBOUND_PATIENT_MODELS:
        return and_(*checks)
    return and_(*checks, or_(*present))


def apply_patient_scope(db: Session, user, data_scope: str = "existing") -> None:
    """Bind ``assigned`` doctor/director restrictions to one request Session.

    Call after authenticating and resolving the administrator's policy, before
    running the endpoint.  ``existing`` keeps the endpoint's current scope.
    A Session cannot be rebound to another identity or widened after binding.
    """
    current = db.info.get(_SCOPE_KEY)
    if current is not None:
        if current.user_id != user.user_id:
            raise HTTPException(403, _DENIED)
        return
    if data_scope == "existing":
        return
    if data_scope != "assigned" or user.user_role not in {"doctor", "director"}:
        raise HTTPException(403, "该角色不能使用此患者数据范围")
    mapped = tuple(sorted((mapper.class_ for mapper in Base.registry.mappers), key=lambda model: model.__table__.name))
    protected = _patient_models(mapped)
    # An identity-map hit does not issue SQL.  Expire previously loaded PHI so
    # existing worker references remain attached but must reload through scope.
    loaded = [instance for instance in db.identity_map.values() if type(instance) in protected]
    if any(instance in db.dirty or instance in db.deleted for instance in loaded):
        raise HTTPException(403, _DENIED)
    for instance in loaded:
        if instance in db:
            db.expire(instance)
    if any(type(instance) in protected for instance in db.new):
        raise HTTPException(403, _DENIED)
    doctors = db.query(Doctor.doctor_id).filter(Doctor.user_id == user.user_id).all()
    db.info[_SCOPE_KEY] = _PatientScope(user.user_id, tuple(row.doctor_id for row in doctors), protected)
    # These legacy helpers bypass both ORM execution and before_flush events.
    scope = db.info[_SCOPE_KEY]
    for method in ("bulk_save_objects", "bulk_insert_mappings", "bulk_update_mappings"):
        original = getattr(db, method)
        if method == "bulk_save_objects":
            def guarded(objects, *args, _original=original, **kwargs):
                objects = list(objects)
                if any(type(item) in scope.models for item in objects):
                    _reject_legacy_bulk()
                return _original(objects, *args, **kwargs)
        else:
            def guarded(mapper, *args, _original=original, **kwargs):
                if inspect(mapper).class_ in scope.models:
                    _reject_legacy_bulk()
                return _original(mapper, *args, **kwargs)
        setattr(db, method, guarded)


def _reject_legacy_bulk(*_args, **_kwargs):
    raise HTTPException(403, "当前患者数据范围请使用逐条校验的写入操作")


@event.listens_for(Session, "do_orm_execute")
def _restrict_patient_statements(state):
    scope = state.session.info.get(_SCOPE_KEY)
    if scope is None:
        return
    statement = state.statement
    # Text and Core statements cannot receive ORM loader criteria reliably.
    # Reject them instead of silently returning unfiltered data.
    protected_tables = {model.__table__ for model in scope.models}
    unsafe = not state.is_orm_statement
    def unscoped_column(node):
        table = node if isinstance(node, Table) else getattr(node, "table", None) if isinstance(node, Column) else None
        return table in protected_tables and not getattr(node, "_annotations", {}).get("parentmapper")

    def unsafe_projection(node):
        # An ORM alias contains its original unannotated Table as a child.
        # Preserve that alias as a single mapped expression for adaptation.
        if getattr(node, "_annotations", {}).get("parentmapper"):
            return False
        if unscoped_column(node):
            return True
        return any(unsafe_projection(child) for child in node.get_children())

    for node in visitors.iterate(statement):
        if isinstance(node, TextClause):
            unsafe = True
        # Adding an unrelated ORM entity does not make Core patient columns
        # filterable: select(User, Patient.__table__.c.name) must also fail.
        for column in getattr(node, "_raw_columns", ()):
            if unsafe_projection(column):
                unsafe = True
        for source in getattr(node, "_from_obj", ()):
            if unscoped_column(source):
                unsafe = True
    if unsafe:
        raise HTTPException(403, "当前患者数据范围禁止执行未限定范围的 SQL")
    if state.is_insert and state.bind_mapper is not None and state.bind_mapper.class_ in scope.models:
        raise HTTPException(403, "当前患者数据范围请使用逐条校验的新增操作")
    if state.is_update:
        mapper = state.bind_mapper
        if mapper is not None and mapper.class_ in scope.models:
            model = mapper.class_
            ownership = {local.key for local, _ in scope.models[model]}
            ownership.update(column.key for column in mapper.primary_key)
            # Bulk assignment expressions cannot be checked by before_flush.
            # Ordinary field updates remain supported; moving ownership uses ORM.
            values = getattr(statement, "_values", None) or {}
            keys = {getattr(key, "key", key) for key in values}
            keys.update(getattr(key, "key", key) for key, _ in (getattr(statement, "_ordered_values", None) or ()))
            parameters = state.parameters
            if parameters:
                dictionaries = parameters if isinstance(parameters, list) else [parameters]
                keys.update(key for item in dictionaries for key in item)
            if ownership & keys:
                raise HTTPException(403, "批量操作不能更改患者或关联记录的归属")
    if state.is_select or state.is_update or state.is_delete:
        statement = statement.options(*scope.criteria)
        # SQLAlchemy intentionally omits with_loader_criteria during refresh /
        # expired-column loads.  Add a direct WHERE for this internal path so
        # an expired identity-map entry cannot reload an out-of-scope patient.
        if state.is_column_load and state.bind_mapper is not None and state.bind_mapper.class_ in scope.models:
            statement = statement.where(_predicate(scope, state.bind_mapper.class_))
        state.statement = statement


def _value_for_column(instance, column):
    """Resolve an FK also when SQLAlchemy has not synchronized a relationship."""
    state = inspect(instance)
    for relationship in state.mapper.relationships:
        if relationship.uselist or column not in relationship.local_columns:
            continue
        history = state.attrs[relationship.key].history
        if not history.added and state.attrs[column.key].history.has_changes():
            # Assigning patient_id does not invalidate an already loaded
            # patient relationship until expiration.  SQL writes the new FK.
            return getattr(instance, column.key, None), None
        related = history.added[0] if history.added else state.dict.get(relationship.key)
        if related is not None:
            for local, remote in relationship.local_remote_pairs:
                if local is column:
                    return getattr(related, remote.key, None), related
        if history.added and history.added[0] is None:
            return None, None
    return getattr(instance, column.key, None), None


def _row_is_allowed(connection, scope, model, identity):
    conditions = [column == value for column, value in zip(inspect(model).primary_key, identity, strict=True)]
    return connection.execute(select(1).select_from(model.__table__).where(*conditions, _predicate(scope, model, table_only=True))).first() is not None


@event.listens_for(Session, "before_flush")
def _validate_patient_writes(db, _flush_context, _instances):
    scope = db.info.get(_SCOPE_KEY)
    if scope is None:
        return
    connection = db.connection()
    by_table = {model.__table__: model for model in scope.models}
    checked = set()

    def validate(instance, visiting):
        if instance in checked:
            return
        if instance in visiting:
            raise HTTPException(403, _DENIED)
        visiting = visiting | {instance}
        model = type(instance)
        if model not in scope.models:
            return
        state = inspect(instance)
        if state.persistent and not _row_is_allowed(connection, scope, model, state.identity):
            raise HTTPException(403, _DENIED)
        if instance in db.deleted:
            checked.add(instance)
            return
        if model is Patient:
            identifier = getattr(instance, "patient_id", None)
            if identifier is None or not _row_is_allowed(connection, scope, Patient, (identifier,)):
                raise HTTPException(403, _DENIED)
            checked.add(instance)
            return
        present = False
        for local, target in scope.models[model]:
            value, related = _value_for_column(instance, local)
            if related is not None and related in db.new:
                validate(related, visiting)
                present = True
                continue
            if value is None:
                continue
            present = True
            parent = by_table[target.table]
            allowed = connection.execute(select(1).select_from(target.table).where(target == value, _predicate(scope, parent, table_only=True))).first()
            if allowed is None:
                raise HTTPException(403, _DENIED)
        if not present and model not in _UNBOUND_PATIENT_MODELS:
            raise HTTPException(403, _DENIED)
        if not present and state.persistent and model in _UNBOUND_PATIENT_MODELS:
            # A patient task cannot be converted into an unbound task to keep
            # access to its contents after the care relationship is revoked.
            conditions = [column == value for column, value in zip(state.mapper.primary_key, state.identity, strict=True)]
            old_patient = connection.execute(select(model.__table__.c.patient_id).where(*conditions)).scalar_one()
            if old_patient is not None:
                raise HTTPException(403, "不能清除已有 AI 任务的患者归属")
        checked.add(instance)

    for instance in set(db.new) | set(db.dirty) | set(db.deleted):
        validate(instance, set())
