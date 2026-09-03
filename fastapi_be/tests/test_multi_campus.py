import pytest

from app.models import HospitalCampus


@pytest.mark.asyncio
class TestMultiCampus:
    async def test_admin_can_create_update_and_filter_campus_departments(self, async_client, seed_data, auth_headers, db_session):
        headers = auth_headers(seed_data["admin_user"].username)
        create = await async_client.post(
            "/api/campusManagement/create",
            headers=headers,
            json={
                "code": "east",
                "name": "东院区",
                "address": "东院区1号路",
                "phone": "01012340000",
            },
        )
        assert create.status_code == 200
        campus = create.json()["data"]
        assert campus["code"] == "east"
        assert campus["department_count"] == 0

        department = await async_client.post(
            "/api/departmentManagement/create",
            headers=headers,
            json={
                "name": "东院区内科",
                "phone": "01012340001",
                "location": "门诊楼1层",
                "director": None,
                "campus_id": campus["id"],
            },
        )
        assert department.status_code == 200
        assert department.json()["code"] == 200

        listing = await async_client.get(
            "/api/departmentManagement/getList",
            headers=headers,
            params={"campus_id": campus["id"]},
        )
        items = listing.json()["data"]
        assert len(items) == 1
        assert items[0]["campus_name"] == "东院区"

        navigation = await async_client.get(
            "/api/navigation/departments",
            headers=headers,
            params={"campus_id": campus["id"]},
        )
        assert navigation.json()["data"][0]["campus_name"] == "东院区"

        updated = await async_client.post(
            "/api/campusManagement/update",
            headers=headers,
            json={
                "campus_id": campus["id"],
                "code": "east",
                "name": "东院区（新）",
                "address": "东院区2号路",
                "phone": "01012340002",
                "status": 1,
                "sort_order": 1,
            },
        )
        assert updated.status_code == 200
        assert updated.json()["data"]["name"] == "东院区（新）"

        campus_row = db_session.query(HospitalCampus).filter(HospitalCampus.campus_id == campus["id"]).one()
        assert campus_row.departments[0].name == "东院区内科"

    async def test_campus_delete_is_blocked_when_departments_exist(self, async_client, seed_data, auth_headers):
        headers = auth_headers(seed_data["admin_user"].username)
        campus = await async_client.post(
            "/api/campusManagement/create",
            headers=headers,
            json={"code": "west", "name": "西院区"},
        )
        campus_id = campus.json()["data"]["id"]
        await async_client.post(
            "/api/departmentManagement/create",
            headers=headers,
            json={"name": "西院区急诊", "campus_id": campus_id},
        )
        deleted = await async_client.post(
            "/api/campusManagement/delete",
            headers=headers,
            json={"campus_id": campus_id},
        )
        assert deleted.status_code == 400
        assert deleted.json()["code"] == 500
        assert "仍有科室" in deleted.json()["msg"]

    async def test_non_admin_cannot_manage_campus(self, async_client, seed_data, auth_headers):
        response = await async_client.post(
            "/api/campusManagement/create",
            headers=auth_headers(seed_data["patient_user"].username),
            json={"code": "blocked", "name": "不应创建"},
        )
        assert response.status_code == 403
