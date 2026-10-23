"""Bridge real domain lifecycle receipts into administrative accounting tests."""

import uuid

from sqlalchemy import event, select

from app.ai.admin_read_snapshot import admin_read_snapshot
from app.ai.admin_usage_receipts import artifact_headers, checked_usage, receipt_bodies
from app.ai.admin_usage_summary import RUN_FIELDS, usage_summary
from app.ai.native_task_routing import _domains
from app.models import User


def assert_exact_usage_event(db, run_id, domain, expected):
    # This independent Super has no patient, event, study or Source purposes.
    actor = User(username="usg_" + uuid.uuid4().hex[:12], password="synthetic-only", user_role="super_admin")
    db.add(actor)
    db.flush()
    returned = []

    def observe(conn, cursor, statement, params, context, many):
        if statement.lstrip().lower().startswith("select"):
            returned.extend(column[0] for column in cursor.description or [])

    event.listen(db.bind, "after_cursor_execute", observe)
    try:
        from app.ai.models import AIRun

        with admin_read_snapshot(db, actor) as snapshot:
            run = snapshot.execute(select(*(getattr(AIRun, name) for name in RUN_FIELDS)).where(AIRun.run_id == run_id)).mappings().one()
            anchors = artifact_headers(snapshot, [run_id], _domains())[run_id]
            assert len(anchors) == 1 and anchors[0][0] == domain
            artifact = anchors[0][1]
            raw = receipt_bodies(snapshot, [(run, domain, artifact)])[(run_id, domain)]
            actual = checked_usage(run, domain, artifact, raw)
            assert {key: actual[key] for key in ("input_tokens", "output_tokens", "model_call_attempted")} == {key: expected[key] for key in ("input_tokens", "output_tokens", "model_call_attempted")}
        summary = usage_summary(db, actor)
        assert summary["coverage"]["complete"] and summary["coverage"]["total"] == summary["coverage"]["scanned"]
        assert any(row["recorded_count"] > 0 for row in summary["data"])
    finally:
        event.remove(db.bind, "after_cursor_execute", observe)
    private = {
        "input_json",
        "evidence_json",
        "context_metadata_json",
        "result_json",
        "source_json",
        "binding_json",
        "prompt_snapshot_json",
        "execution_snapshot_json",
        "private_json",
        "public_json",
        "patient_id",
        "encounter_ref",
        "error_message",
    }
    assert not any(name == key or name.endswith("_" + key) for name in returned for key in private), returned
    return actual
