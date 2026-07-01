import pytest


@pytest.mark.asyncio
class TestAdminDoctor:
    async def test_get_doctor_list(self, async_client, seed_data, auth_headers):
        r = await async_client.get("/api/doctorManagement/getList", headers=auth_headers(seed_data["admin_user"].username))
        assert r.status_code == 200
        body = r.json()
        assert body["code"] == 200
        assert len(body["data"]) >= 1

    async def test_register_doctor(self, async_client, seed_data, auth_headers):
        dept = seed_data["department"]
        headers = auth_headers(seed_data["admin_user"].username)
        r = await async_client.post("/api/doctorManagement/register", headers=headers, json={
            "username": "doc02", "password": "123456", "name": "李医生",
            "title": "副主任医师", "sex": "女", "phone": "13900139001",
            "department": dept.department_id, "permission": "doctor", "education": "硕士"
        })
        assert r.status_code == 200
        assert r.json()["code"] == 200

    async def test_register_doctor_duplicate(self, async_client, seed_data, auth_headers):
        dept = seed_data["department"]
        headers = auth_headers(seed_data["admin_user"].username)
        r = await async_client.post("/api/doctorManagement/register", headers=headers, json={
            "username": "doc02", "password": "123456", "name": "李医生2",
            "title": "副主任医师", "sex": "女", "phone": "13900139002",
            "department": dept.department_id, "permission": "doctor", "education": "硕士"
        })
        assert r.status_code == 200
        assert r.json()["code"] == 500

    async def test_register_doctor_requires_admin(self, async_client, seed_data, auth_headers):
        dept = seed_data["department"]
        headers = auth_headers(seed_data["patient_user"].username)
        r = await async_client.post("/api/doctorManagement/register", headers=headers, json={
            "username": "docx", "password": "123456", "name": "hack",
            "title": "医师", "sex": "男", "phone": "13900139099",
            "department": dept.department_id, "permission": "doctor", "education": "本科"
        })
        assert r.status_code == 403

    async def test_update_doctor(self, async_client, seed_data, auth_headers):
        doctor = seed_data["doctor"]
        headers = auth_headers(seed_data["admin_user"].username)
        r = await async_client.post("/api/doctorManagement/update", headers=headers, json={
            "doctor_id": doctor.doctor_id, "name": "王医生改", "title": "主任医师",
            "sex": "男", "phone": "13900139000", "department": seed_data["department"].department_id,
            "permission": "doctor", "education": "博士"
        })
        assert r.status_code == 200
        assert r.json()["code"] == 200

    async def test_delete_doctor(self, async_client, seed_data, auth_headers):
        dept = seed_data["department"]
        headers = auth_headers(seed_data["admin_user"].username)
        r = await async_client.post("/api/doctorManagement/register", headers=headers, json={
            "username": "docdel", "password": "123456", "name": "临时医生",
            "title": "医师", "sex": "男", "phone": "13900139999",
            "department": dept.department_id, "permission": "doctor", "education": "本科"
        })
        assert r.json()["code"] == 200
        r = await async_client.get("/api/doctorManagement/getList", headers=headers)
        docs = r.json()["data"]
        target = [d for d in docs if d["name"] == "临时医生"][0]

        r = await async_client.post("/api/doctorManagement/delete", headers=headers, json={"doctor_id": target["id"]})
        assert r.status_code == 200
        assert r.json()["code"] == 200


@pytest.mark.asyncio
class TestAdminPatient:
    async def test_get_patient_list(self, async_client, seed_data, auth_headers):
        r = await async_client.get("/api/patientManagement/getList", headers=auth_headers(seed_data["admin_user"].username))
        assert r.status_code == 200
        body = r.json()
        assert body["code"] == 200
        assert len(body["data"]) >= 2

    async def test_update_patient(self, async_client, seed_data, auth_headers):
        patient = seed_data["patient"]
        headers = auth_headers(seed_data["admin_user"].username)
        r = await async_client.post("/api/patientManagement/update", headers=headers, json={
            "patient_id": patient.patient_id, "name": "张三改",
            "sex": 1, "phone": "13800138888", "address": "新地址"
        })
        assert r.status_code == 200
        assert r.json()["code"] == 200


@pytest.mark.asyncio
class TestAdminDepartment:
    async def test_get_department_list(self, async_client, seed_data, auth_headers):
        r = await async_client.get("/api/departmentManagement/getList", headers=auth_headers(seed_data["admin_user"].username))
        assert r.status_code == 200
        body = r.json()
        assert body["code"] == 200
        assert len(body["data"]) >= 1

    async def test_create_department(self, async_client, seed_data, auth_headers):
        headers = auth_headers(seed_data["admin_user"].username)
        r = await async_client.post("/api/departmentManagement/create", headers=headers, json={
            "name": "外科", "phone": "01087654321", "director": 1, "location": "2号楼"
        })
        assert r.status_code == 200
        assert r.json()["code"] == 200

    async def test_update_department(self, async_client, seed_data, auth_headers):
        dept = seed_data["department"]
        headers = auth_headers(seed_data["admin_user"].username)
        r = await async_client.post("/api/departmentManagement/update", headers=headers, json={
            "department_id": dept.department_id, "name": "内科改",
            "phone": "01011111111", "director": 1, "location": "3号楼"
        })
        assert r.status_code == 200
        assert r.json()["code"] == 200

    async def test_delete_department(self, async_client, seed_data, auth_headers):
        headers = auth_headers(seed_data["admin_user"].username)
        r = await async_client.post("/api/departmentManagement/create", headers=headers, json={
            "name": "临时科室删", "phone": "01000000000", "director": 1, "location": "临时楼"
        })
        assert r.json()["code"] == 200
        r = await async_client.get("/api/departmentManagement/getList", headers=headers)
        depts = r.json()["data"]
        target = [d for d in depts if d["name"] == "临时科室删"][0]

        r = await async_client.post("/api/departmentManagement/delete", headers=headers, json={"department_id": target["id"]})
        assert r.status_code == 200
        assert r.json()["code"] == 200


@pytest.mark.asyncio
class TestAdminNotice:
    async def test_get_notice_list(self, async_client, seed_data, auth_headers):
        r = await async_client.get("/api/notice/getList", headers=auth_headers(seed_data["patient_user"].username))
        assert r.status_code == 200
        body = r.json()
        assert body["code"] == 200
        assert len(body["data"]) >= 1

    async def test_create_notice(self, async_client, seed_data, auth_headers):
        r = await async_client.post("/api/notice/create", headers=auth_headers(seed_data["admin_user"].username), json={
            "title": "新通知", "content": "通知内容", "isemergency": 0,
            "towho": ["医生"], "expiredtime": "2026-12-31"
        })
        assert r.status_code == 200
        assert r.json()["code"] == 200

    async def test_update_notice(self, async_client, seed_data, auth_headers):
        notice = seed_data["notice"]
        headers = auth_headers(seed_data["admin_user"].username)
        r = await async_client.post("/api/notice/update", headers=headers, json={
            "notice_id": str(notice.notice_id), "title": "通知改", "content": "内容改",
            "isemergency": 1, "towho": ["病人"], "expiredtime": "2027-01-01"
        })
        assert r.status_code == 200
        assert r.json()["code"] == 200

    async def test_delete_notice(self, async_client, seed_data, auth_headers):
        # create a notice to delete
        headers = auth_headers(seed_data["admin_user"].username)
        r = await async_client.post("/api/notice/create", headers=headers, json={
            "title": "待删除", "content": "内容", "isemergency": 0,
            "towho": ["医生"], "expiredtime": "2026-12-31"
        })
        assert r.json()["code"] == 200
        r = await async_client.get("/api/notice/getList", headers=headers)
        notices = r.json()["data"]
        target = [n for n in notices if n["title"] == "待删除"][0]

        r = await async_client.post("/api/notice/delete", headers=headers, json={"notice_id": target["uuid"]})
        assert r.status_code == 200
        assert r.json()["code"] == 200
