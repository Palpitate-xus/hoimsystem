from base64 import b64decode, b64encode

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import padding


@pytest.mark.asyncio
class TestUserAuth:
    async def test_public_key(self, async_client):
        r = await async_client.get("/api/publicKey")
        assert r.status_code == 200
        body = r.json()
        assert body["code"] == 200
        assert "publicKey" in body["data"]

    async def test_register_and_login(self, async_client):
        # register
        r = await async_client.post("/api/register", json={
            "username": "testuser", "password": "123456",
            "identity": "110101200001011111", "address": "测试地址",
            "sex": 1, "phone": "13800138001", "birthday": "2000-01-01"
        })
        assert r.status_code == 200
        assert r.json()["code"] == 200

        # login success
        r = await async_client.post("/api/login", json={
            "username": "110101200001011111", "password": "123456"
        })
        assert r.status_code == 200
        body = r.json()
        assert body["code"] == 200
        assert "accesstoken" in body["data"]
        assert len(body["data"]["accesstoken"]) > 20

    async def test_encrypted_password_transport(self, async_client):
        key_response = await async_client.get("/api/publicKey")
        public_key = serialization.load_der_public_key(b64decode(key_response.json()["data"]["publicKey"]))

        def encrypted(value):
            ciphertext = public_key.encrypt(value.encode(), padding.PKCS1v15())
            return "RSA1:" + b64encode(ciphertext).decode()

        r = await async_client.post("/api/register", json={
            "username": "加密患者", "password": encrypted("123456"),
            "identity": "110101200001011119", "address": "测试地址",
            "sex": 1, "phone": "13800138009", "birthday": "2000-01-01"
        })
        assert r.json()["code"] == 200
        r = await async_client.post("/api/login", json={
            "username": "110101200001011119", "password": encrypted("123456")
        })
        assert r.json()["code"] == 200

    async def test_register_rejects_duplicate_identity(self, async_client):
        payload = {
            "username": "重复患者",
            "password": "123456",
            "identity": "110101200001011112",
            "address": "测试地址",
            "sex": 1,
            "phone": "13800138002",
            "birthday": "2000-01-01",
        }
        first = await async_client.post("/api/register", json=payload)
        assert first.status_code == 200
        assert first.json()["code"] == 200
        second = await async_client.post("/api/register", json=payload)
        assert second.status_code == 200
        assert second.json()["code"] == 500
        # 注册失败提示统一模糊，不泄露"该身份证号已注册"（防枚举）
        assert "注册失败" in second.json()["msg"]

    async def test_login_fail(self, async_client):
        r = await async_client.post("/api/login", json={
            "username": "nonexistent", "password": "wrong"
        })
        assert r.status_code == 200
        assert r.json()["code"] == 500

    async def test_user_info(self, async_client, seed_data):
        # login to get JWT token
        r = await async_client.post("/api/login", json={
            "username": seed_data["patient_user"].username, "password": "123456"
        })
        token = r.json()["data"]["accesstoken"]
        r = await async_client.post("/api/userInfo", json={
            "accesstoken": token
        })
        assert r.status_code == 200
        body = r.json()
        assert body["code"] == 200
        assert "permissions" in body["data"]
        assert body["data"]["permissions"] == ["patient"]

    async def test_user_info_extended_role(self, async_client, seed_data):
        r = await async_client.post("/api/login", json={
            "username": seed_data["cashier_user"].username, "password": "123456"
        })
        token = r.json()["data"]["accesstoken"]
        r = await async_client.post("/api/userInfo", json={"accesstoken": token})
        assert r.status_code == 200
        body = r.json()
        assert body["code"] == 200
        assert body["data"]["permissions"] == ["cashier"]

    async def test_logout_revokes_token(self, async_client, auth_headers, seed_data):
        headers = auth_headers(seed_data["admin_user"].username)
        r = await async_client.post("/api/logout", headers=headers)
        assert r.status_code == 200
        assert r.json()["code"] == 200
        # 登出后旧 token 应被服务端吊销
        r2 = await async_client.get("/api/doctorManagement/getList", headers=headers)
        assert r2.status_code == 401

    async def test_health_probe(self, async_client):
        r = await async_client.post("/api/test", json={"data": "hello"})
        assert r.status_code == 200
        assert r.json()["data"] == "ok"


@pytest.mark.asyncio
class TestPrepaidPermissions:
    async def test_patient_can_read_own_balance(self, async_client, seed_data, auth_headers):
        r = await async_client.get(
            "/api/prepaid/getBalance",
            params={"identity": seed_data["patient"].identity},
            headers=auth_headers(seed_data["patient_user"].username),
        )
        assert r.status_code == 200
        body = r.json()
        assert body["code"] == 200
        assert "balance" in body["data"]

    async def test_patient_cannot_read_other_balance(self, async_client, seed_data, auth_headers):
        r = await async_client.get(
            "/api/prepaid/getBalance",
            params={"identity": seed_data["patient2"].identity},
            headers=auth_headers(seed_data["patient_user"].username),
        )
        assert r.status_code == 403

    async def test_cashier_can_recharge_and_deduct(self, async_client, seed_data, auth_headers):
        headers = auth_headers(seed_data["cashier_user"].username)
        r = await async_client.post(
            "/api/prepaid/recharge",
            headers=headers,
            json={"identity": seed_data["patient"].identity, "amount": 100},
        )
        assert r.status_code == 200
        assert r.json()["code"] == 200

        r = await async_client.post(
            "/api/prepaid/deduct",
            headers=headers,
            json={"identity": seed_data["patient"].identity, "amount": 30},
        )
        assert r.status_code == 200
        assert r.json()["code"] == 200
        assert r.json()["data"]["balance"] == 70

    async def test_patient_cannot_recharge_directly(self, async_client, seed_data, auth_headers):
        r = await async_client.post(
            "/api/prepaid/recharge",
            headers=auth_headers(seed_data["patient_user"].username),
            json={"identity": seed_data["patient"].identity, "amount": 100},
        )
        assert r.status_code == 403

    async def test_cashier_rejects_non_positive_deduction(self, async_client, seed_data, auth_headers):
        headers = auth_headers(seed_data["cashier_user"].username)
        for amount in (0, -10):
            r = await async_client.post(
                "/api/prepaid/deduct",
                headers=headers,
                json={"identity": seed_data["patient"].identity, "amount": amount},
            )
            assert r.status_code == 200
            assert r.json()["code"] == 500

    async def test_cashier_rejects_non_finite_or_invalid_amounts(self, async_client, seed_data, auth_headers):
        headers = auth_headers(seed_data["cashier_user"].username)
        for endpoint in ("/api/prepaid/recharge", "/api/prepaid/deduct"):
            for amount in ("nan", "inf", "-inf", "not-a-number"):
                r = await async_client.post(
                    endpoint,
                    headers=headers,
                    json={"identity": seed_data["patient"].identity, "amount": amount},
                )
                assert r.status_code == 200
                assert r.json()["code"] == 500

    async def test_cashier_keeps_prepaid_amounts_at_cent_precision(self, async_client, seed_data, auth_headers):
        headers = auth_headers(seed_data["cashier_user"].username)
        before = await async_client.get(
            "/api/prepaid/getBalance",
            headers=auth_headers(seed_data["patient_user"].username),
            params={"identity": seed_data["patient"].identity},
        )
        initial_balance = before.json()["data"]["balance"]
        for amount in ("0.10", "0.20"):
            response = await async_client.post(
                "/api/prepaid/recharge",
                headers=headers,
                json={"identity": seed_data["patient"].identity, "amount": amount},
            )
            assert response.json()["code"] == 200
        balance = await async_client.get(
            "/api/prepaid/getBalance",
            headers=auth_headers(seed_data["patient_user"].username),
            params={"identity": seed_data["patient"].identity},
        )
        assert balance.json()["data"]["balance"] == initial_balance + 0.30

        too_small = await async_client.post(
            "/api/prepaid/recharge",
            headers=headers,
            json={"identity": seed_data["patient"].identity, "amount": "0.001"},
        )
        assert too_small.json()["code"] == 500

    async def test_cashier_can_refund_prepaid_balance_and_record_reason(self, async_client, seed_data, auth_headers):
        headers = auth_headers(seed_data["cashier_user"].username)
        before = await async_client.get(
            "/api/prepaid/getBalance",
            headers=auth_headers(seed_data["patient_user"].username),
            params={"identity": seed_data["patient"].identity},
        )
        initial_balance = before.json()["data"]["balance"]
        recharge = await async_client.post(
            "/api/prepaid/recharge",
            headers=headers,
            json={"identity": seed_data["patient"].identity, "amount": "1.00"},
        )
        assert recharge.json()["code"] == 200
        refund = await async_client.post(
            "/api/prepaid/refund",
            headers=headers,
            json={"identity": seed_data["patient"].identity, "amount": "0.30", "reason": "患者申请退款"},
        )
        assert refund.json()["code"] == 200
        assert refund.json()["data"]["balance"] == initial_balance + 0.70
        transactions = await async_client.get(
            "/api/prepaid/getTransactions",
            headers=auth_headers(seed_data["patient_user"].username),
            params={"identity": seed_data["patient"].identity},
        )
        assert transactions.json()["data"][0]["type"] == "refund"
        assert transactions.json()["data"][0]["note"] == "患者申请退款"

    async def test_cashier_cannot_refund_more_than_prepaid_balance(self, async_client, seed_data, auth_headers):
        response = await async_client.post(
            "/api/prepaid/refund",
            headers=auth_headers(seed_data["cashier_user"].username),
            json={"identity": seed_data["patient"].identity, "amount": "999999.00"},
        )
        assert response.json() == {"code": 500, "msg": "预交金余额不足，无法退款"}

    async def test_prepaid_transactions_record_and_isolate_accounts(self, async_client, seed_data, auth_headers):
        headers = auth_headers(seed_data["cashier_user"].username)
        before = await async_client.get(
            "/api/prepaid/getBalance",
            headers=auth_headers(seed_data["patient_user"].username),
            params={"identity": seed_data["patient"].identity},
        )
        initial_balance = before.json()["data"]["balance"]
        await async_client.post(
            "/api/prepaid/recharge",
            headers=headers,
            json={"identity": seed_data["patient"].identity, "amount": 100},
        )
        await async_client.post(
            "/api/prepaid/deduct",
            headers=headers,
            json={"identity": seed_data["patient"].identity, "amount": 30},
        )
        own = await async_client.get(
            "/api/prepaid/getTransactions",
            headers=auth_headers(seed_data["patient_user"].username),
            params={"identity": seed_data["patient"].identity},
        )
        assert own.status_code == 200
        assert [item["type"] for item in own.json()["data"][:2]] == ["deduct", "recharge"]
        assert own.json()["data"][0]["balance_after"] == initial_balance + 70

        other = await async_client.get(
            "/api/prepaid/getTransactions",
            headers=auth_headers(seed_data["patient_user"].username),
            params={"identity": seed_data["patient2"].identity},
        )
        assert other.status_code == 403


@pytest.mark.asyncio
class TestUserRoleSecurity:
    async def test_admin_cannot_grant_super_admin(self, async_client, seed_data, auth_headers):
        r = await async_client.post(
            "/api/user/updateRole",
            headers=auth_headers(seed_data["admin_user"].username),
            json={"user_id": seed_data["patient2_user"].user_id, "user_role": "super_admin"},
        )
        assert r.status_code == 200
        assert r.json()["code"] == 403

    async def test_admin_cannot_modify_super_admin(self, async_client, seed_data, auth_headers):
        r = await async_client.post(
            "/api/user/updateRole",
            headers=auth_headers(seed_data["admin_user"].username),
            json={"user_id": seed_data["super_admin_user"].user_id, "user_role": "doctor"},
        )
        assert r.status_code == 200
        assert r.json()["code"] == 403

    async def test_admin_cannot_change_own_role(self, async_client, seed_data, auth_headers):
        r = await async_client.post(
            "/api/user/updateRole",
            headers=auth_headers(seed_data["admin_user"].username),
            json={"user_id": seed_data["admin_user"].user_id, "user_role": "patient"},
        )
        assert r.status_code == 200
        assert r.json()["code"] == 500

    async def test_password_reset_does_not_return_plaintext(self, async_client, seed_data, auth_headers):
        identity = "110101200001019999"
        register = await async_client.post(
            "/api/register",
            json={
                "username": "密码重置测试用户",
                "password": "123456",
                "identity": identity,
                "address": "测试地址",
                "sex": 1,
                "phone": "13800139999",
                "birthday": "2000-01-01",
            },
        )
        assert register.json()["code"] == 200
        users = await async_client.get(
            "/api/user/getList",
            headers=auth_headers(seed_data["admin_user"].username),
        )
        target = next(item for item in users.json()["data"] if item["username"] == identity)
        r = await async_client.post(
            "/api/user/resetPassword",
            headers=auth_headers(seed_data["admin_user"].username),
            json={"user_id": target["user_id"], "new_password": "newpass123"},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["code"] == 200
        assert "data" not in body
        assert "newpass123" not in r.text

        login = await async_client.post(
            "/api/login",
            json={"username": identity, "password": "newpass123"},
        )
        assert login.status_code == 200
        assert login.json()["code"] == 200

    async def test_password_reset_rejects_invalid_length(self, async_client, seed_data, auth_headers):
        r = await async_client.post(
            "/api/user/resetPassword",
            headers=auth_headers(seed_data["admin_user"].username),
            json={"user_id": seed_data["patient2_user"].user_id, "new_password": "short"},
        )
        assert r.status_code == 200
        assert r.json()["code"] == 500

    async def test_password_reset_requires_explicit_password(self, async_client, seed_data, auth_headers):
        r = await async_client.post(
            "/api/user/resetPassword",
            headers=auth_headers(seed_data["admin_user"].username),
            json={"user_id": seed_data["patient2_user"].user_id},
        )
        assert r.status_code == 200
        assert r.json()["code"] == 500
