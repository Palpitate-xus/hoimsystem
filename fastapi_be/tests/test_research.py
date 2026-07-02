"""科研数据导出测试。"""
import io
import csv
import pytest


@pytest.mark.asyncio
class TestResearchExport:
    """科研数据导出 RBAC + 功能验证。"""

    async def test_list_tables_requires_auth(self, async_client):
        """未登录不能看表清单。"""
        r = await async_client.get("/api/research/export/tables")
        assert r.status_code == 401

    async def test_list_tables_admin(self, async_client, seed_data, auth_headers):
        """admin 能看到 7 张表。"""
        r = await async_client.get("/api/research/export/tables",
            headers=auth_headers(seed_data["admin_user"].username))
        assert r.status_code == 200
        assert r.json()["code"] == 200
        tables = [t["table"] for t in r.json()["data"]]
        assert "patients" in tables
        assert "prescriptions" in tables
        assert "lab_results" in tables

    async def test_export_patients_anonymized(self, async_client, seed_data, auth_headers):
        """导出患者信息(脱敏)。"""
        r = await async_client.post("/api/research/export",
            headers=auth_headers(seed_data["admin_user"].username),
            json={"table": "patients", "anonymize": True, "format": "csv"})
        assert r.status_code == 200
        content = r.content.decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(content))
        rows = list(reader)
        assert len(rows) >= 1
        row = rows[0]
        assert "patient_id" in row
        assert "name" in row
        # 脱敏:姓名应该是 hash(不是原始中文)
        if row["name"]:
            assert len(row["name"]) == 12  # sha256[:12]

    async def test_export_prescriptions(self, async_client, seed_data, auth_headers):
        """导出处方药品。"""
        r = await async_client.post("/api/research/export",
            headers=auth_headers(seed_data["admin_user"].username),
            json={"table": "prescriptions", "anonymize": False, "format": "csv"})
        assert r.status_code == 200
        content = r.content.decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(content))
        rows = list(reader)
        if rows:
            assert "drug_name" in rows[0]
            assert "number" in rows[0]
            assert "antibiotic_level" in rows[0]

    async def test_export_lab_results(self, async_client, seed_data, auth_headers):
        """导出检验结果。"""
        r = await async_client.post("/api/research/export",
            headers=auth_headers(seed_data["admin_user"].username),
            json={"table": "lab_results", "anonymize": True, "format": "csv"})
        assert r.status_code == 200

    async def test_export_package(self, async_client, seed_data, auth_headers):
        """全量数据包导出(ZIP)。"""
        r = await async_client.post("/api/research/export/package",
            headers=auth_headers(seed_data["admin_user"].username),
            json={"anonymize": True, "tables": ["patients", "prescriptions"]})
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("application/zip")

    async def test_director_can_export(self, async_client, seed_data, auth_headers):
        """director 可导出(临床科研需要)。"""
        r = await async_client.post("/api/research/export",
            headers=auth_headers(seed_data["director_user"].username),
            json={"table": "patients", "anonymize": True, "format": "csv"})
        assert r.status_code == 200

    async def test_patient_cannot_export(self, async_client, seed_data, auth_headers):
        """患者不能导出(防止数据拖取)。"""
        r = await async_client.post("/api/research/export",
            headers=auth_headers(seed_data["patient_user"].username),
            json={"table": "patients", "anonymize": True, "format": "csv"})
        assert r.status_code == 403

    async def test_nurse_cannot_export(self, async_client, seed_data, auth_headers):
        """护士不能导出。"""
        r = await async_client.post("/api/research/export",
            headers=auth_headers(seed_data["nurse_user"].username),
            json={"table": "patients", "anonymize": True, "format": "csv"})
        assert r.status_code == 403

    async def test_invalid_table(self, async_client, seed_data, auth_headers):
        """不支持的表 → 400。"""
        r = await async_client.post("/api/research/export",
            headers=auth_headers(seed_data["admin_user"].username),
            json={"table": "users", "anonymize": True, "format": "csv"})
        assert r.status_code == 400

    async def test_research_audit_log_admin_only(self, async_client, seed_data, auth_headers):
        """仅 admin 可查导出审计日志。"""
        # admin 可见
        r = await async_client.get("/api/research/export/audit",
            headers=auth_headers(seed_data["admin_user"].username))
        assert r.status_code == 200
        # director 不可见
        r = await async_client.get("/api/research/export/audit",
            headers=auth_headers(seed_data["director_user"].username))
        assert r.status_code == 403
