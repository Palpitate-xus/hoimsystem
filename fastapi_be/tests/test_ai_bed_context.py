"""Real bounded SQL series expansion, strict horizons and current/frozen scope access."""

import copy
import datetime
import json

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.ai import bed_series as series
from app.ai.bed_context import BedContextBinding, authorize_bed_snapshot, bed_context, expand_context, selection
from app.ai.bed_contract import canonical_json, hash_content
from tests.test_ai_bed_facts import NOTE, NOW
from tests.test_ai_bed_facts import bed_case as bed_case
from tests.test_ai_bed_series import create_series, publish_series
from tests.test_ai_bed_series_input import series_case as series_case


@pytest.mark.parametrize("horizon", [7, 14])
def test_actual_series_context_short_binding_expands_all_originals_and_exact_horizon(db_session, series_case, horizon):
    row = publish_series(db_session, series_case, create_series(db_session, series_case))
    bundle = bed_context(db_session, series_case["director"], {"bed_series_id": row.series_id, "horizon_days": horizon, "question": "SYNTH_PRIVATE_仅本地问题"})
    assert "bed_source" not in bundle.data and "bed_series" not in bundle.data
    assert len(canonical_json({"context": bundle.data, "evidence": bundle.evidence}).encode()) < 65535
    assert "SYNTH_PRIVATE" not in canonical_json(bundle.data)
    assert bundle.data["bed_binding"]["horizon_days"] == horizon
    expanded = expand_context(db_session, bundle.data, user=series_case["director"], current=True)
    assert expanded["bed_series"]["snapshot"] == json.loads(row.snapshot_json)
    assert expanded["bed_source"] == expanded["bed_series"]["public_source"] == json.loads(row.projection_json)
    assert hash_content(expanded["bed_source"]) == bundle.data["bed_binding"]["projection_hash"]
    assert expanded["bed_series"]["frozen_task_view"] is True
    assert expanded["bed_series"]["can_record"] is expanded["bed_series"]["can_review"] is expanded["bed_series"]["can_revoke"] is False


@pytest.mark.parametrize(
    "changes",
    [
        {},
        {"horizon_days": None},
        {"horizon_days": True},
        {"horizon_days": 7.0},
        {"horizon_days": "7"},
        {"horizon_days": 0},
        {"horizon_days": 8},
        {"horizon_days": 28},
        {"bed_series_id": None},
        {"bed_series_id": "AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA"},
        {"bed_series_id": "aaaaaaaaaaaa4aaa8aaaaaaaaaaaaaaa"},
        {"question": None},
        {"question": "x" * 12001},
        {"department_id": 1},
        {"occupied_beds": 0},
        {"roster_plan_id": "x"},
    ],
)
def test_selection_rejects_missing_horizon_coercions_extra_sources_and_quantity_overrides(changes):
    values = {"bed_series_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", "horizon_days": 7}
    if not changes:
        values.pop("horizon_days")
    else:
        values.update(changes)
    with pytest.raises(HTTPException, match="422"):
        selection(values)


def test_revoked_source_cannot_be_restored_by_ordinary_history_but_super_can_audit_original(db_session, series_case):
    case = series_case
    row = publish_series(db_session, case, create_series(db_session, case))
    context = bed_context(db_session, case["director"], {"bed_series_id": row.series_id, "horizon_days": 14}).data
    original = expand_context(db_session, context)
    series.revoke_series(db_session, case["super"], row.series_id, {"expected_revision": 2, "reason": NOTE})
    db_session.commit()
    with pytest.raises(HTTPException, match="409"):
        authorize_bed_snapshot(db_session, case["director"], context)
    authorize_bed_snapshot(db_session, case["super"], context)
    frozen = expand_context(db_session, context)
    assert frozen["bed_source"] == original["bed_source"]
    assert frozen["bed_series"]["snapshot"] == original["bed_series"]["snapshot"]
    row.projection_hash = "a" * 64
    db_session.commit()
    with pytest.raises(HTTPException, match="409"):
        authorize_bed_snapshot(db_session, case["super"], context)


@pytest.mark.parametrize("field", ["collection_digest", "projection_hash", "source_id", "ward_id", "scope_token", "series_governance_hash"])
def test_other_series_identity_or_projection_cannot_be_spliced_into_original_context(db_session, series_case, field):
    row = publish_series(db_session, series_case, create_series(db_session, series_case))
    context = copy.deepcopy(bed_context(db_session, series_case["director"], {"bed_series_id": row.series_id, "horizon_days": 7}).data)
    bound = context["bed_binding"]
    bound[field] = bound[field] + 1 if field == "ward_id" else "0" * 64
    with pytest.raises(HTTPException, match="409"):
        expand_context(db_session, context)


def test_original_calendar_is_readable_but_cannot_be_used_for_new_execution(db_session, series_case, monkeypatch):
    from app.ai import bed_series_input

    row = publish_series(db_session, series_case, create_series(db_session, series_case))
    context = bed_context(db_session, series_case["director"], {"bed_series_id": row.series_id, "horizon_days": 7}).data
    monkeypatch.setattr(bed_series_input, "utcnow", lambda: NOW + datetime.timedelta(days=1))
    authorize_bed_snapshot(db_session, series_case["director"], context)
    with pytest.raises(HTTPException, match="409"):
        expand_context(db_session, context, user=series_case["director"], current=True)
    for wrong in (True, 7.0, "7"):
        values = {**context["bed_binding"], "horizon_days": wrong}
        with pytest.raises(ValidationError):
            BedContextBinding.model_validate(values)
