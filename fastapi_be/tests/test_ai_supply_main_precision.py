"""Actual mounted application preserves governed source bytes and UTC6 clocks."""

# ruff: noqa: F811 -- register the actual synthetic source fixture.

import datetime

import pytest
from httpx import ASGITransport, AsyncClient

from app.ai import supply_sources as sources
from app.database import get_db
from app.main import app
from tests.test_ai_supply_source_input import NOTE
from tests.test_ai_supply_sources import source_request, supply_case, unit_request  # noqa: F401


@pytest.mark.asyncio
@pytest.mark.parametrize("microsecond", [0, 123456])
async def test_real_main_source_lifecycle_preserves_full_proof_and_microseconds(db_session, supply_case, auth_headers, monkeypatch, microsecond):
    case = supply_case
    now = datetime.datetime(2026, 10, 20, 12, 0, 0, microsecond)
    monkeypatch.setattr(sources, "utcnow", lambda: now)
    monkeypatch.setitem(app.dependency_overrides, get_db, lambda: db_session)
    expected_clock = now.isoformat(timespec="microseconds") + "Z"
    # Both strings are original text, not legacy timestamps to be reformatted.
    literal = NOTE + " 原时钟文本2026-10-20T12:00:00.123456Z；零微秒2026-10-20T12:00:00.000000Z。"
    pharmacy = auth_headers(case["pharmacist"].username)
    super_headers = auth_headers(case["super"].username)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://synthetic") as client:
        body = unit_request(case)
        body["payload"]["definition_basis_note"] = literal
        created = await client.post("/api/ai/supply-sources/units", json=body, headers=pharmacy)
        assert created.status_code == 200
        unit = created.json()["data"]
        assert unit["recorded_at"] == expected_clock
        assert unit["payload"]["definition_basis_note"] == literal
        assert sources.verify_source_wrapper(unit)
        reviewed = await client.post(
            f"/api/ai/supply-sources/units/{unit['source_record_id']}/review",
            json={"expected_revision": 1, "expected_content_hash": unit["content_hash"], "decision": "publish", "basis_note": NOTE},
            headers=super_headers,
        )
        assert reviewed.status_code == 200
        published = reviewed.json()["data"]
        assert published["reviewed_at"] == expected_clock and sources.verify_source_wrapper(published)
        original = sources.record(db_session, "unit", unit["source_record_id"])
        daily = await client.post("/api/ai/supply-sources/daily", json=source_request(case, original), headers=pharmacy)
        assert daily.status_code == 200
        record = daily.json()["data"]
        assert record["recorded_at"] == expected_clock and sources.verify_source_wrapper(record)
        for kind, row in (("units", published), ("daily", record)):
            params = {"item_kind": "pharmaceutical", "item_id": case["drug"].pharmaceutical_id}
            listing = await client.get(f"/api/ai/supply-sources/{kind}", params=params, headers=pharmacy)
            assert listing.status_code == 200
            assert listing.json()["data"]["items"][0]["recorded_at"] == expected_clock
            current = await client.get(f"/api/ai/supply-sources/{kind}/{row['source_record_id']}", headers=pharmacy)
            assert current.status_code == 200 and sources.verify_source_wrapper(current.json()["data"])
            audit = await client.get(
                f"/api/ai/admin/supply-sources/{row['source_record_id']}",
                params={"record_kind": "unit" if kind == "units" else "daily"},
                headers=super_headers,
            )
            assert audit.status_code == 200 and sources.verify_source_wrapper(audit.json()["data"])
            assert audit.json()["data"]["parent_binding"] == row["parent_binding"]
            assert audit.json()["data"]["payload"] == row["payload"]
        revoked = await client.post(
            f"/api/ai/supply-sources/daily/{record['source_record_id']}/revoke",
            json={"expected_revision": 1, "expected_content_hash": record["content_hash"], "basis_note": NOTE},
            headers=pharmacy,
        )
        assert revoked.status_code == 200 and revoked.json()["data"]["revoked_at"] == expected_clock
        assert revoked.json()["data"]["payload"] is None
        frozen = await client.get(f"/api/ai/admin/supply-sources/{record['source_record_id']}", params={"record_kind": "daily"}, headers=super_headers)
        assert frozen.status_code == 200 and sources.verify_source_wrapper(frozen.json()["data"])
    assert case["drug"].stock == 37 and case["consumable"].stock == 11
