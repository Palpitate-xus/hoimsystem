import datetime

import pytest

from app.models import Appointment, DoctorSchedule, Registration


@pytest.mark.asyncio
class TestPatientAppointment:
    async def test_appointment_list(self, async_client, seed_data, auth_headers):
        r = await async_client.get("/api/appointmentManagement/appointmentList", headers=auth_headers(seed_data["patient_user"].username))
        assert r.status_code == 200
        assert r.json()["code"] == 200, r.text

    async def test_create_and_get_appointment(self, async_client, seed_data, auth_headers, db_session):
        patient_user = seed_data["patient_user"]
        headers = auth_headers(patient_user.username)
        schedule = db_session.query(DoctorSchedule).filter(
            DoctorSchedule.doctor_id == seed_data["doctor"].doctor_id,
            DoctorSchedule.specialist == 1,
        ).first()
        # create appointment using the current fixture's schedule
        r = await async_client.post("/api/appointmentManagement/create", headers=headers, json={
            "id": schedule.schedule_id, "date": "2026-05-01", "department_id": seed_data["department"].department_id,
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

    async def test_appointment_rejects_invalid_schedule_and_mismatched_doctor(self, async_client, seed_data, auth_headers, db_session):
        headers = auth_headers(seed_data["patient_user"].username)
        invalid = await async_client.post("/api/appointmentManagement/create", headers=headers, json={
            "id": 999999, "date": "2026-12-01", "department_id": seed_data["department"].department_id,
            "doctor_id": seed_data["doctor"].doctor_id, "time": "上午", "specialist": 1
        })
        assert invalid.status_code == 200
        assert invalid.json()["code"] == 500

        mismatched = await async_client.post("/api/appointmentManagement/create", headers=headers, json={
            "id": 1, "date": "2026-12-01", "department_id": seed_data["department"].department_id,
            "doctor_id": seed_data["director_doctor"].doctor_id, "time": "上午", "specialist": 1
        })
        assert mismatched.status_code == 200
        assert mismatched.json()["code"] == 500

        schedule = db_session.query(DoctorSchedule).filter(DoctorSchedule.doctor_id == seed_data["doctor"].doctor_id).first()
        wrong_department = await async_client.post("/api/appointmentManagement/create", headers=headers, json={
            "id": schedule.schedule_id, "date": "2026-12-01", "department_id": 999999,
            "doctor_id": seed_data["doctor"].doctor_id, "time": "上午", "specialist": 1
        })
        assert wrong_department.status_code == 200
        assert wrong_department.json() == {"code": 500, "msg": "预约科室与排班不匹配"}

    async def test_checked_in_appointment_cannot_be_cancelled(self, async_client, seed_data, auth_headers, db_session):
        appointment = Appointment(
            patient_id=seed_data["patient"].patient_id,
            doctor_id=seed_data["doctor"].doctor_id,
            specialist=1,
            department_id=seed_data["department"].department_id,
            prefer_time="上午",
            appointment_time=datetime.datetime.now(),
            time=datetime.date.today(),
            status=1,
        )
        db_session.add(appointment)
        db_session.commit()
        r = await async_client.post(
            "/api/appointmentManagement/cancel",
            headers=auth_headers(seed_data["patient_user"].username),
            json={"uuid": appointment.registration_uuid},
        )
        assert r.status_code == 200
        assert r.json() == {"code": 500, "msg": "预约已报到或已就诊，不能取消"}

    async def test_appointment_cancel_returns_source_schedule(self, async_client, seed_data, auth_headers, db_session):
        doctor = seed_data["director_doctor"]
        source = DoctorSchedule(week="星期六", time="03", number=1, specialist=1, doctor_id=doctor.doctor_id)
        other = DoctorSchedule(week="星期日", time="03", number=7, specialist=1, doctor_id=doctor.doctor_id)
        db_session.add_all([source, other])
        db_session.commit()
        headers = auth_headers(seed_data["patient_user"].username)
        created = await async_client.post(
            "/api/appointmentManagement/create",
            headers=headers,
            json={"id": source.schedule_id, "date": "2027-01-01", "department_id": seed_data["department"].department_id, "doctor_id": doctor.doctor_id, "time": "上午", "specialist": 1},
        )
        assert created.json()["code"] == 200
        listed = await async_client.get("/api/appointmentManagement/getList", headers=headers)
        appointment_uuid = next(item["uuid"] for item in listed.json()["data"] if item["doctor"] == doctor.name and item["status"] == "未就诊")
        cancelled = await async_client.post("/api/appointmentManagement/cancel", headers=headers, json={"uuid": appointment_uuid})
        assert cancelled.json()["code"] == 200
        db_session.expire_all()
        assert db_session.get(DoctorSchedule, source.schedule_id).number == 1
        assert db_session.get(DoctorSchedule, other.schedule_id).number == 7


@pytest.mark.asyncio
class TestPatientRegistration:
    async def test_registration_list(self, async_client, seed_data, auth_headers):
        r = await async_client.get("/api/registrationManagement/registrationList", headers=auth_headers(seed_data["patient_user"].username))
        assert r.status_code == 200
        assert r.json()["code"] == 200

    async def test_create_and_get_registration(self, async_client, seed_data, auth_headers, db_session):
        patient_user = seed_data["patient_user"]
        headers = auth_headers(patient_user.username)
        doctor2 = seed_data["director_doctor"]
        schedule = DoctorSchedule(week="星期三", time="01", number=20, specialist=1, doctor_id=doctor2.doctor_id)
        db_session.add(schedule)
        db_session.commit()
        r = await async_client.post("/api/registrationManagement/create", headers=headers, json={
            "id": schedule.schedule_id, "doctor_id": doctor2.doctor_id,
            "department_id": seed_data["department"].department_id, "specialist": 1
        })
        assert r.status_code == 200
        assert r.json()["code"] == 200

        r = await async_client.get("/api/registrationManagement/getList", headers=headers)
        assert r.status_code == 200
        body = r.json()
        assert body["code"] == 200
        target_regs = [reg for reg in body["data"] if reg.get("doctor") == "李主任" and reg.get("status") != "已取消"]
        if not target_regs:
            target_regs = [reg for reg in body["data"] if reg.get("status") != "已取消"]
        if not target_regs:
            pytest.skip("无有效挂号")
        reg_uuid = target_regs[0]["uuid"]
        r = await async_client.post("/api/registrationManagement/cancel", headers=headers, json={"uuid": reg_uuid, "schedule_id": schedule.schedule_id})
        assert r.status_code == 200
        assert r.json()["code"] == 200

    async def test_registration_requires_matching_schedule(self, async_client, seed_data, auth_headers):
        headers = auth_headers(seed_data["patient_user"].username)
        invalid = await async_client.post(
            "/api/registrationManagement/create",
            headers=headers,
            json={"id": 999999, "doctor_id": seed_data["doctor"].doctor_id, "department_id": seed_data["department"].department_id, "specialist": 1},
        )
        assert invalid.status_code == 200
        assert invalid.json() == {"code": 500, "msg": "排班不存在"}

        mismatch = await async_client.post(
            "/api/registrationManagement/create",
            headers=headers,
            json={"id": 1, "doctor_id": seed_data["director_doctor"].doctor_id, "department_id": seed_data["department"].department_id, "specialist": 1},
        )
        assert mismatch.status_code == 200
        assert mismatch.json() == {"code": 500, "msg": "挂号医生与排班不匹配"}

    async def test_registration_cancel_returns_source_schedule(self, async_client, seed_data, auth_headers, db_session):
        doctor = seed_data["director_doctor"]
        source = DoctorSchedule(week="星期四", time="01", number=1, specialist=1, doctor_id=doctor.doctor_id)
        other = DoctorSchedule(week="星期五", time="01", number=7, specialist=1, doctor_id=doctor.doctor_id)
        db_session.add_all([source, other])
        db_session.commit()
        response = await async_client.post(
            "/api/registrationManagement/create",
            headers=auth_headers(seed_data["patient_user"].username),
            json={"id": source.schedule_id, "doctor_id": doctor.doctor_id, "department_id": seed_data["department"].department_id, "specialist": 1},
        )
        assert response.json()["code"] == 200
        registration_uuid = response.json()["data"]["registration_uuid"]
        cancelled = await async_client.post(
            "/api/registrationManagement/cancel",
            headers=auth_headers(seed_data["patient_user"].username),
            json={"uuid": registration_uuid},
        )
        assert cancelled.json()["code"] == 200
        db_session.expire_all()
        assert db_session.get(DoctorSchedule, source.schedule_id).number == 1
        assert db_session.get(DoctorSchedule, other.schedule_id).number == 7

    async def test_visited_registration_cannot_be_cancelled(self, async_client, seed_data, auth_headers, db_session):
        registration = Registration(
            patient_id=seed_data["patient"].patient_id,
            doctor_id=seed_data["doctor"].doctor_id,
            specialist=1,
            department_id=seed_data["department"].department_id,
            time=datetime.datetime.now(),
            status=1,
        )
        db_session.add(registration)
        db_session.commit()
        r = await async_client.post(
            "/api/registrationManagement/cancel",
            headers=auth_headers(seed_data["patient_user"].username),
            json={"uuid": registration.registration_uuid, "schedule_id": 1},
        )
        assert r.status_code == 200
        assert r.json() == {"code": 500, "msg": "挂号已就诊，不能退号"}


@pytest.mark.asyncio
class TestFamilyMember:
    async def test_patient_can_create_list_update_and_delete_family_member(self, async_client, seed_data, auth_headers):
        headers = auth_headers(seed_data["patient_user"].username)
        created = await async_client.post(
            "/api/familyMember/create",
            headers=headers,
            json={
                "name": "张小三",
                "identity": "110101201001011234",
                "relation": "子女",
                "sex": 0,
                "birthday": "2010-01-01",
                "phone": "13900139002",
                "address": "北京朝阳",
            },
        )
        assert created.status_code == 200, created.text
        body = created.json()
        assert body["code"] == 200
        member_id = body["data"]["family_member_id"]
        assert body["data"]["identity"] == "110101201001011234"

        listed = await async_client.get("/api/familyMember/list", headers=headers)
        assert listed.status_code == 200
        assert [item["family_member_id"] for item in listed.json()["data"]] == [member_id]

        updated = await async_client.put(
            "/api/familyMember/update",
            headers=headers,
            json={
                "family_member_id": member_id,
                "name": "张小三",
                "identity": "110101201001011234",
                "relation": "女儿",
                "sex": 0,
                "birthday": "2010-01-01",
                "phone": "13900139003",
                "address": "北京海淀",
                "allergy_history": "青霉素",
            },
        )
        assert updated.status_code == 200
        assert updated.json()["data"]["relation"] == "女儿"
        assert updated.json()["data"]["allergy_history"] == "青霉素"

        deleted = await async_client.request("DELETE", "/api/familyMember/delete", headers=headers, json={"id": member_id})
        assert deleted.status_code == 200
        assert deleted.json()["code"] == 200
        assert (await async_client.get("/api/familyMember/list", headers=headers)).json()["data"] == []

    async def test_family_member_isolation_and_validation(self, async_client, seed_data, auth_headers):
        patient_headers = auth_headers(seed_data["patient_user"].username)
        other_headers = auth_headers(seed_data["patient2_user"].username)
        invalid = await async_client.post(
            "/api/familyMember/create",
            headers=patient_headers,
            json={"name": "无效", "identity": "bad", "relation": "亲属", "sex": 1},
        )
        assert invalid.status_code == 422

        created = await async_client.post(
            "/api/familyMember/create",
            headers=patient_headers,
            json={"name": "张小三", "identity": "110101201001011234", "relation": "子女", "sex": 0},
        )
        member_id = created.json()["data"]["family_member_id"]
        forbidden_list = await async_client.get("/api/familyMember/list", headers=auth_headers(seed_data["admin_user"].username))
        assert forbidden_list.status_code == 403
        forbidden_update = await async_client.put(
            "/api/familyMember/update",
            headers=other_headers,
            json={"family_member_id": member_id, "name": "越权", "identity": "110101201001011234", "relation": "亲属", "sex": 0},
        )
        assert forbidden_update.status_code == 404

    async def test_patient_can_book_for_linked_family_member(self, async_client, seed_data, auth_headers, db_session):
        headers = auth_headers(seed_data["patient_user"].username)
        created = await async_client.post(
            "/api/familyMember/create",
            headers=headers,
            json={"name": "张小四", "identity": "110101201001021234", "relation": "子女", "sex": 1},
        )
        member_id = created.json()["data"]["patient_id"]
        schedule = db_session.query(DoctorSchedule).filter(
            DoctorSchedule.doctor_id == seed_data["doctor"].doctor_id,
            DoctorSchedule.specialist == 1,
            DoctorSchedule.number > 0,
        ).first()

        appointment = await async_client.post(
            "/api/appointmentManagement/create",
            headers=headers,
            json={
                "id": schedule.schedule_id,
                "date": "2026-12-01",
                "department_id": seed_data["department"].department_id,
                "doctor_id": schedule.doctor_id,
                "time": schedule.time,
                "specialist": schedule.specialist,
                "patient_id": member_id,
            },
        )
        assert appointment.status_code == 200
        assert appointment.json()["code"] == 200
        appointment_list = await async_client.get("/api/appointmentManagement/getList", headers=headers)
        assert any(item["patient_id"] == member_id and item["patient_name"] == "张小四" for item in appointment_list.json()["data"])

        registration = await async_client.post(
            "/api/registrationManagement/create",
            headers=headers,
            json={
                "id": schedule.schedule_id,
                "doctor_id": schedule.doctor_id,
                "department_id": seed_data["department"].department_id,
                "specialist": schedule.specialist,
                "patient_id": member_id,
            },
        )
        assert registration.status_code == 200
        assert registration.json()["code"] == 200
        registration_list = await async_client.get("/api/registrationManagement/getList", headers=headers)
        assert any(item["patient_id"] == member_id and item["patient_name"] == "张小四" for item in registration_list.json()["data"])


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

    async def test_patient_cannot_view_other_patient_medical_record(self, async_client, seed_data, auth_headers):
        mr = seed_data["medical_record"]
        r = await async_client.post(
            "/api/medicalRecord/detail",
            headers=auth_headers(seed_data["patient2_user"].username),
            json={"medical_record_id": str(mr.medical_record_id)},
        )
        assert r.status_code == 200
        assert r.json()["code"] == 403


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

    async def test_create_review_rejects_other_patient_visit(self, async_client, seed_data, auth_headers):
        r = await async_client.post(
            "/api/review/create",
            headers=auth_headers(seed_data["patient2_user"].username),
            json={
                "doctor_id": seed_data["doctor"].doctor_id,
                "visit_id": str(seed_data["medical_record"].medical_record_id),
                "score": 5,
                "comment": "越权评价",
            },
        )
        assert r.status_code == 200
        assert r.json()["code"] == 403

    async def test_create_review_rejects_duplicate_visit_review(self, async_client, seed_data, auth_headers):
        headers = auth_headers(seed_data["patient_user"].username)
        payload = {
            "doctor_id": seed_data["doctor"].doctor_id,
            "visit_id": str(seed_data["medical_record"].medical_record_id),
            "score": 5,
            "comment": "重复评价测试",
        }
        first = await async_client.post("/api/review/create", headers=headers, json=payload)
        assert first.status_code == 200
        assert first.json()["code"] == 200
        second = await async_client.post("/api/review/create", headers=headers, json=payload)
        assert second.status_code == 200
        assert second.json()["code"] == 500
