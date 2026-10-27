"""PostgreSQL gates must retain an exclusive lock through transaction commit."""

import os
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import dialect
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.ai.charge_reconciliation_models import AIChargeWriteGate
from app.ai.charge_reconciliation_write_guard import lock_charge_gate
from app.ai.coding_evidence_guard import lock_coding_gate
from app.ai.coding_evidence_models import AICodingWriteGate
from app.ai.infection_cluster_models import AIInfectionWriteGate
from app.ai.infection_cluster_write_guard import lock_gate
from app.ai.inventory_native_source_models import AIInventoryWriteGate
from app.ai.inventory_write_guard import lock_inventory_gate
from app.ai.research_cohort_models import AIResearchWriteGate
from app.ai.research_cohort_write_guard import lock_research_gate
from app.ai.satisfaction_models import AISatisfactionWriteGate
from app.ai.satisfaction_write_guard import lock_satisfaction_gate
from app.sql_locks import postgresql_gate_statement

GATES = [
    (AIChargeWriteGate, lock_charge_gate), (AICodingWriteGate, lock_coding_gate),
    (AIInfectionWriteGate, lock_gate), (AIInventoryWriteGate, lock_inventory_gate),
    (AIResearchWriteGate, lock_research_gate), (AISatisfactionWriteGate, lock_satisfaction_gate),
]


@pytest.mark.parametrize(("model", "_lock"), GATES, ids=[model.__name__ for model, _ in GATES])
def test_postgresql_gate_statement_takes_update_lock_without_epoch_increment(model, _lock):
    sql = str(postgresql_gate_statement(model).compile(dialect=dialect(), compile_kwargs={"literal_binds": True}))
    assert "ON CONFLICT (gate_id) DO UPDATE SET revision = " in sql
    assert "DO NOTHING" not in sql
    assert "+ 1" not in sql


@pytest.fixture
def postgres_engine():
    value = os.getenv("HOIM_TEST_POSTGRES_URL")
    if not value:
        pytest.skip("set HOIM_TEST_POSTGRES_URL to the isolated local hoimsystem_benchmark database")
    url = make_url(value)
    if url.get_backend_name() != "postgresql" or url.database != "hoimsystem_benchmark" or url.host not in {"127.0.0.1", "localhost", "::1"}:
        pytest.fail("refusing a PostgreSQL gate test outside the explicit local benchmark database")
    engine = create_engine(url, pool_pre_ping=True, connect_args={"options": "-c statement_timeout=10000"})
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.mark.parametrize(("model", "lock"), GATES, ids=[model.__name__ for model, _ in GATES])
def test_actual_postgresql_gate_serializes_two_transactions(postgres_engine, model, lock):
    entered, completed = threading.Event(), threading.Event()

    def contender():
        with Session(postgres_engine) as other:
            entered.set()
            row = lock(other)
            revision = row.revision
            other.commit()
            completed.set()
            return revision

    with Session(postgres_engine) as first, ThreadPoolExecutor(max_workers=1) as pool:
        initial = lock(first)
        revision = initial.revision
        future = pool.submit(contender)
        try:
            assert entered.wait(timeout=3)
            assert not completed.wait(timeout=0.15), "second transaction escaped the first transaction's gate"
        finally:
            first.commit()
        assert future.result(timeout=10) == revision
    with Session(postgres_engine) as db:
        assert db.query(model).filter_by(gate_id=1).count() == 1
        assert db.get(model, 1).revision == revision
