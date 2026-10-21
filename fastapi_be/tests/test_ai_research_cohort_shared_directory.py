"""Actual allowed clinical write invalidates current Source, not technical directory."""

import hashlib

import pytest

from app.ai.research_cohort_cases import case_current, create_case, preview_input, review_case
from app.ai.research_cohort_registry import create_registry_original, review_registry_original
from app.ai.research_cohort_runtime import create_research_run
from tests.test_ai_research_cohort_contract import BASIS
from tests.test_ai_research_cohort_execution import runtime_case as runtime_case  # noqa: F401
from tests.test_ai_research_cohort_storage import artifact_foreign_keys as artifact_foreign_keys  # noqa: F401
from tests.test_ai_research_cohort_storage import configured as configured  # noqa: F401
from tests.test_ai_research_cohort_storage import research_case as research_case  # noqa: F401
from tests.test_ai_research_cohort_storage import storage_rows as storage_rows  # noqa: F401
from tests.test_ai_research_cohort_tasks_http import actual_task_routes as actual_task_routes  # noqa: F401


@pytest.mark.asyncio
async def test_actual_new_acl_root_cannot_block_global_super_technical_directory(runtime_case, async_client, auth_headers, actual_task_routes):
    case, db = runtime_case, runtime_case["db"]
    before = case_current(db, case["actor"], case["case_id"])
    scope = before["snapshot"]["capture"]["scope_original"]
    acl = create_registry_original(
        db,
        case["identities"]["super_admin_user"],
        "acl",
        {
            "scope_id": scope["identity"]["scope_id"],
            "scope_content_hash": scope["content_hash"],
            "scope_governance_hash": scope["governance_hash"],
            "user_id": case["identities"]["super_admin_user"].user_id,
            "permission": "read_capture",
            "valid_from": scope["payload"]["valid_from"],
            "valid_until": scope["payload"]["valid_until"],
            "basis_note": BASIS,
        },
    )
    review_registry_original(db, case["identities"]["reviewer"], "acl", acl["source_record_id"], {"expected_revision": 1, "decision": "publish", "basis_note": BASIS})
    fresh = preview_input(db, case["actor"], before["snapshot"]["request"])
    made = create_case(db, case["actor"], {"request": fresh["request"], "expected_collection_digest": fresh["expected_collection_digest"], "basis_note": BASIS})
    review_case(db, case["identities"]["super_admin_user"], made["case_id"], {"expected_revision": 1, "decision": "publish", "basis_note": BASIS})
    case["case_id"] = made["case_id"]
    assert case_current(db, case["actor"], case["case_id"])["eligible"]
    identifier = create_research_run(db, case["actor"], {"research_cohort_case_id": case["case_id"], "question": "旧Task临床原问题不得因技术目录而外显。"})
    from app.routers.doctor import create_medical_record
    from app.schemas import MedicalRecordCreateRequest

    actual = create_medical_record(
        MedicalRecordCreateRequest(patient_id=case["identities"]["patient"].patient_id, symptom="通过实际旧Doctor writer新增完整记录，不修改Case DTO。", result="待原医生核对"),
        current_user=case["identities"]["doctor_user"],
        db=db,
    )
    assert actual["code"] == 200, actual
    assert case_current(db, case["actor"], case["case_id"])["eligible"] is False
    paths = [
        "/api/ai/research-cohort/tasks/" + identifier + "?audit_only=true",
        "/api/ai/admin/runs?feature_key=research_cohort",
        "/api/ai/admin/runs/" + identifier,
        "/api/ai/research-cohort/tasks/" + identifier + "/parts/source",
    ]
    wire = []
    for path in paths:
        response = await async_client.get(path, headers=auth_headers(case["identities"]["super_admin_user"].username))
        wire.append({"path": path, "status": response.status_code, "raw_utf8": response.content.decode("utf-8"), "sha256": hashlib.sha256(response.content).hexdigest()})
    assert [row["status"] for row in wire] == [200, 200, 403, 403], [(row["path"], row["status"]) for row in wire]
