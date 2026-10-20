"""The roster original is exclusive to its operational capability and adapter."""

import uuid

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.ai.catalog import FEATURES, describe_feature
from app.ai.context import patient_snapshot
from app.ai.governance import describe_config, provider_feature_issues
from app.ai.models import AIFeatureConfig, AIProvider
from app.ai.operational_sources import operational_context
from app.ai.schemas import RunRequest


def test_all_other_capabilities_reject_roster_reference_and_do_not_advertise_it():
    values = {"roster_plan_id": str(uuid.uuid4())}
    for spec in FEATURES:
        advertised = describe_feature(spec)["source_reference_keys"]
        if spec.number == 63:
            assert advertised == ["roster_plan_id"]
            assert RunRequest(feature_key=spec.key, input=values).input == values
        else:
            assert "roster_plan_id" not in advertised
            with pytest.raises(ValidationError):
                RunRequest(feature_key=spec.key, input=values)
            if spec.scope == "patient":
                with pytest.raises(HTTPException) as caught:
                    patient_snapshot(None, None, spec, 1, source_refs=values)
                assert caught.value.status_code == 422
            elif spec.scope == "hospital":
                with pytest.raises(HTTPException) as caught:
                    operational_context(None, None, spec, values)
                assert caught.value.status_code == 422


def test_registered_roster_runtime_cannot_be_assigned_to_other_feature_or_text_protocol():
    provider = AIProvider(
        kind="specialist", model="roster:" + "a" * 64, supported_features_json='["roster_optimization"]', validation_report="synthetic engineering declaration", allows_patient_data=False
    )
    for spec in FEATURES:
        issues = provider_feature_issues(spec, provider)
        assert any(item["code"] == "ROSTER_SCOPE_MISMATCH" for item in issues) is (spec.number != 63)
    provider.kind = "chat"
    assert any(item["code"] == "ROSTER_SCOPE_MISMATCH" for item in provider_feature_issues(next(spec for spec in FEATURES if spec.number == 63), provider))


def test_live_feature_metadata_selects_roster_input_only_for_registered_specialist(db_session, seed_data):
    provider = AIProvider(
        name="synthetic-roster-catalog-" + uuid.uuid4().hex,
        kind="specialist",
        api_base="http://127.0.0.1:8819",
        model="roster:" + "a" * 64,
        supported_features_json='["roster_optimization"]',
        created_by=seed_data["super_admin_user"].user_id,
    )
    db_session.add(provider)
    db_session.flush()
    spec = next(spec for spec in FEATURES if spec.number == 63)
    config = AIFeatureConfig(feature_key=spec.key, provider_id=provider.provider_id, allowed_roles_json='["super_admin","director"]')
    assert describe_config(db_session, spec, config)["input_mode"] == "roster"
    provider.kind = "chat"
    assert describe_config(db_session, spec, config)["input_mode"] == "external_optimizer"
    provider.kind, provider.model = "specialist", "external-reviewed-optimizer"
    assert describe_config(db_session, spec, config)["input_mode"] == "external_optimizer"
