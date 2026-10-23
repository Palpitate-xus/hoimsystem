"""Actual SQL mixed dispatch; no hospital, live inference or MySQL claim."""

import datetime
import json
import subprocess
import sys
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi import HTTPException
from sqlalchemy import event, inspect
from sqlalchemy.dialects import mysql

from app.ai import native_task_routing as routing
from app.ai.models import AIRun
from tests.test_ai_charge_reconciliation_runtime import configured
from tests.test_ai_charge_reconciliation_sources import charge_case as charge_case  # noqa: F401
from tests.test_ai_document_extraction_storage import task_factory as task_factory  # noqa: F401
from tests.test_ai_drug_label_sources import label_case as label_case  # noqa: F401
from tests.test_ai_drug_label_storage import make_task
from tests.test_ai_satisfaction_sources import satisfaction_case as satisfaction_case  # noqa: F401
from tests.test_ai_satisfaction_storage import configured_run

ROOT = Path(__file__).resolve().parents[1]


def test_catalog_exports_all_fixed_prompts_with_only_standard_library():
    script = """
import builtins,json,runpy
real=builtins.__import__
def checked(name,*args,**kwargs):
    if name.split('.')[0] in {'pydantic','pydantic_settings','sqlalchemy','dotenv'} or name in {'app.config','app.database','app.models'}:
        raise AssertionError('Forbidden metadata dependency: '+name)
    return real(name,*args,**kwargs)
builtins.__import__=checked
values=runpy.run_path('scripts/export_ai_catalog.py')['artifacts']()
p=json.loads(next(text for path,text in values.items() if str(path).endswith('ai-prompts.json')))
print(json.dumps({'features':len(p['features']),'version':p['catalog_version'],'overrides':sorted(p['system_prompt_overrides'])}))
"""
    value = subprocess.run([sys.executable, "-I", "-S", "-c", script], cwd=ROOT, capture_output=True, text=True, check=True)
    assert json.loads(value.stdout) == {
        "features": 80,
        "version": "2026.10.23.32",
        "overrides": ["charge_reconciliation", "clinical_training", "deidentification", "drg_evidence_review", "drug_label_extraction", "feedback_analysis", "guideline_change_review", "guideline_ingestion", "incident_rca", "operations_support", "research_cohort", "research_extraction"],
    }


def test_prompt_reexports_remain_equal_to_actual_typed_protocol_constants():
    from app.ai import document_extraction_contract, document_extraction_prompt, drug_label_draft, drug_label_prompt

    for key in ("EXTRACTION_SYSTEM_PROMPT", "EXTRACTION_TASK_PROMPT"):
        assert getattr(document_extraction_contract, key) == getattr(document_extraction_prompt, key)
    for key in ("SYSTEM_PROMPT", "TASK_PROMPT"):
        assert getattr(drug_label_draft, key) == getattr(drug_label_prompt, key)


def test_additive_merge_has_one_head_and_preserves_both_parent_histories():
    scripts = ScriptDirectory.from_config(Config(str(ROOT / "alembic.ini")))
    assert len(scripts.get_heads()) == 1
    assert set(scripts.get_revision("20261021_native_shared_merge").down_revision) == {"20261021_charge_sat_merge", "20261021_drug_label_runs"}
    chain = list(scripts.walk_revisions())
    assert len(chain) == len({row.revision for row in chain})
    assert {"20261021_native_shared_merge", "20261021_charge_sat_merge", "20261021_drug_label_runs", "20261021_doc_extraction_runs", "20261021_charge_runs", "20261021_sat_usage_receipt"} <= {
        row.revision for row in chain
    }


@pytest.fixture
def actual_native(request, db_session):
    domain = request.param
    if domain == "charge":
        from app.ai.charge_reconciliation_runtime import create_charge_run

        case = request.getfixturevalue("charge_case")
        actor, req, *_ = configured(case)
        return domain, db_session, create_charge_run(db_session, actor, req)
    if domain == "satisfaction":
        case = configured_run(db_session, request.getfixturevalue("satisfaction_case"))
        return domain, db_session, case["run"]
    if domain == "drug_label":
        case = make_task(request.getfixturevalue("label_case"))
        return domain, case.db, case.run
    case = request.getfixturevalue("task_factory")()
    return domain, case.db, case.run


@pytest.mark.parametrize("actual_native", ["charge", "satisfaction", "document", "drug_label"], indirect=True)
def test_actual_dispatch_reads_only_opaque_columns_without_gate_run_lock_or_expired_body(actual_native):
    domain, db, row = actual_native
    identifier = inspect(row).identity[0]
    db.expire(row)
    sql = []

    def observe(state):
        if state.is_select:
            sql.append(str(state.statement.compile(dialect=mysql.dialect())))

    event.listen(db, "do_orm_execute", observe)
    try:
        found = routing.locate_native_task(db, row)
    finally:
        event.remove(db, "do_orm_execute", observe)
    assert found.domain == domain and found.run_id == identifier and found.source_id and type(found.requested_by) is int
    assert sql and all("FOR UPDATE" not in query and "LOCK IN SHARE MODE" not in query and "write_gate" not in query for query in sql)
    assert not any(".input_json" in query or ".result_json" in query or ".mapping_seed" in query or ".source_json" in query for query in sql)
    assert set(inspect(row).unloaded) >= {"input_json", "evidence_json", "result_json", "context_metadata_json"}


@pytest.mark.parametrize("actual_native", ["charge", "satisfaction", "document", "drug_label"], indirect=True)
def test_actual_artifact_wins_after_mutable_feature_and_all_markers_are_erased(actual_native):
    domain, db, row = actual_native
    identifier = inspect(row).identity[0]
    db.query(AIRun).filter_by(run_id=identifier).update(
        {"feature_key": "synthetic_generic", "input_json": "{}", "evidence_json": "[]", "context_metadata_json": "{}", "result_json": "{}"}, synchronize_session=False
    )
    db.commit()
    assert routing.locate_native_task(db, identifier).domain == domain


def test_conflicting_actual_cross_domain_anchors_reject_instead_of_first_wins(db_session, charge_case, satisfaction_case):
    from app.ai.charge_reconciliation_runtime import create_charge_run
    from app.ai.satisfaction_artifact_models import AISatisfactionRunArtifact

    actor, req, *_ = configured(charge_case)
    identifier = create_charge_run(db_session, actor, req).run_id
    satisfied = configured_run(db_session, satisfaction_case)
    artifact = db_session.get(AISatisfactionRunArtifact, satisfied["run"].run_id)
    # Deliberate SQL corruption negative control: real different Sources now
    # have cross-domain Artifact FKs pointing at one actual AIRun.
    values = {column.name: getattr(artifact, column.name) for column in artifact.__table__.columns}
    db_session.add(AISatisfactionRunArtifact(**{**values, "run_id": identifier}))
    db_session.flush()
    with pytest.raises(HTTPException) as error:
        routing.locate_native_task(db_session, identifier)
    assert error.value.status_code == 409


def test_own_uncommitted_anchor_and_rollback_cannot_leave_false_hint(task_factory):
    from app.ai.document_extraction_storage import stage_anchor

    case = task_factory(stage=False)
    identifier = case.run.run_id
    stage_anchor(case.db, case.run)
    assert routing.locate_native_task(case.db, identifier).domain == "document"
    case.db.rollback()
    assert routing.locate_native_task(case.db, identifier) is None


def test_unrelated_non_uuid_generic_claim_acquires_no_native_gate(db_session, seed_data, monkeypatch):
    from app.ai import charge_reconciliation_write_guard, inventory_write_guard, satisfaction_write_guard
    from app.ai.runtime import claim_next_run

    def forbidden(*args, **kwargs):
        pytest.fail("Unrelated legacy claim cannot take another domain's Gate")

    for module, key in ((charge_reconciliation_write_guard, "lock_charge_gate"), (inventory_write_guard, "lock_inventory_gate"), (satisfaction_write_guard, "lock_satisfaction_gate")):
        monkeypatch.setattr(module, key, forbidden)
    row = AIRun(
        run_id="synthetic-legacy-generic-identifier",
        feature_key="patient_summary",
        requested_by=seed_data["admin_user"].user_id,
        prompt_hash="0" * 64,
        context_digest="0" * 64,
        create_time=datetime.datetime(1990, 1, 1),
    )
    db_session.add(row)
    db_session.commit()
    assert routing.locate_native_task(db_session, row) is None
    identifier, lease = claim_next_run(db_session)
    assert identifier == row.run_id and lease and db_session.get(AIRun, identifier).status == "running"


@pytest.mark.parametrize("actual_native", ["charge", "satisfaction", "document", "drug_label"], indirect=True)
@pytest.mark.parametrize("marker", ["document_change_scope_id", "inventory_scenario_id"])
def test_known_actual_domain_cannot_accept_foreign_native_input_markers(actual_native, marker):
    from app.models import User
    from app.routers import ai

    domain, db, row = actual_native
    identifier = inspect(row).identity[0]
    actor = db.get(User, row.requested_by)
    snapshot = json.loads(row.input_json)
    snapshot["payload"]["input"][marker] = None
    row.input_json = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    db.commit()
    with pytest.raises(HTTPException) as error:
        ai.run_detail(identifier, db=db, user=actor)
    # Preserve each real domain's closed input/anchor rejection semantics.
    expected = 422 if domain == "charge" or (domain == "document" and marker == "inventory_scenario_id") else 409
    assert error.value.status_code == expected
