import pytest


@pytest.mark.asyncio
class TestPatientCard:
    async def test_registrar_issues_card_and_patient_can_report_lost(self, async_client, seed_data, auth_headers):
        registrar_headers = auth_headers(seed_data["registrar_user"].username)
        issued = await async_client.post(
            "/api/patientCard/issue", headers=registrar_headers, json={"identity": seed_data["patient"].identity}
        )
        assert issued.json()["code"] == 200
        card = issued.json()["data"]
        assert card["card_no"].startswith("C")

        patient_headers = auth_headers(seed_data["patient_user"].username)
        listed = await async_client.get("/api/patientCard/list", headers=patient_headers)
        assert any(item["card_id"] == card["card_id"] for item in listed.json()["data"])
        lost = await async_client.post("/api/patientCard/lost", headers=patient_headers, json={"card_id": card["card_id"]})
        assert lost.json()["data"]["status_text"] == "已挂失"

        cancelled = await async_client.post("/api/patientCard/cancel", headers=registrar_headers, json={"card_id": card["card_id"]})
        assert cancelled.json()["data"]["status_text"] == "已注销"

    async def test_duplicate_active_card_is_rejected(self, async_client, seed_data, auth_headers):
        headers = auth_headers(seed_data["registrar_user"].username)
        first = await async_client.post("/api/patientCard/issue", headers=headers, json={"patient_id": seed_data["patient2"].patient_id})
        assert first.json()["code"] == 200
        duplicate = await async_client.post("/api/patientCard/issue", headers=headers, json={"patient_id": seed_data["patient2"].patient_id})
        assert duplicate.json()["code"] == 400
