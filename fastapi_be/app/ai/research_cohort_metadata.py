"""Opaque Case metadata hashes: SQL projects digests, never free notes.

The SQLite UDF is installed by the product helper on its actual connection.
MySQL constructs Python's canonical JSON string escaping directly; JSON_QUOTE's
control-character hex case is not assumed to match the original SHA contract.
"""

import datetime as dt
import hashlib
from types import SimpleNamespace

from sqlalchemy import String
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.sql.functions import FunctionElement

from app.ai.research_cohort_contract import canonical_json


class CanonicalNoteHash(FunctionElement):
    type = String(64)
    inherit_cache = True


class CanonicalCaseGovernanceHash(FunctionElement):
    type = String(64)
    inherit_cache = True


def _mysql_quote(expression):
    # Escape the ORIGINAL backslash first. Escaping lower-case \u00xx text
    # after JSON_QUOTE would accidentally change a literal backslash sequence.
    expression = f"REPLACE({expression},CHAR(92),CONCAT(CHAR(92),CHAR(92)))"
    expression = f"REPLACE({expression},CHAR(34),CONCAT(CHAR(92),CHAR(34)))"
    short = {8: "b", 9: "t", 10: "n", 12: "f", 13: "r"}
    for codepoint in range(32):
        replacement = short.get(codepoint, f"u{codepoint:04x}")
        expression = f"REPLACE({expression},CHAR({codepoint}),CONCAT(CHAR(92),'{replacement}'))"
    return f"CONCAT(CHAR(34),{expression},CHAR(34))"


@compiles(CanonicalNoteHash, "mysql")
def mysql_note_hash(element, compiler, **kwargs):
    expression = compiler.process(list(element.clauses)[0], **kwargs)
    return "LOWER(SHA2(" + _mysql_quote(expression) + ",256))"


@compiles(CanonicalNoteHash, "sqlite")
def sqlite_note_hash(element, compiler, **kwargs):
    return "research_canonical_note_hash(" + compiler.process(list(element.clauses)[0], **kwargs) + ")"


GOVERNANCE_KEYS = ("review_basis_note", "reviewed_at", "reviewed_by", "revision", "revoke_reason", "revoked_at", "revoked_by", "status")


def _mysql_clock(column):
    # The source columns are real DATETIME(6); this retains all six places,
    # including .000000. It does not convert a legacy clinical naive clock.
    text = f"CAST({column} AS CHAR)"
    rendered = f"CONCAT(SUBSTRING({text},1,10),'T',SUBSTRING({text},12),'Z')"
    return f"IF({column} IS NULL,'null',{_mysql_quote(rendered)})"


@compiles(CanonicalCaseGovernanceHash, "mysql")
def mysql_case_hash(element, compiler, **kwargs):
    columns = [compiler.process(clause, **kwargs) for clause in element.clauses]
    case_id, content, *fields = columns
    pieces = ["'{\"case_id\":'", _mysql_quote(case_id), "',\"content_hash\":'", _mysql_quote(content), "',\"governance\":{'"]
    for index, (key, column) in enumerate(zip(GOVERNANCE_KEYS, fields, strict=True)):
        pieces.append("'" + ("," if index else "") + '"' + key + '":' + "'")
        if key in {"review_basis_note", "revoke_reason", "status"}:
            pieces.append(_mysql_quote(column))
        elif key.endswith("_at"):
            pieces.append(_mysql_clock(column))
        else:
            pieces.append(f"IF({column} IS NULL,'null',CAST({column} AS CHAR))")
    pieces.append("'}}'")
    return "LOWER(SHA2(CONCAT(" + ",".join(pieces) + "),256))"


@compiles(CanonicalCaseGovernanceHash, "sqlite")
def sqlite_case_hash(element, compiler, **kwargs):
    return "research_canonical_case_governance_hash(" + ",".join(compiler.process(clause, **kwargs) for clause in element.clauses) + ")"


def install_metadata_functions(db):
    if db.get_bind().dialect.name != "sqlite":
        return
    connection = db.connection().connection.driver_connection

    def sha(value):
        return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()

    def governance(case_id, content, *fields):
        values = dict(zip(GOVERNANCE_KEYS, fields, strict=True))
        for key in ("reviewed_at", "revoked_at"):
            if values[key] is not None:
                values[key] = dt.datetime.fromisoformat(values[key]).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        return sha({"case_id": case_id, "content_hash": content, "governance": values})

    connection.create_function("research_canonical_note_hash", 1, sha, deterministic=True)
    connection.create_function("research_canonical_case_governance_hash", 10, governance, deterministic=True)

    def original_governance(fields, keys):
        values = dict(zip(keys, fields, strict=True))
        for key in keys:
            if key.endswith("_at") and values[key] is not None:
                values[key] = dt.datetime.fromisoformat(values[key]).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        return values

    def reviewed(*fields):
        return sha({"governance": original_governance(fields[:8], GOVERNANCE_KEYS), "authorization_review": original_governance(fields[8:], MANUAL_KEYS)})

    def acl(*fields):
        return sha({"governance": original_governance(fields, GOVERNANCE_KEYS), "authorization_review": None})

    connection.create_function("research_canonical_reviewed_governance_hash", 12, reviewed, deterministic=True)
    connection.create_function("research_canonical_acl_governance_hash", 8, acl, deterministic=True)


def case_metadata_query(db):
    from app.ai.research_cohort_models import AIResearchCohortCase

    model = AIResearchCohortCase

    install_metadata_functions(db)
    names = [column.name for column in model.__table__.columns if column.name not in {"snapshot_json", "projection_json", "review_basis_note", "revoke_reason"}]
    columns = [getattr(model, name) for name in names]
    columns.extend((CanonicalNoteHash(model.review_basis_note).label("review_basis_hash"), CanonicalNoteHash(model.revoke_reason).label("revoke_reason_hash")))
    columns.append(CanonicalCaseGovernanceHash(model.case_id, model.content_hash, *(getattr(model, key) for key in GOVERNANCE_KEYS)).label("governance_hash"))
    return db.query(*columns)


def metadata_namespace(value):
    return SimpleNamespace(**dict(value._mapping))


MANUAL_KEYS = ("authorization_review_basis", "authorization_review_status", "authorization_reviewed_at", "authorization_reviewed_by")


class CanonicalReviewedGovernanceHash(FunctionElement):
    type = String(64)
    inherit_cache = True


class CanonicalACLGovernanceHash(FunctionElement):
    type = String(64)
    inherit_cache = True


def _mysql_object(keys, columns):
    pieces = ["'{' "]
    for index, (key, column) in enumerate(zip(keys, columns, strict=True)):
        pieces.append("'" + ("," if index else "") + '"' + key + '":' + "'")
        if key in {"review_basis_note", "revoke_reason", "status", "authorization_review_basis", "authorization_review_status"}:
            pieces.append(_mysql_quote(column))
        elif key.endswith("_at"):
            pieces.append(_mysql_clock(column))
        else:
            pieces.append(f"IF({column} IS NULL,'null',CAST({column} AS CHAR))")
    pieces.append("'}'")
    return "CONCAT(" + ",".join(pieces) + ")"


@compiles(CanonicalReviewedGovernanceHash, "mysql")
def mysql_reviewed_hash(element, compiler, **kwargs):
    fields = [compiler.process(clause, **kwargs) for clause in element.clauses]
    governance = _mysql_object(GOVERNANCE_KEYS, fields[:8])
    manual = _mysql_object(MANUAL_KEYS, fields[8:])
    return "LOWER(SHA2(CONCAT('{\"authorization_review\":'," + manual + ",',\"governance\":'," + governance + ",'}'),256))"


@compiles(CanonicalACLGovernanceHash, "mysql")
def mysql_acl_hash(element, compiler, **kwargs):
    fields = [compiler.process(clause, **kwargs) for clause in element.clauses]
    return 'LOWER(SHA2(CONCAT(\'{"authorization_review":null,"governance":\',' + _mysql_object(GOVERNANCE_KEYS, fields) + ",'}'),256))"


@compiles(CanonicalReviewedGovernanceHash, "sqlite")
def sqlite_reviewed_hash(element, compiler, **kwargs):
    return "research_canonical_reviewed_governance_hash(" + ",".join(compiler.process(clause, **kwargs) for clause in element.clauses) + ")"


@compiles(CanonicalACLGovernanceHash, "sqlite")
def sqlite_acl_hash(element, compiler, **kwargs):
    return "research_canonical_acl_governance_hash(" + ",".join(compiler.process(clause, **kwargs) for clause in element.clauses) + ")"


def registry_hash_expression(model, *, manual):
    args = [getattr(model, key) for key in GOVERNANCE_KEYS]
    if manual:
        return CanonicalReviewedGovernanceHash(*args, *(getattr(model, key) for key in MANUAL_KEYS)).label("governance_hash")
    return CanonicalACLGovernanceHash(*args).label("governance_hash")
