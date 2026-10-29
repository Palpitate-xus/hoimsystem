"""Actual additive upgrade/down/upgrade; existing stock never changes."""

import importlib.util
from io import StringIO
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import CheckConstraint, create_engine, inspect, text
from sqlalchemy.dialects import mysql
from sqlalchemy.schema import CreateTable

from app.ai.supply_series_models import SUPPLY_SERIES_MODELS
from app.database import Base
from tests.test_inpatient_support_migration import snapshot

REVISION = "20261020_supply_series"
PARENT = "20261020_supply_sources"
TABLES = {model.__tablename__ for model in SUPPLY_SERIES_MODELS}


def migration():
    path = Path(__file__).resolve().parents[1] / "alembic/versions" / (REVISION + ".py")
    spec = importlib.util.spec_from_file_location("isolated_supply_series_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def offline(action):
    output = StringIO()
    with Operations.context(MigrationContext.configure(dialect=mysql.dialect(), opts={"as_sql": True, "output_buffer": output})):
        getattr(migration(), action)()
    return output.getvalue()


def test_additive_real_up_down_up_preserves_all_existing_table_definitions_and_stock(tmp_path):
    engine = create_engine("sqlite:///" + str(tmp_path / "controlled-supply-series.sqlite"))
    Base.metadata.create_all(engine, tables=[t for t in Base.metadata.sorted_tables if t.name not in TABLES])
    old_names = set(inspect(engine).get_table_names())
    with engine.begin() as c:
        c.execute(Base.metadata.tables["hoimsystem_users"].insert().values(user_id=90661, username='old-supply-user', user_role='pharmacist'))
        c.execute(text("INSERT INTO hoimsystem_pharmaceutical(pharmaceutical_id,name,stock,price,status) VALUES(90662,'原药品',73,12.34,0)"))
        c.execute(text("INSERT INTO hoimsystem_consumable(consumable_id,name,stock,unit,status) VALUES(90663,'原耗材',19,'套',0)"))
        original = snapshot(c, old_names)
    for action in ("upgrade", "downgrade", "upgrade"):
        with engine.begin() as connection, Operations.context(MigrationContext.configure(connection)):
            getattr(migration(), action)()
        inspector = inspect(engine)
        assert set(inspector.get_table_names()) == old_names | (TABLES if action == "upgrade" else set())
        if action == "upgrade":
            for model in SUPPLY_SERIES_MODELS:
                table = model.__table__
                columns = inspector.get_columns(table.name)
                assert {r["name"]: r["nullable"] for r in columns} == {col.name: col.nullable for col in table.columns}
                assert {r["name"] for r in inspector.get_check_constraints(table.name)} == {r.name for r in table.constraints if isinstance(r, CheckConstraint)}
                assert {(r["name"], tuple(r["column_names"])) for r in inspector.get_indexes(table.name)} == {(idx.name, tuple(idx.columns.keys())) for idx in table.indexes}
                assert {(tuple(r["constrained_columns"]), r["referred_table"], tuple(r["referred_columns"])) for r in inspector.get_foreign_keys(table.name)} == {
                    (tuple(e.parent.name for e in fk.elements), next(iter(fk.elements)).column.table.name, tuple(e.column.name for e in fk.elements)) for fk in table.foreign_key_constraints
                }
        with engine.connect() as connection:
            assert snapshot(connection, old_names) == original
    engine.dispose()


def test_mysql_originals_use_utc6_mediumtext_and_unicode_revoke_column_not_char_byte_conflation():
    module = migration()
    assert module.revision == REVISION and module.down_revision == PARENT and module.branch_labels is module.depends_on is None
    ddl = offline("upgrade")
    assert ddl.count("MEDIUMTEXT") == 3 and ddl.count("DATETIME(6)") == 5
    assert "revoke_reason VARCHAR(1000)" in ddl and "length(review_basis_note) <= 4000" in ddl
    assert "length(revoke_reason) <= 1000" not in ddl  # MySQL LENGTH counts bytes; 1000emoji is4000bytes.
    for model in SUPPLY_SERIES_MODELS:
        compiled = str(CreateTable(model.__table__).compile(dialect=mysql.dialect()))
        assert "MEDIUMTEXT" in compiled and "DATETIME(6)" in compiled
    assert "fk_supply_series_unit_scope" in ddl and "FOREIGN KEY(unit_definition_id, item_kind, item_id, scope)" in ddl
    assert offline("downgrade").count("DROP TABLE") == 2
    assert all(name in offline("downgrade") for name in TABLES)
