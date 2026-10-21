"""Same actual main JWT Case/task states for ordinary business and Super audit UI."""

import json
import os
from pathlib import Path

import httpx
import pytest

from app.ai import charge_reconciliation_contract as c
from app.ai.models import AIRun
from app.ai.runtime import claim_next_run, execute_claimed
from tests.test_ai_charge_reconciliation_gateway import envelope
from tests.test_ai_charge_reconciliation_runtime import configured
from tests.test_ai_charge_reconciliation_sources import NOTE, cas, request
from tests.test_ai_charge_reconciliation_sources import charge_case as _charge_case
from tests.test_ai_charge_reconciliation_sources_http import source_app as _source_app

charge_case, source_app = _charge_case, _source_app


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["chat", "responses"])
async def test_actual_main_same_case_all_task_states_and_frozen_source_export(source_app, charge_case, auth_headers, kind):
    case, db = charge_case, charge_case["db"]
    case["charges"][0].item_name = "\ufeff原记录🙂e\u0301\r\n2026-10-21T12:00:00.123456Z"
    db.commit()
    actor, req, value, _, _ = configured(case, actor=case["admin_user"], preview=False, kind=kind)
    ordinary, super_headers = auth_headers(actor.username), auth_headers(case["super_admin_user"].username)
    packet = {
        "schema_version": "charge_assistant_actual_main_v1",
        "provenance": {
            "source_setup": "Actual synthetic SQLite Source services create and publish; all recorded wrappers below use actual mounted main JWT/ASGI routes.",
            "model": "Actual generic worker dispatch and dedicated gateway with HTTP MockTransport; no real model or hospital access.",
            "owner_role": "admin",
            "audit_role": "super_admin",
            "provider_kind": kind,
        },
        "request": req.model_dump(mode="json"),
        "states": {},
    }
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=source_app), base_url="http://synthetic") as client:

        async def call(method, path, *, headers=ordinary, **kwargs):
            response = await client.request(method, "/api" + path, headers=headers, **kwargs)
            assert response.status_code == 200, (method, path, response.status_code, response.text)
            return response.json()

        async def state(identifier):
            detail = await call("GET", "/ai/runs/" + identifier)
            trace = await call("GET", "/ai/admin/runs/" + identifier, headers=super_headers)
            assert detail["data"]["charge_findings"]["input"] == req.input
            return {"detail": detail, "trace": trace}

        async def create():
            queued = await call("POST", "/ai/runs", json=req.model_dump(mode="json"))
            return queued["data"]["run_id"], queued

        def claim(identifier):
            db.rollback()  # Simulate closing the intentionally shared test request session.
            claimed = claim_next_run(db)
            assert claimed is not None and claimed[0] == identifier
            return claimed

        packet["features"] = await call("GET", "/ai/features", headers=super_headers)
        packet["feature"] = next(row for row in packet["features"]["data"] if row["key"] == req.feature_key)
        packet["ordinary_features"] = await call("GET", "/ai/features")
        packet["preview_request"] = {"feature_key": req.feature_key, "patient_id": req.patient_id, "encounter_ref": req.encounter_ref, "source_refs": {"charge_case_id": req.input["charge_case_id"]}}
        packet["preview"] = await call("POST", "/ai/context", json=packet["preview_request"])
        root = "/ai/charge-reconciliation"
        packet["source"] = {
            "ordinary": await call("GET", root + "/cases/" + value["case_snapshot_id"]),
            "super_current": await call("GET", root + "/cases/" + value["case_snapshot_id"], headers=super_headers),
            "ordinary_directory": await call("GET", root + "/cases", params=request(case)),
            "super_directory": await call("GET", root + "/cases", headers=super_headers, params={**request(case), "audit_only": True}),
            "options": await call("GET", root + "/options", params=request(case)),
        }
        public = value["public_source"]
        member = next(row for row in public["charges"] if row["item_name"].startswith("\ufeff原记录🙂"))
        text = member["item_name"]
        draft = {
            "schema_version": "charge_reconciliation_draft_v1",
            "source_id": value["source_id"],
            "source_projection_hash": value["projection_hash"],
            "coverage": "partial_questions_no_completeness_or_correctness_claim",
            "observations": [
                {
                    "kind": "association_question",
                    "referenced_source_ids": [member["source_id"]],
                    "review_note": "请核对这条原记录的实际关联依据，尚未确认漏记账。",
                    "clarification_question": "是否存在尚未提供的逐收费行执行依据？",
                    "citations": [{"source_id": member["source_id"], "field": "item_name", "start": 0, "end": len(text), "quote": text}],
                }
            ],
        }
        identifier, queued = await create()
        packet["states"]["queued"] = {"ack": queued, **await state(identifier)}
        claimed = claim(identifier)
        packet["states"]["running"] = await state(identifier)
        db.rollback()
        outbound = []

        def handle(http_request):
            outbound.append(json.loads(http_request.content))
            return httpx.Response(200, json=envelope(kind, draft))

        await execute_claimed(*claimed, transport=httpx.MockTransport(handle))
        assert len(outbound) == 1
        packet["outbound"] = outbound[0]
        packet["states"]["succeeded"] = await state(identifier)
        assert packet["states"]["succeeded"]["detail"]["data"]["result"]["charge_analysis"] == draft
        packet["feedback_request"] = {"outcome": "rejected", "comment": "合成人工复核：<img src=x onerror=alert(1)>只作文字，不能确认财务正确。"}
        packet["feedback_ack"] = await call("POST", "/ai/runs/" + identifier + "/feedback", json=packet["feedback_request"])
        packet["states"]["succeeded"]["trace"] = await call("GET", "/ai/admin/runs/" + identifier, headers=super_headers)

        failed_id, _ = await create()
        failed_claim = claim(failed_id)
        partial = envelope(kind, draft)
        del partial["usage"]["completion_tokens" if kind == "chat" else "output_tokens"]
        await execute_claimed(*failed_claim, transport=httpx.MockTransport(lambda _: httpx.Response(200, json=partial)))
        packet["states"]["failed"] = await state(failed_id)
        assert packet["states"]["failed"]["detail"]["data"]["usage_receipt"] == {"input_tokens": 13, "output_tokens": None, "complete": False, "model_call_attempted": True}

        cancelled_id, _ = await create()
        packet["queued_cancel_ack"] = await call("POST", "/ai/runs/" + cancelled_id + "/cancel")
        packet["states"]["cancelled_zero"] = await state(cancelled_id)
        assert packet["states"]["cancelled_zero"]["detail"]["data"]["usage_receipt"] == {"input_tokens": 0, "output_tokens": 0, "complete": True, "model_call_attempted": False}

        inflight_id, _ = await create()
        inflight_claim = claim(inflight_id)

        async def cancel_inflight(http_request):
            packet["inflight_cancel_ack"] = await call("POST", "/ai/runs/" + inflight_id + "/cancel")
            packet["states"]["cancelled_pending"] = await state(inflight_id)
            db.rollback()
            return httpx.Response(200, json=envelope(kind, draft))

        await execute_claimed(*inflight_claim, transport=httpx.MockTransport(cancel_inflight))
        packet["states"]["cancelled_paid"] = await state(inflight_id)
        assert packet["states"]["cancelled_paid"]["detail"]["data"]["usage_receipt"] == {"input_tokens": 13, "output_tokens": 7, "complete": True, "model_call_attempted": True}
        assert packet["states"]["cancelled_paid"]["detail"]["data"]["result"] is None
        params = {"feature_key": req.feature_key, "patient_id": req.patient_id, "encounter_ref": req.encounter_ref, "charge_case_id": value["case_snapshot_id"]}
        packet["history_params"] = params
        packet["ordinary_history"] = await call("GET", "/ai/runs", params=params)
        packet["admin_history"] = await call("GET", "/ai/admin/runs", headers=super_headers, params=params)
        assert len(packet["ordinary_history"]["data"]) == packet["admin_history"]["total"] == 4
        packet["revoke_request"] = {**cas(value), "basis_note": NOTE}
        packet["revoke_ack"] = await call("POST", root + "/cases/" + value["case_snapshot_id"] + "/revoke", headers=super_headers, json=packet["revoke_request"])
        packet["revoked_super_trace"] = await call("GET", "/ai/admin/runs/" + identifier, headers=super_headers)
        denied = await client.get("/api/ai/runs/" + identifier, headers=ordinary)
        assert denied.status_code == 409
        packet["revoked_ordinary_denial"] = {"status_code": denied.status_code, "body": denied.json()}
        assert packet["revoked_super_trace"]["data"]["charge_findings"]["charge_source"] == public
        db.expire_all()
        assert db.get(AIRun, identifier).status == "succeeded"
    target = os.environ.get("HOIM_CHARGE_ASSISTANT_EXPORT_DIR")
    if target:
        destination = Path(target) / (kind + ".json")
        assert not destination.exists()
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(packet, ensure_ascii=False, indent=2) + "\n")
    assert c.digest(packet["preview"]["data"]["context"]["charge_source"]) == value["projection_hash"]
