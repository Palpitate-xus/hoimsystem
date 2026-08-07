import pytest

from app.config import settings
from app.database import Base
from app.models import InsuranceSettlement


@pytest.fixture(autouse=True)
def isolate_insurance_integration_database(db_session):
    yield
    bind = db_session.get_bind()
    Base.metadata.drop_all(bind=bind)
    Base.metadata.create_all(bind=bind)


@pytest.mark.asyncio
class TestInsuranceIntegration:
    async def test_external_settlement_callback_is_authenticated_and_idempotent(
        self, async_client, seed_data, auth_headers, db_session, monkeypatch
    ):
        monkeypatch.setattr(settings, "MEDICAL_INSURANCE_INTEGRATION_KEY", "insurance-secret")
        created = await async_client.post(
            "/api/insurance/settlement/create",
            headers=auth_headers(seed_data["cashier_user"].username),
            json={
                "patient_id": seed_data["patient"].patient_id,
                "insurance_no": "INS-EXT-001",
                "total_amount": 1000,
                "covered_amount": 0,
                "integration_mode": "external",
            },
        )
        assert created.status_code == 200
        assert created.json()["data"]["status"] == 0
        settlement_id = created.json()["data"]["settlement_id"]
        payload = {
            "settlement_id": settlement_id,
            "external_settlement_id": "医保平台-001",
            "status": 1,
            "total_amount": 1000,
            "covered_amount": 800,
            "self_amount": 200,
        }

        denied = await async_client.post(
            "/api/integration/insurance/settlement",
            headers={"X-Integration-Key": "bad"},
            json=payload,
        )
        assert denied.status_code == 401

        synced = await async_client.post(
            "/api/integration/insurance/settlement",
            headers={"X-Integration-Key": "insurance-secret"},
            json=payload,
        )
        assert synced.status_code == 200
        assert synced.json()["data"]["idempotent"] is False
        assert synced.json()["data"]["status"] == 1

        duplicate = await async_client.post(
            "/api/integration/insurance/settlement",
            headers={"X-Integration-Key": "insurance-secret"},
            json=payload,
        )
        assert duplicate.status_code == 200
        assert duplicate.json()["data"]["idempotent"] is True
        row = db_session.query(InsuranceSettlement).filter(InsuranceSettlement.settlement_id == settlement_id).one()
        assert row.integration_status == "synced"
        assert row.covered_amount == 800
        assert row.self_amount == 200

    async def test_external_settlement_rejects_inconsistent_amounts(self, async_client, seed_data, auth_headers, monkeypatch):
        monkeypatch.setattr(settings, "MEDICAL_INSURANCE_INTEGRATION_KEY", "insurance-secret")
        created = await async_client.post(
            "/api/insurance/settlement/create",
            headers=auth_headers(seed_data["cashier_user"].username),
            json={
                "patient_id": seed_data["patient"].patient_id,
                "insurance_no": "INS-EXT-002",
                "total_amount": 100,
                "covered_amount": 0,
                "integration_mode": "external",
            },
        )
        response = await async_client.post(
            "/api/integration/insurance/settlement",
            headers={"X-Integration-Key": "insurance-secret"},
            json={
                "settlement_id": created.json()["data"]["settlement_id"],
                "status": 1,
                "total_amount": 100,
                "covered_amount": 120,
            },
        )
        assert response.status_code == 400

