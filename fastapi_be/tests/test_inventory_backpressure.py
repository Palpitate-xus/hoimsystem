"""Real PostgreSQL lock deadlines must reject cleanly without partial writes."""

import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.ai.inventory_native_source_models import AIInventoryWriteGate
from app.ai.inventory_write_guard import lock_inventory_gate
from tests.test_postgresql_write_gates import postgres_engine as postgres_engine


@pytest.mark.parametrize("timeout", ["lock_timeout", "statement_timeout"])
def test_inventory_lock_deadline_returns_retryable_response_and_rolls_back(postgres_engine, timeout):
    schema = "inventory_pressure_" + uuid.uuid4().hex
    with postgres_engine.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        connection.execute(text(f'CREATE TABLE "{schema}".business_probe (value INTEGER)'))
    isolated = postgres_engine.execution_options(schema_translate_map={None: schema})
    AIInventoryWriteGate.__table__.create(isolated)
    try:
        with Session(isolated) as owner, Session(isolated) as contender:
            lock_inventory_gate(owner)
            contender.execute(text(f"SET LOCAL {timeout} = '100ms'"))
            contender.execute(text(f'INSERT INTO "{schema}".business_probe VALUES (1)'))
            with pytest.raises(HTTPException) as raised:
                lock_inventory_gate(contender)
            assert raised.value.status_code == 503
            assert raised.value.headers == {"Retry-After": "1"}
            assert "繁忙" in raised.value.detail
            assert contender.execute(text("SELECT 1")).scalar_one() == 1
            assert contender.execute(text(f'SELECT count(*) FROM "{schema}".business_probe')).scalar_one() == 0
            owner.rollback()
    finally:
        with postgres_engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
