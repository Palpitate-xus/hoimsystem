import pytest

from app.config import settings


@pytest.mark.asyncio
class TestBackupOperations:
    async def test_backup_rejects_non_sqlite_database_operations(self, async_client, seed_data, auth_headers, monkeypatch):
        monkeypatch.setattr(settings, "DATABASE_URL", "postgresql://db-user:db-pass@db.example/hoimsystem")
        headers = auth_headers(seed_data["admin_user"].username)
        create = await async_client.post("/api/backup/create", headers=headers)
        assert create.json() == {"code": 501, "msg": "当前数据库不是 SQLite 文件库，请使用数据库原生备份工具"}
        restore = await async_client.post("/api/backup/restore", headers=headers, json={"filename": "backup_20260807.db"})
        assert restore.json() == {"code": 501, "msg": "当前数据库不是 SQLite 文件库，请使用数据库原生恢复工具"}

    async def test_backup_file_endpoints_reject_path_traversal_and_non_db(self, async_client, seed_data, auth_headers):
        headers = auth_headers(seed_data["admin_user"].username)
        invalid_names = ["../secret.db", "notes.txt", ""]
        for filename in invalid_names:
            deleted = await async_client.post("/api/backup/delete", headers=headers, json={"filename": filename})
            assert deleted.json() == {"code": 500, "msg": "非法文件名"}
            downloaded = await async_client.get(f"/api/backup/download/{filename or 'notes.txt'}", headers=headers)
            assert downloaded.status_code == 404 or downloaded.json() == {"code": 500, "msg": "非法文件名"}
