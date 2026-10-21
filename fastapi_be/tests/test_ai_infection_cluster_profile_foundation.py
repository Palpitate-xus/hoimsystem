"""Explicit local model/config declarations and additive DDL, not clinical proof."""

import copy
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
from app.ai import infection_cluster_profile_input as i
from app.ai.infection_cluster_implementation import implementation_descriptor
from app.ai.infection_cluster_profile_models import AIInfectionLocalProfile, AIInfectionLocalSelection


def request():
    return dict(
        version_label="明确本地版本v1",
        expected_implementation_hash=c.digest(implementation_descriptor()),
        scope=dict(
            definition_id="00000000-0000-0000-0000-000000000001",
            definition_content_hash="a" * 64,
            definition_governance_hash="b" * 64,
            department_ids=[1],
            source_window=dict(date_from="2026-10-01", date_to="2026-10-21", coordinate_basis="recorded_onset_date_inclusive_no_event_timezone"),
            pathogen_codes=["LOCAL_P"],
            alpha_decimals=["0.0500"],
            max_source_records=4096,
            max_comparisons=256,
            unknown_department_policy="retain_all_unknown_records_and_exclude_from_inference_not_normal",
            scope_basis="only_explicit_source_records_departments_definition_calendar_and_literal_parameters_not_hospital_coverage",
        ),
        validation_status="unreviewed",
        validation_evidence_reference=None,
        validation_basis_note="尚未提供真实本地验证，不能因方法/代码身份而启用。",
        basis_note="完整代码/参数/范围声明，不冒称临床有效。",
    )


def test_explicit_recorded_validation_has_no_automatic_positive_defaults():
    value = i.ProfileCreate.model_validate(request())
    assert value.validation_status == "unreviewed" and value.validation_evidence_reference is None
    with pytest.raises(ValidationError):
        i.ProfileCreate.model_validate({**request(), "validation_status": "validated"})
    assert (
        i.ProfileCreate.model_validate({**request(), "validation_status": "validated", "validation_evidence_reference": "synthetic-test-only:not-real-clinical-validation"}).validation_status
        == "validated"
    )
    for field in ("validation_status", "expected_implementation_hash"):
        value = request()
        del value[field]
        with pytest.raises(ValidationError):
            i.ProfileCreate.model_validate(value)


@pytest.mark.parametrize(
    "field,value",
    [
        ("alpha_decimals", [0.05]),
        ("alpha_decimals", ["0"]),
        ("department_ids", [1, 1]),
        ("pathogen_codes", ["LOCAL_P", "LOCAL_P"]),
        ("max_comparisons", 257),
        ("max_source_records", True),
        ("max_source_records", 4097),
    ],
)
def test_review_scope_does_not_deduplicate_normalize_or_exceed_fixed_recipe(field, value):
    raw = request()
    raw["scope"][field] = value
    with pytest.raises(ValidationError):
        i.ProfileCreate.model_validate(raw)


def test_local_descriptor_is_closed_not_a_fabricated_provider_or_endpoint():
    descriptor = implementation_descriptor()
    assert i.InstalledImplementation.model_validate(descriptor).automatic_enable is False
    for mutation in (dict(api_base="http://fake-local-endpoint"), dict(local_clinical_validation="validated"), dict(automatic_enable=True)):
        with pytest.raises(ValidationError):
            i.InstalledImplementation.model_validate({**descriptor, **mutation})
    changed = copy.deepcopy(descriptor)
    changed["code_hashes"].pop("infection_cluster_contract.py")
    with pytest.raises(ValidationError):
        i.InstalledImplementation.model_validate(changed)


def test_local_configuration_is_explicit_disabled_without_profile_and_rejects_provider_fields():
    raw = dict(
        expected_feature_revision=0,
        expected_selection_revision=0,
        profile_id=None,
        enabled=False,
        allowed_roles=["super_admin"],
        validation_status="unreviewed",
        validation_note=None,
        daily_limit=10,
        basis_note="明确关闭本地功能，不选择或伪造任何外部模型。",
    )
    assert i.LocalConfigWrite.model_validate(raw).profile_id is None
    for change in (dict(enabled=True), dict(provider_id=1), dict(enabled=1), dict(validation_status="validated"), dict(allowed_roles=["admin", "admin"])):
        with pytest.raises(ValidationError):
            i.LocalConfigWrite.model_validate({**raw, **change})


def test_mysql_actual_model_types_and_selection_real_foreign_keys():
    ddl = "\n".join(str(CreateTable(model.__table__).compile(dialect=mysql.dialect())) for model in (AIInfectionLocalProfile, AIInfectionLocalSelection))
    assert ddl.count("DATETIME(6)") == 4 and ddl.count("MEDIUMTEXT") == 1
    assert "hoimsystem_ai_feature_config" in ddl and "change_event_id" in ddl
    assert "reviewed_by<>created_by" in ddl


def test_incremental_sqlite_up_down_up_and_mysql_down_does_not_drop_supporting_indexes_first():
    path = Path(__file__).parents[1] / "alembic/versions/20261021_infection_profiles.py"
    spec = importlib.util.spec_from_file_location("infection_profiles_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    assert migration.down_revision == "20261021_infection_scenarios"
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        conn.exec_driver_sql("CREATE TABLE original (id INTEGER PRIMARY KEY, raw TEXT)")
        conn.exec_driver_sql("INSERT INTO original VALUES(1, '原样😀')")
        with Operations.context(MigrationContext.configure(conn)):
            migration.upgrade()
            assert all(m.__tablename__ in inspect(conn).get_table_names() for m in (AIInfectionLocalProfile, AIInfectionLocalSelection))
            migration.downgrade()
            migration.upgrade()
        assert conn.exec_driver_sql("SELECT * FROM original").all() == [(1, "原样😀")]
    engine.dispose()
    output = io.StringIO()
    with Operations.context(MigrationContext.configure(dialect_name="mysql", opts={"as_sql": True, "output_buffer": output})):
        migration.upgrade()
        migration.downgrade()
    sql = output.getvalue()
    assert "CAST(payload_json AS BINARY)" in sql and " AS BLOB" not in sql and "DROP INDEX" not in sql
    assert sql.index("DROP TABLE hoimsystem_ai_infection_local_selection") < sql.index("DROP TABLE hoimsystem_ai_infection_local_profile")
