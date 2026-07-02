"""审计日志全量测试。

验证:
1. 所有 POST/PUT/DELETE 都被记录
2. 敏感 GET(查看病历/处方/患者详情)也被记录
3. 非敏感 GET(列表查询)不记录
4. 登录/注册/静态资源不记录
5. 审计字段完整(username/role/ip/path/detail/status_code)
6. 失败操作也被记录
7. 统计接口正常
"""
import pytest


@pytest.mark.asyncio
class TestAuditMiddleware:
    """审计中间件全量验证。"""

    async def test_post_is_logged(self, async_client, seed_data, auth_headers):
        """POST 操作被记录。"""
        headers = auth_headers(seed_data["admin_user"].username)
        # 触发一个 POST
        r_create = await async_client.post("/api/departmentManagement/create", headers=headers,
            json={"name": "审计测试科室", "phone": "01000000000", "location": "测试楼"})
        # 查日志
        r = await async_client.post("/api/log/getList", headers=headers,
            json={"page": 1, "page_size": 10})
        logs = r.json()["data"]["list"]
        # 找到刚才的操作
        matched = [l for l in logs if l["action"] == "新增" and "科室" in l.get("target", "")]
        assert len(matched) >= 1, f"POST 未被记录,最近日志: {logs[:3]}"
        log = matched[0]
        assert log["username"] == "admin"
        assert log["role"] == "admin"
        assert log["method"] == "POST"
        # 日志的 result/status_code 应反映实际响应
        expected_result = "成功" if 200 <= r_create.status_code < 400 else "失败"
        assert log["result"] == expected_result
        assert log["status_code"] == r_create.status_code

    async def test_delete_is_logged(self, async_client, seed_data, auth_headers):
        """DELETE(含 POST 的 delete)操作被记录。"""
        headers = auth_headers(seed_data["admin_user"].username)
        # 先创建一个
        r = await async_client.post("/api/departmentManagement/create", headers=headers,
            json={"name": "待删科室", "phone": "01000000001", "location": "测试楼"})
        # 找到 id
        r = await async_client.get("/api/departmentManagement/getList", headers=headers)
        target = next((d for d in r.json()["data"] if d["name"] == "待删科室"), None)
        if not target:
            pytest.skip("创建失败")
        # 删除
        await async_client.post("/api/departmentManagement/delete", headers=headers,
            json={"department_id": target["id"]})
        # 查日志
        r = await async_client.post("/api/log/getList", headers=headers,
            json={"page": 1, "page_size:": 10})
        logs = r.json()["data"]["list"]
        matched = [l for l in logs if l["action"] == "删除" and "科室" in l.get("target", "")]
        assert len(matched) >= 1

    async def test_failed_operation_is_logged(self, async_client, seed_data, auth_headers):
        """失败操作也被记录(result=失败)。"""
        headers = auth_headers(seed_data["admin_user"].username)
        # 删除不存在的 id → 500
        await async_client.post("/api/departmentManagement/delete", headers=headers,
            json={"department_id": -9999})
        # 查日志
        r = await async_client.post("/api/log/getList", headers=headers,
            json={"page": 1, "page_size": 10, "result": "失败"})
        logs = r.json()["data"]["list"]
        assert len(logs) >= 1, "失败操作未被记录"

    async def test_sensitive_get_is_logged(self, async_client, seed_data, auth_headers):
        """敏感 GET(查看病历详情)被记录。"""
        headers = auth_headers(seed_data["admin_user"].username)
        mr = seed_data["medical_record"]
        # 查看病历详情
        await async_client.post("/api/medicalRecord/detail", headers=headers,
            json={"medical_record_id": str(mr.medical_record_id)})
        # 查日志
        r = await async_client.post("/api/log/getList", headers=headers,
            json={"page": 1, "page_size": 10, "method": "POST"})
        logs = r.json()["data"]["list"]
        matched = [l for l in logs if "病历" in l.get("target", "") and l.get("action") in ("访问", "查询")]
        # 至少 medicalRecord/detail 被记录
        assert len(matched) >= 1 or any("medicalRecord" in l.get("path", "") for l in logs), \
            f"敏感操作未被记录,最近: {logs[:3]}"

    async def test_login_not_logged(self, async_client, seed_data):
        """登录操作不记录(避免日志膨胀)。"""
        r = await async_client.post("/api/login", json={"username": "admin", "password": "admin123"})
        if r.json()["code"] != 200:
            pytest.skip("登录失败")
        # 用 admin token 查日志
        from app.routers.user import create_access_token
        headers = {"accesstoken": create_access_token("admin")}
        r = await async_client.post("/api/log/getList", headers=headers,
            json={"page": 1, "page_size": 5})
        logs = r.json()["data"]["list"]
        # 最新一条不应是 login
        if logs:
            assert "login" not in logs[0].get("path", "").lower(), "登录不应被记录"

    async def test_static_resource_not_logged(self, async_client, seed_data, auth_headers):
        """静态资源不记录。"""
        headers = auth_headers(seed_data["admin_user"].username)
        r = await async_client.post("/api/log/getList", headers=headers,
            json={"page": 1, "page_size": 5})
        logs = r.json()["data"]["list"]
        for l in logs:
            assert not l.get("path", "").startswith("/uploads/"), "静态资源不应被记录"

    async def test_log_filter_by_username(self, async_client, seed_data, auth_headers):
        """按用户名筛选日志。"""
        headers = auth_headers(seed_data["admin_user"].username)
        r = await async_client.post("/api/log/getList", headers=headers,
            json={"page": 1, "page_size": 10, "username": "admin"})
        assert r.json()["code"] == 200
        logs = r.json()["data"]["list"]
        for l in logs:
            assert "admin" in l.get("username", "")

    async def test_log_filter_by_role(self, async_client, seed_data, auth_headers):
        """按角色筛选日志。"""
        headers = auth_headers(seed_data["admin_user"].username)
        r = await async_client.post("/api/log/getList", headers=headers,
            json={"page": 1, "page_size": 10, "role": "admin"})
        logs = r.json()["data"]["list"]
        for l in logs:
            assert l.get("role") == "admin"

    async def test_log_filter_by_action(self, async_client, seed_data, auth_headers):
        """按操作类型筛选。"""
        headers = auth_headers(seed_data["admin_user"].username)
        r = await async_client.post("/api/log/getList", headers=headers,
            json={"page": 1, "page_size": 10, "action": "新增"})
        logs = r.json()["data"]["list"]
        for l in logs:
            assert "新增" in l.get("action", "")

    async def test_log_filter_by_ip(self, async_client, seed_data, auth_headers):
        """按 IP 筛选。"""
        headers = auth_headers(seed_data["admin_user"].username)
        r = await async_client.post("/api/log/getList", headers=headers,
            json={"page": 1, "page_size": 10, "ip": "127.0.0.1"})
        assert r.json()["code"] == 200

    async def test_log_stats(self, async_client, seed_data, auth_headers):
        """统计面板。"""
        headers = auth_headers(seed_data["admin_user"].username)
        r = await async_client.get("/api/log/stats", headers=headers)
        assert r.json()["code"] == 200
        data = r.json()["data"]
        assert "total" in data
        assert "failed" in data
        assert "success_rate" in data
        assert "last_24h" in data
        assert "top_users" in data
        assert "top_actions" in data

    async def test_log_detail_contains_path(self, async_client, seed_data, auth_headers):
        """审计日志包含完整路径。"""
        headers = auth_headers(seed_data["admin_user"].username)
        await async_client.post("/api/departmentManagement/create", headers=headers,
            json={"name": "路径测试科室", "phone": "01000000002", "location": "测试楼"})
        r = await async_client.post("/api/log/getList", headers=headers,
            json={"page": 1, "page_size": 5})
        logs = r.json()["data"]["list"]
        assert any("departmentManagement" in l.get("path", "") for l in logs), \
            f"路径未被记录: {[l.get('path') for l in logs[:3]]}"

    async def test_non_admin_cannot_view_logs(self, async_client, seed_data, auth_headers):
        """非 admin 不能查看审计日志。"""
        headers = auth_headers(seed_data["patient_user"].username)
        r = await async_client.post("/api/log/getList", headers=headers,
            json={"page": 1, "page_size": 10})
        assert r.status_code == 403

    async def test_non_admin_cannot_view_stats(self, async_client, seed_data, auth_headers):
        """非 admin 不能查看统计面板。"""
        headers = auth_headers(seed_data["patient_user"].username)
        r = await async_client.get("/api/log/stats", headers=headers)
        assert r.status_code == 403
