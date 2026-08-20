import pytest


@pytest.mark.asyncio
class TestEmergencyGreenChannel:
    async def test_green_channel_approval_lifecycle(self, async_client, seed_data, auth_headers):
        nurse_headers = auth_headers(seed_data["nurse_user"].username)
        triage = await async_client.post("/api/emergency/triage/create", headers=nurse_headers, json={"patient_id": seed_data["patient"].patient_id, "triage_level": 1, "chief_complaint": "胸痛", "green_channel": 1})
        triage_id = triage.json()["data"]["triage_id"]
        created = await async_client.post("/api/emergency/greenChannel/create", headers=nurse_headers, json={"triage_id": triage_id, "reason": "疑似急性心肌梗死，需先救治后付费"})
        assert created.json()["code"] == 200
        channel_id = created.json()["data"]["channel_id"]
        duplicate = await async_client.post("/api/emergency/greenChannel/create", headers=nurse_headers, json={"triage_id": triage_id, "reason": "重复申请"})
        assert duplicate.json()["code"] == 500
        approved = await async_client.post("/api/emergency/greenChannel/approve", headers=auth_headers(seed_data["director_user"].username), json={"channel_id": channel_id, "note": "同意先救治"})
        assert approved.json()["data"]["status_text"] == "已批准"
        closed = await async_client.post("/api/emergency/greenChannel/close", headers=nurse_headers, json={"channel_id": channel_id, "note": "费用已补录"})
        assert closed.json()["data"]["status_text"] == "已关闭"

    async def test_green_channel_requires_flag_and_approval(self, async_client, seed_data, auth_headers):
        nurse_headers = auth_headers(seed_data["nurse_user"].username)
        triage = await async_client.post("/api/emergency/triage/create", headers=nurse_headers, json={"patient_id": seed_data["patient"].patient_id, "triage_level": 2, "chief_complaint": "发热"})
        response = await async_client.post("/api/emergency/greenChannel/create", headers=nurse_headers, json={"triage_id": triage.json()["data"]["triage_id"], "reason": "未标记"})
        assert response.json()["code"] == 500

    async def test_green_channel_close_settles_observation_charges(self, async_client, seed_data, auth_headers):
        """绿色通道关闭时自动补记待计费留观费用（先救治后收费闭环）。"""
        from app.models import Charge
        from tests.conftest import TestingSessionLocal

        nurse_headers = auth_headers(seed_data["nurse_user"].username)
        triage = await async_client.post("/api/emergency/triage/create", headers=nurse_headers, json={"patient_id": seed_data["patient"].patient_id, "triage_level": 1, "chief_complaint": "多发伤", "green_channel": 1})
        triage_id = triage.json()["data"]["triage_id"]
        channel_id = (await async_client.post("/api/emergency/greenChannel/create", headers=nurse_headers, json={"triage_id": triage_id, "reason": "车祸多发伤"})).json()["data"]["channel_id"]
        await async_client.post("/api/emergency/greenChannel/approve", headers=auth_headers(seed_data["director_user"].username), json={"channel_id": channel_id, "note": "同意"})

        # 两条留观：一条有待计费金额（结束后新开一条无费用留观）
        obs1 = await async_client.post("/api/emergency/observation/create", headers=nurse_headers, json={"triage_id": triage_id, "condition": "留观中", "fee_amount": 156.8})
        assert obs1.json()["code"] == 200
        oid1 = obs1.json()["data"]["observation_id"]
        ended = await async_client.put("/api/emergency/observation/update", headers=nurse_headers, json={"observation_id": oid1, "status": 2})
        assert ended.json()["code"] == 200, ended.json()
        obs2 = await async_client.post("/api/emergency/observation/create", headers=nurse_headers, json={"triage_id": triage_id, "condition": "无费用留观", "fee_amount": 0})
        assert obs2.json()["code"] == 200, obs2.json()

        closed = await async_client.post("/api/emergency/greenChannel/close", headers=nurse_headers, json={"channel_id": channel_id, "note": "费用补记"})
        assert closed.json()["data"]["settled_charges"] == 1

        s = TestingSessionLocal()
        try:
            charges = s.query(Charge).filter(Charge.charge_type == "emergency_observation").all()
            assert len(charges) == 1
            assert float(charges[0].amount) == 156.8
            assert charges[0].status == 1
        finally:
            s.close()
