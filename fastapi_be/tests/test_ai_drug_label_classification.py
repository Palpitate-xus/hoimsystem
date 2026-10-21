"""Current durable classification precedes generic IDs and private task text."""

from types import SimpleNamespace

import pytest
from sqlalchemy import event
from sqlalchemy.dialects import mysql

from app.ai import drug_label_runtime as runtime
from app.ai import drug_label_storage as storage
from app.ai.models import AIRun
from tests.test_ai_drug_label_sources import label_case as _label_case
from tests.test_ai_drug_label_storage import make_task

label_case = _label_case


@pytest.mark.parametrize("role", ["doctor_user", "patient_user"])
def test_non_uuid_generic_real_task_keeps_original_route_and_no_source_permission_is_granted(label_case, role):
    case = make_task(label_case)
    identifier = "legacy-generic-73-" + role
    row = AIRun(run_id=identifier, feature_key="synthetic_generic", requested_by=case.users[role].user_id, provider_id=case.provider.provider_id, prompt_hash="0" * 64, context_digest="0" * 64)
    case.db.add(row)
    case.db.commit()
    assert storage.is_drug_label_run(case.db, row) is False
    assert runtime.guard_drug_label_run_id(case.db, case.users[role], identifier) is False
    assert runtime.guard_drug_label_run_id(case.db, case.users[role], "missing-generic-73") is False


def test_current_artifact_before_json_marker_parsing_and_expired_run_never_loads_private_text(label_case, monkeypatch):
    case = make_task(label_case)
    db, row = case.db, case.run
    identifier = row.run_id
    db.expire(row)
    sql = []

    def observe(state):
        if state.is_select:
            sql.append(str(state.statement.compile(dialect=mysql.dialect())))

    def no_json(*args, **kwargs):
        raise AssertionError("A real current Artifact must classify before parsing any task JSON")

    event.listen(db, "do_orm_execute", observe)
    monkeypatch.setattr(storage.json, "loads", no_json)
    try:
        assert storage.is_drug_label_run(db, row)
        assert not any("hoimsystem_ai_run.input_json" in query or "mapping_seed" in query or "snapshot_json" in query for query in sql)
        locator = next(query for query in sql if "hoimsystem_ai_drug_label_run_artifact" in query)
        assert "LOCK IN SHARE MODE" in locator
        assert storage._opaque_run_id(row) == identifier
    finally:
        event.remove(db, "do_orm_execute", observe)


def test_actual_anchor_wins_after_loaded_feature_and_all_json_markers_are_stripped(label_case):
    case = make_task(label_case)
    case.db.query(AIRun).filter_by(run_id=case.run.run_id).update(
        {"feature_key": "generic", "input_json": "{}", "result_json": "{}", "context_metadata_json": "{}", "evidence_json": "[]"}, synchronize_session=False
    )
    case.db.commit()
    assert storage.is_drug_label_run(case.db, SimpleNamespace(run_id=case.run.run_id, feature_key="generic", input_json="{}", result_json="{}"))
