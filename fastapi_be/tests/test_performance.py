"""科室绩效核算测试：明细求和、绩效公式、状态机、RBAC。"""
import pytest


@pytest.mark.asyncio
class TestDepartmentPerformance:
    async def test_performance_calc_and_flow(self, async_client, seed_data, auth_headers):
        admin_headers = auth_headers("admin")
        dept_id = seed_data["department"].department_id

        # 重复期拒绝 & 非法系数拒绝
        r = await async_client.post("/api/performance/create", headers=admin_headers, json={
            "period": "2026-08", "department_id": dept_id, "coefficient": 99,
            "workload_items": [], "cost_items": [],
        })
        assert r.json()["code"] == 400

        r = await async_client.post("/api/performance/create", headers=admin_headers, json={
            "period": "2026-08", "department_id": dept_id,
            "workload_items": [
                {"项目": "门诊诊查", "数量": 1200, "单价": 1.5},
                {"项目": "出院人次", "数量": 80, "单价": 30},
                {"项目": "手术台次", "小计": 9000},
            ],
            "cost_items": [
                {"科目": "人力成本", "金额": 15000},
                {"科目": "耗材分摊", "金额": 3200.5},
            ],
            "coefficient": 1.2,
        })
        assert r.json()["code"] == 200, r.json()
        # 工作量 = 1800 + 2400 + 9000 = 13200；成本 = 18200.5
        # 绩效 = (13200 - 18200.5) × 1.2 = -6000.6（负绩效如实反映亏损）
        assert r.json()["data"]["performance_amount"] == -6000.6
        pid = r.json()["data"]["performance_id"]

        # 同期重复拒绝
        r = await async_client.post("/api/performance/create", headers=admin_headers, json={
            "period": "2026-08", "department_id": dept_id, "workload_items": [], "cost_items": []})
        assert r.json()["code"] == 500

        # 更新明细重算（补记工作量 10000 小计）
        r = await async_client.post("/api/performance/update", headers=admin_headers, json={
            "performance_id": pid,
            "workload_items": [{"项目": "门诊诊查", "数量": 1200, "单价": 1.5},
                               {"项目": "出院人次", "数量": 80, "单价": 30},
                               {"项目": "手术台次", "小计": 9000},
                               {"项目": "会诊收入", "小计": 10000}],
        })
        assert r.json()["data"]["performance_amount"] == 5999.4  # (23200-18200.5)*1.2

        # 提交 → 审核发放
        r = await async_client.post("/api/performance/submit", headers=admin_headers, json={"performance_id": pid})
        assert r.json()["code"] == 200
        # 提交后不能改
        r = await async_client.post("/api/performance/update", headers=admin_headers, json={"performance_id": pid, "coefficient": 2})
        assert r.json()["code"] == 500
        # 重复提交拒绝
        r = await async_client.post("/api/performance/submit", headers=admin_headers, json={"performance_id": pid})
        assert r.json()["code"] == 500
        # 审核发放
        r = await async_client.post("/api/performance/audit", headers=admin_headers, json={"performance_id": pid, "approve": True})
        assert r.json()["data"]["status_text"] == "已审核发放"
        # 已发放不能改
        r = await async_client.post("/api/performance/update", headers=admin_headers, json={"performance_id": pid, "coefficient": 2})
        assert r.json()["code"] == 500

    async def test_performance_reject_and_rbac(self, async_client, seed_data, auth_headers):
        admin_headers = auth_headers("admin")
        doctor_headers = auth_headers(seed_data["doctor_user"].username)
        dept_id = seed_data["department"].department_id

        # 医生无权访问绩效
        r = await async_client.get("/api/performance/getList", headers=doctor_headers)
        assert r.status_code == 403

        # 草稿被审核退回后可修改
        r = await async_client.post("/api/performance/create", headers=admin_headers, json={
            "period": "2026-09", "department_id": dept_id,
            "workload_items": [{"项目": "门诊", "数量": 10, "单价": 2}],
            "cost_items": [], "coefficient": 1})
        pid = r.json()["data"]["performance_id"]
        await async_client.post("/api/performance/submit", headers=admin_headers, json={"performance_id": pid})
        r = await async_client.post("/api/performance/audit", headers=admin_headers, json={"performance_id": pid, "approve": False})
        assert r.json()["data"]["status"] == 0
        r = await async_client.post("/api/performance/update", headers=admin_headers, json={"performance_id": pid, "coefficient": 1.5})
        assert r.json()["code"] == 200
