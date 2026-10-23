"""Independent SQL structural constraints, not fabricated clinical Task proof.

Each fixture owns a fresh in-memory connection with FK enforcement. It never
changes the shared application-test connection's PRAGMA or claims MySQL locks.
"""

import datetime as dt
import importlib.util
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import Column, Integer, MetaData, String, Table, create_engine, event, inspect
from sqlalchemy.dialects.mysql import dialect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.schema import CreateTable

from app.ai import research_variables_run_models as m
from tests.test_ai_research_variables_migration import signature

NOW = dt.datetime(2026, 10, 21, 12, 34, 56, 123456)
RUN = "00000000-0000-0000-0000-000000000001"
BATCH = "00000000-0000-0000-0000-000000000002"
SCOPE = "00000000-0000-0000-0000-000000000003"
ACL = "00000000-0000-0000-0000-000000000004"
LEASE = "00000000-0000-0000-0000-000000000005"
PATH = Path(__file__).resolve().parents[1] / "alembic/versions/20261021_research_variable_runs.py"


def migration():
    spec = importlib.util.spec_from_file_location("isolated76_run_migration", PATH)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def parent_metadata():
    meta = MetaData()
    for name, key, kind in (
        ("hoimsystem_ai_run", "run_id", String(36)),
        ("hoimsystem_ai_research_variable_batch", "batch_id", String(36)),
        ("hoimsystem_ai_research_study_scope", "scope_id", String(36)),
        ("hoimsystem_ai_research_project_acl", "acl_id", String(36)),
        ("hoimsystem_users", "user_id", Integer),
        ("hoimsystem_ai_audit_event", "event_id", Integer),
    ):
        Table(name, meta, Column(key, kind, primary_key=True))
    return meta


@pytest.fixture
def sql():
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def foreign_keys(connection, record):
        connection.execute("PRAGMA foreign_keys=ON")

    meta = parent_metadata()
    artifact = m.AIResearchVariableRunArtifact.__table__.to_metadata(meta)
    result = m.AIResearchVariableRunResult.__table__.to_metadata(meta)
    meta.create_all(engine)
    with engine.connect() as conn:
        for name, key, value in (
            ("hoimsystem_ai_run", "run_id", RUN),
            ("hoimsystem_ai_research_variable_batch", "batch_id", BATCH),
            ("hoimsystem_ai_research_study_scope", "scope_id", SCOPE),
            ("hoimsystem_ai_research_project_acl", "acl_id", ACL),
            ("hoimsystem_users", "user_id", 1),
        ):
            conn.execute(meta.tables[name].insert().values(**{key: value}))
        conn.execute(meta.tables["hoimsystem_ai_audit_event"].insert(), [{"event_id": i} for i in range(1, 10)])
        conn.commit()
        yield conn, artifact, result
    engine.dispose()


def artifact():
    source, binding = '{"原量":"🧪"}', '{"explicit_permission_refs":[]}'
    return {
        "run_id": RUN,
        "batch_id": BATCH,
        "scope_id": SCOPE,
        "requested_by": 1,
        "task_acl_id": ACL,
        "actor_role": "doctor",
        "actor_token_invalid_before": None,
        "schema_version": m.ARTIFACT_SCHEMA,
        "recorded_at": NOW,
        "source_json": source,
        "source_bytes": len(source.encode()),
        "binding_json": binding,
        "binding_bytes": len(binding.encode()),
        **dict.fromkeys((*m.ANCHOR_FIELDS, *m.AUTH_HASH_FIELDS), "a" * 64),
        "create_event_id": 1,
        "claim_event_id": None,
        "claim_lease": None,
        "claimed_at": None,
        "dispatch_event_id": None,
        "dispatched_at": None,
        "usage_event_id": None,
    }


def result():
    return {
        "run_id": RUN,
        "schema_version": m.RESULT_SCHEMA,
        "source_hash": "a" * 64,
        "instructions_digest": "a" * 64,
        "accepted_lease": LEASE,
        "accepted_at": NOW,
        "result_json": "{}",
        "result_bytes": 2,
        "result_hash": "b" * 64,
        "accept_audit_event_id": 5,
    }


def test_actual_sql_all_five_audit_phases_utc6_and_independent_256k_binding_without_private_batch_copy(sql):
    conn, table, results = sql
    value = artifact()
    value.update(claim_event_id=2, claim_lease=LEASE, claimed_at=NOW, dispatch_event_id=3, dispatched_at=NOW, usage_event_id=4)
    value["binding_json"] = '"' + "a" * 65536 + '"'
    value["binding_bytes"] = len(value["binding_json"].encode())
    conn.execute(table.insert().values(**value))
    conn.execute(results.insert().values(**result()))
    stored = dict(conn.execute(table.select()).mappings().one())
    assert stored == value and stored["recorded_at"].microsecond == 123456
    assert conn.execute(results.select()).mappings().one()["accepted_at"].microsecond == 123456
    assert len({stored[k] for k in m.AUDIT_FIELDS} | {result()["accept_audit_event_id"]}) == 5
    assert "snapshot_json" not in table.c and "private_scope_json" not in table.c


@pytest.mark.parametrize(
    "change",
    [
        {"batch_id": RUN},
        {"scope_id": RUN},
        {"task_acl_id": RUN},
        {"requested_by": 2},
        {"actor_role": "nurse"},
        {"source_hash": "A" * 64},
        {"schema_version": "wrong"},
        {"source_bytes": 1},
        {"source_json": "{broken", "source_bytes": 7},
        {"binding_json": '"' + "x" * 262143 + '"', "binding_bytes": 262145},
        {"actor_token_invalid_before": NOW + dt.timedelta(microseconds=1)},
        {"claim_event_id": 2},
        {"claim_lease": LEASE},
        {"dispatch_event_id": 3, "dispatched_at": NOW},
        {"usage_event_id": 1},
    ],
)
def test_actual_sql_rejects_dangling_original_fk_invalid_role_hash_byte_or_incomplete_claim_tuple(sql, change):
    conn, table, _ = sql
    with pytest.raises(IntegrityError):
        conn.execute(table.insert().values(**{**artifact(), **change}))
    conn.rollback()


@pytest.mark.parametrize("field,value", [("accepted_lease", BATCH), ("source_hash", "f" * 64), ("instructions_digest", "f" * 64), ("accept_audit_event_id", 99), ("result_bytes", 3)])
def test_result_requires_exact_original_claim_source_and_specific_accept_audit_pk(sql, field, value):
    conn, table, results = sql
    conn.execute(table.insert().values(**{**artifact(), "claim_event_id": 2, "claim_lease": LEASE, "claimed_at": NOW}))
    conn.commit()
    with pytest.raises(IntegrityError):
        conn.execute(results.insert().values(**{**result(), field: value}))
    conn.rollback()
    assert conn.execute(results.select()).first() is None


def test_incremental_up_down_up_preserves_all_existing_ddl_rows_and_matches_real_models():
    module = migration()
    assert module.revision == "20261021_research_variable_runs" and len(module.revision) <= 32
    assert module.down_revision == "20261021_research_variables" and "from app" not in PATH.read_text()
    config = Config(str(PATH.parents[2] / "alembic.ini"))
    config.set_main_option("script_location", str(PATH.parent.parent))
    script = ScriptDirectory.from_config(config)
    assert len(script.get_heads()) == 1
    ancestry = [row.revision for row in script.walk_revisions()]
    assert len(ancestry) == len(set(ancestry)) and ancestry.index(module.revision) < ancestry.index(module.down_revision)
    engines = [create_engine("sqlite:///:memory:") for _ in range(2)]
    meta = parent_metadata()
    meta.create_all(engines[0])
    m.AIResearchVariableRunArtifact.__table__.to_metadata(meta)
    m.AIResearchVariableRunResult.__table__.to_metadata(meta)
    meta.create_all(engines[1])
    new = {row.__tablename__ for row in m.RESEARCH_VARIABLE_RUN_MODELS}
    from sqlalchemy import text

    with engines[0].begin() as conn, engines[1].connect() as expected:
        conn.execute(text("INSERT INTO hoimsystem_users(user_id) VALUES(7)"))
        before = conn.execute(text("SELECT type,name,tbl_name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name")).all()
        for action in ("upgrade", "downgrade", "upgrade"):
            module.op = Operations(MigrationContext.configure(conn))
            getattr(module, action)()
            after = conn.execute(text("SELECT type,name,tbl_name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name")).all()
            assert [r for r in after if r.tbl_name not in new] == before
            assert conn.execute(text("SELECT user_id FROM hoimsystem_users")).all() == [(7,)]
            if action == "upgrade":
                assert {name: signature(conn, name) for name in new} == {name: signature(expected, name) for name in new}
            else:
                assert not new.intersection(inspect(conn).get_table_names())
    for engine in engines:
        engine.dispose()


def test_mysql_ddl_has_three_mediumtext_five_utc6_exact_audit_fks_and_no_private_copy():
    ddl = "\n".join(str(CreateTable(row.__table__).compile(dialect=dialect())) for row in m.RESEARCH_VARIABLE_RUN_MODELS)
    assert ddl.count("MEDIUMTEXT") == 3 and ddl.count("DATETIME(6)") == 5
    for name in (*m.AUDIT_FIELDS, "accept_audit_event_id"):
        assert f"FOREIGN KEY({name}) REFERENCES hoimsystem_ai_audit_event (event_id)" in ddl
    assert "snapshot_json" not in ddl and "private_scope_json" not in ddl
