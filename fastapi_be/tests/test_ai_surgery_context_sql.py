"""Real scenario authorization, short context and feature-specific references."""

import copy
import uuid

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.ai import surgery_scenarios as scenarios
from app.ai.catalog import FEATURE_BY_KEY, FEATURES, describe_feature
from app.ai.context import patient_snapshot
from app.ai.governance import describe_config
from app.ai.models import AIFeatureConfig, AIProvider
from app.ai.operational_sources import operational_context
from app.ai.schemas import RunRequest
from app.ai.surgery_context import MISSING_DATA, SCOPE_NOTE, expand_context, public_payload, surgery_context, surgery_evidence
from app.ai.surgery_contract import canonical_json
from tests.test_ai_surgery_facts import NOTE
from tests.test_ai_surgery_facts import surgery_case as surgery_case
from tests.test_ai_surgery_snapshot import snapshot_case as snapshot_case


@pytest.fixture
def published_scenario(db_session, snapshot_case):
    _, _, declaration, case = snapshot_case
    row = scenarios.create_scenario(db_session, case["director"], declaration)
    db_session.commit()
    scenarios.review_scenario(db_session, case["super"], row.scenario_id, {"expected_revision": 1, "expected_content_hash": row.content_hash, "decision": "publish", "basis_note": NOTE})
    db_session.commit()
    return row, case


def test_only_feature65_advertises_its_own_scenario_reference_and_cross_feature_requests_reject():
    values = {"surgery_scenario_id": str(uuid.uuid4())}
    for spec in FEATURES:
        keys = describe_feature(spec)["source_reference_keys"]
        assert ("surgery_scenario_id" in keys) is (spec.number == 65)
        if spec.number != 65:
            with pytest.raises(ValidationError):
                RunRequest(feature_key=spec.key, input=values)
            if spec.scope == "patient":
                with pytest.raises(HTTPException) as error:
                    patient_snapshot(None, None, spec, 1, source_refs=values)
                assert error.value.status_code == 422
            elif spec.scope == "hospital":
                with pytest.raises(HTTPException) as error:
                    operational_context(None, None, spec, values)
                assert error.value.status_code == 422
    assert describe_feature(FEATURE_BY_KEY["surgery_scheduling"])["source_reference_keys"] == ["surgery_scenario_id"]
    with pytest.raises(ValidationError):
        RunRequest(feature_key="bed_forecast", input={"surgery_scenario_id": "selected"})
    with pytest.raises(HTTPException) as error:
        patient_snapshot(None, None, FEATURE_BY_KEY["surgery_scheduling"], 1, source_refs={"surgery_scenario_id": "selected"})
    assert error.value.status_code == 422


def test_metadata_offers_local_surgery_input_only_for_configured_native_specialist(db_session, seed_data):
    provider = AIProvider(
        name="synthetic-surgery-input-mode-" + uuid.uuid4().hex,
        kind="specialist",
        api_base="http://127.0.0.1:8821",
        model="surgery:" + "a" * 64,
        supported_features_json='["surgery_scheduling"]',
        created_by=seed_data["super_admin_user"].user_id,
    )
    db_session.add(provider)
    db_session.flush()
    spec = FEATURE_BY_KEY["surgery_scheduling"]
    config = AIFeatureConfig(feature_key=spec.key, provider_id=provider.provider_id, allowed_roles_json='["super_admin","director"]')
    assert describe_config(db_session, spec, config)["input_mode"] == "surgery"
    provider.kind = "chat"
    assert describe_config(db_session, spec, config)["input_mode"] == "external_optimizer"
    provider.kind, provider.model = "specialist", "external-reviewed-optimizer"
    assert describe_config(db_session, spec, config)["input_mode"] == "external_optimizer"
    assert describe_config(db_session, spec, None)["input_mode"] == "external_optimizer"
    with pytest.raises(HTTPException) as error:
        operational_context(None, None, FEATURE_BY_KEY["bed_forecast"], {"surgery_scenario_id": "selected"})
    assert error.value.status_code == 422


def test_actual_sql_context_contains_one_short_closed_citation_and_expands_only_for_native_payload(db_session, published_scenario):
    row, case = published_scenario
    values = {"surgery_scenario_id": row.scenario_id, "question": "SYNTH_PRIVATE_LOCAL_QUESTION"}
    bundle = surgery_context(db_session, case["director"], values)
    assert bundle.data["scope_note"] == SCOPE_NOTE and bundle.data["missing_data"] == list(MISSING_DATA)
    assert bundle.evidence == [surgery_evidence(bundle.data["surgery_binding"])] and bundle.department_ids == {row.department_id}
    assert "surgery_source" not in bundle.data and "surgery_scenario" not in bundle.data
    assert len(canonical_json(bundle.data).encode()) < 65535 and len(canonical_json(bundle.evidence).encode()) < 65535
    expanded = expand_context(db_session, bundle.data, user=case["director"], current=True)
    assert expanded["surgery_scenario"]["frozen_task_view"] and expanded["surgery_scenario"]["can_review"] is False
    resolution = expanded["surgery_scenario"]["local_resolution"]
    assert resolution["scenario_id"] == row.scenario_id and resolution["source_content_hash"] == row.content_hash
    assert resolution["cases"][0]["application_id"] == case["application"].application_id
    assert resolution["cases"][0]["case_token"] == expanded["surgery_source"]["cases"][0]["case_id"]
    assert {item["resource_token"] for item in resolution["resources"]} == {item["resource_id"] for item in expanded["surgery_source"]["resources"]}
    assert {item["label"] for item in resolution["resources"]} == {item["original"]["payload"]["label"] for item in expanded["surgery_scenario"]["snapshot"]["collection"]["resources"]}
    outward = public_payload({"input": values, "context": expanded})
    text = canonical_json(outward)
    assert outward == {"context": {"surgery_source": expanded["surgery_source"]}}
    assert "SYNTH_PRIVATE_LOCAL_QUESTION" not in text and NOTE not in text and expanded["surgery_scenario"]["snapshot"]["identity_secret"] not in text
    assert "local_resolution" not in text and all(item["label"] not in text for item in resolution["resources"])
    routed = operational_context(db_session, case["director"], FEATURE_BY_KEY["surgery_scheduling"], values)
    assert routed.data == bundle.data and routed.evidence == bundle.evidence


@pytest.mark.parametrize("change", ["extra_scope", "pool", "published_projection", "selection", "missing_note"])
def test_actual_short_context_cannot_expand_with_changed_original_scope_or_binding(db_session, published_scenario, change):
    row, case = published_scenario
    value = copy.deepcopy(surgery_context(db_session, case["director"], {"surgery_scenario_id": row.scenario_id}).data)
    if change == "extra_scope":
        value["private_override"] = True
    elif change == "pool":
        value["pool_ids"] = []
    elif change == "published_projection":
        value["surgery_binding"]["projection_hash"] = "0" * 64
    elif change == "selection":
        value["selected_sources"] = {}
    else:
        value["missing_data"] = []
    with pytest.raises(HTTPException) as error:
        expand_context(db_session, value, user=case["director"], current=True)
    assert error.value.status_code == 409
