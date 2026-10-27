"""Native orphan detection must work on PostgreSQL without fetching Task text."""

import json
import os
import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.ai import infection_cluster_task_contract as contract
from app.ai.infection_cluster_task_storage import guard_run_id
from app.ai.models import AIRun
from app.models import Base, User

MARKERS = ("infection_local_frozen_task_v1", "infection_statistics_result_pointer_v1", "infection_cluster_scenario_id")
CASES = [(None, None, False), ("feature_key", contract.FEATURE_KEY, True), ("input_json", "infectionXclusterXscenarioXid", False)] + [
    (field, marker, True) for field in contract.RAW_FIELDS for marker in MARKERS
]


@pytest.fixture(scope="module")
def isolated_marker_engine():
    value = os.getenv("HOIM_TEST_POSTGRES_URL")
    if not value:
        pytest.skip("requires explicit isolated local benchmark PostgreSQL")
    url = make_url(value)
    assert url.get_backend_name() == "postgresql" and url.database == "hoimsystem_benchmark" and url.host in {"127.0.0.1", "localhost", "::1"}, "refusing a non-benchmark database"
    schema = "validation_markers_" + uuid.uuid4().hex
    owner = create_engine(url)
    with owner.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    isolated = create_engine(url, connect_args={"options": f"-csearch_path={schema} -cstatement_timeout=3000"})
    try:
        Base.metadata.create_all(isolated)
        yield isolated
    finally:
        isolated.dispose()
        with owner.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        owner.dispose()


@pytest.mark.parametrize("field,marker,marked", CASES)
def test_postgresql_scalar_native_locator_keeps_orphan_rejection_without_private_text(isolated_marker_engine, field, marker, marked):
    with Session(isolated_marker_engine) as db:
        user = User(username="marker_" + uuid.uuid4().hex[:12], password="synthetic-unused-hash", user_role="super_admin")
        db.add(user)
        db.flush()
        run = AIRun(feature_key="patient_summary", requested_by=user.user_id, prompt_hash="0" * 64, context_digest="0" * 64)
        if field is not None:
            setattr(run, field, marker if field == "feature_key" else json.dumps({"note": "prefix:" + marker + ":suffix"}))
        db.add(run)
        db.commit()
        rid = run.run_id
        statements = []

        def capture(_conn, _cursor, sql, _params, _context, _many):
            statements.append(sql)

        event.listen(isolated_marker_engine, "before_cursor_execute", capture)
        try:
            if marked:
                with pytest.raises(HTTPException) as raised:
                    guard_run_id(db, user, rid)
                assert raised.value.status_code == 409
            else:
                assert guard_run_id(db, user, rid) is False
        finally:
            event.remove(isolated_marker_engine, "before_cursor_execute", capture)
        assert statements
        for sql in statements:
            projection = sql.lower().split("from", 1)[0]
            assert all("hoimsystem_ai_run." + name not in projection for name in contract.RAW_FIELDS)
