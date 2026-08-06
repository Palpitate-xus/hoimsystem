import pytest

from app.models import Consumable, Equipment


@pytest.mark.asyncio
class TestEquipment:
    async def test_equipment_maintenance_inspection_inventory_flow(self, async_client, seed_data, auth_headers, db_session):
        created = await async_client.post("/api/equipment/create", headers=auth_headers(seed_data["director_user"].username), json={"asset_no": "EQ-TEST-001", "name": "便携式监护仪", "category": "监护设备"})
        assert created.json()["code"] == 200
        equipment_id = created.json()["data"]["equipment_id"]
        maintenance = await async_client.post("/api/equipment/maintenance/create", headers=auth_headers(seed_data["nurse_user"].username), json={"equipment_id": equipment_id, "maintenance_type": "维修", "description": "电池异常"})
        assert maintenance.json()["code"] == 200
        inspection = await async_client.post("/api/equipment/inspection/create", headers=auth_headers(seed_data["nurse_user"].username), json={"equipment_id": equipment_id, "result": "功能正常"})
        assert inspection.json()["code"] == 200
        inventory = await async_client.post("/api/equipment/inventory/check", headers=auth_headers(seed_data["director_user"].username), json={"equipment_id": equipment_id, "normal": True})
        assert inventory.json()["code"] == 200
        assert db_session.query(Equipment).filter(Equipment.equipment_id == equipment_id).one().inventory_status == 1

    async def test_patient_cannot_manage_equipment(self, async_client, seed_data, auth_headers):
        response = await async_client.get("/api/equipment/list", headers=auth_headers(seed_data["patient_user"].username))
        assert response.status_code == 403
