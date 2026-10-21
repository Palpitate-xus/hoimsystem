"""Actual mounted Main/JWT tasks and separate parts, no real model or export."""

import hashlib
import json

import httpx
import pytest
from fastapi.routing import APIRoute

from app.ai.models import AIFeatureConfig, AIPromptVersion, AIProvider, AIRun
from app.ai.research_cohort_artifact_models import AIResearchCohortRunArtifact
from app.ai.research_cohort_cases import case_current
from app.ai.research_cohort_contract import canonical_json
from app.ai.research_cohort_execution import claim_research_run, execute_research_claimed
from app.ai.research_cohort_registry import review_registry_original
from app.models import MedicalRecord, Patient, Registration
from tests.test_ai_research_cohort_contract import BASIS
from tests.test_ai_research_cohort_execution import reply
from tests.test_ai_research_cohort_execution import runtime_case as runtime_case  # noqa: F401
from tests.test_ai_research_cohort_storage import artifact_foreign_keys as artifact_foreign_keys  # noqa: F401
from tests.test_ai_research_cohort_storage import capture_sql, task_body_selects
from tests.test_ai_research_cohort_storage import configured as configured  # noqa: F401
from tests.test_ai_research_cohort_storage import research_case as research_case  # noqa: F401
from tests.test_ai_research_cohort_storage import storage_rows as storage_rows  # noqa: F401

BASE = "/api/ai/research-cohort/tasks"


@pytest.fixture
def actual_task_routes():
    from app.main import app

    routes = [r for r in app.routes if isinstance(r, APIRoute) and r.endpoint.__module__ == "app.routers.ai_research_cohort_tasks"]
    assert len(routes) == 5
    assert len({(method, route.path) for route in routes for method in route.methods}) == 5
    source = [r for r in app.routes if isinstance(r, APIRoute) and r.endpoint.__module__ == "app.routers.ai_research_cohort_sources"]
    assert len(source) == 23


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["chat", "responses"])
async def test_actual_main_jwt_task_receipt_claim_complete_separate_whole_parts_and_no_business_writes(runtime_case, async_client, auth_headers, actual_task_routes, tmp_path, kind):
    case, db = runtime_case, runtime_case["db"]
    db.get(AIProvider, case["values"]["provider_id"]).kind = kind
    db.get(AIFeatureConfig, "research_cohort").active_prompt_id = None
    db.commit()
    prompts_before = db.query(AIPromptVersion).count()
    clinical_before = {model: db.query(model).count() for model in (Patient, Registration, MedicalRecord)}
    headers = auth_headers(case["actor"].username)
    wire = []

    async def call(method, path, **kwargs):
        response = await async_client.request(method, path, headers=headers, **kwargs)
        wire.append({"method": method, "path": path, "status": response.status_code, "raw_utf8": response.content.decode("utf-8"), "raw_sha256": hashlib.sha256(response.content).hexdigest()})
        assert response.status_code == 200, response.text
        return response.json()["data"]

    live = await call("GET", "/api/ai/research-cohort/cases/" + case["case_id"])
    selected = {"research_cohort_case_id": case["case_id"], "question": "本次原问题\ufeff\r\n🧪只提出待核条件，不扩大患者集合。"}
    queued = await call("POST", BASE, json=selected)
    identifier = queued["run_id"]
    assert queued["status"] == "queued" and queued["usage"] == {"input_tokens": 0, "output_tokens": 0, "complete": True, "model_call_attempted": False}
    assert "snapshot" not in queued and "question" not in queued
    db.commit()
    claim = claim_research_run(db, identifier)
    running = await call("GET", BASE + "/" + identifier)
    assert running["status"] == "running" and running["usage"]["input_tokens"] is None
    outgoing = []

    def model(incoming):
        assert all(not session.in_transaction() for session in case["sessions"])
        outgoing.append({"method": incoming.method, "path": incoming.url.path, "raw_utf8": incoming.content.decode("utf-8"), "raw_sha256": hashlib.sha256(incoming.content).hexdigest()})
        return httpx.Response(200, json=reply(case["source"], kind))

    assert await execute_research_claimed(identifier, claim.lease_token, claim_event_id=claim.claim_event_id, transport=httpx.MockTransport(model), session_factory=case["factory"])
    succeeded = await call("GET", BASE + "/" + identifier)
    assert succeeded["status"] == "succeeded" and succeeded["usage"]["model_call_attempted"] is True
    parts = {part: await call("GET", BASE + "/" + identifier + "/parts/" + part) for part in ("source", "scope", "result", "task")}
    assert parts["source"] == live["public_source"] and parts["scope"] == live["snapshot"]
    rebuilt = {**parts["task"]["case_metadata"], "snapshot": parts["scope"], "public_source": parts["source"]}
    assert rebuilt == live
    task = parts["task"]
    assert task["prompt_snapshot"]["origin"] == "packaged_catalog" and task["prompt_snapshot"]["prompt_id"] is None and task["prompt_snapshot"]["prompt_version"] == 0
    assert json.loads(task["input_json"])["question"] == selected["question"]
    for name, key in (("input_json", "input_hash"), ("evidence_json", "evidence_hash"), ("context_metadata_json", "metadata_hash")):
        assert task[key] == hashlib.sha256(task[name].encode("utf-8")).hexdigest()
    assert parts["result"]["deterministic_evaluation"]["counts"] == parts["source"]["counts"]
    assert all(len(canonical_json(value).encode("utf-8")) <= 8 * 1024 * 1024 for value in parts.values())
    statements, close = capture_sql(db)
    try:
        directory = await call("GET", BASE + "?case_id=" + case["case_id"] + "&size=1")
    finally:
        close()
    assert directory["items"][0]["run_id"] == identifier and directory["items"][0]["detail_required"]
    assert not task_body_selects(statements) and selected["question"] not in canonical_json(directory)
    assert db.query(AIPromptVersion).count() == prompts_before
    assert {model: db.query(model).count() for model in clinical_before} == clinical_before
    packet = {
        "scope": "Feature74 actual mounted Main/JWT HTTP with dedicated real SQLite claim/execute and HTTP MockTransport; not shared dispatcher or real model",
        "same_case_only": True,
        "selection": selected,
        "live_case": live,
        "queued": queued,
        "running": running,
        "succeeded": succeeded,
        "parts": parts,
        "directory": directory,
        "actual_http": wire,
        "model_outgoing": outgoing,
    }
    (tmp_path / ("actual-research-main-task-" + kind + ".json")).write_text(canonical_json(packet), encoding="utf-8")


@pytest.mark.asyncio
async def test_actual_main_withdrawal_hides_all_four_parts_before_task_text_even_super_but_allows_technical_cancel(runtime_case, async_client, auth_headers, actual_task_routes):
    case, db = runtime_case, runtime_case["db"]
    ordinary = auth_headers(case["actor"].username)
    super_headers = auth_headers(case["identities"]["super_admin_user"].username)
    full = case_current(db, case["actor"], case["case_id"])
    authorization = full["snapshot"]["capture"]["patient_authorizations"][0]["identity"]["source_record_id"]
    response = await async_client.post(BASE, headers=ordinary, json={"research_cohort_case_id": case["case_id"], "question": "不可通过技术审计恢复的私有问题"})
    assert response.status_code == 200, response.text
    identifier = response.json()["data"]["run_id"]
    review_registry_original(db, case["identities"]["super_admin_user"], "authorization", authorization, {"expected_revision": 2, "basis_note": BASIS}, revoke=True)
    statements, close = capture_sql(db)
    try:
        for headers, query in ((ordinary, ""), (super_headers, "?audit_only=true")):
            for part in ("source", "scope", "result", "task"):
                response = await async_client.get(BASE + "/" + identifier + "/parts/" + part + query, headers=headers)
                assert response.status_code == 403, response.text
            response = await async_client.get(BASE + "/" + identifier + query, headers=headers)
            assert response.status_code == 200 and not response.json()["data"]["clinical_parts_available"]
            assert response.json()["data"]["binding"] is None
        response = await async_client.post(BASE + "/" + identifier + "/cancel", headers=super_headers)
        assert response.status_code == 200 and response.json()["data"]["status"] == "cancelled", response.text
        assert response.json()["data"]["usage"]["model_call_attempted"] is False
    finally:
        close()
    assert not task_body_selects(statements)


@pytest.mark.asyncio
@pytest.mark.parametrize("foreign", [{"patient_id": 1}, {"encounter_ref": "foreign"}, {"case_id": "foreign"}, {"question": "x" * 2001}])
async def test_actual_main_closed_selection_rejects_foreign_fields_and_overflow_without_run_or_artifact(runtime_case, async_client, auth_headers, actual_task_routes, foreign):
    case, db = runtime_case, runtime_case["db"]
    before = db.query(AIRun).count(), db.query(AIResearchCohortRunArtifact).count()
    response = await async_client.post(BASE, headers=auth_headers(case["actor"].username), json={"research_cohort_case_id": case["case_id"], **foreign})
    assert response.status_code == 422, response.text
    assert (db.query(AIRun).count(), db.query(AIResearchCohortRunArtifact).count()) == before


@pytest.mark.asyncio
async def test_actual_main_fixed_role_owner_scope_strict_ids_and_metadata_only_super_directory(runtime_case, async_client, auth_headers, actual_task_routes):
    case = runtime_case
    patient = auth_headers(case["identities"]["patient_user"].username)
    super_headers = auth_headers(case["identities"]["super_admin_user"].username)
    # A current technical Super has no implicit project/patient model rights.
    for headers, denied in ((patient, 403), (super_headers, 409)):
        response = await async_client.post(BASE, headers=headers, json={"research_cohort_case_id": case["case_id"]})
        assert response.status_code == denied, response.text
    ordinary = auth_headers(case["actor"].username)
    for path in (BASE + "/not-a-uuid", BASE + "?size=true", BASE + "?status=unknown", BASE + "?case_id=1"):
        response = await async_client.get(path, headers=ordinary)
        assert response.status_code == 422, response.text
    response = await async_client.get(BASE + "?audit_only=true", headers=ordinary)
    assert response.status_code == 403
    response = await async_client.get(BASE + "?audit_only=true", headers=super_headers)
    assert response.status_code == 200 and set(response.json()["data"]) == {"items", "page", "size", "total"}
    assert "snapshot" not in response.text and "input_json" not in response.text
