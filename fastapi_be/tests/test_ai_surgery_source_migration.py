"""Real additive SQL and identity invariants; MySQL assertions are compiled DDL."""

import importlib.util
import re
from io import StringIO
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import CheckConstraint, create_engine, event, inspect, text
from sqlalchemy.dialects import mysql
from sqlalchemy.exc import IntegrityError
from sqlalchemy.schema import CreateIndex, CreateTable

from alembic import command
from app.ai.surgery_models import SURGERY_MODELS, AISurgerySource
from app.db_migrate import migrate
from tests.test_inpatient_support_migration import normalize_sql, snapshot

REVISION = "20261020_surgery_sources"
PARENT = "20261020_bed_series"
TABLES = {model.__tablename__ for model in SURGERY_MODELS}


def migration():
    path = Path(__file__).resolve().parents[1] / "alembic/versions" / (REVISION + ".py")
    spec = importlib.util.spec_from_file_location("isolated_surgery_source_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def offline(action):
    output = StringIO()
    with Operations.context(MigrationContext.configure(dialect=mysql.dialect(), opts={"as_sql": True, "output_buffer": output})):
        getattr(migration(), action)()
    return output.getvalue()


def test_actual_up_down_up_preserves_every_previous_table_definition_and_row(tmp_path):
    url = "sqlite:///" + str(tmp_path / "surgery-originals.sqlite")
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", url)
    assert migrate(url) == "bootstrapped"
    command.downgrade(config, PARENT)
    engine = create_engine(url)
    old_names = set(inspect(engine).get_table_names())
    assert not old_names & TABLES
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO hoimsystem_department(department_id,name) VALUES(90651,'合成旧手术科')"))
        connection.execute(
            text(
                "INSERT INTO hoimsystem_equipment(equipment_id,asset_no,name,department_id,status,inventory_status,create_time) VALUES(90652,'synthetic-old-65','合成旧设备',90651,1,0,'2020-01-02 03:04:05')"
            )
        )
        connection.execute(text("INSERT INTO hoimsystem_surgery_schedule(schedule_id,operating_room,surgery_date,status) VALUES('synthetic-old-schedule','旧房间原文','2020-01-02',3)"))
        old = snapshot(connection, old_names - {"alembic_version"})
    for action in ("up", "down", "up"):
        if action == "up":
            command.upgrade(config, REVISION)
            inspector = inspect(engine)
            assert set(inspector.get_table_names()) == old_names | TABLES
            for model in SURGERY_MODELS:
                name = model.__tablename__
                assert [(item["name"], item["nullable"]) for item in inspector.get_columns(name)] == [(col.name, col.nullable) for col in model.__table__.columns]
                assert {item["name"] for item in inspector.get_check_constraints(name)} == {item.name for item in model.__table__.constraints if isinstance(item, CheckConstraint)}
                assert {(item["name"], tuple(item["column_names"])) for item in inspector.get_indexes(name)} == {(item.name, tuple(item.columns.keys())) for item in model.__table__.indexes}
                assert {(tuple(item["constrained_columns"]), item["referred_table"], tuple(item["referred_columns"])) for item in inspector.get_foreign_keys(name)} == {
                    (tuple(element.parent.name for element in constraint.elements), next(iter(constraint.elements)).column.table.name, tuple(element.column.name for element in constraint.elements))
                    for constraint in model.__table__.foreign_key_constraints
                }
            with engine.connect() as connection:
                assert connection.execute(text("SELECT gate_id,revision FROM hoimsystem_ai_surgery_write_gate")).all() == [(1, 1)]
        else:
            command.downgrade(config, PARENT)
            assert set(inspect(engine).get_table_names()) == old_names
        with engine.connect() as connection:
            assert snapshot(connection, old_names - {"alembic_version"}) == old
    engine.dispose()


def test_mysql_ddl_matches_models_and_keeps_identity_in_real_fk_and_unique_columns():
    module = migration()
    assert module.revision == REVISION and module.down_revision == PARENT
    assert module.branch_labels is module.depends_on is None
    sql = offline("upgrade")
    assert sql.count("CREATE TABLE ") == 8 and sql.count("DATETIME(6)") == 16 and sql.count("MEDIUMTEXT") == 13
    assert all(token not in sql for token in ("ALTER TABLE", "DELETE FROM", "UPDATE hoimsystem_"))

    def entries(body):
        # Constraint ordering is not semantic (SQLAlchemy stores constraints in a set).
        result, start, depth, quoted = [], 0, 0, False
        for index, char in enumerate(body):
            if char == "'":
                quoted = not quoted
            if not quoted:
                depth += (char == "(") - (char == ")")
                if char == "," and depth == 0:
                    result.append(normalize_sql(body[start:index]))
                    start = index + 1
        result.append(normalize_sql(body[start:]))
        return sorted(result)

    generated = dict(re.findall(r"CREATE TABLE (\w+) \((.*?)\);", sql, re.DOTALL))
    for model in SURGERY_MODELS:
        expected = str(CreateTable(model.__table__).compile(dialect=mysql.dialect())).strip()
        assert entries(expected[expected.index("(") + 1 : expected.rindex(")")]) == entries(generated[model.__tablename__])
        for index in model.__table__.indexes:
            assert normalize_sql(str(CreateIndex(index).compile(dialect=mysql.dialect()))) in normalize_sql(sql)
    assert [part.strip() for part in offline("downgrade").split(";") if part.strip()] == ["DROP TABLE " + model.__tablename__ for model in reversed(SURGERY_MODELS)]
    assert "UNIQUE (equipment_id)" in sql and "UNIQUE (cssd_instrument_id)" in sql and "UNIQUE (user_id)" in sql
    assert "FOREIGN KEY(resource_id, resource_kind)" in sql


@pytest.fixture
def sql():
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def foreign_keys(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")

    parents = {
        "users": "user_id INTEGER PRIMARY KEY",
        "department": "department_id INTEGER PRIMARY KEY",
        "doctor": "doctor_id INTEGER PRIMARY KEY",
        "equipment": "equipment_id INTEGER PRIMARY KEY",
        "cssd_instrument": "instrument_id INTEGER PRIMARY KEY",
        "surgery_schedule": "schedule_id VARCHAR(36) PRIMARY KEY",
        "surgery_application": "application_id VARCHAR(36) PRIMARY KEY",
        "patient": "patient_id INTEGER PRIMARY KEY",
        "admission": "admission_id VARCHAR(36) PRIMARY KEY",
    }
    with engine.begin() as connection, Operations.context(MigrationContext.configure(connection)):
        for name, column in parents.items():
            connection.execute(text(f"CREATE TABLE hoimsystem_{name} ({column})"))
            connection.execute(text(f"INSERT INTO hoimsystem_{name} VALUES (1)"))
        connection.execute(text("INSERT INTO hoimsystem_users VALUES(2)"))
        migration().upgrade()
    with engine.begin() as connection:
        yield connection
    engine.dispose()


def original(**changes):
    return {
        "schema_version": "surgery_registry_private_v1",
        "payload_json": "{}",
        "parent_binding_json": "{}",
        "content_hash": "a" * 64,
        "recorded_at": "2026-10-20 12:00:00.123456",
        "created_by": 1,
        **changes,
    }


def governed(**changes):
    return original(status="draft", revision=1, reviewed_by=None, reviewed_at=None, review_basis_note="", revoked_by=None, revoked_at=None, revoke_reason="", **changes)


def insert(connection, table, values):
    connection.execute(text("INSERT INTO hoimsystem_ai_surgery_" + table + "(" + ",".join(values) + ") VALUES(" + ",".join(":" + key for key in values) + ")"), values)


def resource(connection, identity="resource-1", **changes):
    values = original(resource_id=identity, resource_kind="person", equipment_id=None, cssd_instrument_id=None)
    values.update(changes)
    insert(connection, "resource", values)


def case_source(connection, **changes):
    insert(connection, "pool", governed(pool_id="pool-1", department_id=1))
    values = governed(
        source_record_id="case-source-1",
        source_kind="case_requirements",
        pool_id="pool-1",
        resource_id=None,
        application_id="1",
        patient_id=1,
        admission_id="1",
        professional_status="unknown",
        signed_by_doctor_id=None,
        signed_by_user_id=None,
        signed_at=None,
    )
    values.update(changes)
    insert(connection, "source", values)
    return values


@pytest.mark.parametrize("parent", ["equipment", "cssd"])
def test_one_physical_asset_has_permanent_identity_even_after_claims_are_withdrawn(sql, parent):
    values = {"resource_kind": "equipment", "equipment_id": 1 if parent == "equipment" else None, "cssd_instrument_id": 1 if parent == "cssd" else None}
    resource(sql, **values)
    insert(sql, "pool", governed(pool_id="pool-1", department_id=1))
    claim = governed(
        source_record_id="claim-1",
        source_kind="resource_availability_busy",
        pool_id="pool-1",
        resource_id="resource-1",
        application_id=None,
        patient_id=None,
        admission_id=None,
        professional_status="unknown",
        signed_by_doctor_id=None,
        signed_by_user_id=None,
        signed_at=None,
    )
    insert(sql, "source", claim)
    sql.execute(
        text(
            "UPDATE hoimsystem_ai_surgery_source SET status='revoked',revision=2,revoked_by=2,revoked_at='2026-10-20 12:01:00.654321',revoke_reason='合成撤销声明，不释放资源身份' WHERE source_record_id='claim-1'"
        )
    )
    with pytest.raises(IntegrityError):
        resource(sql, "resource-2", **values)
    claim.update(source_record_id="claim-2")
    insert(sql, "source", claim)
    assert sql.execute(text("SELECT resource_id FROM hoimsystem_ai_surgery_source ORDER BY source_record_id")).all() == [("resource-1",), ("resource-1",)]


def test_same_user_cannot_be_split_into_two_people_but_two_explicit_accounts_can_share_one_person(sql):
    resource(sql)
    resource(sql, "resource-2")
    insert(sql, "person_account", original(binding_id="binding-1", resource_id="resource-1", resource_kind="person", user_id=1))
    with pytest.raises(IntegrityError):
        insert(sql, "person_account", original(binding_id="binding-2", resource_id="resource-2", resource_kind="person", user_id=1))
    insert(sql, "person_account", original(binding_id="binding-3", resource_id="resource-1", resource_kind="person", user_id=2))
    assert sql.execute(text("SELECT COUNT(*) FROM hoimsystem_ai_surgery_person_account WHERE resource_id='resource-1'")).scalar_one() == 2


def test_real_fk_and_kind_reject_equipment_as_person_or_orphaned_parent(sql):
    resource(sql, resource_kind="equipment", equipment_id=1)
    with pytest.raises(IntegrityError):
        insert(sql, "person_account", original(binding_id="bad-kind", resource_id="resource-1", resource_kind="person", user_id=1))
    with pytest.raises(IntegrityError):
        resource(sql, "orphan", resource_kind="equipment", equipment_id=999)
    with pytest.raises(IntegrityError):
        sql.execute(text("DELETE FROM hoimsystem_equipment WHERE equipment_id=1"))


@pytest.mark.parametrize(
    "changes",
    [
        {"source_kind": "invented"},
        {"source_kind": "resource_availability_busy"},
        {"payload_json": ""},
        {"parent_binding_json": ""},
        {"revision": 2},
        {"status": "published", "revision": 2},
        {"professional_status": "confirmed"},
        {"professional_status": "confirmed", "signed_by_doctor_id": 1, "signed_by_user_id": 1, "signed_at": "2026-10-20 11:59:59.123456"},
        {"professional_status": "unknown", "signed_by_doctor_id": 1},
        {"reviewed_at": "2026-10-20 11:59:59.123456", "reviewed_by": 2, "review_basis_note": "合成", "revision": 2, "status": "published"},
        {"admission_id": "missing-admission"},
        {"pool_id": "missing-pool"},
    ],
)
def test_source_rejects_false_governance_or_signature_and_missing_real_parents(sql, changes):
    with pytest.raises(IntegrityError):
        case_source(sql, **changes)


def test_clinical_signature_is_independent_of_super_publication_and_cas_keeps_full_original(sql):
    body = '{"synthetic":"' + "合成逐病例专业确认" * 6000 + '"}'
    values = case_source(sql, payload_json=body, professional_status="confirmed", signed_by_doctor_id=1, signed_by_user_id=1, signed_at="2026-10-20 12:00:00.123456")
    assert len(body.encode()) > 65535
    publish = text(
        "UPDATE hoimsystem_ai_surgery_source SET status='published',revision=2,reviewed_by=2,reviewed_at='2026-10-20 12:01:00.654321',review_basis_note='合成独立技术发布，不代专业签署' WHERE source_record_id='case-source-1' AND status='draft' AND revision=1"
    )
    assert sql.execute(publish).rowcount == 1 and sql.execute(publish).rowcount == 0
    row = sql.execute(text("SELECT payload_json,content_hash,recorded_at,signed_by_user_id,signed_at,reviewed_by,reviewed_at FROM hoimsystem_ai_surgery_source")).one()
    assert row == (body, values["content_hash"], values["recorded_at"], 1, values["signed_at"], 2, "2026-10-20 12:01:00.654321")


def test_membership_active_unique_releases_claim_without_replacing_physical_resource(sql):
    resource(sql)
    insert(sql, "pool", governed(pool_id="pool-1", department_id=1))
    values = governed(membership_id="member-1", pool_id="pool-1", resource_id="resource-1", pair_key="b" * 64, active_pair_key=None)
    insert(sql, "pool_membership", values)
    values.update(membership_id="member-2")
    insert(sql, "pool_membership", values)
    publish = text(
        "UPDATE hoimsystem_ai_surgery_pool_membership SET status='published',revision=2,reviewed_by=2,reviewed_at='2026-10-20 12:01:00.654321',review_basis_note='合成审核',active_pair_key=pair_key WHERE membership_id=:id"
    )
    sql.execute(publish, {"id": "member-1"})
    with pytest.raises(IntegrityError):
        sql.execute(publish, {"id": "member-2"})
    sql.execute(
        text(
            "UPDATE hoimsystem_ai_surgery_pool_membership SET status='revoked',revision=3,revoked_by=2,revoked_at='2026-10-20 12:02:00.654321',revoke_reason='合成更正成员声明',active_pair_key=NULL WHERE membership_id='member-1'"
        )
    )
    assert sql.execute(publish, {"id": "member-2"}).rowcount == 1


def test_foreign_busy_protected_body_cannot_attach_to_a_clinical_case_source(sql):
    case_source(sql)
    with pytest.raises(IntegrityError):
        insert(
            sql,
            "protected_witness",
            {
                "source_record_id": "case-source-1",
                "source_kind": "resource_availability_busy",
                "witness_json": '{"server_only":"synthetic"}',
                "content_hash": "c" * 64,
                "recorded_at": "2026-10-20 12:00:00.123456",
                "created_by": 1,
            },
        )
    assert AISurgerySource.__table__.c.payload_json.type.length is None
