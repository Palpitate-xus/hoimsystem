import pytest


@pytest.mark.asyncio
class TestGuideFaq:
    async def test_faq_create_update_and_public_query(self, async_client, seed_data, auth_headers):
        admin_headers = auth_headers(seed_data["admin_user"].username)
        patient_headers = auth_headers(seed_data["patient_user"].username)
        created = await async_client.post("/api/navigation/faq/create", headers=admin_headers, json={"question": "如何挂号", "answer": "登录后选择预约挂号", "category": "挂号"})
        assert created.json()["code"] == 200
        faq_id = created.json()["data"]["faq_id"]
        updated = await async_client.put("/api/navigation/faq/update", headers=admin_headers, json={"faq_id": faq_id, "answer": "登录后选择预约挂号并确认"})
        assert updated.json()["data"]["answer"].endswith("确认")
        listing = await async_client.get("/api/navigation/faq", headers=patient_headers, params={"keyword": "挂号"})
        assert listing.json()["data"][0]["faq_id"] == faq_id
