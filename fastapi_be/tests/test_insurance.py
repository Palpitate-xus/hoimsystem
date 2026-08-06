import pytest


@pytest.mark.asyncio
class TestInsurance:
    async def test_insurance_settlement_chronic_drg_and_warning(self, async_client, seed_data, auth_headers):
        admin_headers = auth_headers(seed_data["admin_user"].username)
        assert (await async_client.post("/api/insurance/catalog/save", headers=admin_headers, json={"code": "I-001", "name": "普通门诊", "reimbursement_ratio": 0.8})).json()["code"] == 200
        settlement = await async_client.post("/api/insurance/settlement/create", headers=auth_headers(seed_data["cashier_user"].username), json={"patient_id": seed_data["patient"].patient_id, "insurance_no": "INS-001", "total_amount": 1000, "covered_amount": 800})
        assert settlement.json()["data"]["self_amount"] == 200
        assert (await async_client.post("/api/insurance/chronic/create", headers=auth_headers(seed_data["doctor_user"].username), json={"patient_id": seed_data["patient"].patient_id, "disease_name": "高血压"})).json()["code"] == 200
        grouping = await async_client.post("/api/insurance/drg/group", headers=admin_headers, json={"patient_id": seed_data["patient"].patient_id, "group_code": "DRG-001", "diagnosis": "肺炎", "expected_amount": 5000, "actual_amount": 12000})
        assert grouping.json()["data"]["profit"] == -7000
        warnings = await async_client.get("/api/insurance/control/warnings", headers=admin_headers)
        assert warnings.json()["data"][0]["over_amount"] == 7000

    async def test_patient_cannot_settle_insurance(self, async_client, seed_data, auth_headers):
        response = await async_client.get("/api/insurance/settlement/list", headers=auth_headers(seed_data["patient_user"].username))
        assert response.status_code == 403
