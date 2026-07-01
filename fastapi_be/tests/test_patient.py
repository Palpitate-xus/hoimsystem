import pytest


@pytest.mark.asyncio
class TestPatientAppointment:
    async def test_appointment_list(self, async_client, seed_data, auth_headers):
        r = await async_client.get("/api/appointmentManagement/appointmentList", headers=auth_headers(seed_data["patient_user"].username))
        assert r.status_code == 200
        assert r.json()["code"] == 200

    async def test_create_and_get_appointment(self, async_client, seed_data, auth_headers):
        patient_user = seed_data["patient_user"]
        headers = auth_headers(patient_user.username)
        # create appointment using first schedule
        r = await async_client.post("/api/appointmentManagement/create", headers=headers, json={
            "id": 1, "date": "2026-05-01", "department_id": seed_data["department"].department_id,
            "doctor_id": seed_data["doctor"].doctor_id, "time": "上午", "specialist": 1
        })
        assert r.status_code == 200
        assert r.json()["code"] == 200

        # get list
        r = await async_client.get("/api/appointmentManagement/getList", headers=headers)
        assert r.status_code == 200
        body = r.json()
        assert body["code"] == 200
        assert len(body["data"]) >= 1
        appt_uuid = body["data"][0]["uuid"]

        # cancel
        r = await async_client.post("/api/appointmentManagement/cancel", headers=headers, json={"uuid": appt_uuid})
        assert r.status_code == 200
        assert r.json()["code"] == 200

        # verify cancelled
        r = await async_client.get("/api/appointmentManagement/getList", headers=headers)
        assert r.json()["data"][0]["status"] == "已取消"


@pytest.mark.asyncio
class TestPatientRegistration:
    async def test_registration_list(self, async_client, seed_data, auth_headers):
        r = await async_client.get("/api/registrationManagement/registrationList", headers=auth_headers(seed_data["patient_user"].username))
        assert r.status_code == 200
        assert r.json()["code"] == 200

    async def test_create_and_get_registration(self, async_client, seed_data, auth_headers):
        patient_user = seed_data["patient_user"]
        headers = auth_headers(patient_user.username)
        r = await async_client.post("/api/registrationManagement/create", headers=headers, json={
            "id": 1, "doctor_id": seed_data["doctor"].doctor_id,
            "department_id": seed_data["department"].department_id, "specialist": 1
        })
        assert r.status_code == 200
        assert r.json()["code"] == 200

        r = await async_client.get("/api/registrationManagement/getList", headers=headers)
        assert r.status_code == 200
        body = r.json()
        assert body["code"] == 200
        assert len(body["data"]) >= 1
        reg_uuid = body["data"][0]["uuid"]

        # cancel
        r = await async_client.post("/api/registrationManagement/cancel", headers=headers, json={"uuid": reg_uuid})
        assert r.status_code == 200
        assert r.json()["code"] == 200


@pytest.mark.asyncio
class TestPatientCharge:
    async def test_charge_list_patient(self, async_client, seed_data, auth_headers):
        r = await async_client.get("/api/chargeManagement/getList", headers=auth_headers(seed_data["patient_user"].username))
        assert r.status_code == 200
        body = r.json()
        assert body["code"] == 200
        assert len(body["data"]) >= 1

    async def test_charge_commit(self, async_client, seed_data, auth_headers):
        charge = seed_data["charge"]
        r = await async_client.post("/api/chargeManagement/charge", headers=auth_headers(seed_data["cashier_user"].username), json={"id": str(charge.charge_id)})
        assert r.status_code == 200
        assert r.json()["code"] == 200

        # verify status changed
        r = await async_client.get("/api/chargeManagement/getList", headers=auth_headers(seed_data["patient_user"].username))
        for item in r.json()["data"]:
            if item["id"] == str(charge.charge_id):
                assert item["status"] == 1


@pytest.mark.asyncio
class TestPatientMedicalRecord:
    async def test_get_medical_record_list(self, async_client, seed_data, auth_headers):
        r = await async_client.get("/api/medicalRecord/getList", headers=auth_headers(seed_data["patient_user"].username))
        assert r.status_code == 200
        body = r.json()
        assert body["code"] == 200
        assert len(body["data"]) >= 1
        assert "doctor_name" in body["data"][0]

    async def test_get_medical_record_detail(self, async_client, seed_data, auth_headers):
        mr = seed_data["medical_record"]
        r = await async_client.post("/api/medicalRecord/detail", headers=auth_headers(seed_data["patient_user"].username), json={"medical_record_id": str(mr.medical_record_id)})
        assert r.status_code == 200
        body = r.json()
        assert body["code"] == 200
        assert body["data"]["symptom"] == "头痛发热"


@pytest.mark.asyncio
class TestPatientHealthRecord:
    async def test_get_profile(self, async_client, seed_data, auth_headers):
        r = await async_client.get("/api/healthRecord/getProfile", headers=auth_headers(seed_data["patient_user"].username))
        assert r.status_code == 200
        body = r.json()
        assert body["code"] == 200
        assert body["data"]["name"] == seed_data["patient"].name

    async def test_get_visits(self, async_client, seed_data, auth_headers):
        r = await async_client.get("/api/healthRecord/getVisits", headers=auth_headers(seed_data["patient_user"].username))
        assert r.status_code == 200
        body = r.json()
        assert body["code"] == 200
        assert len(body["data"]) >= 1


@pytest.mark.asyncio
class TestPatientPrescription:
    async def test_get_prescription_list(self, async_client, seed_data, auth_headers):
        r = await async_client.get("/api/prescriptionManagement/getList", headers=auth_headers(seed_data["patient_user"].username))
        assert r.status_code == 200
        body = r.json()
        assert body["code"] == 200
        assert len(body["data"]) >= 1


@pytest.mark.asyncio
class TestPatientReview:
    async def test_create_review(self, async_client, seed_data, auth_headers):
        r = await async_client.post("/api/review/create", headers=auth_headers(seed_data["patient_user"].username), json={
            "doctor_id": seed_data["doctor"].doctor_id,
            "visit_id": str(seed_data["medical_record"].medical_record_id),
            "score": 5, "comment": "医生很专业"
        })
        assert r.status_code == 200
        assert r.json()["code"] == 200
