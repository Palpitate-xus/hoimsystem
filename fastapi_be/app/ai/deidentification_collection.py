"""Single authorized patient's complete finite candidate manifest for use75.

This never calls the cohort collector's default74 purpose. All bodies are read
only after current project and patient authorization with the explicit75 use.
Nonselected registry bodies stay opaque SQL byte hashes, never model text.
"""

import datetime as dt
import hashlib

from fastapi import HTTPException
from pydantic import TypeAdapter
from sqlalchemy import Date, DateTime, Integer, String, Text, func, or_

from app.ai.deidentification_access import authorize_subject
from app.ai.deidentification_contract import MAX_BYTES, MAX_ROOTS, SOURCE_ROLES, TEXT_FIELDS, CaptureRequest, PatientScopeRequest
from app.ai.deidentification_spans import canonical, digest, document, text_digest, utf8
from app.ai.research_cohort_collection import FAMILY_CLOCKS, FAMILY_COLUMNS, FAMILY_KEYS, _models, _parent_locator
from app.ai.research_cohort_contract import SHA, UTC, Positive
from app.ai.research_cohort_models import AIResearchPatientAuthorization, AIResearchProjectACL
from app.ai.research_cohort_registry import verify_registry_proof
from app.ai.research_cohort_sources import _typed, utc_text, utcnow, verify_scope_proof
from app.ai.research_cohort_write_guard import current_research_rows, lock_research_write


class Budget:
    def __init__(self):
        self.roots = 0
        self.bytes = 0

    def add(self, value, *, root=True):
        self.roots += int(root)
        self.bytes += len(utf8(canonical(value)))
        if self.roots > MAX_ROOTS or self.bytes > MAX_BYTES:
            raise HTTPException(413, "完整选定领域超过8192根或8MiB，未截断或只选有利成员")


def _sql_hash(db, field):
    if db.get_bind().dialect.name == "mysql":
        return func.sha2(field, 256)
    if db.get_bind().dialect.name == "sqlite":
        raw = db.connection().connection.driver_connection
        raw.create_function("deid_sha256_utf8", 1, lambda v: hashlib.sha256(v.encode("utf-8", errors="strict")).hexdigest() if type(v) is str else None, deterministic=True)
        return func.deid_sha256_utf8(field)
    raise HTTPException(409, "未声明的数据库类型，未猜测原件字节摘要")


def _literal(value):
    if isinstance(value, dt.datetime):
        if value.tzinfo is not None:
            raise HTTPException(409, "旧时间时区依据未知，未自动转换")
        return value.isoformat(timespec="microseconds")
    if isinstance(value, dt.date):
        return value.isoformat()
    if value is None or type(value) in {str, int}:
        if type(value) is str:
            utf8(value)
        return value
    raise HTTPException(409, "实际字段类型不在明确来源约束内")


def authority_manifest(db, scope_id, budget):
    result, users = [], set()
    for kind, model, key in (("acl", AIResearchProjectACL, "acl_id"), ("authorization", AIResearchPatientAuthorization, "authorization_id")):
        names = [
            key,
            "scope_id",
            "schema_version",
            "content_hash",
            "status",
            "revision",
            "created_by",
            "created_at",
            "reviewed_by",
            "reviewed_at",
            "revoked_by",
            "revoked_at",
            "valid_from",
            "valid_until",
        ]
        names += (
            ["user_id", "permission"]
            if kind == "acl"
            else ["patient_id", "authorization_kind", "access_basis", "authorization_review_status", "authorization_reviewed_by", "authorization_reviewed_at"]
        )
        hashes = ["payload_json", "parent_binding_json", "review_basis_note", "revoke_reason"] + (["authorization_review_basis"] if kind == "authorization" else [])
        cursor = None
        while True:
            query = db.query(*(getattr(model, n) for n in names), *(_sql_hash(db, getattr(model, n)).label(n + "_hash") for n in hashes)).filter_by(scope_id=scope_id)
            if cursor is not None:
                query = query.filter(getattr(model, key) > cursor)
            rows = current_research_rows(query.order_by(getattr(model, key)), shared=True).limit(32).all()
            if not rows:
                break
            for row in rows:
                raw = {
                    n: utc_text(v) if n in {"created_at", "reviewed_at", "revoked_at", "valid_from", "valid_until", "authorization_reviewed_at"} else _literal(v)
                    for n, v in zip(names + [n + "_hash" for n in hashes], row, strict=True)
                }
                for field in ["content_hash", *[n + "_hash" for n in hashes]]:
                    TypeAdapter(SHA).validate_python(raw[field], strict=True)
                for field in ("created_by", "reviewed_by", "revoked_by", "authorization_reviewed_by", "user_id"):
                    if raw.get(field) is not None:
                        users.add(raw[field])
                entry = {"kind": kind, "source_record_id": raw[key], "metadata": raw}
                budget.add(entry)
                result.append(entry)
                cursor = raw[key]
    return result, users


def _actors(db, identifiers, budget):
    from app.models import User

    result = []
    for identifier in sorted(identifiers):
        row = current_research_rows(db.query(User.user_id, User.user_role, User.token_invalid_before).filter_by(user_id=identifier), shared=True).one_or_none()
        value = {"user_id": identifier, "exists": row is not None, "role": row.user_role if row else None, "token_invalid_before": _literal(row.token_invalid_before) if row else None}
        budget.add(value)
        result.append(value)
    return result


def _rows(db, model, key, where, columns):
    cursor = None
    while True:
        query = db.query(getattr(model, key)).filter(*where)
        if cursor is not None:
            query = query.filter(getattr(model, key) > cursor)
        ids = current_research_rows(query.order_by(getattr(model, key)), shared=True).limit(32).all()
        if not ids:
            return
        for entry in ids:
            identifier = entry[0]
            # Reapply the patient/window boundary to the body SELECT itself.
            # A changed locator never causes reading another patient's text.
            row = current_research_rows(db.query(*(getattr(model, n) for n in columns)).filter(getattr(model, key) == identifier, *where)).one_or_none()
            if row is None:
                raise HTTPException(409, "候选定位后当前患者或窗口边界变化，未读取外域正文")
            yield {n: _literal(v) for n, v in zip(columns, row, strict=True)}
            cursor = identifier


def _scope(db, user, request, *, capture, external_model):
    actor = lock_research_write(db, user, allowed_roles=SOURCE_ROLES)
    actor, acl, authorization = authorize_subject(db, actor, request.scope_id, request.patient_id, capture=capture, external_model=external_model)
    scope = acl["parent_binding"]["scope"]
    if (scope["content_hash"], scope["governance_hash"]) != (request.scope_content_hash, request.scope_governance_hash):
        raise HTTPException(409, "明确项目三锚已变化，未使用新版本偷偷补权")
    return actor, scope, acl, authorization


def capture_sources(db, user, values, *, selections=True, external_model=False):
    model = CaptureRequest if selections else PatientScopeRequest
    request = _typed(model, values)
    actor, scope, acl, authorization = _scope(db, user, request, capture=True, external_model=external_model)
    lock_research_write(db, actor, allowed_roles=SOURCE_ROLES, scope_ids=(request.scope_id,), patient_ids=(request.patient_id,))
    fresh_actor, fresh_scope, fresh_acl, fresh_authorization = _scope(db, actor, request, capture=True, external_model=external_model)
    if (fresh_scope, fresh_acl, fresh_authorization) != (scope, acl, authorization):
        raise HTTPException(409, "当前患者父锁后项目或逐患者授权变化")
    actor = fresh_actor
    if selections and any(x.family not in scope["payload"]["data_families"] for x in request.documents):
        raise HTTPException(403, "明确文书类型不在项目声明字段领域中")
    budget = Budget()
    for proof in (scope, acl, authorization):
        budget.add(proof)
    authorities, users = authority_manifest(db, request.scope_id, budget)
    users.update((actor.user_id, scope["identity"]["created_by"]))
    users.update(x for x in (scope["governance"]["reviewed_by"], scope["authorization_review"]["authorization_reviewed_by"]) if x is not None)
    actors = _actors(db, users, budget)
    period = scope["payload"]["record_window"]
    start = dt.datetime.fromisoformat(period["date_from"])
    end = dt.datetime.fromisoformat(period["date_to"]) + dt.timedelta(days=1)
    chosen = {(x.family, x.record_id) for x in request.documents} if selections else set()
    manifest, originals, available = [], [], []
    for family in scope["payload"]["data_families"]:
        model, key = _models()[family], FAMILY_KEYS[family]
        conditions = [model.patient_id == request.patient_id]
        if family in FAMILY_CLOCKS:
            clock = getattr(model, FAMILY_CLOCKS[family])
            conditions.append(or_(clock.is_(None), (clock >= start) & (clock < end)))
        for raw in _rows(db, model, key, conditions, FAMILY_COLUMNS[family]):
            parent = _parent_locator(db, family, raw, request.patient_id, locking=True)
            status = "unknown_clock" if family in FAMILY_CLOCKS and raw[FAMILY_CLOCKS[family]] is None else "recorded_calendar_in_scope"
            entry = {"family": family, "record_id": raw[key], "original_hash": digest(raw), "parent_binding": parent, "window_status": status}
            budget.add(entry)
            budget.add(raw, root=False)
            manifest.append(entry)
            if (family, raw[key]) in chosen:
                originals.append({**entry, "original": raw})
            for field in TEXT_FIELDS.get(family, ()):
                value = document("selected", field, raw[field])
                choice = {
                    **entry,
                    "field": field,
                    "text_state": "not_recorded" if raw[field] is None else "recorded_empty" if raw[field] == "" else "recorded",
                    "utf8_bytes": value["utf8_bytes"],
                    "codepoint_length": value["codepoint_length"],
                }
                budget.add(choice, root=False)
                available.append(choice)
    selected = []
    by_id = {(r["family"], r["record_id"]): r for r in originals}
    if selections:
        for index, selection in enumerate(request.documents):
            entry = by_id.get((selection.family, selection.record_id))
            if entry is None:
                raise HTTPException(409, "明确原文已缺失或不在当前患者与项目窗口内")
            if entry["original_hash"] != selection.expected_original_hash:
                raise HTTPException(409, "明确完整原文已改变，未偷偷采用新文字")
            if entry["parent_binding"]["status"] != "patient_bound" or entry["window_status"] != "recorded_calendar_in_scope":
                raise HTTPException(409, "当前父件或窗口依据未知/冲突，未导出未闭合正文")
            selected.append({"locator": selection.model_dump(), "document": document("selected_document:" + str(index), selection.field, entry["original"][selection.field])})
    body = {
        "schema_version": "deidentification_capture_v1",
        "purpose": "deidentification_review",
        "request": request.model_dump(),
        "actor_id": actor.user_id,
        "scope_original": scope,
        "actor_acl": acl,
        "patient_authorization": authorization,
        "authorization_manifest": authorities,
        "authority_actors": actors,
        "supported_columns": {f: list(FAMILY_COLUMNS[f]) for f in scope["payload"]["data_families"]},
        "member_manifest": manifest,
        "selected_originals": originals,
        "selected_documents": selected,
        "manifest_hash": digest(manifest),
    }
    value = {**body, "captured_at": utc_text(utcnow()), "collection_digest": digest(body)}
    if len(utf8(canonical(value))) > MAX_BYTES:
        raise HTTPException(413, "完整来源连同所选全文与权限锚超过8MiB，未截断")
    return value, available


def _validate_raw(family, raw):
    model = _models()[family]
    if type(raw) is not dict or set(raw) != set(FAMILY_COLUMNS[family]):
        raise ValueError("Closed actual clinical field set required")
    for name, value in raw.items():
        if value is None:
            continue
        column = model.__table__.c[name]
        if isinstance(column.type, Integer):
            if type(value) is not int:
                raise ValueError("Actual integer scalar required")
        elif isinstance(column.type, DateTime):
            if type(value) is not str or dt.datetime.fromisoformat(value).tzinfo is not None or dt.datetime.fromisoformat(value).isoformat(timespec="microseconds") != value:
                raise ValueError("Actual naive microsecond representation required")
        elif isinstance(column.type, Date):
            if type(value) is not str or dt.date.fromisoformat(value).isoformat() != value:
                raise ValueError("Actual calendar date required")
        elif isinstance(column.type, (String, Text)):
            if type(value) is not str:
                raise ValueError("Actual text scalar required")
            utf8(value)
        else:
            raise ValueError("Unsupported original SQL field type")


def verify_capture(value):
    """Own selected raw integrity; nonselected original body hashes are opaque.

    Fresh SQL whole collection comparison separately proves currentness. A
    hash of an undisclosed body is never claimed to reconstruct its full text.
    """
    from app.ai.deidentification_spans import verify_document

    try:
        keys = {
            "schema_version",
            "purpose",
            "request",
            "actor_id",
            "scope_original",
            "actor_acl",
            "patient_authorization",
            "authorization_manifest",
            "authority_actors",
            "supported_columns",
            "member_manifest",
            "selected_originals",
            "selected_documents",
            "manifest_hash",
            "captured_at",
            "collection_digest",
        }
        if (
            type(value) is not dict
            or set(value) != keys
            or value["schema_version"] != "deidentification_capture_v1"
            or value["purpose"] != "deidentification_review"
            or len(utf8(canonical(value))) > MAX_BYTES
        ):
            raise ValueError("Closed whole capture required")
        request = CaptureRequest.model_validate(value["request"])
        TypeAdapter(Positive).validate_python(value["actor_id"], strict=True)
        TypeAdapter(UTC).validate_python(value["captured_at"], strict=True)
        scope = verify_scope_proof(value["scope_original"])
        acl = verify_registry_proof("acl", value["actor_acl"])
        permission = verify_registry_proof("authorization", value["patient_authorization"])
        if (request.scope_id, request.scope_content_hash, request.scope_governance_hash) != (scope["identity"]["scope_id"], scope["content_hash"], scope["governance_hash"]):
            raise ValueError("Exact original project anchors required")
        if "deidentification_review" not in scope["payload"]["permitted_uses"] or request.patient_id not in scope["payload"]["patient_ids"]:
            raise ValueError("Captured purpose and patient must be explicit")
        if acl["identity"]["user_id"] != value["actor_id"] or acl["identity"]["permission"] != "read_capture" or permission["identity"]["patient_id"] != request.patient_id:
            raise ValueError("Explicit actor grant and exact patient required")
        for proof in (scope, acl, permission):
            if proof is not scope and proof["parent_binding"]["scope"] != scope:
                raise ValueError("Exact frozen parent project required")
            identity = proof["identity"]
            if (
                proof["governance"]["status"] != "published"
                or proof["governance"]["reviewed_at"] > value["captured_at"]
                or identity["valid_from"] is None
                or not identity["valid_from"] <= value["captured_at"] < identity["valid_until"]
            ):
                raise ValueError("A real valid publication must precede capture")
        if (
            permission["identity"]["authorization_kind"] not in {"permission_recorded", "waiver_recorded"}
            or permission["authorization_review"]["authorization_review_status"] != "recorded_reviewed"
            or scope["authorization_review"]["authorization_review_status"] != "recorded_reviewed"
        ):
            raise ValueError("Independent documentary review is not technical publication")
        if value["supported_columns"] != {f: list(FAMILY_COLUMNS[f]) for f in scope["payload"]["data_families"]}:
            raise ValueError("Exact supported recorded columns required")
        previous, manifest = None, {}
        for entry in value["member_manifest"]:
            if type(entry) is not dict or set(entry) != {"family", "record_id", "original_hash", "parent_binding", "window_status"}:
                raise ValueError("Closed complete candidate metadata required")
            key = (entry["family"], entry["record_id"])
            if entry["family"] not in value["supported_columns"] or previous is not None and key <= previous:
                raise ValueError("Distinct sorted candidate metadata required")
            TypeAdapter(SHA).validate_python(entry["original_hash"], strict=True)
            parent = entry["parent_binding"]
            if (
                type(parent) is not dict
                or set(parent) != {"kind", "status", "technical_hash"}
                or parent["status"] not in {"patient_bound", "unknown_parent", "missing_parent", "patient_mismatch"}
                or entry["window_status"] not in {"unknown_clock", "recorded_calendar_in_scope"}
            ):
                raise ValueError("Typed actual parent/window evidence required")
            TypeAdapter(SHA).validate_python(parent["technical_hash"], strict=True)
            manifest[key], previous = entry, key
        if "patient_demographics" in scope["payload"]["data_families"] and [key for key in manifest if key[0] == "patient_demographics"] != [("patient_demographics", request.patient_id)]:
            raise ValueError("The actual authorized Patient singleton cannot disappear from the declared domain")
        if value["manifest_hash"] != digest(value["member_manifest"]):
            raise ValueError("Whole manifest hash required")
        originals = {}
        for entry in value["selected_originals"]:
            raw = entry["original"]
            meta = {k: v for k, v in entry.items() if k != "original"}
            key = (entry["family"], entry["record_id"])
            _validate_raw(entry["family"], raw)
            if key in originals or meta != manifest[key] or digest(raw) != entry["original_hash"] or raw["patient_id"] != request.patient_id or raw[FAMILY_KEYS[entry["family"]]] != entry["record_id"]:
                raise ValueError("Every disclosed complete original must match its manifest")
            originals[key] = entry
        if set(originals) != {(x.family, x.record_id) for x in request.documents} or len(value["selected_documents"]) != len(request.documents):
            raise ValueError("Complete explicit selected field set required")
        for index, (selection, item) in enumerate(zip(request.documents, value["selected_documents"], strict=True)):
            raw = originals[(selection.family, selection.record_id)]
            if item != {"locator": selection.model_dump(), "document": document("selected_document:" + str(index), selection.field, raw["original"][selection.field])} or not verify_document(
                item["document"]
            ):
                raise ValueError("Original field text/UTF8/CP/hash differs")
            parent_kind = "registration_uuid" if selection.family == "medical_records" else "admission_id" if selection.family == "structured_medical_records" else "direct_patient_fk"
            expected_parent = {
                "kind": parent_kind,
                "status": "patient_bound",
                "technical_hash": digest({"patient_id": request.patient_id})
                if parent_kind == "direct_patient_fk"
                else digest({parent_kind: raw["original"][parent_kind], "exists": True, "patient_id": request.patient_id}),
            }
            clock = raw["original"][FAMILY_CLOCKS[selection.family]]
            if (
                selection.family not in scope["payload"]["data_families"]
                or clock is None
                or not scope["payload"]["record_window"]["date_from"] <= clock[:10] <= scope["payload"]["record_window"]["date_to"]
            ):
                raise ValueError("Exact declared legacy calendar/family required")
            if raw["original_hash"] != selection.expected_original_hash or raw["parent_binding"] != expected_parent or raw["window_status"] != "recorded_calendar_in_scope":
                raise ValueError("Unknown/mismatched source parents cannot become a selected known field")
        _verify_safe_authorities(value, scope, acl, permission)
        body = {k: v for k, v in value.items() if k not in {"captured_at", "collection_digest"}}
        if value["collection_digest"] != digest(body):
            raise ValueError("Whole capture digest differs")
        return value
    except (ValueError, TypeError, KeyError, AttributeError, HTTPException, UnicodeError) as exc:
        raise HTTPException(409, "完整75来源、明确用途、原文字段或权限集合证明无法核对") from exc


def _verify_safe_authorities(value, scope, acl, permission):
    seen, required_users, previous_key = {}, {value["actor_id"], scope["identity"]["created_by"]}, None
    required_users.update(x for x in (scope["governance"]["reviewed_by"], scope["authorization_review"]["authorization_reviewed_by"]) if x is not None)
    common = {
        "scope_id",
        "schema_version",
        "content_hash",
        "status",
        "revision",
        "created_by",
        "created_at",
        "reviewed_by",
        "reviewed_at",
        "revoked_by",
        "revoked_at",
        "valid_from",
        "valid_until",
        "payload_json_hash",
        "parent_binding_json_hash",
        "review_basis_note_hash",
        "revoke_reason_hash",
    }
    for item in value["authorization_manifest"]:
        if type(item) is not dict or set(item) != {"kind", "source_record_id", "metadata"} or item["kind"] not in {"acl", "authorization"}:
            raise ValueError("Closed authority metadata required")
        kind = item["kind"]
        key = (kind, item["source_record_id"])
        if key in seen or previous_key is not None and key <= previous_key:
            raise ValueError("Distinct sorted authority roots required")
        previous_key = key
        raw = item["metadata"]
        fields = (
            {"acl_id", "user_id", "permission"}
            if kind == "acl"
            else {
                "authorization_id",
                "patient_id",
                "authorization_kind",
                "access_basis",
                "authorization_review_status",
                "authorization_reviewed_by",
                "authorization_reviewed_at",
                "authorization_review_basis_hash",
            }
        )
        if (
            type(raw) is not dict
            or set(raw) != common | fields
            or raw["scope_id"] != scope["identity"]["scope_id"]
            or raw["acl_id" if kind == "acl" else "authorization_id"] != item["source_record_id"]
        ):
            raise ValueError("Exact safe kind-specific authority metadata required")
        from app.ai.research_cohort_contract import UUID

        TypeAdapter(UUID).validate_python(item["source_record_id"], strict=True)
        if raw["schema_version"] != ("research_project_acl_v1" if kind == "acl" else "research_patient_auth_v1"):
            raise ValueError("Exact original schema required")
        for name, text in raw.items():
            if name.endswith("_hash"):
                TypeAdapter(SHA).validate_python(text, strict=True)
            if name.endswith("_at") or name in {"valid_from", "valid_until"}:
                if text is not None:
                    TypeAdapter(UTC).validate_python(text, strict=True)
        for name in ("created_by", "reviewed_by", "revoked_by", "authorization_reviewed_by", "user_id", "patient_id"):
            if name in raw and raw[name] is not None:
                TypeAdapter(Positive).validate_python(raw[name], strict=True)
                if name != "patient_id":
                    required_users.add(raw[name])
        if type(raw["revision"]) is not int or raw["status"] not in {"draft", "published", "rejected", "revoked"}:
            raise ValueError("Literal closed governance required")
        if raw["status"] == "draft" and raw["revision"] != 1 or raw["status"] in {"published", "rejected"} and raw["revision"] != 2 or raw["status"] == "revoked" and raw["revision"] not in {2, 3}:
            raise ValueError("Original revision/status differs")
        if (
            kind == "acl"
            and raw["permission"] not in {"read_only", "read_capture"}
            or kind == "authorization"
            and (
                raw["authorization_kind"] not in {"permission_recorded", "waiver_recorded", "unknown", "withdrawn", "denied"}
                or raw["access_basis"] not in {"explicit_project_acl", "current_care_or_grant"}
                or raw["authorization_review_status"] not in {"unknown", "recorded_reviewed", "not_confirmed"}
            )
        ):
            raise ValueError("Original technical states are closed, unknown is not permission")
        seen[key] = raw
    for kind, proof in (("acl", acl), ("authorization", permission)):
        raw = seen.get((kind, proof["identity"]["source_record_id"]))
        if raw is None:
            raise ValueError("Chosen positive authority cannot disappear from whole manifest")
        expected = {k: v for k, v in proof["identity"].items() if k not in {"source_kind", "source_record_id"}}
        expected["acl_id" if kind == "acl" else "authorization_id"] = proof["identity"]["source_record_id"]
        expected.update({k: v for k, v in proof["governance"].items() if k not in {"review_basis_note", "revoke_reason"}})
        expected.update(
            content_hash=proof["content_hash"],
            payload_json_hash=text_digest(canonical(proof["payload"])),
            parent_binding_json_hash=text_digest(canonical(proof["parent_binding"])),
            review_basis_note_hash=text_digest(proof["governance"]["review_basis_note"]),
            revoke_reason_hash=text_digest(proof["governance"]["revoke_reason"]),
        )
        if kind == "authorization":
            expected.update({k: v for k, v in proof["authorization_review"].items() if k != "authorization_review_basis"})
            expected["authorization_review_basis_hash"] = text_digest(proof["authorization_review"]["authorization_review_basis"])
        if raw != expected:
            raise ValueError("Disclosed authority must mechanically match every frozen metadata/hash field")
    previous = 0
    actual_users = set()
    for actor in value["authority_actors"]:
        if type(actor) is not dict or set(actor) != {"user_id", "exists", "role", "token_invalid_before"} or type(actor["exists"]) is not bool:
            raise ValueError("Typed actual actor metadata required")
        TypeAdapter(Positive).validate_python(actor["user_id"], strict=True)
        if actor["user_id"] <= previous:
            raise ValueError("Distinct sorted actors required")
        if actor["exists"]:
            if type(actor["role"]) is not str or not actor["role"] or len(actor["role"]) > 64:
                raise ValueError("Actual role string required")
            if actor["token_invalid_before"] is not None:
                clock = actor["token_invalid_before"]
                if type(clock) is not str or dt.datetime.fromisoformat(clock).tzinfo is not None or dt.datetime.fromisoformat(clock).isoformat(timespec="microseconds") != clock:
                    raise ValueError("Literal legacy token clock required")
        elif actor["role"] is not None or actor["token_invalid_before"] is not None:
            raise ValueError("Missing actor cannot have an invented current role")
        actual_users.add(actor["user_id"])
        previous = actor["user_id"]
    if actual_users != required_users:
        raise ValueError("Complete authority actor set required")
    if 3 + len(value["member_manifest"]) + len(value["authorization_manifest"]) + len(value["authority_actors"]) > MAX_ROOTS:
        raise ValueError("Complete root budget")
