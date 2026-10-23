"""Current local configuration is explicit and is not patient-purpose authority."""

# ruff: noqa: F811 -- actual same-case Source/configuration fixtures are intentionally registered.

import json
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import event, text

from app.ai import infection_cluster_profiles as profiles
from app.ai import infection_cluster_registry as registry
from app.ai.catalog import FEATURE_BY_KEY, FEATURES, describe_feature
from app.ai.governance import describe_config
from app.ai.infection_cluster_management import readiness
from app.ai.infection_cluster_task_contract import LOCAL_PROMPT_HASH, LOCAL_TASK_TEXT
from app.ai.models import AIFeatureConfig
from app.ai.runtime import authorized_feature
from tests.test_ai_infection_cluster_sources import cas
from tests.test_ai_infection_cluster_task_storage import profile_case, task_case, task_text_queries  # noqa: F401


def test_metadata_does_not_demand_a_fake_provider_or_claim_patient_purpose(profile_case):
    case = profile_case
    spec = FEATURE_BY_KEY["infection_cluster"]
    data = describe_config(case["db"], spec, None, management=True, user=case["author"])
    assert data["input_mode"] == "infection_cluster_evidence" and data["implementation_status"] == "local_fixed_recipe"
    assert data["provider_id"] is None and data["external_provider_required"] is False and data["external_model_transfer"] is False
    assert data["revision"] == data["prompt_version"] == 0 and not data["enabled"]
    assert data["local_profile_id"] is None and data["patient_purpose_not_verified_by_feature_metadata"]
    codes = {i["code"] for i in readiness(case["db"], spec, user=case["author"])["issues"]}
    assert "LOCAL_PROFILE_REQUIRED" in codes and "MODEL_UNASSIGNED" not in codes
    assert case["db"].get(AIFeatureConfig, spec.key) is None


def test_ready_local_configuration_remains_separate_from_every_patient_permission(task_case):
    case, spec = task_case, FEATURE_BY_KEY["infection_cluster"]
    value = readiness(case["db"], spec, user=case["author"])
    assert value["ready"] and value["issues"] == []
    for grant in case["grants"]:
        registry.revoke_record(case["db"], case["reviewer"], "grant", grant.record_id, cas(grant))
        case["db"].commit()
    assert readiness(case["db"], spec, user=case["author"])["ready"]
    from app.ai.infection_cluster_task_context import prepare

    with pytest.raises(HTTPException) as exc:
        prepare(case["db"], case["author"], case["scenario"].scenario_id)
    assert exc.value.status_code == 403


def test_withdrawn_profile_is_not_reported_ready_or_an_external_service_problem(task_case):
    case = task_case
    profile_id = profiles.configuration(case["db"], case["author"])["profile_id"]
    full = profiles.detail(case["db"], case["author"], profile_id)
    profiles.revoke_profile(case["db"], case["reviewer"], profile_id, cas(full))
    case["db"].commit()
    value = readiness(case["db"], FEATURE_BY_KEY["infection_cluster"], user=case["author"])
    assert not value["ready"] and "LOCAL_PROFILE_REQUIRED" in {i["code"] for i in value["issues"]}
    assert "MODEL_UNASSIGNED" not in {i["code"] for i in value["issues"]}


def test_current_configuration_roles_intersect_even_super_while_governance_stays_independent(task_case):
    case = task_case
    state = profiles.configuration(case["db"], case["author"], management=True)
    from tests.test_ai_infection_cluster_profiles import configuration_request

    req = configuration_request(state["profile_id"])
    req.update(expected_feature_revision=state["feature_revision"], expected_selection_revision=state["selection_revision"], allowed_roles=["admin", "director"])
    profiles.configure(case["db"], case["author"], req)
    case["db"].commit()
    with pytest.raises(HTTPException) as exc:
        authorized_feature(case["db"], case["author"], "infection_cluster")
    assert exc.value.status_code == 403
    assert profiles.configuration(case["db"], case["author"], management=True)["allowed_roles"] == ["admin", "director"]


@pytest.mark.asyncio
async def test_actual_main_admin_and_business_feature_and_prompt_metadata_are_local(async_client, task_case, auth_headers, tmp_path):
    headers = auth_headers(task_case["author"].username)
    packets = []
    for path in ["/api/ai/features", "/api/ai/admin/features", "/api/ai/admin/prompts/infection_cluster"]:
        response = await async_client.get(path, headers=headers)
        packets.append(dict(path=path, status=response.status_code, raw_utf8=response.text))
        assert response.status_code == 200, response.text
    business, admin = [next(x for x in json.loads(packet["raw_utf8"])["data"] if x["key"] == "infection_cluster") for packet in packets[:2]]
    assert business["enabled"] and business["input_mode"] == "infection_cluster_evidence"
    assert business["source_reference_keys"] == ["infection_cluster_scenario_id"]
    assert business["local_profile_current"] is None and "validation_note" not in business
    assert admin["setup_check"]["ready"] and admin["local_profile_current"] and admin["provider_id"] is None
    prompt = json.loads(packets[2]["raw_utf8"])["data"]
    assert prompt["system_prompt"] == "" and prompt["versions"] == [{"prompt_id": None, "version": 0, "task_prompt": LOCAL_TASK_TEXT, "change_note": "local_fixed_recipe"}]
    assert prompt["prompt_hash"] == LOCAL_PROMPT_HASH and prompt["read_only"]
    (tmp_path / "actual-infection-local-feature-main-http.json").write_text(json.dumps(packets, ensure_ascii=False, indent=2) + "\n")


@pytest.mark.asyncio
async def test_current_admin_role_change_denies_before_profile_payload_or_task_text(async_client, task_case, auth_headers):
    case, db = task_case, task_case["db"]
    headers = auth_headers(case["author"].username)
    # A real current JWT actor is resolved after the SQL change; no cached role
    # or technical Super claim can authorize Profile or clinical reads.
    db.execute(text("UPDATE hoimsystem_users SET user_role='patient' WHERE user_id=:id"), {"id": case["author"].user_id})
    db.commit()
    queries = []

    def capture(conn, cursor, sql, params, ctx, many):
        queries.append(sql)

    event.listen(db.get_bind(), "before_cursor_execute", capture)
    try:
        response = await async_client.get("/api/ai/admin/features", headers=headers)
    finally:
        event.remove(db.get_bind(), "before_cursor_execute", capture)
        db.execute(text("UPDATE hoimsystem_users SET user_role='super_admin' WHERE user_id=:id"), {"id": case["author"].user_id})
        db.commit()
    assert response.status_code == 403 and task_text_queries(queries) == []
    assert not any("hoimsystem_ai_infection_local_profile.payload_json" in sql for sql in queries)


def test_catalog_has_only_native_reference_and_offline_export_remains_standard_library_only():
    for spec in FEATURES:
        assert ("infection_cluster_scenario_id" in describe_feature(spec)["source_reference_keys"]) == (spec.number == 78)
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run([sys.executable, "-I", "-S", str(root / "scripts/export_ai_catalog.py"), "--check"], cwd=root, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert "80" in result.stdout
