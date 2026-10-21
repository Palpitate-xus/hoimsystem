"""Local Task protocol and additive split storage, not a worker execution claim."""

import importlib.util
import io
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from pydantic import ValidationError
from sqlalchemy import create_engine, inspect
from sqlalchemy.dialects import mysql
from sqlalchemy.schema import CreateTable

from app.ai import infection_cluster_contract as c
from app.ai import infection_cluster_task_contract as t
from app.ai.infection_cluster_run_models import AIInfectionRunArtifact

ID = "00000000-0000-0000-0000-000000000001"


def test_task_accepts_only_actual_explicit_scenario_and_strict_preview_no_scope_or_arithmetic_overrides():
    value = dict(infection_cluster_scenario_id=ID, preview=False)
    assert t.TaskCreate.model_validate(value).infection_cluster_scenario_id == ID
    for mutation in [dict(preview=0), dict(preview=None), dict(alpha_decimal="0.01"), dict(patient_id=1), dict(provider_id=None), dict(question="ignored"), dict(infection_cluster_scenario_id=None)]:
        with pytest.raises(ValidationError):
            t.TaskCreate.model_validate({**value, **mutation})
    with pytest.raises(ValidationError):
        t.TaskCreate.model_validate({"infection_cluster_scenario_id": ID})


def test_local_fixed_recipe_hash_is_canonical_pair_and_does_not_claim_a_model_prompt_call():
    assert t.LOCAL_PROMPT_HASH == c.digest(["", t.LOCAL_TASK_TEXT])
    assert '"origin":"local_fixed_recipe"' in t.LOCAL_TASK_TEXT and '"engine":"prediction"' in t.LOCAL_TASK_TEXT
    assert '"max_records":4096' in t.LOCAL_TASK_TEXT
    assert "APIProvider" not in t.LOCAL_TASK_TEXT


@pytest.mark.parametrize("role", ["admin", "super_admin", "director"])
def test_request_epoch_retains_real_allowed_role_and_literal_token_clock(role):
    raw = dict(user_id=1, user_role=role, token_invalid_before="2026-10-21T00:00:00.123456")
    assert t.RequesterEpoch.model_validate(raw).model_dump() == raw
    for bad in ["2026-10-21T00:00:00Z", "2026-10-21 00:00:00", "2026-02-30T00:00:00"]:
        with pytest.raises(ValidationError):
            t.RequesterEpoch.model_validate({**raw, "token_invalid_before": bad})


def usage(**extra):
    return dict(
        schema_version="infection_local_usage_v1",
        run_id=ID,
        lease=None,
        terminal_status="cancelled",
        input_tokens=0,
        output_tokens=0,
        model_call_attempted=False,
        accounting_basis="installed_local_calculation_without_external_model_call_not_a_cpu_cost_estimate",
        calculation_attempted=False,
        calculation_completed=False,
        calculation_ms=None,
        result_hash=None,
        **extra,
    )


def test_wholly_local_external_token_zero_is_separate_from_unknown_or_observed_cpu_attempt():
    assert t.LocalUsage.model_validate(usage()).calculation_attempted is False
    pending = usage()
    pending.update(calculation_attempted=None, calculation_completed=None)
    assert t.LocalUsage.model_validate(pending).calculation_attempted is None
    for changed in [dict(input_tokens=False), dict(output_tokens=1), dict(model_call_attempted=True), dict(calculation_completed=True), dict(calculation_ms=0), dict(result_hash="a" * 64)]:
        with pytest.raises(ValidationError):
            t.LocalUsage.model_validate({**usage(), **changed})
    observed = usage()
    observed.update(terminal_status="succeeded", lease=ID, calculation_attempted=True, calculation_completed=True, calculation_ms=0, result_hash="a" * 64)
    assert t.LocalUsage.model_validate(observed).calculation_ms == 0


def test_legacy_text_budget_is_actual_utf8_whole_not_clipped_codepoints():
    assert len(c.utf8(t.task_json("a" * 65533))) == 65535
    with pytest.raises(ValueError):
        t.task_json("a" * 65534)
    with pytest.raises(ValueError):
        t.task_json("😀" * 16384)


def test_actual_artifact_real_foreign_keys_split_bytes_and_independent_audits_mysql_ddl():
    table = AIInfectionRunArtifact.__table__
    ddl = str(CreateTable(table).compile(dialect=mysql.dialect()))
    assert ddl.count("MEDIUMTEXT") == 2 and ddl.count("DATETIME(6)") == 2
    assert len(table.foreign_keys) == 8
    for target in [
        "hoimsystem_ai_run",
        "hoimsystem_ai_infection_scenario",
        "hoimsystem_ai_infection_snapshot",
        "hoimsystem_ai_infection_local_profile",
        "hoimsystem_users",
        "hoimsystem_ai_audit_event",
    ]:
        assert target in ddl
    assert "accept_event_id<>usage_event_id" in ddl and "CAST(source_json AS BINARY)" in ddl
    assert "APIProvider" not in ddl and "mapping_key" not in table.columns


def test_sqlite_additive_up_down_up_preserves_original_rows_and_mysql_uses_octets():
    path = Path(__file__).parents[1] / "alembic/versions/20261021_infection_runs.py"
    spec = importlib.util.spec_from_file_location("infection_runs_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    assert migration.down_revision == "20261021_infection_profiles"
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        conn.exec_driver_sql("CREATE TABLE original(id INTEGER PRIMARY KEY,raw TEXT)")
        conn.exec_driver_sql("INSERT INTO original VALUES(1,'原样😀')")
        with Operations.context(MigrationContext.configure(conn)):
            migration.upgrade()
            assert AIInfectionRunArtifact.__tablename__ in inspect(conn).get_table_names()
            migration.downgrade()
            migration.upgrade()
        assert conn.exec_driver_sql("SELECT * FROM original").all() == [(1, "原样😀")]
    engine.dispose()
    output = io.StringIO()
    with Operations.context(MigrationContext.configure(dialect_name="mysql", opts={"as_sql": True, "output_buffer": output})):
        migration.upgrade()
        migration.downgrade()
    ddl = output.getvalue()
    assert "CAST(source_json AS BINARY)" in ddl and "CAST(result_json AS BINARY)" in ddl and " AS BLOB" not in ddl and "DROP INDEX" not in ddl
