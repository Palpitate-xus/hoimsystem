"""Actual authorized complete SQL task views before mounted shared HTTP."""

import hashlib
import json

import httpx
import pytest

from app.ai import drug_label_runtime as runtime
from app.ai import drug_label_storage as storage
from app.ai import drug_label_views as views
from app.ai.drug_label_draft import SYSTEM_PROMPT
from tests.test_ai_drug_label_gateway import envelope
from tests.test_ai_drug_label_runtime import case as _case
from tests.test_ai_drug_label_runtime import queued, revoke
from tests.test_ai_drug_label_sources import label_case as _label_case

case, label_case = _case, _label_case


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["chat", "responses"])
async def test_actual_preview_short_full_and_super_raw_trace_preserve_complete_nonempty_literal_result(case, kind):
    case.provider.kind = kind
    case.request.input["question"] = "\ufeff请逐字核对\r\n🧪e\u0301 2026-10-21T12:30:00.123456Z"
    case.db.commit()
    preview = views.preview(case.db, case.actor, case.request.input)
    assert preview["drug_label_source_record"]["snapshot"]["source_binding_id"] == case.request.input["drug_label_source_binding_id"]
    assert preview["metadata"]["instructions_digest"] == storage.instructions_digest(SYSTEM_PROMPT, case.prompt.task_prompt)
    queued(case)
    row = storage.load_snapshot(case.db, case.id)
    seed = row.artifact.mapping_seed
    original = row.public_source.text
    quote = original[: min(60, len(original))]
    draft = {"fields": [{"field": "other", "spans": [{"start": 0, "end": len(quote), "quote": quote}], "review_question": "请药师逐字核对本段原文与其适用条件。"}]}
    short = views.run_view(case.db, case.actor, case.id, False)
    assert short["status"] == "queued" and "result" not in short
    lease = runtime.claim_drug_label_run(case.db, case.id)
    await runtime.execute_drug_label_claimed(case.id, lease, transport=httpx.MockTransport(lambda request: httpx.Response(200, json=envelope(kind, draft))))
    full = views.run_view(case.db, case.actor, case.id)
    assert full["result"]["drug_label_extraction"]["fields"][0]["spans"][0]["quote"] == quote
    trace = views.trace_view(case.db, case.users["super_admin_user"], case.id)
    raw = trace["raw_frozen_json"]
    assert json.loads(raw["input_json"])["payload"]["input"] == case.request.input
    for name, anchor in (("input_json", "input_hash"), ("evidence_json", "evidence_hash"), ("context_metadata_json", "metadata_hash")):
        assert hashlib.sha256(raw[name].encode()).hexdigest() == trace["drug_label_artifact"][anchor]
    assert seed not in json.dumps(views.response(trace), ensure_ascii=False)
    assert ".123456" in quote
    revoke(case)
    frozen = views.trace_view(case.db, case.users["super_admin_user"], case.id)
    assert frozen["result"] == full["result"]
    assert frozen["drug_label_findings"]["drug_label_source_record"]["governance"]["status"] == "revoked"
