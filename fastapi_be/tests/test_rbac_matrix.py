"""Exhaustive RBAC enforcement test.

For every protected endpoint that uses require_roles, verify:
- Required roles get 200/500 (not 401/403)
- Non-required roles get 403
- Unauthenticated request gets 401

We don't assert 200 because the endpoint may return 500 due to business logic
depending on state; we only verify that the auth layer lets them through.
"""
import pytest
import pytest_asyncio

ENDPOINTS = [
    # (method, path, required_roles, body, query_params)
    # admin.py
    # getDoctorList/getPatientList/getDepartmentList/getNoticeList: auth-any
    # (patients need to browse doctors/departments for registration)
    ("GET", "/api/doctorManagement/getList", {"admin", "super_admin", "director", "doctor", "nurse", "cashier", "pharmacist", "guide", "patient", "lab_technician", "registrar"}, None, {}),
    ("POST", "/api/doctorManagement/delete", {"admin", "super_admin"}, {"doctor_id": 1}, {}),
    ("GET", "/api/patientManagement/getList", {"admin", "super_admin", "director", "doctor", "nurse", "cashier", "pharmacist", "guide", "patient", "lab_technician", "registrar"}, None, {}),
    ("GET", "/api/departmentManagement/getList", {"admin", "super_admin", "director", "doctor", "nurse", "cashier", "pharmacist", "guide", "patient", "lab_technician", "registrar"}, None, {}),
    ("POST", "/api/departmentManagement/create", {"admin", "super_admin"}, {"name": "外科", "phone": "01011112222", "location": "2号"}, {}),
    ("POST", "/api/notice/create", {"admin", "super_admin", "director"}, {"title": "t", "content": "c", "isemergency": 0, "towho": ["医生"], "expiredtime": "2026-12-31"}, {}),
    ("POST", "/api/notice/update", {"admin", "super_admin", "director"}, {"notice_id": "1", "title": "t", "content": "c", "isemergency": 0, "towho": ["医生"], "expiredtime": "2026-12-31"}, {}),
    ("POST", "/api/notice/delete", {"admin", "super_admin", "director"}, {"notice_id": "1"}, {}),

    # admission.py
    ("GET", "/api/admission/getList", {"admin", "super_admin", "nurse"}, None, {}),
    ("POST", "/api/admission/create", {"admin", "super_admin", "nurse"}, {"patient_id": 1, "department_id": 1, "admission_type": 0}, {}),

    # adverse_event.py
    ("POST", "/api/adverseEvent/create", {"admin", "super_admin"}, {"event_type": "跌倒", "patient_id": 1, "description": "x", "severity": 1}, {}),
    ("POST", "/api/adverseEvent/updateStatus", {"admin", "super_admin"}, {"event_id": 1, "status": 1}, {}),

    # adverse_reaction.py
    ("POST", "/api/adverseReaction/create", {"admin", "super_admin"}, {"patient_id": 1, "pharmaceutical_id": 1, "symptom": "x", "severity": 1}, {}),
    ("POST", "/api/adverseReaction/updateStatus", {"admin", "super_admin"}, {"reaction_id": 1, "status": 1}, {}),

    # backup.py
    ("POST", "/api/backup/create", {"admin", "super_admin"}, {}, {}),
    ("GET", "/api/backup/getList", {"admin", "super_admin"}, None, {}),
    ("POST", "/api/backup/delete", {"admin", "super_admin"}, {"filename": "x"}, {}),
    ("POST", "/api/backup/restore", {"admin", "super_admin"}, {"filename": "x"}, {}),

    # charge.py
    ("POST", "/api/chargeManagement/charge", {"admin", "super_admin", "cashier"}, {"id": "1"}, {}),
    ("POST", "/api/chargeManagement/refund", {"admin", "super_admin", "cashier"}, {"charge_id": "1", "reason": "x"}, {}),
    ("GET", "/api/invoice/getList", {"admin", "super_admin", "cashier"}, None, {}),
    ("POST", "/api/invoice/create", {"admin", "super_admin", "cashier"}, {"charge_id": "1"}, {}),
    ("POST", "/api/windowRegistration/create", {"admin", "super_admin", "cashier"}, {}, {}),
    ("POST", "/api/dailySettlement/report", {"admin", "super_admin", "cashier"}, {}, {}),
    ("POST", "/api/payment/mockNotify", {"admin", "super_admin", "cashier"}, {"payment_no": "PAY01"}, {}),
    ("GET", "/api/payment/getList", {"admin", "super_admin", "cashier"}, None, {}),

    # checkin.py (kiosk public)
    # clinical_pathway.py
    ("POST", "/api/clinicalPathway/create", {"admin", "super_admin", "director", "doctor"}, {"name": "path", "disease_code": "I10", "disease_name": "高", "steps": "[]", "expected_days": 7}, {}),

    # consumable.py
    ("POST", "/api/consumable/create", {"admin", "super_admin", "pharmacist"}, {"name": "针头", "category": "耗材", "stock": 100, "unit": "支", "price": 1.0, "supplier": "x", "remark": ""}, {}),
    ("POST", "/api/consumable/update", {"admin", "super_admin", "pharmacist"}, {"consumable_id": 1, "name": "针头"}, {}),
    ("POST", "/api/consumable/delete", {"admin", "super_admin", "pharmacist"}, {"consumable_id": 1}, {}),

    # discharge.py
    ("POST", "/api/discharge/doDischarge", {"admin", "super_admin", "nurse"}, {"admission_id": "1"}, {}),
    ("GET", "/api/discharge/getSummary", {"admin", "super_admin", "nurse"}, None, {"admission_id": "1"}),

    # doctor.py
    ("POST", "/api/doctorManagement/register", {"admin", "super_admin"}, {"username": "x1", "password": "p", "name": "n", "title": "t", "sex": "男", "phone": "1", "department": 1, "permission": "doctor", "education": "b"}, {}),
    ("POST", "/api/doctorScheduleManagement/register", {"admin", "super_admin"}, {"schedule": ["星期一01"], "specialist": 1, "number": 10, "doctor": 1}, {}),
    ("POST", "/api/pharmaceuticalManagement/create", {"admin", "super_admin", "pharmacist"}, {"name": "药", "stock": 10, "price": "1", "expireddate": "2028-01-01", "supplier": "s", "remark": "r"}, {}),
    ("POST", "/api/pharmaceuticalManagement/update", {"admin", "super_admin", "pharmacist"}, {"pharmaceutical_id": 1, "name": "药"}, {}),
    ("POST", "/api/pharmaceuticalManagement/delete", {"admin", "super_admin", "pharmacist"}, {"pharmaceutical_id": 1}, {}),
    ("POST", "/api/pharmaceuticalManagement/stock_query", {"admin", "super_admin", "pharmacist"}, {"id": 1}, {}),
    ("GET", "/api/pharmaceuticalManagement/lowStock", {"admin", "super_admin", "pharmacist"}, None, {}),
    ("GET", "/api/pharmaceuticalManagement/nearExpiry", {"admin", "super_admin", "pharmacist"}, None, {}),
    ("POST", "/api/prescriptionManagement/cancel", {"admin", "super_admin", "director", "doctor"}, {"prescription_id": "1"}, {}),
    ("POST", "/api/medicalRecord/update", {"admin", "super_admin", "director", "doctor"}, {"medical_record_id": "1", "symptom": "x", "result": "y"}, {}),
    ("GET", "/api/attendance/getList", {"admin", "super_admin", "director", "doctor"}, None, {}),
    ("POST", "/api/slotPool/adjust", {"admin", "super_admin"}, {"schedule_id": 1, "number": 10}, {}),

    # emr.py
    ("POST", "/api/emrTemplate/create", {"admin", "super_admin", "director", "doctor"}, {"name": "t", "category": "admission", "content": "x", "department_id": 1}, {}),
    ("POST", "/api/structuredMedicalRecord/create", {"admin", "super_admin", "director", "doctor"}, {"admission_id": "1", "patient_id": 1, "doctor_id": 1, "record_type": 0}, {}),

    # exam.py
    ("POST", "/api/examPackage/create", {"admin", "super_admin", "director", "doctor"}, {"name": "套餐", "category": "basic", "price": 100.0, "items": "x", "description": "d"}, {}),
    ("POST", "/api/examItem/create", {"admin", "super_admin", "director", "doctor"}, {"name": "item", "category": "basic", "unit": "次", "reference_range": "x", "price": 10}, {}),

    # followup.py
    ("POST", "/api/followUp/createPlan", {"admin", "super_admin", "director", "doctor"}, {"patient_id": 1, "plan_date": "2026-05-01", "content": "x"}, {}),

    # inpatient_charge.py (settle/refund require CASHISTER; nurse has separate access via ward)
    ("POST", "/api/inpatientCharge/settle", {"admin", "super_admin", "cashier"}, {"admission_id": "1"}, {}),
    ("POST", "/api/inpatientCharge/refund", {"admin", "super_admin", "cashier"}, {"admission_id": "1", "amount": 10}, {}),

    # inpatient_order.py
    ("POST", "/api/inpatientOrder/create", {"admin", "super_admin", "director", "doctor"}, {"patient_id": 1, "doctor_id": 1, "order_type": "long", "items": [{"name": "x", "dosage": "1", "frequency": "qd", "route": "po", "days": 3}]}, {}),
    ("POST", "/api/inpatientOrder/audit", {"admin", "super_admin", "director", "doctor"}, {"order_id": 1}, {}),
    ("POST", "/api/inpatientOrder/execute", {"admin", "super_admin", "nurse"}, {"order_id": 1, "nurse_id": 1}, {}),

    # lab.py
    ("POST", "/api/lab/sampleReceive", {"admin", "super_admin", "lab_technician"}, {"lab_order_id": "1"}, {}),
    ("POST", "/api/labResult/create", {"admin", "super_admin", "lab_technician"}, {"lab_order_id": "1", "sample_id": "s1", "result": "正常", "abnormal_flag": 0}, {}),
    ("POST", "/api/labResult/audit", {"admin", "super_admin", "lab_technician"}, {"lab_result_id": 1}, {}),

    # mdt.py
    ("POST", "/api/mdt/create", {"admin", "super_admin", "director", "doctor"}, {"patient_id": 1, "title": "x", "participants": [1], "plan_date": "2026-05-01"}, {}),
    ("POST", "/api/mdt/update", {"admin", "super_admin", "director", "doctor"}, {"mdt_id": 1, "result": "x"}, {}),

    # nursing.py
    ("POST", "/api/nursingRecord/delete", {"admin", "super_admin", "nurse"}, {"record_id": 1}, {}),
    ("POST", "/api/temperatureRecord/create", {"admin", "super_admin", "nurse"}, {"admission_id": "1", "patient_id": 1, "record_date": "2026-01-01", "time_point": "08:00", "temperature": 36.5}, {}),
    ("POST", "/api/temperatureRecord/delete", {"admin", "super_admin", "nurse"}, {"temp_id": 1}, {}),

    # pharmacy.py
    ("POST", "/api/pharmacy/audit", {"admin", "super_admin", "pharmacist"}, {"prescription_id": "1"}, {}),
    ("POST", "/api/pharmacy/dispense", {"admin", "super_admin", "pharmacist"}, {"prescription_id": "1"}, {}),
    ("POST", "/api/pharmacy/return", {"admin", "super_admin", "pharmacist"}, {"prescription_id": "1", "pha_id": 1, "number": 1}, {}),
    ("POST", "/api/pharmacy/stockCheck", {"admin", "super_admin", "pharmacist"}, {"items": [{"pharmaceutical_id": 1, "actual_stock": 10}]}, {}),
    ("POST", "/api/pharmacy/review", {"admin", "super_admin", "pharmacist"}, {"prescription_id": "1", "score": 90, "comment": "ok"}, {}),
    ("GET", "/api/pharmacy/dispenseList", {"admin", "super_admin", "pharmacist"}, None, {}),
    ("GET", "/api/pharmacy/reviewList", {"admin", "super_admin", "pharmacist"}, None, {}),

    # purchase.py (getList is auth-only, not admin-only — pharmacist/cashier may view)
    ("GET", "/api/purchase/getList", {"admin", "super_admin", "director", "doctor", "nurse", "cashier", "pharmacist", "guide", "patient", "lab_technician", "registrar"}, None, {"status": 0}),
    ("POST", "/api/purchase/approve", {"admin", "super_admin"}, {"purchase_id": 1}, {}),
    ("POST", "/api/purchase/create", {"admin", "super_admin"}, {"items": [{"pharmaceutical_id": 1, "quantity": 10, "price": 15.5}], "supplier": "x"}, {}),
    ("POST", "/api/purchase/cancel", {"admin", "super_admin"}, {"purchase_id": 1}, {}),

    # queue.py (getList requires any auth; mutations require CLINICAL)
    ("GET", "/api/queue/getList", {"admin", "super_admin", "director", "doctor", "nurse", "cashier", "pharmacist", "guide", "patient", "lab_technician", "registrar"}, None, {}),

    # referral.py
    ("POST", "/api/referral/create", {"admin", "super_admin", "director", "doctor"}, {"patient_id": 1, "target_hospital": "x", "target_department": "y", "referral_type": "out"}, {}),
    ("POST", "/api/referral/updateStatus", {"admin", "super_admin", "director", "doctor"}, {"referral_id": 1, "status": 1}, {}),

    # report.py
    ("POST", "/api/report/outpatientVolume", {"admin", "super_admin", "director", "doctor", "cashier"}, {"start_date": "2026-01-01", "end_date": "2026-12-31"}, {}),
    ("POST", "/api/report/finance", {"admin", "super_admin", "director", "doctor", "cashier"}, {"start_date": "2026-01-01", "end_date": "2026-12-31"}, {}),

    # surgery.py
    ("POST", "/api/surgeryApplication/create", {"admin", "super_admin", "director", "doctor"}, {"patient_id": 1, "doctor_id": 1, "surgery_name": "x", "surgery_date": "2026-06-01", "surgery_type": "elective", "anesthesia_type": "general"}, {}),
    ("POST", "/api/surgerySchedule/create", {"admin", "super_admin", "director", "doctor"}, {"application_id": 1, "surgeon_id": 1, "anesthesiologist_id": 1, "surgery_date": "2026-06-01", "room": "room1"}, {}),
    ("POST", "/api/anesthesiaRecord/create", {"admin", "super_admin", "director", "doctor"}, {"schedule_id": 1, "patient_id": 1}, {}),

    # system.py
    ("POST", "/api/log/getList", {"admin", "super_admin"}, {"page": 1, "page_size": 10}, {}),
    ("POST", "/api/dict/create", {"admin", "super_admin"}, {"dict_type": "x", "dict_code": "x", "dict_value": "x", "sort_order": 1}, {}),
    ("POST", "/api/config/update", {"admin", "super_admin"}, {"config_key": "x", "config_value": "x"}, {}),
    ("POST", "/api/message/send", {"admin", "super_admin"}, {"recipient_id": 1, "title": "x", "content": "c"}, {}),

    # upload.py — static file serving, publicly accessible (file-level permissions should still apply via auth)

    # vitalsign.py
    ("POST", "/api/vitalSign/create", {"admin", "super_admin", "nurse"}, {"patient_id": 1, "temperature": 36.5, "blood_pressure_systolic": 120, "blood_pressure_diastolic": 80, "pulse": 75, "weight": 70}, {}),

    # ward.py
    ("POST", "/api/ward/create", {"admin", "super_admin", "nurse"}, {"name": "外科病区", "department_id": 1, "bed_count": 30}, {}),
]


def role_to_fixture_name(role):
    mapping = {
        "admin": "admin_user",
        "super_admin": "super_admin_user",
        "director": "director_user",
        "doctor": "doctor_user",
        "nurse": "nurse_user",
        "cashier": "cashier_user",
        "pharmacist": "pharmacist_user",
        "guide": "guide_user",
        "lab_technician": "lab_tech_user",
        "registrar": "registrar_user",
    }
    return mapping.get(role)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "method,path,required_roles,body,query_params",
    ENDPOINTS,
    ids=[f"{m} {p}" for m, p, _, _, _ in ENDPOINTS],
)
class TestRBACEnforcement:
    async def test_unauthenticated_gets_401(self, async_client, method, path, required_roles, body, query_params):
        """Unauthenticated request should get 401 for truly protected routes."""
        if method == "GET":
            r = await async_client.get(path, params=query_params)
        elif method == "POST":
            r = await async_client.post(path, json=body, params=query_params)
        else:
            r = await async_client.request(method, path, json=body, params=query_params)
        # 401 or 404(文件不存在)均表示没有处理请求;只有 200/500 才算"通过认证"
        assert r.status_code in (401, 403) or (method == "GET" and r.status_code == 404 and "/uploads/" in path), (
            f"Unauthenticated {method} {path} got {r.status_code}, expected 401 (or 404 for static files)"
        )

    async def test_required_roles_get_through(self, async_client, seed_data, auth_headers, method, path, required_roles, body, query_params):
        """Each role in required_roles should get 200/500 (NOT 401/403)."""
        for role in required_roles:
            user_fixture = role_to_fixture_name(role)
            if user_fixture not in seed_data:
                continue
            hdrs = auth_headers(seed_data[user_fixture].username)
            if method == "GET":
                r = await async_client.get(path, params=query_params, headers=hdrs)
            elif method == "POST":
                r = await async_client.post(path, json=body, params=query_params, headers=hdrs)
            else:
                r = await async_client.request(method, path, json=body, params=query_params, headers=hdrs)
            reject_reasons = {401, 403}
            assert r.status_code not in reject_reasons, (
                f"Required role `{role}` blocked from {method} {path}: HTTP {r.status_code} {r.text[:100]}"
            )

    async def test_unauthorized_roles_get_403(self, async_client, seed_data, auth_headers, method, path, required_roles, body, query_params):
        """Roles NOT in required_roles should get 403."""
        all_roles = ["admin", "super_admin", "director", "doctor", "nurse", "cashier",
                     "pharmacist", "guide", "patient", "lab_technician", "registrar"]
        unauthorized = [r for r in all_roles if r not in required_roles]
        for role in unauthorized:
            user_fixture = role_to_fixture_name(role)
            if user_fixture not in seed_data:
                continue
            hdrs = auth_headers(seed_data[user_fixture].username)
            if method == "GET":
                r = await async_client.get(path, params=query_params, headers=hdrs)
            elif method == "POST":
                r = await async_client.post(path, json=body, params=query_params, headers=hdrs)
            else:
                r = await async_client.request(method, path, json=body, params=query_params, headers=hdrs)
            assert r.status_code == 403, (
                f"Unauthorized role `{role}` allowed to {method} {path}: HTTP {r.status_code}"
            )
