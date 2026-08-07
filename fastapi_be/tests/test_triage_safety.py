import pytest


@pytest.mark.asyncio
class TestTriageSafety:
    async def test_triage_explains_rule_based_limitations(self, async_client, seed_data):
        response = await async_client.post("/api/triage/suggest", json={"symptom": "普通咳嗽"})
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["mode"] == "rule_based"
        assert "不构成医疗诊断" in data["disclaimer"]
        assert data["emergency"] is False

    async def test_triage_warns_about_possible_emergency(self, async_client, seed_data):
        response = await async_client.post("/api/triage/suggest", json={"symptom": "胸痛并且呼吸困难"})
        data = response.json()["data"]
        assert data["emergency"] is True
        assert set(data["emergency_keywords"]) == {"胸痛", "呼吸困难"}
        assert "急救" in data["emergency_message"]
