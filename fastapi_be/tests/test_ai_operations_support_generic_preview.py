"""The legacy operational preview cannot replace a reviewed operations Case."""

import pytest
from fastapi import HTTPException
from sqlalchemy import event

from app.ai.catalog import FEATURE_BY_KEY
from app.ai.operational_sources import operational_context, operational_options
from tests.test_ai_operations_support_configuration import actors as actors
from tests.test_ai_operations_support_configuration import configured as configured
from tests.test_ai_operations_support_configuration import source as source


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["native_options", "native_context", "foreign_reference", "foreign_null_reference"])
async def test_actual_main_rejects_generic_operations_preview_before_source_body(configured, async_client, auth_headers, kind):
    db, registrar, creator, reviewer, admin = configured[0]
    headers = auth_headers(admin.username)
    seen = []

    def observe(conn, cursor, statement, params, context, many):
        if statement.lstrip().lower().startswith("select"):
            seen.extend(column[0] for column in cursor.description or [])

    event.listen(db.get_bind(), "after_cursor_execute", observe)
    try:
        if kind == "native_options":
            response = await async_client.get("/api/ai/service-options", headers=headers, params={"feature_key": "operations_support"})
        else:
            values = {} if kind == "native_context" else {"operations_case_id": None if kind == "foreign_null_reference" else configured[3]["case_id"]}
            response = await async_client.post("/api/ai/operational-context", headers=headers, json={"feature_key": "operations_support" if kind == "native_context" else "operations_qa", "input": values})
        assert response.status_code == 422, response.text
    finally:
        event.remove(db.get_bind(), "after_cursor_execute", observe)
    protected = {"content_text", "draft_json", "private_json", "public_json", "published_review_json"}
    assert not [column for column in seen if any(column == key or column.endswith("_" + key) for key in protected)]


@pytest.mark.parametrize("kind", ["options", "context", "foreign_null"])
def test_helpers_reject_before_scope_queries(configured, kind):
    class NoDatabase:
        def __getattr__(self, name):
            raise AssertionError("Generic operations rejection must precede SQL")

    actor = configured[0][-1]
    with pytest.raises(HTTPException) as exc:
        if kind == "options":
            operational_options(NoDatabase(), actor, FEATURE_BY_KEY["operations_support"])
        else:
            operational_context(NoDatabase(), actor, FEATURE_BY_KEY["operations_support" if kind == "context" else "operations_qa"], {} if kind == "context" else {"operations_case_id": None})
    assert exc.value.status_code == 422
