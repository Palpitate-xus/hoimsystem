"""Dedicated supply prompts, role boundaries and reference isolation."""

from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.ai.catalog import FEATURE_BY_KEY, FEATURES, describe_feature
from app.ai.context import patient_snapshot
from app.ai.operational_sources import operational_context
from app.ai.references import SOURCE_REFERENCE_KEYS
from app.ai.schemas import RunRequest
from tests.test_ai_supply_contract import uid


def test_supply_has_dedicated_nonclinical_forecast_prompt_and_management_roles():
    spec = FEATURE_BY_KEY["supply_forecast"]
    assert spec.number == 66 and spec.requires_operational_validation and not spec.clinical
    assert spec.default_roles == ("super_admin", "admin", "director", "pharmacist")
    assert describe_feature(spec)["source_reference_keys"] == ["supply_series_id"]
    assert "supply_series_id" in SOURCE_REFERENCE_KEYS
    assert len(FEATURES) == len({item.task_prompt for item in FEATURES}) == 80
    for text in ("申请量", "实际毛发出量", "确认消耗量", "Croston", "SBA", "TSB", "28", "WAPE", "MASE", "未决冲突", "stock_constraint_unknown_days", "不套用月度经验值", "不提供概率"):
        assert text in spec.task_prompt


@pytest.mark.parametrize("spec", [item for item in FEATURES if item.number != 66], ids=lambda item: str(item.number))
def test_other_capabilities_cannot_select_supply_originals(spec):
    assert "supply_series_id" not in describe_feature(spec)["source_reference_keys"]
    with pytest.raises(ValidationError):
        RunRequest(feature_key=spec.key, input={"supply_series_id": uid("series")})


def test_patient_context_rejects_supply_reference_before_any_database_read():
    with pytest.raises(HTTPException) as error:
        patient_snapshot(None, SimpleNamespace(user_id=1), FEATURE_BY_KEY["treatment_pathway"], 1, source_refs={"supply_series_id": uid("series")})
    assert error.value.status_code == 422


def test_operational_reference_dispatch_uses_only_supply_context(monkeypatch):
    from app.ai import supply_context

    db, user, values = object(), object(), {"supply_series_id": uid("series"), "horizon_days": 14}
    marker = object()

    def actual_dispatch(actual_db, actual_user, actual_values):
        assert actual_db is db and actual_user is user and actual_values is values
        return marker

    monkeypatch.setattr(supply_context, "supply_context", actual_dispatch)
    assert operational_context(db, user, FEATURE_BY_KEY["supply_forecast"], values) is marker
    with pytest.raises(HTTPException) as error:
        operational_context(None, None, FEATURE_BY_KEY["inventory_optimization"], values)
    assert error.value.status_code == 422
