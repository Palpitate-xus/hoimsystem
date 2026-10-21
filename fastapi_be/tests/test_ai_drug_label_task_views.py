"""Wire shape tests using actual dedicated SQL/MockTransport tasks, not main HTTP."""

import copy
import json

import httpx
import pytest
from fastapi.encoders import jsonable_encoder

from app.ai import drug_label_runtime as runtime
from app.ai import drug_label_storage as storage
from app.ai.drug_label_task_view_contract import DrugLabelRunDetail, DrugLabelRunSummary, DrugLabelRunTrace, checked_wire
from tests.test_ai_drug_label_gateway import envelope
from tests.test_ai_drug_label_runtime import case as _case
from tests.test_ai_drug_label_runtime import queued, revoke, stored, view
from tests.test_ai_drug_label_sources import label_case as _label_case

case, label_case = _case, _label_case


def trace(case):
    value = runtime.describe_drug_label_run(case.db, case.users["super_admin_user"], case.id, frozen_audit=True)
    actual = storage.authorize_drug_label_run(case.db, case.users["super_admin_user"], case.id, frozen_audit=True)
    return jsonable_encoder(
        {
            **value,
            "requested_by": actual.run.requested_by,
            "provider_id": actual.run.provider_id,
            "snapshot_complete": True,
            "frozen_request": actual.snapshot,
            "raw_frozen_json": {key: getattr(actual.run, key) for key in ("input_json", "evidence_json", "context_metadata_json")},
        }
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["chat", "responses"])
async def test_actual_task_views_all_states_full_exact_text_private_seed_excluded_and_source_withdrawal(case, kind, tmp_path):
    case.provider.kind = kind
    case.db.commit()
    packet = {
        "scope": "Actual SQLite governed Source and dedicated Task functions/MockTransport. Trace is from authorized SQL functions, not mounted HTTP/JWT or a real model.",
        "kind": kind,
        "states": {},
    }

    def capture(name):
        detail = jsonable_encoder(view(case))
        audit = trace(case)
        checked_wire(detail, DrugLabelRunDetail)
        checked_wire(audit, DrugLabelRunTrace)
        short = jsonable_encoder(runtime.describe_drug_label_run(case.db, case.actor, case.id, include_result=False))
        checked_wire(short, DrugLabelRunSummary)
        actual = storage.load_snapshot(case.db, case.id)
        assert actual.artifact.mapping_seed not in json.dumps([detail, audit, short], ensure_ascii=False)
        assert audit["raw_frozen_json"]["input_json"] == actual.run.input_json
        assert detail["drug_label_findings"]["drug_label_source"]["text"] == actual.source_record.snapshot.original.snapshot.text
        packet["states"][name] = {"detail": detail, "trace": audit, "summary": short}
        case.db.rollback()

    queued(case)
    capture("queued")
    lease = runtime.claim_drug_label_run(case.db, case.id)
    capture("running")
    await runtime.execute_drug_label_claimed(case.id, lease, transport=httpx.MockTransport(lambda request: httpx.Response(200, json=envelope(kind))))
    capture("succeeded")
    succeeded_id = case.id

    queued(case)
    lease = runtime.claim_drug_label_run(case.db, case.id)
    failed = envelope(kind)
    if kind == "chat":
        del failed["usage"]["completion_tokens"]
    else:
        del failed["usage"]["output_tokens"]
    del failed["usage"]["total_tokens"]
    await runtime.execute_drug_label_claimed(case.id, lease, transport=httpx.MockTransport(lambda request: httpx.Response(200, json=failed)))
    capture("failed_partial_usage")

    queued(case)
    runtime.cancel_drug_label_run(case.db, case.actor, case.id)
    capture("cancelled_zero")

    queued(case)
    lease = runtime.claim_drug_label_run(case.db, case.id)

    def cancel_during_model(request):
        runtime.cancel_drug_label_run(case.db, case.actor, case.id)
        capture("cancelled_pending")
        return httpx.Response(200, json=envelope(kind))

    await runtime.execute_drug_label_claimed(case.id, lease, transport=httpx.MockTransport(cancel_during_model))
    capture("cancelled_paid")
    assert packet["states"]["cancelled_pending"]["detail"]["run_id"] == packet["states"]["cancelled_paid"]["detail"]["run_id"]

    case.id = succeeded_id
    revoke(case)
    frozen = trace(case)
    checked_wire(frozen, DrugLabelRunTrace)
    assert frozen["drug_label_findings"]["drug_label_source_record"]["governance"]["status"] == "revoked"
    assert not frozen["drug_label_findings"]["drug_label_source_record"]["eligible"]
    packet["revoked_super_trace"] = frozen
    (tmp_path / ("actual-drug-label-task-" + kind + ".json")).write_text(json.dumps(packet, ensure_ascii=False, indent=2))


@pytest.mark.parametrize("axis", ["seed", "foreign_marker", "missing_anchor", "wrong_clock_precision"])
def test_closed_actual_queue_view_rejects_private_or_mixed_or_incomplete_fields(case, axis):
    queued(case)
    value = jsonable_encoder(view(case))
    if axis == "seed":
        value["drug_label_artifact"]["mapping_seed"] = stored(case).artifact.mapping_seed
    elif axis == "foreign_marker":
        value["supply_findings"] = {}
    elif axis == "missing_anchor":
        del value["drug_label_artifact"]["source_binding_hash"]
    else:
        value["create_time"] += ".123456"
    with pytest.raises(ValueError):
        checked_wire(copy.deepcopy(value))
