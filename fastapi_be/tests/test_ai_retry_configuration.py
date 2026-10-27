"""Retry policy governance, frozen history and an additive reversible migration."""

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from pydantic import ValidationError
from sqlalchemy.dialects import mysql, postgresql
from sqlalchemy.schema import CreateTable

from app.ai.charge_reconciliation_frozen import ChargeFrozenProvider
from app.ai.coding_evidence_frozen import CodingFrozenProvider
from app.ai.deidentification_task_contract import FrozenProvider
from app.ai.document_extraction_view_contract import DocumentFrozenProvider
from app.ai.models import AIProvider
from app.ai.rca_evidence_task_views import RcaFrozenProvider
from app.ai.research_variables_storage_contract import VariableFrozenProvider
from app.ai.retry_policy import retry_snapshot_hash_matches, retry_snapshots_equal
from app.ai.satisfaction_frozen import SatisfactionFrozenProvider
from app.ai.schemas import ProviderWrite

PROVIDERS = (ChargeFrozenProvider, CodingFrozenProvider, FrozenProvider, DocumentFrozenProvider, RcaFrozenProvider, VariableFrozenProvider, SatisfactionFrozenProvider)
LEGACY = dict(provider_id=1, revision=1, name="synthetic", kind="chat", api_base="http://localhost:11434/v1", model="synthetic", timeout_seconds=30, max_output_tokens=2000, validation_report="", temperature=0.2, allows_patient_data=True, effective_output_limit=2000)


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


@pytest.mark.parametrize("model", PROVIDERS)
def test_original_frozen_provider_bytes_and_implicit_single_attempt_are_preserved(model):
    frozen = model.model_validate(LEGACY)
    assert frozen.max_attempts == 1
    assert frozen.model_dump(mode="json") == LEGACY
    assert digest(frozen.model_dump(mode="json")) == digest(LEGACY)
    current = {**LEGACY, "max_attempts": 1}
    assert retry_snapshots_equal(current, frozen)
    assert retry_snapshot_hash_matches({"provider_snapshot": current}, digest({"provider_snapshot": LEGACY}), digest)
    assert not retry_snapshots_equal({**current, "max_attempts": 2}, frozen)
    assert not retry_snapshots_equal({**current, "revision": 2}, frozen)


@pytest.mark.parametrize("model", PROVIDERS)
@pytest.mark.parametrize("attempts", (1, 2, 3))
def test_new_frozen_policy_preserves_explicit_attempts_and_closed_structure(model, attempts):
    wire = {**LEGACY, "max_attempts": attempts}
    assert model.model_validate(wire).model_dump(mode="json") == wire
    with pytest.raises(ValidationError):
        model.model_validate({**wire, "retry_unbounded": True})


@pytest.mark.parametrize("attempts", (None, True, False, 0, 4, "2", 2.0))
def test_management_and_frozen_policies_reject_noninteger_or_out_of_range(attempts):
    with pytest.raises(ValidationError):
        ProviderWrite(name="test", api_base="http://localhost/v1", model="test", max_attempts=attempts)
    with pytest.raises(ValidationError):
        DocumentFrozenProvider.model_validate({**LEGACY, "max_attempts": attempts})


def test_new_provider_defaults_to_three_but_specialist_remains_single_attempt():
    common = dict(name="test", api_base="http://localhost/v1", model="test")
    assert ProviderWrite(**common).max_attempts == 3
    assert ProviderWrite(**common, kind="specialist").max_attempts == 1


@pytest.mark.asyncio
async def test_super_admin_controls_retry_policy_with_revision_conflicts(async_client, seed_data, auth_headers, db_session):
    headers = auth_headers("super01")
    body = dict(name="retry-governance", api_base="http://localhost:11434/v1", model="synthetic")
    denied = await async_client.post("/api/ai/admin/providers", headers=auth_headers("admin"), json=body)
    assert denied.status_code == 403
    created = await async_client.post("/api/ai/admin/providers", headers=headers, json=body)
    assert created.status_code == 200
    current = created.json()["data"]
    assert current["max_attempts"] == 3
    path = "/api/ai/admin/providers/" + str(current["provider_id"])
    request = {**body, "max_attempts": 1, "expected_revision": current["revision"]}
    saved = await async_client.put(path, headers=headers, json=request)
    assert saved.status_code == 200 and saved.json()["data"]["max_attempts"] == 1
    assert saved.json()["data"]["revision"] == current["revision"] + 1
    stale = await async_client.put(path, headers=headers, json=request)
    assert stale.status_code == 409
    listed = await async_client.get("/api/ai/admin/providers", headers=headers)
    assert next(row for row in listed.json()["data"] if row["provider_id"] == current["provider_id"])["max_attempts"] == 1
    assert db_session.get(AIProvider, current["provider_id"]).max_attempts == 1


def migration(name="ai_provider_retry"):
    file = Path(__file__).resolve().parents[1] / ("alembic/versions/20261027_" + name + ".py")
    spec = importlib.util.spec_from_file_location("isolated_provider_retry_migration", file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_retry_migration_retains_existing_single_attempt_rows_and_new_default(tmp_path):
    engine = sa.create_engine("sqlite:///" + str(tmp_path / "retry-migration.sqlite"))
    with engine.begin() as connection:
        connection.execute(sa.text("CREATE TABLE hoimsystem_ai_provider (provider_id INTEGER PRIMARY KEY, name TEXT NOT NULL, revision INTEGER NOT NULL, credential TEXT)"))
        connection.execute(sa.text("INSERT INTO hoimsystem_ai_provider VALUES (1,'synthetic',7,'opaque-synthetic')"))
        old = tuple(connection.execute(sa.text("SELECT * FROM hoimsystem_ai_provider")).one())
        with Operations.context(MigrationContext.configure(connection)):
            migration().upgrade()
        assert tuple(connection.execute(sa.text("SELECT provider_id,name,revision,credential FROM hoimsystem_ai_provider WHERE provider_id=1")).one()) == old
        assert connection.scalar(sa.text("SELECT max_attempts FROM hoimsystem_ai_provider WHERE provider_id=1")) == 1
        connection.execute(sa.text("INSERT INTO hoimsystem_ai_provider(provider_id,name,revision) VALUES (2,'new',1)"))
        assert connection.scalar(sa.text("SELECT max_attempts FROM hoimsystem_ai_provider WHERE provider_id=2")) == 3
        for value in (0, 4):
            with pytest.raises(sa.exc.IntegrityError), connection.begin_nested():
                connection.execute(sa.text("UPDATE hoimsystem_ai_provider SET max_attempts=:value WHERE provider_id=2"), {"value": value})
        with Operations.context(MigrationContext.configure(connection)):
            migration().downgrade()
        assert "max_attempts" not in {row["name"] for row in sa.inspect(connection).get_columns("hoimsystem_ai_provider")}
        assert tuple(connection.execute(sa.text("SELECT * FROM hoimsystem_ai_provider WHERE provider_id=1")).one()) == old
    engine.dispose()


def test_unknown_usage_migration_preserves_rows_and_rejects_lossy_downgrade(tmp_path):
    engine = sa.create_engine("sqlite:///" + str(tmp_path / "nullable-usage.sqlite"))
    with engine.begin() as connection:
        connection.execute(sa.text("CREATE TABLE hoimsystem_ai_run (run_id TEXT PRIMARY KEY, input_tokens INTEGER NOT NULL, output_tokens INTEGER NOT NULL)"))
        connection.execute(sa.text("INSERT INTO hoimsystem_ai_run VALUES ('synthetic',5,7)"))
        with Operations.context(MigrationContext.configure(connection)):
            migration("text_retry_usage").upgrade()
        assert tuple(connection.execute(sa.text("SELECT * FROM hoimsystem_ai_run")).one()) == ("synthetic", 5, 7)
        connection.execute(sa.text("UPDATE hoimsystem_ai_run SET input_tokens=NULL"))
        with Operations.context(MigrationContext.configure(connection)), pytest.raises(RuntimeError, match="unknown must not become zero"):
            migration("text_retry_usage").downgrade()
        assert connection.scalar(sa.text("SELECT input_tokens IS NULL FROM hoimsystem_ai_run")) == 1
        assert all(row["nullable"] for row in sa.inspect(connection).get_columns("hoimsystem_ai_run") if row["name"] in {"input_tokens", "output_tokens"})
    engine.dispose()


@pytest.mark.parametrize("dialect", (mysql.dialect(), postgresql.dialect()))
def test_provider_retry_column_default_and_closed_bounds_compile_for_supported_servers(dialect):
    ddl = str(CreateTable(AIProvider.__table__).compile(dialect=dialect))
    assert "max_attempts INTEGER NOT NULL DEFAULT '3'" in ddl or "max_attempts INTEGER DEFAULT '3' NOT NULL" in ddl
    assert "max_attempts BETWEEN 1 AND 3" in ddl
