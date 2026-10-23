"""Five-domain integration checks on actual SQLite rows, not MySQL waits."""

from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi import HTTPException
from sqlalchemy import event, inspect
from sqlalchemy.dialects import mysql

from app.ai import document_change_sources as sources
from app.ai import document_change_storage as storage
from app.ai import native_task_routing as routing
from app.ai.models import AIRun
from tests.test_ai_document_change_sources import change_case as change_case  # noqa: F401
from tests.test_ai_document_change_storage import remove_prior_tasks as remove_prior_tasks  # noqa: F401
from tests.test_ai_document_change_storage import task
from tests.test_ai_document_change_task_access import no_task_text, observed
from tests.test_ai_document_evidence_contract import NOTE
from tests.test_ai_document_evidence_sources import cas

ROOT = Path(__file__).resolve().parents[1]


def test_expanded_histories_and_additive_domains_preserve_all_twelve_artifact_domains():
    scripts = ScriptDirectory.from_config(Config(str(ROOT / "alembic.ini")))
    assert scripts.get_heads() == ["20261023_native_variables_merge"]
    assert set(scripts.get_revision("20261023_native_variables_merge").down_revision) == {"20261023_native_infection_merge", "20261021_research_variable_runs"}
    assert set(scripts.get_revision("20261023_native_infection_merge").down_revision) == {"20261023_native_rca_merge", "20261021_infection_runs"}
    assert set(scripts.get_revision("20261023_native_rca_merge").down_revision) == {"20261023_native_training_merge", "20261021_rca_evidence_runs"}
    assert set(scripts.get_revision("20261023_native_training_merge").down_revision) == {"20261021_native_ops_deid_merge", "20261021_training_runs"}
    assert set(scripts.get_revision("20261021_native_ops_deid_merge").down_revision) == {"20261021_native_deid_merge", "20261021_ops_runs"}
    assert set(scripts.get_revision("20261021_native_deid_merge").down_revision) == {"20261021_native_research_merge", "20261021_deid_dispatch"}
    assert scripts.get_revision("20261021_ops_runs").down_revision == "20261021_ops_sources"
    assert scripts.get_revision("20261021_ops_sources").down_revision == "20261021_native_research_merge"
    assert set(scripts.get_revision("20261021_native_research_merge").down_revision) == {"20261021_native_expanded_merge", "20261021_research_dispatch"}
    additions = ["20261021_infection_runs", "20261021_infection_profiles", "20261021_infection_scenarios", "20261021_infection_sources", "20261021_native_expanded_merge"]
    for child, parent in zip(additions, additions[1:]):
        assert scripts.get_revision(child).down_revision == parent
    assert set(scripts.get_revision("20261021_native_expanded_merge").down_revision) == {"20261021_native_shared_merge", "20261021_document_change_runs"}
    chain = list(scripts.walk_revisions())
    assert len(chain) == len({row.revision for row in chain})
    assert {"20261021_charge_runs", "20261021_sat_usage_receipt", "20261021_doc_extraction_runs", "20261021_drug_label_runs", "20261021_document_change_runs"} <= {row.revision for row in chain}
    assert [row[0] for row in routing._domains()] == ["charge", "satisfaction", "document", "drug_label", "document_change", "research_cohort", "deidentification", "operations_support", "clinical_training", "rca", "infection", "research_variables"]


def test_document_change_pure_prompt_reexports_are_exact():
    from app.ai import document_change_draft, document_change_prompt

    assert document_change_draft.SYSTEM_PROMPT == document_change_prompt.SYSTEM_PROMPT
    assert document_change_draft.TASK_PROMPT == document_change_prompt.TASK_PROMPT


def test_actual_fifth_domain_dispatch_reads_opaque_columns_without_expired_task_or_locks(change_case):
    db = change_case[0]
    case = task(change_case)
    row = case["run"]
    identifier = inspect(row).identity[0]
    db.expire(row)
    sql = []

    def observe(state):
        if state.is_select:
            sql.append(str(state.statement.compile(dialect=mysql.dialect())))

    event.listen(db, "do_orm_execute", observe)
    try:
        identity = routing.locate_native_task(db, row)
    finally:
        event.remove(db, "do_orm_execute", observe)
    assert identity == routing.NativeTaskIdentity("document_change", identifier, case["scope"].snapshot.scope_id, change_case[1].user_id)
    assert sql and all("FOR UPDATE" not in query and "LOCK IN SHARE MODE" not in query and "write_gate" not in query for query in sql)
    assert not any(".input_json" in query or ".result_json" in query or ".mapping_seed" in query or ".source_json" in query or ".scope_json" in query for query in sql)
    assert set(inspect(row).unloaded) >= {"input_json", "evidence_json", "result_json", "context_metadata_json"}


def test_fifth_domain_artifact_remains_classifier_after_all_mutable_markers_erased(change_case):
    db = change_case[0]
    case = task(change_case)
    identifier = inspect(case["run"]).identity[0]
    db.query(AIRun).filter_by(run_id=identifier).update(
        {"feature_key": "patient_summary", "input_json": "{}", "evidence_json": "[]", "context_metadata_json": "{}", "result_json": "{}"}, synchronize_session=False
    )
    db.commit()
    assert routing.locate_native_task(db, identifier).domain == "document_change"
    with pytest.raises(HTTPException) as error:
        storage.authorize_run_id(db, change_case[1], identifier)
    assert error.value.status_code == 409


def test_real_fifth_domain_writer_registers_own_uncommitted_identity_and_rollback_clears_it(change_case):
    db, actor, *_ = change_case
    case = task(change_case, stage=False)
    identifier = inspect(case["run"]).identity[0]
    storage.stage_artifact(db, actor, case["run"])
    assert ("document_change", identifier) in db.info["native_task_routing_staged_identities"]
    assert routing.locate_native_task(db, identifier).domain == "document_change"
    db.rollback()
    assert routing.locate_native_task(db, identifier) is None


@pytest.mark.parametrize("loss", ["scope", "original", "role"])
def test_shared_private_guard_fifth_domain_authority_precedes_task_text(change_case, loss):
    from app.ai.native_task_access import guard_private_task_read

    db, actor, original, *_ = change_case
    case = task(change_case)
    identifier = inspect(case["run"]).identity[0]
    if loss == "scope":
        sources.revoke_scope(db, actor, case["scope"].snapshot.scope_id, {**cas(case["scope"]), "basis_note": NOTE})
    elif loss == "original":
        sources.originals.revoke_original(db, actor, original.snapshot.original_id, {**cas(original), "basis_note": NOTE})
    else:
        actor.user_role = "admin"
    db.commit()
    db.expire_all()

    def rejected():
        with pytest.raises(HTTPException):
            guard_private_task_read(db, actor, identifier)

    _, statements = observed(db, rejected)
    no_task_text(statements)


@pytest.mark.parametrize("marker", ["document_original_id", "drug_label_source_binding_id"])
def test_known_fifth_domain_cannot_accept_foreign_native_input_markers(change_case, marker):
    import json

    from app.routers import ai

    db, actor, *_ = change_case
    case = task(change_case)
    row = case["run"]
    identifier = inspect(row).identity[0]
    snapshot = json.loads(row.input_json)
    snapshot["payload"]["input"][marker] = None
    row.input_json = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    db.commit()
    with pytest.raises(HTTPException) as error:
        ai.run_detail(identifier, db=db, user=actor)
    assert error.value.status_code == (422 if marker == "document_original_id" else 409)
