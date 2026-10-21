"""Actual SQL/JWT technical directories and canonical opaque hash projection."""

import datetime as dt

import pytest
from fastapi import HTTPException
from sqlalchemy import column, event
from sqlalchemy.dialects import mysql

from app.ai import research_cohort_cases as cases
from app.ai import research_cohort_collection as collection
from app.ai import research_cohort_registry as registry
from app.ai import research_cohort_sources as sources
from app.ai.research_cohort_directories import list_registry
from app.ai.research_cohort_metadata import GOVERNANCE_KEYS, MANUAL_KEYS, CanonicalReviewedGovernanceHash, case_metadata_query
from app.ai.research_cohort_models import AIResearchCohortCase
from app.ai.research_cohort_sources import hash_content
from tests.test_ai_research_cohort_cases import prepared
from tests.test_ai_research_cohort_contract import BASIS
from tests.test_ai_research_cohort_registry import permitted
from tests.test_ai_research_cohort_sources import complete_scope
from tests.test_ai_research_cohort_sources import research_case as research_case  # noqa: F401
from tests.test_ai_research_cohort_sources_http import mounted_research_router as mounted_research_router  # noqa: F401


def test_scope_candidates_from_recorded_acl_do_not_require_or_disclose_original_purpose(db_session, research_case):
    db, case = db_session, research_case
    scope, _, _ = permitted(db, case)
    _, _, peer = complete_scope(db, case)
    statements = []

    def seen(conn, cursor, statement, params, context, many):
        statements.append(statement)

    event.listen(db.bind, "before_cursor_execute", seen)
    try:
        ordinary = list_registry(db, case["admin_user"], "scope", size=100)
        for kind in ("scope", "acl", "authorization"):
            super_view = list_registry(db, case["super_admin_user"], kind, scope_id=scope["scope_id"], size=100)
            assert super_view["items"]
            assert all(row["detail_required"] and row["candidate_reference_only"] for row in super_view["items"])
    finally:
        event.remove(db.bind, "before_cursor_execute", seen)
    assert scope["scope_id"] in {row["scope_id"] for row in ordinary["items"]}
    assert peer["scope_id"] not in {row["scope_id"] for row in ordinary["items"]}
    own = next(row for row in ordinary["items"] if row["scope_id"] == scope["scope_id"])
    assert own["governance_hash"] == scope["governance_hash"]
    assert not any(".scope_json" in sql or ".payload_json" in sql or ".parent_binding_json" in sql or ".snapshot_json" in sql or ".projection_json" in sql for sql in statements)
    assert "purpose" not in own and "patient_ids" not in own and "original" not in own
    # A candidate header is not a grant to the original Scope or consent docs.
    with pytest.raises(HTTPException) as error:
        sources.scope_current(db, case["admin_user"], scope["scope_id"])
    assert error.value.status_code == 403
    with pytest.raises(HTTPException):
        list_registry(db, case["admin_user"], "authorization", scope_id=scope["scope_id"])


@pytest.mark.parametrize("microsecond", [0, 123456])
def test_product_sqlite_udf_canonical_note_hashes_and_case_governance_preserve_original_json_escaping(db_session, research_case, monkeypatch, microsecond):
    db, case = db_session, research_case
    clock = dt.datetime(2026, 10, 21, 12, 0, 0, microsecond)
    for module in (cases, collection, registry, sources):
        monkeypatch.setattr(module, "utcnow", lambda: clock)
    _, _, _, _, made = prepared(db, case)
    note = BASIS + '\ufeff\r\n"\\literal\\u001F🧪' + "".join(chr(i) for i in range(32)) + "\u007f\u2028\u2029"
    cases.review_case(db, case["super_admin_user"], made["case_id"], {"expected_revision": 1, "decision": "publish", "basis_note": note})
    row = db.get(AIResearchCohortCase, made["case_id"])
    selected = case_metadata_query(db).filter(AIResearchCohortCase.case_id == made["case_id"]).one()
    assert selected.review_basis_hash == hash_content(note)
    assert selected.revoke_reason_hash == hash_content("")
    assert selected.governance_hash == cases.governance_hash(row)
    full = cases.case_current(db, case["admin_user"], made["case_id"])
    assert full["governance"]["review_basis_note"] == note
    assert hash_content({"case_id": made["case_id"], "content_hash": full["content_hash"], "governance": full["governance"]}) == full["governance_hash"]
    technical = cases.case_current(db, case["super_admin_user"], made["case_id"], audit_only=True)
    assert technical["governance"] is None and technical["snapshot"] is None
    assert technical["review_basis_hash"] == hash_content(note)


def test_mysql_compilation_projects_only_opaque_hash_labels_not_free_notes_or_large_body(db_session):
    query = case_metadata_query(db_session)
    columns = {column.key for column in query.statement.selected_columns}
    assert not columns & {"review_basis_note", "revoke_reason", "snapshot_json", "projection_json"}
    assert {"review_basis_hash", "revoke_reason_hash", "governance_hash"} <= columns
    compiled = str(query.statement.compile(dialect=mysql.dialect()))
    assert "SHA2" in compiled and "JSON_QUOTE" not in compiled and "CHAR(92)" in compiled
    registry = str(CanonicalReviewedGovernanceHash(*(column(key) for key in (*GOVERNANCE_KEYS, *MANUAL_KEYS))).compile(dialect=mysql.dialect()))
    assert "' ,\"governance\":'" not in registry
    assert "',\"governance\":'" in registry


@pytest.mark.asyncio
async def test_actual_main_three_technical_directory_routes_and_strict_pagination(db_session, research_case, async_client, auth_headers, mounted_research_router):
    db, case = db_session, research_case
    scope, acl, authorization = permitted(db, case)
    sup = auth_headers(case["super_admin_user"].username)
    admin = auth_headers(case["admin_user"].username)
    base = "/api/ai/research-cohort"
    for path, expected in (("scopes", scope), ("project-acls", acl), ("patient-authorizations", authorization)):
        response = await async_client.get(base + "/" + path, headers=sup, params={"scope_id": scope["scope_id"], "size": 100})
        assert response.status_code == 200, response.text
        candidates = response.json()["data"]["items"]
        identifier = expected.get("source_record_id", expected["scope_id"])
        actual = next(row for row in candidates if row["source_record_id"] == identifier)
        assert actual["governance_hash"] == expected["governance_hash"]
        assert actual["detail_required"] and "original" not in actual
    response = await async_client.get(base + "/scopes", headers=admin)
    assert response.status_code == 200 and any(row["scope_id"] == scope["scope_id"] for row in response.json()["data"]["items"])
    for path in ("project-acls", "patient-authorizations"):
        response = await async_client.get(base + "/" + path, headers=admin, params={"scope_id": scope["scope_id"]})
        assert response.status_code == 403
    for value in ("1.0", "01", "true", "1e0"):
        response = await async_client.get(base + "/scopes", headers=sup, params={"page": value})
        assert response.status_code == 422
