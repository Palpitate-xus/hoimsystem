"""Persist a complete real worker result only when its exact UTF-8 fits MySQL TEXT."""

import json

import httpx
import pytest

from app.ai.governance import encode_json
from app.ai.models import AIRun
from app.ai.runtime import claim_next_run, create_run, execute_claimed
from app.ai.schemas import GenerationResult, RunRequest
from app.models import MedicalRecord, Prescription
from tests.test_ai_runtime import clean_ai_tasks as clean_ai_tasks
from tests.test_ai_runtime import configure


def result_at_bytes(size, char):
    result = {"summary": "Synthetic bounded complete result", "sections": [], "warnings": [], "missing_data": []}
    for index in range(7):
        result["sections"].append({"title": f"Synthetic source section {index}", "content": "", "source_ids": []})
    needed = size - len(encode_json(result).encode())
    for section in result["sections"]:
        count = min(11000, needed // len(char.encode()))
        section["content"] = char * count
        needed -= count * len(char.encode())
    result["sections"][-1]["content"] += "x" * needed
    GenerationResult.model_validate(result)
    assert len(encode_json(result).encode()) == size
    return result


@pytest.mark.asyncio
@pytest.mark.parametrize("char", ["x", "合"])
@pytest.mark.parametrize("size", [65535, 65536])
async def test_actual_worker_checks_complete_result_bytes_and_keeps_reported_usage(size, char, db_session, seed_data, clean_ai_tasks):
    configure(db_session, seed_data)
    result = result_at_bytes(size, char)
    before = (db_session.query(MedicalRecord).count(), db_session.query(Prescription).count())
    run = create_run(
        db_session, seed_data["doctor_user"], RunRequest(feature_key="patient_summary", patient_id=seed_data["patient"].patient_id, input={"question": "Synthetic storage result boundary"})
    )
    calls = []

    def reply(request):
        calls.append(request)
        return httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {"content": json.dumps(result)}}], "usage": {"prompt_tokens": 5, "completion_tokens": 7}})

    await execute_claimed(*claim_next_run(db_session), transport=httpx.MockTransport(reply))
    db_session.expire_all()
    stored = db_session.get(AIRun, run.run_id)
    assert len(calls) == 1
    assert (stored.input_tokens, stored.output_tokens) == (5, 7)
    assert stored.finish_time is not None
    if size == 65535:
        assert stored.status == "succeeded", stored.error_message
        assert stored.result_json == encode_json(result)
        assert len(stored.result_json.encode()) == 65535
    else:
        assert stored.status == "failed"
        assert stored.error_code == "RESULT_STORAGE_LIMIT"
        assert stored.result_json == "{}"
    assert before == (db_session.query(MedicalRecord).count(), db_session.query(Prescription).count())
