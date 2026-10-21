"""Actual isolated SQLite migration/FKs and MySQL DDL compilation only.

Minimal synthetic legacy parents preserve their complete DDL/rows. Loading the
real new model declarations uses a fresh Base, never hospital config or SQL.
No Source service, MySQL wait or already-authorized clinical read is claimed.
"""

import datetime as dt
import hashlib
import importlib.util
import json
import sys
import types
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy.dialects import mysql
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import declarative_base

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "alembic/versions/20261021_rca_evidence.py"
TABLES = ("hoimsystem_ai_rca_purpose_grant", "hoimsystem_ai_rca_evidence_original", "hoimsystem_ai_rca_evidence_case")
LEGACY = ("hoimsystem_users", "hoimsystem_patient", "hoimsystem_adverse_event", "hoimsystem_adverse_event_rca", "hoimsystem_ai_audit_event")
NOW = dt.datetime(2026, 10, 21, 12, 0, 0, 123456)


def module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


migration = module(PATH, "synthetic_rca_migration")


@pytest.fixture
def database():
    engine = sa.create_engine("sqlite:///:memory:")

    @sa.event.listens_for(engine, "connect")
    def foreign_keys(connection, record):
        connection.execute("PRAGMA foreign_keys=ON")

    with engine.connect() as db:
        db.exec_driver_sql("CREATE TABLE hoimsystem_users (user_id INTEGER PRIMARY KEY, username TEXT NOT NULL)")
        db.exec_driver_sql("CREATE TABLE hoimsystem_patient (patient_id INTEGER PRIMARY KEY, permission TEXT)")
        db.exec_driver_sql("CREATE TABLE hoimsystem_adverse_event (event_id INTEGER PRIMARY KEY, patient_id INTEGER REFERENCES hoimsystem_patient(patient_id), description TEXT)")
        db.exec_driver_sql("CREATE TABLE hoimsystem_adverse_event_rca (rca_id INTEGER PRIMARY KEY, event_id INTEGER NOT NULL REFERENCES hoimsystem_adverse_event(event_id), root_cause TEXT)")
        db.exec_driver_sql("CREATE TABLE hoimsystem_ai_audit_event (event_id INTEGER PRIMARY KEY, actor_id INTEGER REFERENCES hoimsystem_users(user_id), action TEXT)")
        db.exec_driver_sql("INSERT INTO hoimsystem_users VALUES (1,'synthetic_super'),(2,'synthetic_second')")
        db.exec_driver_sql("INSERT INTO hoimsystem_patient VALUES (1,'allow'),(2,NULL)")
        db.exec_driver_sql("INSERT INTO hoimsystem_adverse_event VALUES (1,1,'原始合成事件😀'),(2,NULL,NULL)")
        db.exec_driver_sql("INSERT INTO hoimsystem_adverse_event_rca VALUES (1,1,'原始RCA自由陈述并非已证因果')")
        for number in range(1, 21):
            db.execute(sa.text("INSERT INTO hoimsystem_ai_audit_event VALUES (:id,1,'synthetic_only')"), {"id": number})
        db.commit()
        yield db
    engine.dispose()


def apply(db, name):
    with Operations.context(MigrationContext.configure(db)):
        getattr(migration, name)()
    db.commit()


def snapshot(db):
    return {
        name: {
            "ddl": db.scalar(sa.text("SELECT sql FROM sqlite_master WHERE type='table' AND name=:name"), {"name": name}),
            "rows": [list(row) for row in db.execute(sa.text("SELECT * FROM " + name + " ORDER BY 1"))],
        }
        for name in LEGACY
    }


def table(db, name):
    return sa.Table(name, sa.MetaData(), autoload_with=db)


def grant(number=1, **changes):
    return {
        "grant_id": f"00000000-0000-0000-0000-{number:012d}",
        "event_id": 1,
        "patient_id_at_grant": 1,
        "grantee_id": 1,
        "permission_kind": "event_investigation",
        "purpose": "incident_rca",
        "grant_json": '{"private_basis":"synthetic"}',
        "content_hash": str(number) * 64,
        "issued_by": 1,
        "issued_at": NOW,
        "valid_until": NOW + dt.timedelta(days=1),
        "status": "active",
        "revision": 1,
        "revoked_by": None,
        "revoked_at": None,
        "revoke_reason": "",
        "created_audit_event_id": number,
        "revoked_audit_event_id": None,
        **changes,
    }


def draft(audit):
    return {
        "status": "draft",
        "revision": 1,
        "privacy_review": "unknown",
        "faithfulness_review": "unknown",
        "provenance_review": "unknown",
        "reviewed_by": None,
        "reviewed_at": None,
        "review_basis_note": "",
        "revoked_by": None,
        "revoked_at": None,
        "revoke_reason": "",
        "created_audit_event_id": audit,
        "reviewed_audit_event_id": None,
        "revoked_audit_event_id": None,
    }


def raw_payload():
    raw = json.dumps({"whole_original": "\ufeff原文\r\n😀" * 20000}, ensure_ascii=False, separators=(",", ":"))
    return raw, len(raw.encode()), hashlib.sha256(raw.encode()).hexdigest()


def original(**changes):
    raw, size, sha = raw_payload()
    return {
        "original_id": "00000000-0000-0000-0000-000000000010",
        "event_id": 1,
        "patient_id_at_capture": 1,
        "legacy_rca_id": None,
        "origin_kind": "manual_evidence",
        "original_json": raw,
        "json_bytes": size,
        "content_hash": sha,
        "created_by": 1,
        "recorded_at": NOW,
        **draft(3),
        **changes,
    }


def case(**changes):
    raw, size, sha = raw_payload()
    return {
        "case_id": "00000000-0000-0000-0000-000000000020",
        "event_id": 1,
        "patient_id_at_capture": 1,
        "event_grant_id": grant(1)["grant_id"],
        "patient_grant_id": grant(2)["grant_id"],
        "case_json": raw,
        "json_bytes": size,
        "member_count": 1,
        "collection_hash": "a" * 64,
        "content_hash": sha,
        "created_by": 1,
        "recorded_at": NOW,
        **draft(4),
        **changes,
    }


def test_additive_revision_follows_actual_parent_and_keeps_old_merge_ancestry():
    scripts = ScriptDirectory.from_config(Config(str(ROOT / "alembic.ini")))
    assert scripts.get_heads() == [migration.revision]
    assert migration.revision == "20261021_rca_evidence" and len(migration.revision) <= 32
    assert migration.down_revision == "20261021_native_shared_merge"
    chain = [row.revision for row in scripts.walk_revisions()]
    assert len(chain) == len(set(chain)) and chain.index(migration.revision) < chain.index(migration.down_revision)
    assert {"20261021_document_evidence", "20261021_doc_extraction_runs", "20261021_charge_sat_merge", "20261021_drug_label_runs"} <= set(chain)


def test_up_down_up_preserves_all_legacy_ddl_rows_and_whole_unicode(database):
    db = database
    before = snapshot(db)
    for _ in range(2):
        apply(db, "upgrade")
        assert snapshot(db) == before
        assert set(TABLES) <= set(sa.inspect(db).get_table_names())
        g, o, s = (table(db, name) for name in TABLES)
        db.execute(g.insert(), [grant(1), grant(2, permission_kind="associated_patient_processing")])
        db.execute(o.insert(), original())
        db.execute(s.insert(), case())
        db.commit()
        stored = db.execute(sa.select(o)).mappings().one()
        stored_case = db.execute(sa.select(s)).mappings().one()
        assert stored["original_json"] == original()["original_json"] and stored["json_bytes"] > 65535
        assert stored_case["case_json"] == case()["case_json"] and stored_case["recorded_at"] == NOW
        assert stored["recorded_at"] == NOW and stored["content_hash"] == hashlib.sha256(stored["original_json"].encode()).hexdigest()
        apply(db, "downgrade")
        assert snapshot(db) == before and not set(TABLES).intersection(sa.inspect(db).get_table_names())


@pytest.mark.parametrize(
    "changes", [{"permission_kind": "associated_patient_processing", "patient_id_at_grant": None}, {"purpose": "research"}, {"valid_until": NOW}, {"status": "revoked"}, {"revoked_at": NOW}]
)
def test_actual_sql_grant_constraints_do_not_allow_implied_or_inconsistent_permission(database, changes):
    apply(database, "upgrade")
    with pytest.raises(IntegrityError):
        database.execute(table(database, TABLES[0]).insert(), grant(**changes))
    database.rollback()


@pytest.mark.parametrize("changes", [{"created_by": 2}, {"event_id": 2}, {"patient_grant_id": None}, {"patient_grant_id": grant(1)["grant_id"]}, {"member_count": 4097}, {"json_bytes": 8388609}])
def test_actual_case_fk_and_limits_reject_wrong_grantee_scope_or_single_combined_patient_grant(database, changes):
    apply(database, "upgrade")
    database.execute(table(database, TABLES[0]).insert(), [grant(1), grant(2, permission_kind="associated_patient_processing")])
    database.commit()
    with pytest.raises(IntegrityError):
        database.execute(table(database, TABLES[2]).insert(), case(**changes))
    database.rollback()


@pytest.mark.parametrize("review", ["privacy_review", "faithfulness_review", "provenance_review"])
def test_each_actual_sql_publication_requires_its_own_confirmed_review(database, review):
    apply(database, "upgrade")
    fields = original(
        status="published",
        revision=2,
        privacy_review="confirmed",
        faithfulness_review="confirmed",
        provenance_review="confirmed",
        reviewed_by=1,
        reviewed_at=NOW,
        reviewed_audit_event_id=5,
        review_basis_note="逐字独立审核声明，并非因果认证",
    )
    fields[review] = "unknown"
    with pytest.raises(IntegrityError):
        database.execute(table(database, TABLES[1]).insert(), fields)
    database.rollback()


def test_real_model_mysql_types_and_composite_capture_grantee_fks(monkeypatch):
    stub = types.ModuleType("app.database")
    stub.Base = declarative_base()
    stub._rca_synthetic_metadata = True
    with monkeypatch.context() as patch:
        patch.setitem(sys.modules, "app.database", stub)
        models = module(ROOT / "app/ai/rca_evidence_models.py", "synthetic_rca_actual_models")
    metadata = stub.Base.metadata
    for name, primary in zip(LEGACY, ("user_id", "patient_id", "event_id", "rca_id", "event_id"), strict=True):
        sa.Table(name, metadata, sa.Column(primary, sa.Integer, primary_key=True))
    assert len(models.RCA_EVIDENCE_MODELS) == 3
    dates = [column for model in models.RCA_EVIDENCE_MODELS for column in model.__table__.columns if isinstance(column.type, sa.DateTime)]
    assert len(dates) == 9 and all(str(column.type.compile(dialect=mysql.dialect())) == "DATETIME(6)" for column in dates)
    text = [column for model in models.RCA_EVIDENCE_MODELS for column in model.__table__.columns if str(column.type.compile(dialect=mysql.dialect())) == "MEDIUMTEXT"]
    assert {column.name for column in text} == {"original_json", "case_json"}
    for model in models.RCA_EVIDENCE_MODELS:
        ddl = str(sa.schema.CreateTable(model.__table__).compile(dialect=mysql.dialect()))
        assert "AUTO_INCREMENT" not in ddl
    captured = models.AIRcaEvidenceCase.__table__
    assert {tuple(constraint.column_keys) for constraint in captured.foreign_key_constraints} >= {("event_grant_id", "event_id", "created_by"), ("patient_grant_id", "event_id", "created_by")}


def test_mysql_downgrade_removes_only_owned_tables_with_dependents_before_grants():
    import io

    stream = io.StringIO()
    context = MigrationContext.configure(dialect_name="mysql", opts={"as_sql": True, "output_buffer": stream})
    with Operations.context(context):
        migration.downgrade()
    statements = [line.strip() for line in stream.getvalue().splitlines() if line.strip()]
    assert statements == ["DROP TABLE hoimsystem_ai_rca_evidence_case;", "DROP TABLE hoimsystem_ai_rca_evidence_original;", "DROP TABLE hoimsystem_ai_rca_purpose_grant;"]
    # InnoDB event FKs can require the explicit event-prefix indexes. Whole
    # owned-table removal does not transiently drop their supporting indexes.
    assert all(name not in stream.getvalue() for name in LEGACY)
