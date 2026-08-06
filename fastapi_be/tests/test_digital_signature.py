import pytest


@pytest.mark.asyncio
class TestDigitalSignature:
    async def test_signature_can_be_verified_and_tampering_is_rejected(self, async_client, seed_data, auth_headers):
        headers = auth_headers(seed_data["admin_user"].username)
        signed = await async_client.post(
            "/api/digitalSignature/sign", headers=headers, json={"content": "出院记录：患者病情稳定"}
        )
        assert signed.status_code == 200
        result = signed.json()["data"]

        verified = await async_client.post(
            "/api/digitalSignature/verify",
            headers=headers,
            json={"content": "出院记录：患者病情稳定", **result},
        )
        assert verified.status_code == 200
        assert verified.json()["data"]["valid"] is True

        tampered = await async_client.post(
            "/api/digitalSignature/verify",
            headers=headers,
            json={"content": "出院记录：患者病情已变化", **result},
        )
        assert tampered.status_code == 200
        assert tampered.json()["data"]["valid"] is False

    async def test_signature_requires_content_and_verify_authentication(self, async_client, seed_data, auth_headers):
        headers = auth_headers(seed_data["admin_user"].username)
        signed = await async_client.post("/api/digitalSignature/sign", headers=headers, json={"content": "  "})
        assert signed.status_code == 200
        assert signed.json()["code"] == 500

        verified = await async_client.post(
            "/api/digitalSignature/verify",
            json={"content": "anything", "sign_hash": "not-a-signature"},
        )
        assert verified.status_code == 401
