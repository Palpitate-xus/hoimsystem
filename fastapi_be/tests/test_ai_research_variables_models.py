"""Physical dictionary/batch constraints; placeholder JSON grants no Source rights."""

import datetime as dt
import json
import uuid

import pytest
from sqlalchemy import ForeignKeyConstraint, text
from sqlalchemy.dialects import mysql
from sqlalchemy.exc import IntegrityError
from sqlalchemy.schema import CreateTable

from app.ai.models import AIAuditEvent
from app.ai.research_variables_models import MAX_BYTES, RESEARCH_VARIABLE_MODELS, AIResearchVariableBatch, AIResearchVariableDictionary
from tests.test_ai_research_cohort_models import draft, scope_row

NOW = dt.datetime(2026, 10, 21, 12, 0, 0, 123456)


@pytest.fixture(autouse=True)
def physical_foreign_keys(db_session):
    previous = db_session.execute(text("PRAGMA foreign_keys")).scalar_one()
    db_session.execute(text("PRAGMA foreign_keys=ON"))
    assert db_session.execute(text("PRAGMA foreign_keys")).scalar_one() == 1
    try:
        yield
    finally:
        db_session.rollback()
        db_session.execute(text("PRAGMA foreign_keys=" + str(previous)))
        db_session.commit()


@pytest.fixture
def physical_rows(db_session, seed_data):
    db = db_session
    creator = seed_data["admin_user"].user_id
    scope = scope_row(creator)
    audit = AIAuditEvent(actor_id=creator, action="synthetic_physical_fixture", target="no-source-authorization", detail_json="{}", create_time=NOW)
    db.add_all([scope, audit])
    db.flush()
    common = dict(**draft(creator), created_event_id=audit.event_id, last_event_id=audit.event_id)
    dictionary = AIResearchVariableDictionary(
        dictionary_id=str(uuid.uuid4()),
        scope_id=scope.scope_id,
        dictionary_json="{}",
        parent_binding_json="{}",
        content_hash="a" * 64,
        scope_content_hash="b" * 64,
        scope_governance_hash="c" * 64,
        definition_review_status="unknown",
        definition_reviewed_by=None,
        definition_reviewed_at=None,
        definition_review_basis="",
        **common,
    )
    db.add(dictionary)
    db.flush()
    batch = AIResearchVariableBatch(
        batch_id=str(uuid.uuid4()),
        scope_id=scope.scope_id,
        dictionary_id=dictionary.dictionary_id,
        snapshot_json="{}",
        projection_json="{}",
        identity_key=b"x" * 32,
        **{
            name: "d" * 64
            for name in (
                "content_hash",
                "projection_hash",
                "collection_digest",
                "member_manifest_hash",
                "scope_content_hash",
                "scope_governance_hash",
                "dictionary_content_hash",
                "dictionary_governance_hash",
            )
        },
        **common,
    )
    db.add(batch)
    db.commit()
    return dictionary, batch


def test_mysql_compilation_preserves_whole_text_clocks_and_exact_audit_foreign_keys():
    tables = [m.__table__ for m in RESEARCH_VARIABLE_MODELS]
    ddls = [str(CreateTable(t).compile(dialect=mysql.dialect())) for t in tables]
    assert sum(ddl.count("DATETIME(6)") for ddl in ddls) == 7
    assert sum(ddl.count("MEDIUMTEXT") for ddl in ddls) == 4
    assert sum(isinstance(c, ForeignKeyConstraint) for t in tables for c in t.constraints) == 14
    for table in tables:
        for field in ("created_event_id", "last_event_id"):
            assert {f.target_fullname for f in table.c[field].foreign_keys} == {"hoimsystem_ai_audit_event.event_id"}
        assert all(len(c.name or "") <= 64 for c in table.constraints)


@pytest.mark.parametrize("which,column", [(0, "dictionary_json"), (1, "snapshot_json"), (1, "projection_json")])
@pytest.mark.parametrize("extra", [0, 1])
def test_complete_unicode_json_is_retained_at_eight_mebibytes_and_one_byte_over_is_rejected(db_session, physical_rows, which, column, extra):
    # JSON framing is eight bytes. The non-ASCII payload distinguishes bytes
    # from character counts; the exact SQL round trip must retain every byte.
    body = json.dumps({"x": "汉" * ((MAX_BYTES - 8) // 3) + "x" * ((MAX_BYTES - 8) % 3 + extra)}, ensure_ascii=False, separators=(",", ":"))
    assert len(body.encode("utf-8")) == MAX_BYTES + extra
    row = physical_rows[which]
    setattr(row, column, body)
    if extra:
        with pytest.raises(IntegrityError):
            db_session.flush()
        db_session.rollback()
    else:
        db_session.commit()
        db_session.refresh(row)
        assert getattr(row, column) == body


@pytest.mark.parametrize(
    "which,field,value",
    [
        (0, "scope_id", "no-such-scope"),
        (1, "dictionary_id", "no-such-dictionary"),
        (0, "created_by", 2147483647),
        (1, "created_event_id", 2147483647),
        (0, "last_event_id", 2147483647),
        (0, "dictionary_json", "{bad}"),
        (0, "parent_binding_json", "[]" + " " * 262143),
        (1, "identity_key", b"x" * 31),
        (1, "identity_key", b"x" * 33),
        (0, "content_hash", "A" * 64),
        (1, "collection_digest", "g" * 64),
        (1, "member_manifest_hash", "a" * 63),
        (0, "status", "PUBLISHED"),
        (1, "revision", 2),
        (0, "review_basis_note", "unsigned review"),
    ],
)
def test_actual_sql_rejects_broken_parent_audit_hash_key_and_governance_anchors(db_session, physical_rows, which, field, value):
    setattr(physical_rows[which], field, value)
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


@pytest.mark.parametrize("change", ["self", "no_clock", "no_basis", "unknown_signed", "invented_status", "before_creation", "after_publication"])
def test_definition_review_is_a_distinct_complete_human_record(db_session, seed_data, physical_rows, change):
    row = physical_rows[0]
    row.definition_review_status = "recorded_reviewed"
    row.definition_reviewed_by = seed_data["director_user"].user_id
    row.definition_reviewed_at = NOW
    row.definition_review_basis = "隔离合成人工变量定义核查声明，不代表真实伦理或科学有效性认证。"
    if change == "self":
        row.definition_reviewed_by = row.created_by
    elif change == "no_clock":
        row.definition_reviewed_at = None
    elif change == "no_basis":
        row.definition_review_basis = ""
    elif change == "unknown_signed":
        row.definition_review_status = "unknown"
    elif change == "invented_status":
        row.definition_review_status = "scientifically_validated"
    elif change == "before_creation":
        row.definition_reviewed_at = NOW - dt.timedelta(microseconds=1)
    else:
        row.status, row.revision = "published", 2
        row.reviewed_by, row.reviewed_at, row.review_basis_note = row.created_by, NOW, "技术发布"
        row.definition_reviewed_at = NOW + dt.timedelta(microseconds=1)
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


def test_technical_publication_does_not_invent_definition_review_or_execution_authority(db_session, physical_rows):
    row = physical_rows[0]
    row.status, row.revision = "published", 2
    row.reviewed_by, row.reviewed_at, row.review_basis_note = row.created_by, NOW, "隔离合成技术发布。"
    db_session.commit()
    db_session.refresh(row)
    assert row.definition_review_status == "unknown"
    assert row.definition_reviewed_by is None and row.definition_reviewed_at is None


@pytest.mark.parametrize("change", ["missing_signature", "before_creation", "before_publication", "overlong_basis"])
def test_revocation_is_complete_and_chronological(db_session, physical_rows, change):
    row = physical_rows[1]
    row.status, row.revision = "revoked", 2
    row.revoked_by, row.revoked_at, row.revoke_reason = row.created_by, NOW, "隔离合成撤销"
    if change == "missing_signature":
        row.revoked_by = None
    elif change == "before_creation":
        row.revoked_at = NOW - dt.timedelta(microseconds=1)
    elif change == "before_publication":
        row.revision = 3
        row.reviewed_by, row.reviewed_at, row.review_basis_note = row.created_by, NOW + dt.timedelta(microseconds=1), "技术发布"
    else:
        row.revoke_reason = "汉" * 1334
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()
