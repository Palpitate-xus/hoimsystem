"""76 bounded metadata and separately authorized whole source parts.

A directory row is an opaque reference, never a current eligibility claim.
Normal directories conservatively authorize every original Scope patient
before any variable dictionary or Batch body. Technical directories contain
no definition, clinical text, review note, patient membership or eligibility.
"""

from fastapi import HTTPException
from pydantic import TypeAdapter

from app.ai.research_cohort_contract import UUID, ScopeReference
from app.ai.research_cohort_sources import _typed, utc_text
from app.ai.research_cohort_write_guard import current_research_rows, lock_research_write
from app.ai.research_variables_authority import authorize_variable_scope
from app.ai.research_variables_batches import batch_current
from app.ai.research_variables_dictionary import dictionary_current
from app.ai.research_variables_fields import VARIABLE_SOURCE_ROLES
from app.ai.research_variables_models import AIResearchVariableBatch, AIResearchVariableDictionary
from app.sql_counts import locked_row_count

COMMON_COLUMNS = (
    "scope_id",
    "scope_content_hash",
    "scope_governance_hash",
    "content_hash",
    "created_by",
    "created_at",
    "created_event_id",
    "last_event_id",
    "status",
    "revision",
    "reviewed_by",
    "reviewed_at",
    "revoked_by",
    "revoked_at",
)
DICTIONARY_COLUMNS = ("definition_review_status", "definition_reviewed_by", "definition_reviewed_at")
BATCH_COLUMNS = ("dictionary_id", "dictionary_content_hash", "dictionary_governance_hash", "projection_hash", "collection_digest", "member_manifest_hash")
KINDS = {
    "dictionary": (AIResearchVariableDictionary, "dictionary_id", DICTIONARY_COLUMNS),
    "batch": (AIResearchVariableBatch, "batch_id", BATCH_COLUMNS),
}


def _kind(kind):
    if kind not in KINDS:
        raise HTTPException(422, "须明确变量字典或变量批次来源")
    return KINDS[kind]


def _uuid(value):
    try:
        return TypeAdapter(UUID).validate_python(value, strict=True)
    except (ValueError, TypeError) as exc:
        raise HTTPException(422, "来源技术标识须为规范UUID") from exc


def _columns(kind):
    model, pk, extra = _kind(kind)
    return tuple(getattr(model, name) for name in (pk, *COMMON_COLUMNS, *extra))


def _header(db, kind, identifier):
    model, pk, _ = _kind(kind)
    identifier = _uuid(identifier)
    with db.no_autoflush:
        row = current_research_rows(db.query(*_columns(kind)).filter(getattr(model, pk) == identifier), shared=True).one_or_none()
    if row is None:
        raise HTTPException(404, "明确科研变量来源不存在")
    return row


def _metadata(row, kind, *, technical=False):
    _, pk, extra = _kind(kind)
    result = {
        name: (getattr(row, name) if isinstance(getattr(row, name), str) else utc_text(getattr(row, name))) if name.endswith("_at") else getattr(row, name) for name in (pk, *COMMON_COLUMNS, *extra)
    }
    result.update(
        schema_version="research_variable_source_metadata_v1",
        record_kind=kind,
        record_id=getattr(row, pk),
        technical_only=technical,
        body_included=False,
        detail_required=True,
        original=None,
        review_basis_note=None,
        revoke_reason=None,
    )
    if kind == "dictionary":
        result["definition_review_basis"] = None
    return result


def _scope_reference(row):
    return {name: getattr(row, name) for name in ("scope_id", "scope_content_hash", "scope_governance_hash")}


def source_metadata(db, user, kind, identifier, *, technical=False):
    """Only projected short columns; a successful GET does not select a source."""
    if type(technical) is not bool:
        raise HTTPException(422, "技术目录开关须为明确布尔值")
    actor = lock_research_write(db, user, allowed_roles={"super_admin"} if technical else VARIABLE_SOURCE_ROLES)
    row = _header(db, kind, identifier)
    if not technical:
        authorize_variable_scope(db, actor, _scope_reference(row))
    return _metadata(row, kind, technical=technical)


def list_sources(db, user, kind, *, scope_reference=None, technical=False, scope_id=None, status=None, page=1, size=20):
    """A bounded metadata page is not a truncated capture or patient cohort."""
    if type(technical) is not bool or type(page) is not int or not 1 <= page <= 100000 or type(size) is not int or not 1 <= size <= 100:
        raise HTTPException(422, "技术目录页码须为明确有界整数")
    if status is not None and status not in {"draft", "published", "rejected", "revoked"}:
        raise HTTPException(422, "来源状态须为明确治理状态")
    model, pk, _ = _kind(kind)
    actor = lock_research_write(db, user, allowed_roles={"super_admin"} if technical else VARIABLE_SOURCE_ROLES)
    if technical:
        if scope_reference is not None:
            raise HTTPException(422, "技术目录不接收临床项目授权声明")
        if scope_id is not None:
            scope_id = _uuid(scope_id)
    else:
        if scope_id is not None:
            raise HTTPException(422, "普通目录须明确完整项目三锚而非只给项目标识")
        request = _typed(ScopeReference, scope_reference)
        authorize_variable_scope(db, actor, request)
        scope_id = request.scope_id
    where = []
    if scope_id is not None:
        where.append(model.scope_id == scope_id)
    if status is not None:
        where.append(model.status == status)
    with db.no_autoflush:
        total = locked_row_count(current_research_rows(db.query(model).filter(*where), shared=True), getattr(model, pk), aggregate=True)
        query = db.query(*_columns(kind)).filter(*where).order_by(model.created_at.desc(), getattr(model, pk))
        rows = current_research_rows(query, shared=True).offset((page - 1) * size).limit(size).all()
    return {
        "schema_version": "research_variable_source_directory_v1",
        "items": [_metadata(row, kind, technical=technical) for row in rows],
        "page": page,
        "size": size,
        "total": total,
        "metadata_page_not_complete_source": True,
    }


def _packet_metadata(packet, kind):
    """Use the exact verified transaction receipt, without a later ORM reload."""
    from types import SimpleNamespace

    original = packet["original"]
    fields = {**original["identity"], **original["governance"], "content_hash": original["content_hash"], "last_event_id": original["last_event_id"]}
    if kind == "dictionary":
        fields.update(original["definition_review"])
        fields.update({name: original["payload"][name] for name in ("scope_content_hash", "scope_governance_hash")})
    else:
        snapshot = original["snapshot"]
        fields.update({name: snapshot["request"][name] for name in ("scope_content_hash", "scope_governance_hash", "dictionary_content_hash", "dictionary_governance_hash")})
        fields.update(projection_hash=original["projection_hash"], collection_digest=snapshot["collection_digest"], member_manifest_hash=snapshot["member_manifest_hash"])
    # The packet already contains exact UTC6 strings; do not parse and emit a
    # different lexical clock or perform a post-commit private-body query.
    _, pk, extra = _kind(kind)
    values = {name: fields[name] for name in (pk, *COMMON_COLUMNS, *extra)}
    return _metadata(SimpleNamespace(**values), kind)


def mutation_ack(packet, kind):
    """A short write ACK is never a full source or eligibility decision."""
    return {"schema_version": "research_variable_source_ack_v1", "metadata": _packet_metadata(packet, kind), "fresh_parts_required": True}


def read_source_part(db, user, kind, identifier, part):
    allowed = {"dictionary": {"definition", "scope"}, "batch": {"source", "snapshot"}}
    if kind not in allowed or part not in allowed[kind]:
        raise HTTPException(422, "来源须分别读取已声明的完整分件")
    packet = dictionary_current(db, user, identifier) if kind == "dictionary" else batch_current(db, user, identifier)
    original = packet["original"]
    result = {
        "schema_version": "research_variable_source_part_v1",
        "metadata": _packet_metadata(packet, kind),
        "part": part,
        "current_validation": {"eligible": packet["eligible"], "exclusion_reasons": packet["exclusion_reasons"], "eligibility_basis": packet["eligibility_basis"]},
    }
    if kind == "dictionary":
        if part == "definition":
            result["value"] = {name: value for name, value in original.items() if name != "parent_binding"}
        else:
            result["value"] = original["parent_binding"]
    elif part == "source":
        result["value"] = original["source"]
    else:
        result["value"] = {
            "snapshot": original["snapshot"],
            "proof": {name: value for name, value in original.items() if name not in {"snapshot", "source"}},
        }
    return result
