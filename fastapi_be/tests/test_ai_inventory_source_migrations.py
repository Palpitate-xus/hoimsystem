"""Two real additive migrations and independent MySQL DDL shape checks."""

import importlib.util
from io import StringIO
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import CheckConstraint, create_engine, inspect, text
from sqlalchemy.dialects import mysql
from sqlalchemy.exc import IntegrityError
from sqlalchemy.schema import CreateTable

from app.ai.inventory_native_source_models import AIInventoryNativeSource, AIInventoryWriteGate
from app.database import Base
from tests.test_inpatient_support_migration import snapshot

MODELS = (AIInventoryWriteGate, AIInventoryNativeSource)
TABLES = {m.__tablename__ for m in MODELS}


def migration(name):
    p = Path(__file__).resolve().parents[1] / "alembic/versions" / f"20261021_inventory_{name}.py"
    spec = importlib.util.spec_from_file_location("isolated_inventory_" + name, p)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_actual_additive_up_down_up_preserves_every_legacy_ddl_and_row(tmp_path):
    engine = create_engine("sqlite:///" + str(tmp_path / "inventory-additive.sqlite"))
    Base.metadata.create_all(engine, tables=[t for t in Base.metadata.sorted_tables if t.name not in TABLES])
    names = set(inspect(engine).get_table_names())
    with engine.begin() as c:
        c.execute(Base.metadata.tables["hoimsystem_users"].insert().values(user_id=90671, username='synthetic-inventory', user_role='pharmacist'))
        c.execute(text("INSERT INTO hoimsystem_pharmaceutical(pharmaceutical_id,name,stock,status) VALUES(90672,'原目录与批次可不符',19,0)"))
        c.execute(text("INSERT INTO hoimsystem_consumable(consumable_id,name,stock,unit,status) VALUES(90673,'原无批次耗材',0,'套',0)"))
        original = snapshot(c, names)
    for action, order in (("upgrade", ("gate", "sources")), ("downgrade", ("sources", "gate")), ("upgrade", ("gate", "sources"))):
        with engine.begin() as c, Operations.context(MigrationContext.configure(c)):
            for name in order:
                getattr(migration(name), action)()
        inspector = inspect(engine)
        assert set(inspector.get_table_names()) == names | (TABLES if action == "upgrade" else set())
        with engine.connect() as c:
            assert snapshot(c, names) == original
        if action == "upgrade":
            for model in MODELS:
                table = model.__table__
                assert {c["name"]: c["nullable"] for c in inspector.get_columns(table.name)} == {c.name: c.nullable for c in table.columns}
                sql_checks = {c["name"]: " ".join(c["sqltext"].split()) for c in inspector.get_check_constraints(table.name)}
                assert sql_checks == {c.name: " ".join(str(c.sqltext).split()) for c in table.constraints if isinstance(c, CheckConstraint)}
                assert {(i["name"], tuple(i["column_names"])) for i in inspector.get_indexes(table.name)} == {(i.name, tuple(i.columns.keys())) for i in table.indexes}
                assert {(tuple(f["constrained_columns"]), f["referred_table"], tuple(f["referred_columns"])) for f in inspector.get_foreign_keys(table.name)} == {
                    (tuple(e.parent.name for e in f.elements), next(iter(f.elements)).column.table.name, tuple(e.column.name for e in f.elements)) for f in table.foreign_key_constraints
                }
            with engine.begin() as c:
                assert c.scalar(text("SELECT revision FROM hoimsystem_ai_inventory_write_gate WHERE gate_id=1")) == 1
                with pytest.raises(IntegrityError):
                    c.execute(text("INSERT INTO hoimsystem_ai_inventory_write_gate(gate_id,revision) VALUES(2,1)"))
    engine.dispose()


def test_mysql_utc6_utf8_bounds_and_only_new_table_downgrade():
    modules = [migration(name) for name in ("gate", "sources")]
    assert modules[0].down_revision == "20261020_supply_series" and modules[1].down_revision == modules[0].revision
    output = StringIO()
    with Operations.context(MigrationContext.configure(dialect=mysql.dialect(), opts={"as_sql": True, "output_buffer": output})):
        for module in modules:
            module.upgrade()
    ddl = output.getvalue()
    assert "AUTO_INCREMENT" not in ddl.split("CREATE TABLE hoimsystem_ai_inventory_native_source")[0]
    assert "AUTO_INCREMENT" not in str(CreateTable(AIInventoryWriteGate.__table__).compile(dialect=mysql.dialect()))
    assert ddl.count("DATETIME(6)") == 3 and ddl.count("MEDIUMTEXT") == 2
    assert "revoke_reason VARCHAR(1000)" in ddl
    assert "length(review_basis_note) <= 4000" in ddl and "length(revoke_reason) <= 1000" not in ddl
    assert "fk_inventory_source_unit_scope" in ddl and "inventory_observation" in ddl
    output = StringIO()
    with Operations.context(MigrationContext.configure(dialect=mysql.dialect(), opts={"as_sql": True, "output_buffer": output})):
        for module in reversed(modules):
            module.downgrade()
    assert output.getvalue().count("DROP TABLE") == 2
    assert all(table in output.getvalue() for table in TABLES)
