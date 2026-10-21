"""Actual mounted JWT APIs and shared durable dispatch; synthetic model HTTP."""

import hashlib
import json

import httpx
import pytest
from sqlalchemy import event

from app.ai import drug_label_storage as storage
from app.ai import runtime
from app.ai.drug_label_run_models import AIDrugLabelRunArtifact
from app.ai.models import AIFeatureConfig, AIRun
from tests.test_ai_drug_label_gateway import envelope
from tests.test_ai_drug_label_runtime import case as _case
from tests.test_ai_drug_label_runtime import revoke
from tests.test_ai_drug_label_sources import label_case as _label_case

case, label_case = _case, _label_case


@pytest.fixture
def shared_case(case):
    db = case.db
    # Discard only the storage fixture's synthetic sample. This test submits
    # its own task through the real mounted JWT API and shared worker.
    db.delete(db.get(AIDrugLabelRunArtifact, case.run.run_id))
    db.delete(case.run)
    case.request.input["question"] = "\ufeff请逐字核对\r\n🧪e\u0301 2026-10-21T12:30:00.123456Z"
    db.commit()
    yield case
    db.rollback()
    if getattr(case, "id", None):
        row = db.get(AIRun, case.id)
        if row is not None and row.status in {"queued", "running"}:
            from app.ai.drug_label_runtime import cancel_drug_label_run

            cancel_drug_label_run(db, case.users["super_admin_user"], case.id, frozen_audit=True)
    db.rollback()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["chat", "responses"])
async def test_actual_main_full_source_preview_submit_shared_claim_worker_trace_feedback_and_fk_history(async_client, auth_headers, shared_case, kind):
    c, db = shared_case, shared_case.db
    c.provider.kind = kind
    db.commit()
    headers = auth_headers(c.actor.username)
    super_headers = auth_headers(c.users["super_admin_user"].username)
    values = c.request.input
    binding_id = values["drug_label_source_binding_id"]
    features = await async_client.get("/api/ai/features", headers=headers)
    assert features.status_code == 200, features.text
    feature = next(row for row in features.json()["data"] if row["key"] == "drug_label_extraction")
    assert feature["input_mode"] == "drug_label_evidence"
    source = await async_client.get(f"/api/ai/drug-label-sources/{binding_id}", headers=headers)
    assert source.status_code == 200, source.text
    options = await async_client.get("/api/ai/drug-label-sources/options", headers=headers)
    catalog = await async_client.get("/api/ai/drug-label-sources/catalog", headers=headers)
    directory = await async_client.get("/api/ai/drug-label-sources", headers=headers, params={"pharmaceutical_id": source.json()["data"]["snapshot"]["identity"]["pharmaceutical_id"]})
    for response in (options, catalog, directory):
        assert response.status_code == 200, response.text
    options_super = await async_client.get("/api/ai/drug-label-sources/options", headers=super_headers)
    source_super = await async_client.get(f"/api/ai/drug-label-sources/{binding_id}", headers=super_headers, params={"audit_only": False})
    directory_super_audit = await async_client.get("/api/ai/drug-label-sources", headers=super_headers, params={"audit_only": True})
    for response in (options_super, source_super, directory_super_audit):
        assert response.status_code == 200, response.text
    assert options_super.json()["data"]["can_release"] is True
    assert source_super.json()["data"]["audit_only"] is False and source_super.json()["data"]["eligible"] is True
    preview = await async_client.post("/api/ai/drug-label/context", headers=headers, json=values)
    assert preview.status_code == 200, preview.text
    assert set(preview.json()["data"]) == {"context", "metadata", "evidence", "drug_label_source_record"}
    assert preview.json()["data"]["drug_label_source_record"] == source.json()["data"]
    created = await async_client.post("/api/ai/runs", headers=headers, json=c.request.model_dump())
    assert created.status_code == 200, created.text
    short = created.json()["data"]
    assert short["status"] == "queued" and "result" not in short
    c.id = short["run_id"]
    before = storage.load_snapshot(db, c.id)
    original = before.public_source.text
    quote = original[: min(60, len(original))]
    assert ".123456" in quote and "\r\n" in quote and "😀" in quote
    seed = before.artifact.mapping_seed
    draft = {"fields": [{"field": "other", "spans": [{"start": 0, "end": len(quote), "quote": quote}], "review_question": "请药师逐字核对本段原文与其适用条件。"}]}
    db.rollback()
    claimed = runtime.claim_next_run(db)
    assert claimed is not None and claimed[0] == c.id
    db.rollback()
    calls, active = [], []

    def checkout(*_):
        active.append(True)

    def checkin(*_):
        active.pop()

    def handle(request):
        assert not active, "No SQL checkout may remain during model HTTP"
        packet = json.loads(request.content)
        public = json.loads(packet["input"][0]["content"] if kind == "responses" else packet["messages"][1]["content"])
        assert set(public) == {"drug_label_source", "question"}
        assert public["question"] == values["question"]
        assert seed not in request.content.decode()
        calls.append(request)
        return httpx.Response(200, json=envelope(kind, draft))

    engine = db.get_bind()
    event.listen(engine, "checkout", checkout)
    event.listen(engine, "checkin", checkin)
    try:
        await runtime.execute_claimed(*claimed, transport=httpx.MockTransport(handle))
        assert not active
    finally:
        event.remove(engine, "checkout", checkout)
        event.remove(engine, "checkin", checkin)
    assert len(calls) == 1
    full = await async_client.get(f"/api/ai/runs/{c.id}", headers=headers)
    assert full.status_code == 200, full.text
    detail = full.json()["data"]
    assert detail["status"] == "succeeded"
    assert detail["result"]["drug_label_extraction"]["fields"][0]["spans"][0]["quote"] == quote
    super_full = await async_client.get(f"/api/ai/runs/{c.id}", headers=super_headers)
    assert super_full.status_code == 200, super_full.text
    assert super_full.json()["data"]["drug_label_findings"]["drug_label_source_record"]["audit_only"] is True
    trace = await async_client.get(f"/api/ai/admin/runs/{c.id}", headers=super_headers)
    assert trace.status_code == 200, trace.text
    audit = trace.json()["data"]
    assert seed not in trace.text
    for key, digest in (("input_json", "input_hash"), ("evidence_json", "evidence_hash"), ("context_metadata_json", "metadata_hash")):
        assert hashlib.sha256(audit["raw_frozen_json"][key].encode()).hexdigest() == audit["drug_label_artifact"][digest]
    assert json.loads(audit["raw_frozen_json"]["input_json"])["payload"]["input"] == values
    reviewed = await async_client.post(f"/api/ai/runs/{c.id}/feedback", headers=headers, json={"outcome": "accepted", "comment": "\ufeff已逐字人工复核\r\n🧪"})
    assert reviewed.status_code == 200, reviewed.text
    params = {"feature_key": "drug_label_extraction", "drug_label_source_binding_id": binding_id}
    history = await async_client.get("/api/ai/runs", headers=headers, params=params)
    assert history.status_code == 200, history.text
    assert [r["run_id"] for r in history.json()["data"]] == [c.id]
    global_history = await async_client.get("/api/ai/admin/runs", headers=super_headers, params=params)
    assert global_history.status_code == 200, global_history.text
    assert [r["run_id"] for r in global_history.json()["data"]] == [c.id]
    if getattr(c, "export_wire", None):
        packets = {
            "feature": feature,
            "options": options.json(),
            "catalog": catalog.json(),
            "directory": directory.json(),
            "options_super": options_super.json(),
            "source_super": source_super.json(),
            "directory_super_audit": directory_super_audit.json(),
            "source": source.json(),
            "preview": preview.json(),
            "queued": created.json(),
            "full": full.json(),
            "super_full": super_full.json(),
            "trace": trace.json(),
            "history": history.json(),
            "admin_history": global_history.json(),
            "input": values,
        }
        packets["raw_http_responses"] = {
            name: {"body_utf8": value.text, "body_sha256": hashlib.sha256(value.content).hexdigest(), "body_bytes": len(value.content), "status_code": value.status_code}
            for name, value in {
                "source": source,
                "options": options,
                "catalog": catalog,
                "directory": directory,
                "options_super": options_super,
                "source_super": source_super,
                "directory_super_audit": directory_super_audit,
                "preview": preview,
                "queued": created,
                "full": full,
                "super_full": super_full,
                "trace": trace,
                "history": history,
                "admin_history": global_history,
            }.items()
        }
        c.export_wire(kind, packets)


@pytest.mark.asyncio
async def test_actual_main_source_withdrawal_rejects_before_any_private_task_text_and_super_can_audit(async_client, auth_headers, shared_case):
    c, db = shared_case, shared_case.db
    headers, super_headers = auth_headers(c.actor.username), auth_headers(c.users["super_admin_user"].username)
    created = await async_client.post("/api/ai/runs", headers=headers, json=c.request.model_dump())
    assert created.status_code == 200, created.text
    c.id = created.json()["data"]["run_id"]
    revoke(c)
    private_selects = []

    def observe(_, __, statement, ___, ____, _____):
        lowered = statement.lower()
        if lowered.lstrip().startswith("select") and "ai_run" in lowered and any("ai_run." + key in lowered for key in ("input_json", "evidence_json", "context_metadata_json", "result_json")):
            private_selects.append(statement)

    event.listen(db.get_bind(), "before_cursor_execute", observe)
    try:
        denied = await async_client.get(f"/api/ai/runs/{c.id}", headers=headers)
        assert denied.status_code == 409, denied.text
        assert private_selects == []
    finally:
        event.remove(db.get_bind(), "before_cursor_execute", observe)
    frozen = await async_client.get(f"/api/ai/admin/runs/{c.id}", headers=super_headers)
    assert frozen.status_code == 200, frozen.text
    assert frozen.json()["data"]["drug_label_findings"]["drug_label_source_record"]["governance"]["status"] == "revoked"
    db.rollback()
    # The shared claimer records the genuine queued/no-call rejection.
    assert runtime.claim_next_run(db) is None
    db.expire_all()
    actual = db.get(AIRun, c.id)
    assert actual.status == "failed" and actual.input_tokens == actual.output_tokens == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(("roles", "expected"), [("[" + '"super_admin"' + "]", 403), ("{invalid-json", 409)])
async def test_actual_main_current_feature_role_revocation_precedes_private_task_text(async_client, auth_headers, shared_case, roles, expected):
    c, db = shared_case, shared_case.db
    headers, super_headers = auth_headers(c.actor.username), auth_headers(c.users["super_admin_user"].username)
    created = await async_client.post("/api/ai/runs", headers=headers, json=c.request.model_dump())
    assert created.status_code == 200, created.text
    c.id = created.json()["data"]["run_id"]
    db.query(AIFeatureConfig).filter_by(feature_key="drug_label_extraction").update({"allowed_roles_json": roles}, synchronize_session=False)
    db.commit()
    private_selects = []

    def observe(_, __, statement, ___, ____, _____):
        lowered = statement.lower()
        if lowered.lstrip().startswith("select") and any("ai_run." + key in lowered for key in ("input_json", "evidence_json", "context_metadata_json", "result_json")):
            private_selects.append(statement)

    event.listen(db.get_bind(), "before_cursor_execute", observe)
    try:
        denied = await async_client.get(f"/api/ai/runs/{c.id}", headers=headers)
        assert denied.status_code == expected, denied.text
        assert private_selects == []
    finally:
        event.remove(db.get_bind(), "before_cursor_execute", observe)
    frozen = await async_client.get(f"/api/ai/admin/runs/{c.id}", headers=super_headers)
    assert frozen.status_code == 200, frozen.text
    history = await async_client.get(
        "/api/ai/runs", headers=super_headers, params={"feature_key": "drug_label_extraction", "drug_label_source_binding_id": c.request.input["drug_label_source_binding_id"]}
    )
    assert history.status_code == 200, history.text
    assert [row["run_id"] for row in history.json()["data"]] == [c.id]
