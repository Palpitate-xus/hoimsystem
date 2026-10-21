"""Actual stage FK checks stay enabled and cannot leak to unrelated tests."""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from tests.rca_sqlite_test_support import preserve_foreign_key_mode
from tests.test_ai_rca_evidence_grants import grant_case as grant_case
from tests.test_ai_rca_evidence_storage import stage


@pytest.mark.parametrize("raise_after_stage", [False, True])
def test_actual_task_stage_enforces_fk_and_restores_original_connection_policy_on_normal_and_exception_exit(grant_case, raise_after_stage):
    db = grant_case["db"]
    original = db.execute(text("PRAGMA foreign_keys")).scalar_one()

    def scoped_task():
        with preserve_foreign_key_mode(db):
            stored, _ = stage(grant_case)
            assert db.execute(text("PRAGMA foreign_keys")).scalar_one() == 1
            with pytest.raises(IntegrityError, match="FOREIGN KEY constraint failed"):
                db.execute(text("UPDATE hoimsystem_ai_rca_evidence_run_artifact SET requested_by=2147483647 WHERE run_id=:run"), {"run": stored.run.run_id})
            db.rollback()
            if raise_after_stage:
                raise ValueError("controlled actual test-body exception")

    if raise_after_stage:
        with pytest.raises(ValueError, match="controlled actual test-body exception"):
            scoped_task()
    else:
        scoped_task()
    assert db.execute(text("PRAGMA foreign_keys")).scalar_one() == original
