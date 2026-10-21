"""Dedicated inventory prompts, role boundaries and reference isolation."""

from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.ai.catalog import FEATURE_BY_KEY, FEATURES, describe_feature
from app.ai.context import patient_snapshot
from app.ai.operational_sources import operational_context
from app.ai.references import SOURCE_REFERENCE_KEYS
from app.ai.schemas import RunRequest
from tests.test_ai_inventory_contract import uid


def test_inventory_has_dedicated_nonclinical_comparison_prompt_and_management_roles():
    spec = FEATURE_BY_KEY["inventory_optimization"]
    assert spec.number == 67 and spec.requires_operational_validation and not spec.clinical
    assert spec.default_roles == ("super_admin", "admin", "director", "pharmacist")
    assert describe_feature(spec)["source_reference_keys"] == ["inventory_scenario_id"]
    assert "inventory_scenario_id" in SOURCE_REFERENCE_KEYS
    assert len(FEATURES) == len({item.task_prompt for item in FEATURES}) == 80
    for text in (
        "inventory_scenario_id",
        "FEFO",
        "零订单",
        "best_among_declared_candidates",
        "legacy_current_capture",
        "observed_at",
        "Prompt",
        "不自动采购",
        "原币种",
        "全部并列",
        "任一声明候选未知",
    ):
        assert text in spec.task_prompt


@pytest.mark.parametrize("spec", [item for item in FEATURES if item.number != 67], ids=lambda item: str(item.number))
def test_other_capabilities_cannot_select_inventory_originals(spec):
    assert "inventory_scenario_id" not in describe_feature(spec)["source_reference_keys"]
    with pytest.raises(ValidationError):
        RunRequest(feature_key=spec.key, input={"inventory_scenario_id": uid("scenario")})


def test_patient_context_rejects_inventory_reference_before_any_database_read():
    with pytest.raises(HTTPException) as error:
        patient_snapshot(None, SimpleNamespace(user_id=1), FEATURE_BY_KEY["treatment_pathway"], 1, source_refs={"inventory_scenario_id": uid("scenario")})
    assert error.value.status_code == 422


def test_operational_reference_dispatch_uses_only_inventory_context(monkeypatch):
    from app.ai import inventory_context

    db, user, values = object(), object(), {"inventory_scenario_id": uid("scenario")}
    marker = object()

    def actual_dispatch(actual_db, actual_user, actual_values):
        assert actual_db is db and actual_user is user and actual_values is values
        return marker

    monkeypatch.setattr(inventory_context, "inventory_context", actual_dispatch)
    assert operational_context(db, user, FEATURE_BY_KEY["inventory_optimization"], values) is marker
    with pytest.raises(HTTPException) as error:
        operational_context(None, None, FEATURE_BY_KEY["supply_forecast"], values)
    assert error.value.status_code == 422
