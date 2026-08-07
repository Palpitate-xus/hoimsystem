import datetime

import pytest

from app.config import settings
from app.database import Base
from app.models import ImagingOrder, LabOrder


@pytest.fixture(autouse=True)
def isolate_integration_database(db_session):
    """The legacy seed fixture is intentionally reusable; isolate bridge tests from later workflow tests."""
    yield
    bind = db_session.get_bind()
    Base.metadata.drop_all(bind=bind)
    Base.metadata.create_all(bind=bind)


@pytest.mark.asyncio
class TestIntegrationBridge:
    async def test_lis_callback_is_authenticated_and_idempotent(self, async_client, seed_data, db_session, monkeypatch):
        monkeypatch.setattr(settings, "LIS_INTEGRATION_KEY", "lis-secret")
        order = LabOrder(
            patient_id=seed_data["patient"].patient_id,
            doctor_id=seed_data["doctor"].doctor_id,
            check_type="血糖",
            check_items="空腹血糖",
            urgent=0,
            status=0,
            sample_status=0,
            create_time=datetime.datetime.now(),
        )
        db_session.add(order)
        db_session.commit()
        db_session.refresh(order)
        payload = {
            "lab_order_id": order.lab_order_id,
            "external_order_id": "LIS-20260807-001",
            "sample_id": "S-001",
            "result": "18.2 mmol/L",
            "abnormal_flag": 0,
        }

        denied = await async_client.post("/api/integration/lis/result", json=payload, headers={"X-Integration-Key": "bad"})
        assert denied.status_code == 401

        first = await async_client.post("/api/integration/lis/result", json=payload, headers={"X-Integration-Key": "lis-secret"})
        assert first.status_code == 200
        assert first.json()["data"]["idempotent"] is False
        assert first.json()["msg"] == "LIS结果已接收，等待审核"

        duplicate = await async_client.post("/api/integration/lis/result", json=payload, headers={"X-Integration-Key": "lis-secret"})
        assert duplicate.status_code == 200
        assert duplicate.json()["data"]["idempotent"] is True
        db_session.refresh(order)
        assert order.integration_status == "synced"
        assert order.sample_status == 1
        assert len(order.lab_results) == 1
        assert order.lab_results[0].abnormal_flag == 1

    async def test_lis_callback_rejects_external_order_rebinding(self, async_client, seed_data, db_session, monkeypatch):
        monkeypatch.setattr(settings, "LIS_INTEGRATION_KEY", "lis-secret")
        order = LabOrder(
            patient_id=seed_data["patient"].patient_id,
            doctor_id=seed_data["doctor"].doctor_id,
            check_type="血常规",
            create_time=datetime.datetime.now(),
            external_order_id="LIS-ORIGINAL",
        )
        db_session.add(order)
        db_session.commit()
        response = await async_client.post(
            "/api/integration/lis/result",
            headers={"X-Integration-Key": "lis-secret"},
            json={"lab_order_id": order.lab_order_id, "external_order_id": "LIS-OTHER", "result": "正常"},
        )
        assert response.status_code == 409

    async def test_pacs_callback_creates_pending_review_report(self, async_client, seed_data, db_session, monkeypatch):
        monkeypatch.setattr(settings, "PACS_INTEGRATION_KEY", "pacs-secret")
        order = ImagingOrder(
            patient_id=seed_data["patient"].patient_id,
            doctor_id=seed_data["doctor"].doctor_id,
            modality="CT",
            body_part="胸部",
            priority=0,
            status=2,
            create_time=datetime.datetime.now(),
        )
        db_session.add(order)
        db_session.commit()
        db_session.refresh(order)
        payload = {
            "imaging_order_id": order.imaging_order_id,
            "external_order_id": "PACS-20260807-001",
            "findings": "双肺未见明显异常密度影。",
            "impression": "胸部 CT 未见明显异常。",
            "viewer_url": "https://pacs.example/view/001",
        }
        response = await async_client.post("/api/integration/pacs/report", headers={"X-Integration-Key": "pacs-secret"}, json=payload)
        assert response.status_code == 200
        assert response.json()["data"]["idempotent"] is False
        db_session.refresh(order)
        assert order.integration_status == "synced"
        assert order.status == 3
        assert order.report.status == 0
        assert order.report.findings.startswith("双肺")

        duplicate = await async_client.post("/api/integration/pacs/report", headers={"X-Integration-Key": "pacs-secret"}, json=payload)
        assert duplicate.status_code == 200
        assert duplicate.json()["data"]["idempotent"] is True

    async def test_integration_is_disabled_without_configured_key(self, async_client, seed_data, monkeypatch):
        monkeypatch.setattr(settings, "PACS_INTEGRATION_KEY", "")
        response = await async_client.post(
            "/api/integration/pacs/report",
            headers={"X-Integration-Key": "anything"},
            json={"imaging_order_id": "missing", "findings": "", "impression": ""},
        )
        assert response.status_code == 503
