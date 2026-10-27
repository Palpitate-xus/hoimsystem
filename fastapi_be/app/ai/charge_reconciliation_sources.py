"""Current authorized complete Admission evidence and immutable technical review."""

import datetime as dt
import functools
import json
import secrets
import uuid
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import Double, Float, event, inspect, or_
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.sql.functions import FunctionElement

from app.ai import charge_reconciliation_contract as c
from app.ai.charge_reconciliation_models import AIChargeCaseSnapshot
from app.ai.charge_reconciliation_write_guard import current_charge_actor, current_charge_rows, lock_charge_write
from app.ai.governance import audit
from app.ai.native_acceptance import AUDIT_FIELDS

IDENTITY = ("case_snapshot_id", "patient_id", "admission_id", "schema_version", "created_at", "created_by", "collection_digest")
GOVERNANCE = ("status", "revision", "reviewed_at", "reviewed_by", "review_basis_note", "revoked_at", "revoked_by", "revoke_reason")
GROUPS = (
    ("charges", "charge", "charge_id"),
    ("orders", "order", "order_id"),
    ("order_items", "order_item", "item_id"),
    ("executions", "execution", "execution_id"),
    ("administrations", "administration", "administration_id"),
)


class SQLFloatPromotion(FunctionElement):
    """Generic MySQL cast(Double) omits CAST; retain the actual verified SQL."""

    type = Double()
    inherit_cache = True


@compiles(SQLFloatPromotion, "mysql")
def exact_float_promotion(element, compiler, **kwargs):
    return "CAST(" + compiler.process(list(element.clauses)[0], **kwargs) + " AS DOUBLE)"


@compiles(SQLFloatPromotion, "postgresql")
def exact_postgresql_float_promotion(element, compiler, **kwargs):
    return "CAST(" + compiler.process(list(element.clauses)[0], **kwargs) + " AS DOUBLE PRECISION)"


def utcnow():
    return dt.datetime.now(dt.UTC).replace(tzinfo=None)


def typed(model, value):
    raw = value.model_dump(mode="json") if hasattr(value, "model_dump") else value
    checked = model.model_validate(raw)
    if c.canonical_json(checked) != c.canonical_json(raw):
        raise ValueError("Complete fields and scalar types must remain exact")
    return checked


def bounded(value):
    if len(c.utf8(c.canonical_json(value))) > c.MAX_BYTES:
        raise HTTPException(409, "完整住院账目证据超过8MiB，未返回或保存部分原件")
    return value


def parse_json(value):
    def pairs(items):
        result = {}
        for key, child in items:
            if key in result:
                raise ValueError("Duplicate JSON key")
            result[key] = child
        return result

    parsed = json.loads(value, object_pairs_hook=pairs, parse_constant=lambda _: (_ for _ in ()).throw(ValueError("Nonfinite JSON")))
    if c.canonical_json(parsed) != value:
        raise ValueError("Whole canonical JSON required")
    return bounded(parsed)


def row_value(row, sql_witnesses=None, *, sql_witness_method="mysql_CAST_AS_DOUBLE_in_same_current_statement"):
    result = {}
    for column in inspect(type(row)).columns:
        value = getattr(row, column.name)
        witness = None
        if sql_witnesses is not None and column.name in sql_witnesses:
            promoted = sql_witnesses[column.name]
            witness = {
                "method": sql_witness_method,
                "value_text": repr(promoted) if promoted is not None else None,
                "binary_hex": promoted.hex() if promoted is not None else None,
            }
        result[column.name] = (
            c.stored_float(value, sql_witness=witness)
            if isinstance(column.type, Float)
            else value.isoformat(timespec="microseconds")
            if isinstance(value, dt.datetime)
            else value.isoformat()
            if isinstance(value, dt.date)
            else str(value)
            if isinstance(value, Decimal)
            else value
        )
    return result


def current_actor(db, user, roles=c.SOURCE_ROLES):
    return lock_charge_write(db, user, allowed_roles=roles)


def authorize_scope(db, user, request):
    from app.ai.context import authorize_patient
    from app.ai.models import AIPatientGrant
    from app.models import Admission, Doctor, Patient

    actor = current_actor(db, user)
    # Only the actual identity scope is read before common patient access.
    locator = current_charge_rows(db.query(Admission.admission_id, Admission.patient_id, Admission.doctor_id, Admission.department_id).filter_by(admission_id=request.admission_id)).one_or_none()
    if locator is None or locator.patient_id != request.patient_id:
        raise HTTPException(403, "实际患者与住院作用域不一致")
    doctors = current_charge_rows(db.query(Doctor).filter_by(user_id=actor.user_id), shared=True).all()
    grants = current_charge_rows(db.query(AIPatientGrant).filter_by(user_id=actor.user_id, patient_id=request.patient_id, category="operations"), shared=True).all()
    if (
        actor.user_role not in {"admin", "super_admin"}
        and not any(g.revoked == 0 and g.expires_at > utcnow() for g in grants)
        and not any(locator.doctor_id == d.doctor_id or actor.user_role == "director" and locator.department_id == d.department_id for d in doctors)
    ):
        raise HTTPException(403, "当前实际住院关系或有效operations授权不可用")

    def current_authorization(orm):
        if orm.is_select:
            orm.statement = orm.statement.with_for_update(read=True).execution_options(populate_existing=True)

    # The common access check must not fall back to an older RR grant/Doctor
    # view after the current precheck. This hook exists only during that call.
    event.listen(db, "do_orm_execute", current_authorization)
    try:
        authorize_patient(db, actor, request.patient_id, "operations", request.admission_id)
    finally:
        event.remove(db, "do_orm_execute", current_authorization)
    patient = current_charge_rows(db.query(Patient).filter_by(patient_id=request.patient_id), shared=True).one()
    admission = current_charge_rows(db.query(Admission).filter_by(admission_id=request.admission_id)).one()
    return actor, patient, admission


def member_manifest(value):
    members = [
        {"kind": "patient_binding", "record_id": str(value["request"]["patient_id"]), "content_hash": c.digest(value["patient_binding"])},
        {"kind": "admission", "record_id": value["request"]["admission_id"], "content_hash": c.digest(value["admission"])},
    ]
    for key, kind, primary in GROUPS:
        members.extend({"kind": kind, "record_id": str(row[primary]), "content_hash": c.digest(row)} for row in value[key])
    return sorted(members, key=lambda row: (row["kind"], row["record_id"]))


def collection_content(value):
    return {key: child for key, child in value.items() if key not in {"captured_at", "collection_digest"}}


def verify_capture(value):
    try:
        typed(c.Collection, value)
        request = value["request"]
        if value["patient_binding"]["patient_id"] != request["patient_id"] or (value["admission"]["admission_id"], value["admission"]["patient_id"]) != (
            request["admission_id"],
            request["patient_id"],
        ):
            return False
        if (
            len(value["member_manifest"]) > c.MAX_ROWS
            or member_manifest(value) != value["member_manifest"]
            or c.digest(value["member_manifest"]) != value["manifest_hash"]
            or c.digest(collection_content(value)) != value["collection_digest"]
        ):
            return False
        for key, _, primary in GROUPS:
            ids = [row[primary] for row in value[key]]
            if any(identifier is None for identifier in ids) or ids != sorted(set(ids)):
                return False
        orders = {row["order_id"]: row for row in value["orders"]}
        executions = {row["execution_id"]: row for row in value["executions"]}
        if any((row["patient_id"], row["admission_id"]) != (request["patient_id"], request["admission_id"]) for row in [*value["charges"], *value["orders"]]):
            return False
        witness_method = {
            "mysql_same_statement_double_promotion": "mysql_CAST_AS_DOUBLE_in_same_current_statement",
            "postgresql_same_statement_float8": "postgresql_CAST_AS_DOUBLE_PRECISION_in_same_current_statement",
        }.get(value["float_capture_basis"])
        if any(
            (row["quantity"]["storage_witness"] is not None) != (witness_method is not None)
            or row["quantity"]["storage_witness"] is not None
            and (
                row["quantity"]["storage_witness"]["method"] != witness_method
                or (row["quantity"]["state"] == "null") != (row["quantity"]["storage_witness"]["value_text"] is None)
            )
            for row in value["charges"]
        ):
            return False
        if any(row["order_id"] not in orders for row in [*value["order_items"], *value["executions"]]):
            return False
        if any(
            row["order_id"] not in orders or row["patient_id"] != request["patient_id"] or row["execution_id"] not in executions or executions[row["execution_id"]]["order_id"] != row["order_id"]
            for row in value["administrations"]
        ):
            return False
        bounded(value)
        return True
    except (ValueError, TypeError, KeyError, UnicodeError, HTTPException):
        return False


def capture_case(db, user, values):
    from app.models import InpatientCharge, InpatientOrder, InpatientOrderItem, MedicationAdministration, OrderExecution

    request = typed(c.CaptureRequest, values)
    _, patient, admission = authorize_scope(db, user, request)
    dialect = db.get_bind().dialect.name
    if dialect not in {"mysql", "sqlite", "postgresql"}:
        raise HTTPException(409, "该数据库Float原值捕获方式尚未独立验证")
    result = {
        "schema_version": "charge_ledger_collection_v1",
        "request": request.model_dump(mode="json"),
        "captured_at": c.utc_text(utcnow()),
        "float_capture_basis": {"mysql": "mysql_same_statement_double_promotion", "sqlite": "sqlite_orm_float_only", "postgresql": "postgresql_same_statement_float8"}[dialect],
        "patient_binding": {"patient_id": patient.patient_id, **{key: getattr(patient, key) for key in ("name", "identity", "phone", "address")}},
        "admission": row_value(admission),
    }
    rows_used = 2
    bytes_used = len(c.utf8(c.canonical_json(result)))

    def collect(model, query, primary):
        nonlocal rows_used, bytes_used
        rows, last = [], None
        float_columns = [column for column in model.__table__.columns if isinstance(column.type, Float)] if dialect in {"mysql", "postgresql"} else []
        if float_columns:
            query = query.add_columns(*(SQLFloatPromotion(getattr(model, column.name)).label("exact_float_" + column.name) for column in float_columns))
        while True:
            part = query if last is None else query.filter(primary > last)
            batch = current_charge_rows(part, shared=True).order_by(primary).limit(128).all()
            for item in batch:
                row = item[0] if float_columns else item
                rows_used += 1
                raw = row_value(
                    row,
                    {column.name: item[index + 1] for index, column in enumerate(float_columns)} if float_columns else None,
                    sql_witness_method="postgresql_CAST_AS_DOUBLE_PRECISION_in_same_current_statement" if dialect == "postgresql" else "mysql_CAST_AS_DOUBLE_in_same_current_statement",
                )
                bytes_used += len(c.utf8(c.canonical_json(raw)))
                if rows_used > c.MAX_ROWS or bytes_used > c.MAX_BYTES:
                    raise HTTPException(409, "完整账目成员超过8192行或8MiB，拒绝截断")
                rows.append(raw)
            if len(batch) < 128:
                break
            last = getattr(batch[-1][0] if float_columns else batch[-1], primary.key)
        return rows

    result["charges"] = collect(InpatientCharge, db.query(InpatientCharge).filter_by(admission_id=request.admission_id), InpatientCharge.charge_id)
    result["orders"] = collect(InpatientOrder, db.query(InpatientOrder).filter_by(admission_id=request.admission_id), InpatientOrder.order_id)
    ids = [row["order_id"] for row in result["orders"]]
    result["order_items"] = collect(InpatientOrderItem, db.query(InpatientOrderItem).filter(InpatientOrderItem.order_id.in_(ids)), InpatientOrderItem.item_id)
    result["executions"] = collect(OrderExecution, db.query(OrderExecution).filter(OrderExecution.order_id.in_(ids)), OrderExecution.execution_id)
    execution_ids = [row["execution_id"] for row in result["executions"]]
    result["administrations"] = collect(
        MedicationAdministration,
        db.query(MedicationAdministration).filter(or_(MedicationAdministration.order_id.in_(ids), MedicationAdministration.execution_id.in_(execution_ids))),
        MedicationAdministration.administration_id,
    )
    result["member_manifest"] = member_manifest(result)
    result["manifest_hash"] = c.digest(result["member_manifest"])
    result["collection_digest"] = c.digest(collection_content(result))
    bounded(result)
    if not verify_capture(result):
        raise HTTPException(409, "实际住院原件父链或完整证明冲突，未返回部分正文")
    return result


def metadata(row):
    value = {key: getattr(row, key) for key in (*IDENTITY, *GOVERNANCE, "content_hash")}
    for key in ("created_at", "reviewed_at", "revoked_at"):
        value[key] = c.utc_text(value[key]) if value[key] is not None else None
    value["source_id"] = "charge_case:" + row.case_snapshot_id + ":" + row.content_hash[:12]
    value["governance_hash"] = c.digest({key: value[key] for key in GOVERNANCE})
    return value


def governance_valid(value):
    try:
        status, revision = value["status"], value["revision"]
        if type(revision) is not int or status not in {"draft", "published", "rejected", "revoked"}:
            return False
        created = dt.datetime.strptime(value["created_at"], "%Y-%m-%dT%H:%M:%S.%fZ")
        reviewed = value["reviewed_at"] is not None
        revoked = value["revoked_at"] is not None
        for clock_key, actor_key, note_key in (("reviewed_at", "reviewed_by", "review_basis_note"), ("revoked_at", "revoked_by", "revoke_reason")):
            if value[clock_key] is None:
                if value[actor_key] is not None or value[note_key] != "":
                    return False
            elif type(value[actor_key]) is not int or value[actor_key] <= 0 or dt.datetime.strptime(value[clock_key], "%Y-%m-%dT%H:%M:%S.%fZ") < created:
                return False
            else:
                c.check_basis(value[note_key])
        return (
            (status == "draft" and revision == 1 and not reviewed and not revoked)
            or (status in {"published", "rejected"} and revision == 2 and reviewed and not revoked)
            or (status == "revoked" and revoked and revision == (3 if reviewed else 2) and (not reviewed or value["revoked_at"] >= value["reviewed_at"]))
        )
    except (ValueError, KeyError, TypeError):
        return False


def verify_original(value):
    try:
        typed(c.CaseOriginalProof, value)
        snapshot = value["snapshot"]
        if (
            not governance_valid(value)
            or c.digest({key: value[key] for key in GOVERNANCE}) != value["governance_hash"]
            or value["source_id"] != "charge_case:" + value["case_snapshot_id"] + ":" + value["content_hash"][:12]
        ):
            return False
        if (
            c.digest(snapshot) != value["content_hash"]
            or not verify_capture(snapshot["collection"])
            or snapshot["collection"]["collection_digest"] != value["collection_digest"]
            or value["created_at"] < snapshot["collection"]["captured_at"]
        ):
            return False
        if any(snapshot[key] != value[key] for key in ("case_snapshot_id", "patient_id", "admission_id", "schema_version", "created_by", "created_at")) or snapshot["collection"]["request"] != {
            "patient_id": value["patient_id"],
            "admission_id": value["admission_id"],
        }:
            return False
        public = value["public_source"]
        if public is not None and (c.digest(public) != value["projection_hash"] or c.project_snapshot(snapshot, published_metadata(value)) != public):
            return False
        requires_public = value["status"] == "published" or value["status"] == "revoked" and value["reviewed_at"] is not None
        if (public is None) != (value["projection_hash"] is None) or (public is not None) != requires_public:
            return False
        return len(c.utf8(c.canonical_json(value))) <= c.MAX_BYTES
    except (ValueError, TypeError, KeyError, UnicodeError, HTTPException):
        return False


def published_metadata(value):
    if value["reviewed_at"] is None:
        raise ValueError("No retained publication proof")
    result = {**value, "status": "published", "revision": 2, "revoked_at": None, "revoked_by": None, "revoke_reason": ""}
    result["governance_hash"] = c.digest({key: result[key] for key in GOVERNANCE})
    return result


def original_proof(row):
    snapshot = parse_json(row.snapshot_json)
    typed(c.CaseSnapshot, snapshot)
    value = metadata(row)
    if not governance_valid(value) or c.digest(snapshot) != row.content_hash or not verify_capture(snapshot["collection"]) or snapshot["collection"]["collection_digest"] != row.collection_digest:
        raise HTTPException(409, "完整住院账目冻结原件或治理证明无效")
    if any(snapshot[key] != value[key] for key in ("case_snapshot_id", "patient_id", "admission_id", "schema_version", "created_by", "created_at")) or snapshot["collection"]["request"] != {
        "patient_id": row.patient_id,
        "admission_id": row.admission_id,
    }:
        raise HTTPException(409, "实际原件身份、住院或作者绑定不完整")
    public = None if row.projection_json is None else parse_json(row.projection_json)
    if public is not None and (c.digest(public) != row.projection_hash or c.project_snapshot(snapshot, published_metadata(value)) != public):
        raise HTTPException(409, "完整公开投影与实际冻结原件不符")
    if (row.status in {"draft", "rejected"} and public is not None) or (row.status == "published" and public is None):
        raise HTTPException(409, "实际发布状态缺少完整投影或混入未发布正文")
    result = {**value, "snapshot": snapshot, "public_source": public, "projection_hash": row.projection_hash}
    if not verify_original(result):
        raise HTTPException(409, "完整原件闭集、真实治理或公开投影证明无效")
    return result


def frozen_case_proof(db, identifier):
    """Internal current SQL proof only; the caller must authorize the full Case.

    This retains the original publication projection after revocation and does
    not claim the captured ledger is still current or eligible for a new run.
    No patient authorization is performed by this deliberately userless helper.
    """
    row = current_charge_rows(db.query(AIChargeCaseSnapshot).filter_by(case_snapshot_id=identifier), shared=True).one_or_none()
    if row is None:
        raise HTTPException(404, "住院账目原件不存在")
    return original_proof(row)


def case_current(db, user, identifier, *, audit_only=False, execution=False):
    if audit_only and execution:
        raise HTTPException(409, "冻结审计原件不能用于创建新任务")
    actor = current_actor(db, user, {"super_admin"} if audit_only else c.SOURCE_ROLES)
    locator = current_charge_rows(db.query(AIChargeCaseSnapshot.patient_id, AIChargeCaseSnapshot.admission_id).filter_by(case_snapshot_id=identifier), shared=True).one_or_none()
    if locator is None:
        raise HTTPException(404, "住院账目原件不存在")
    if not audit_only:
        authorize_scope(db, actor, c.CaptureRequest(patient_id=locator.patient_id, admission_id=locator.admission_id))
    row = current_charge_rows(db.query(AIChargeCaseSnapshot).filter_by(case_snapshot_id=identifier), shared=True).one_or_none()
    if row is None:
        raise HTTPException(404, "住院账目原件不存在")
    value = original_proof(row)
    same = False
    try:
        current = capture_case(db, actor, {"patient_id": row.patient_id, "admission_id": row.admission_id})
        same = current["collection_digest"] == row.collection_digest
    except HTTPException:
        if not audit_only:
            # Scope authorization must never be downgraded to a redacted success.
            authorize_scope(db, actor, c.CaptureRequest(patient_id=row.patient_id, admission_id=row.admission_id))
    eligible = row.status == "published" and same and not audit_only
    if execution and not eligible:
        raise HTTPException(409, "仅当前完整且已发布的住院账目原件可用于新任务")
    full = audit_only or same and row.status in {"draft", "published"}
    return {
        **value,
        "snapshot": value["snapshot"] if full else None,
        "public_source": value["public_source"] if full else None,
        "scope_current": same,
        "eligible": eligible,
        "audit_only": audit_only,
        "ineligibility_reasons": ([] if same else ["recorded_collection_changed_or_unavailable"])
        + ([] if row.status == "published" else ["case_not_published"])
        + (["frozen_audit_not_new_execution"] if audit_only else []),
        "can_record": True,
        "can_review": actor.user_role == "super_admin" and row.status == "draft" and same,
        "can_revoke": row.status in {"draft", "published"} and (actor.user_role == "super_admin" or actor.user_id == row.created_by),
        "review_basis_note": value["review_basis_note"] if full else None,
        "revoke_reason": value["revoke_reason"] if full else None,
    }


def write_transaction(fn):
    @functools.wraps(fn)
    def call(db, *args, **kwargs):
        try:
            return fn(db, *args, **kwargs)
        except HTTPException:
            db.rollback()
            raise
        except (ValueError, TypeError, KeyError, UnicodeError, SQLAlchemyError) as exc:
            db.rollback()
            raise HTTPException(409, "完整账目原件与本次治理审计未能原子保存") from exc

    return call


def finish(db, actor, row, action, detail, expected, actor_epoch):
    audit(db, actor.user_id, action, row.case_snapshot_id, detail)
    events = [item for item in db.new if hasattr(item, "action") and item.action == action and item.target == row.case_snapshot_id]
    if len(events) != 1:
        raise HTTPException(409, "本次具体审计不唯一")
    event = events[0]
    audit_expected = {key: getattr(event, key) for key in AUDIT_FIELDS}
    db.flush()
    actual = current_charge_rows(db.query(AIChargeCaseSnapshot).filter_by(case_snapshot_id=row.case_snapshot_id)).one()
    if any(getattr(actual, key) != value for key, value in expected.items()):
        raise HTTPException(409, "实际账目原件写入与本次完整提交不同")
    from app.ai.models import AIAuditEvent

    actual_event = db.query(*(getattr(AIAuditEvent, key) for key in AUDIT_FIELDS)).filter_by(event_id=event.event_id).with_for_update(read=True).one_or_none()
    if actual_event is None or dict(actual_event._mapping) != audit_expected:
        raise HTTPException(409, "本次实际治理审计缺失或改变")
    original_proof(actual)
    current = current_charge_actor(db, actor, {"super_admin"} if action.endswith("review") else c.SOURCE_ROLES)
    if (current.user_role, current.token_invalid_before) != actor_epoch:
        raise HTTPException(403, "本次原件治理期间真实身份或会话已改变")


@write_transaction
def create_case(db, user, values):
    request = typed(c.CaseCreate, values)
    actor = current_actor(db, user)
    actor_epoch = (actor.user_role, actor.token_invalid_before)
    collection = capture_case(db, actor, request.request)
    if collection["collection_digest"] != request.expected_collection_digest:
        raise HTTPException(409, "实际完整账目成员已改变，请重新捕获并明确核对")
    now = utcnow()
    snapshot = {
        "schema_version": "charge_case_snapshot_v1",
        "case_snapshot_id": str(uuid.uuid4()),
        "patient_id": request.request.patient_id,
        "admission_id": request.request.admission_id,
        "created_by": actor.user_id,
        "created_at": c.utc_text(now),
        "identity_secret": secrets.token_hex(32),
        "note": request.note,
        "collection": collection,
    }
    typed(c.CaseSnapshot, snapshot)
    bounded(snapshot)
    row = AIChargeCaseSnapshot(
        **{key: snapshot[key] for key in ("case_snapshot_id", "patient_id", "admission_id", "schema_version", "created_by")},
        created_at=now,
        collection_digest=collection["collection_digest"],
        snapshot_json=c.canonical_json(snapshot),
        content_hash=c.digest(snapshot),
        projection_json=None,
        projection_hash=None,
        status="draft",
        revision=1,
        reviewed_at=None,
        reviewed_by=None,
        review_basis_note="",
        revoked_at=None,
        revoked_by=None,
        revoke_reason="",
    )
    db.add(row)
    expected = {column.name: getattr(row, column.name) for column in row.__table__.columns}
    finish(db, actor, row, "charge.case.create", {"content_hash": row.content_hash, "collection_digest": row.collection_digest}, expected, actor_epoch)
    if capture_case(db, actor, request.request)["collection_digest"] != row.collection_digest:
        raise HTTPException(409, "保存期间实际完整账目已改变")
    return case_current(db, actor, row.case_snapshot_id)


def cas(row, request):
    value = metadata(row)
    if (row.revision, row.content_hash, value["governance_hash"]) != (request.expected_revision, request.expected_content_hash, request.expected_governance_hash):
        raise HTTPException(409, "原件治理版本已变化，请刷新")


@write_transaction
def review_case(db, user, identifier, values):
    request = typed(c.SourceReview, values)
    actor = current_actor(db, user, {"super_admin"})
    actor_epoch = (actor.user_role, actor.token_invalid_before)
    row = current_charge_rows(db.query(AIChargeCaseSnapshot).filter_by(case_snapshot_id=identifier)).one_or_none()
    if row is None:
        raise HTTPException(404, "原件不存在")
    cas(row, request)
    before = original_proof(row)
    if row.status != "draft" or capture_case(db, actor, before["snapshot"]["collection"]["request"])["collection_digest"] != row.collection_digest:
        raise HTTPException(409, "仅能审核当前完整draft账目原件")
    row.status, row.revision, row.reviewed_by, row.reviewed_at, row.review_basis_note = ("published" if request.decision == "publish" else "rejected"), 2, actor.user_id, utcnow(), request.basis_note
    if row.reviewed_at < row.created_at:
        raise HTTPException(409, "服务器审核时钟早于原件")
    if row.status == "published":
        public = bounded(c.project_snapshot(before["snapshot"], metadata(row)))
        row.projection_json, row.projection_hash = c.canonical_json(public), c.digest(public)
    expected = {column.name: getattr(row, column.name) for column in row.__table__.columns}
    finish(db, actor, row, "charge.case.review", {"decision": request.decision, "content_hash": row.content_hash}, expected, actor_epoch)
    if capture_case(db, actor, before["snapshot"]["collection"]["request"])["collection_digest"] != row.collection_digest:
        raise HTTPException(409, "审核期间完整账目已改变")
    return case_current(db, actor, identifier, audit_only=True)


@write_transaction
def revoke_case(db, user, identifier, values):
    request = typed(c.SourceRevoke, values)
    actor = current_actor(db, user)
    actor_epoch = (actor.user_role, actor.token_invalid_before)
    locator = current_charge_rows(db.query(AIChargeCaseSnapshot.patient_id, AIChargeCaseSnapshot.admission_id).filter_by(case_snapshot_id=identifier), shared=True).one_or_none()
    if locator is None:
        raise HTTPException(404, "原件不存在")
    authorize_scope(db, actor, c.CaptureRequest(patient_id=locator.patient_id, admission_id=locator.admission_id))
    row = current_charge_rows(db.query(AIChargeCaseSnapshot).filter_by(case_snapshot_id=identifier)).one_or_none()
    if row is None:
        raise HTTPException(404, "原件不存在")
    authorize_scope(db, actor, c.CaptureRequest(patient_id=row.patient_id, admission_id=row.admission_id))
    if actor.user_role != "super_admin" and actor.user_id != row.created_by:
        raise HTTPException(403, "仅原作者或Super可撤销")
    cas(row, request)
    original_proof(row)
    if row.status not in {"draft", "published"}:
        raise HTTPException(409, "原件当前不可撤销")
    row.status, row.revision, row.revoked_by, row.revoked_at, row.revoke_reason = "revoked", row.revision + 1, actor.user_id, utcnow(), request.basis_note
    expected = {column.name: getattr(row, column.name) for column in row.__table__.columns}
    finish(db, actor, row, "charge.case.revoke", {"content_hash": row.content_hash, "revision": row.revision}, expected, actor_epoch)
    return case_current(db, actor, identifier, audit_only=actor.user_role == "super_admin")
