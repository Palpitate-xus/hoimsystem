"""Explicit declarations and actual additive SQLite DDL; no MySQL lock claims."""

import copy
import importlib.util
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from pydantic import ValidationError
from sqlalchemy import create_engine, inspect
from sqlalchemy.dialects import mysql
from sqlalchemy.schema import CreateTable

from app.ai import infection_cluster_contract as c
from app.ai import infection_cluster_scenario_input as i
from app.ai.infection_cluster_implementation import implementation_descriptor
from app.ai.infection_cluster_scenario_models import AIInfectionScenario
from tests.test_ai_infection_cluster_statistics import input_for_table


def request():
    plan = input_for_table()["scenario"]
    return dict(
        source_binding=plan["source_binding"],
        department_ids=[1],
        windows=plan["windows"],
        pathogen_code=plan["pathogen_code"],
        alpha_decimal="0.0500",
        basis_note="显式完整比较族和参数，不声称未看过数据或临床验证。",
    )


def test_no_default_alpha_full_cartesian_and_no_deduplication():
    value = request()
    assert i.ScenarioCreate.model_validate(value).alpha_decimal == "0.0500"
    for field, bad in [("alpha_decimal", 0.05), ("alpha_decimal", "0"), ("alpha_decimal", None), ("department_ids", [1, 1]), ("department_ids", [True]), ("windows", value["windows"] * 2)]:
        modified = {**value, field: bad}
        with pytest.raises(ValidationError):
            i.ScenarioCreate.model_validate(modified)
    value["department_ids"] = list(range(1, 257))
    assert len(i.ScenarioCreate.model_validate(value).department_ids) == 256
    value["department_ids"].append(257)
    with pytest.raises(ValidationError):
        i.ScenarioCreate.model_validate(value)
    with pytest.raises(ValidationError):
        i.ScenarioCreate.model_validate({**request(), "published": True})


def test_review_explicit_parameters_negative_does_not_force_false_privacy_claim():
    value = dict(
        expected_revision=1,
        expected_content_hash="a" * 64,
        expected_governance_hash="b" * 64,
        basis_note="仅参数复核不通过，不能因此伪造隐私复核未通过。",
        privacy_review="confirmed",
        faithfulness_review="confirmed",
        parameters_review="not_confirmed",
        decision="reject",
    )
    assert i.ScenarioReview.model_validate(value).parameters_review == "not_confirmed"
    with pytest.raises(ValidationError):
        i.ScenarioReview.model_validate({**value, "decision": "publish"})


def test_department_anchor_preserves_null_and_empty_and_does_not_invent_status():
    base = dict(department_id=9, recorded_name=None, department_token="d" * 64, identity_fields="actual_department_id_and_recorded_name_only_not_full_directory_or_active_status")
    base["directory_hash"] = c.digest({"department_id": 9, "name": None})
    assert i.DepartmentBinding.model_validate(base).recorded_name is None
    with pytest.raises(ValidationError):
        i.DepartmentBinding.model_validate({**base, "recorded_name": ""})
    with pytest.raises(ValidationError):
        i.DepartmentBinding.model_validate({**base, "active": True})


def test_local_descriptor_binds_actual_files_without_endpoint_or_validation():
    import hashlib

    value = implementation_descriptor()
    assert value["engine"] == "prediction" and value["automatic_enable"] is False
    assert "provider_id" not in value and "endpoint" not in value
    root = Path(__file__).parents[1] / "app/ai"
    assert all(hashlib.sha256((root / path).read_bytes()).hexdigest() == sha for path, sha in value["code_hashes"].items())
    changed = copy.deepcopy(value)
    changed["code_hashes"]["infection_cluster_statistics.py"] = "e" * 64
    assert c.digest(value) != c.digest(changed)


def test_mysql_compiled_utc6_mediumtext_and_independent_review_fk():
    ddl = str(CreateTable(AIInfectionScenario.__table__).compile(dialect=mysql.dialect()))
    assert ddl.count("DATETIME(6)") == 3 and ddl.count("MEDIUMTEXT") == 1
    assert "reviewed_by<>created_by" in ddl and "parameters_review='not_confirmed'" in ddl
    assert "hoimsystem_ai_infection_snapshot" in ddl and "hoimsystem_ai_audit_event" in ddl


def test_actual_sqlite_incremental_up_down_up_preserves_parent():
    path = Path(__file__).parents[1] / "alembic/versions/20261021_infection_scenarios.py"
    spec = importlib.util.spec_from_file_location("infection_scenario_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    assert migration.down_revision == "20261021_infection_sources"
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        conn.exec_driver_sql("CREATE TABLE parent_source (id INTEGER PRIMARY KEY, raw TEXT)")
        conn.exec_driver_sql("INSERT INTO parent_source VALUES(7, '原文😀\r\n')")
        before = conn.exec_driver_sql("SELECT * FROM parent_source").all()
        with Operations.context(MigrationContext.configure(conn)):
            migration.upgrade()
            assert AIInfectionScenario.__tablename__ in inspect(conn).get_table_names()
            assert len(inspect(conn).get_foreign_keys(AIInfectionScenario.__tablename__)) == 7
            migration.downgrade()
            assert AIInfectionScenario.__tablename__ not in inspect(conn).get_table_names()
            migration.upgrade()
        assert conn.exec_driver_sql("SELECT * FROM parent_source").all() == before
    engine.dispose()


def test_actual_migration_mysql_offline_sql_uses_binary_bytes_not_sqlite_blob_cast():
    import io

    path = Path(__file__).parents[1] / "alembic/versions/20261021_infection_scenarios.py"
    spec = importlib.util.spec_from_file_location("infection_scenario_mysql_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    output = io.StringIO()
    with Operations.context(MigrationContext.configure(dialect_name="mysql", opts={"as_sql": True, "output_buffer": output})):
        migration.upgrade()
    sql = output.getvalue()
    assert "CAST(payload_json AS BINARY)" in sql and " AS BLOB" not in sql
    assert "implementation_hash VARCHAR(64) NOT NULL" in sql
