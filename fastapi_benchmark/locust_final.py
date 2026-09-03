"""HOIM System 最终性能测试。"""

import os
import random

from benchmark_auth import load_tokens_or_stop
from locust import HttpUser, between, events, task

BENCHMARK_CREDENTIALS = {
    "admin": ((os.getenv("BENCHMARK_ADMIN_USERNAME", "admin"), os.getenv("BENCHMARK_ADMIN_PASSWORD", "admin123")),),
    "doctor": ((os.getenv("BENCHMARK_DOCTOR_USERNAME", "doc01"), os.getenv("BENCHMARK_DOCTOR_PASSWORD", "123456")),),
    "patient": (
        (
            os.getenv("BENCHMARK_PATIENT_USERNAME", "370101199001011234"),
            os.getenv("BENCHMARK_PATIENT_PASSWORD", "123456"),
        ),
    ),
}
TOKEN_POOLS: dict[str, tuple[str, ...]] = {}


@events.test_start.add_listener
def prepare_runtime_tokens(environment, **_kwargs):
    """Refresh tokens at the beginning of every local or worker test run."""
    TOKEN_POOLS.clear()
    TOKEN_POOLS.update(load_tokens_or_stop(environment, BENCHMARK_CREDENTIALS))


def mark_business_result(response) -> bool:
    """Count only successful HTTP responses with the API's success code."""
    if not 200 <= response.status_code < 300:
        response.failure(f"HTTP {response.status_code}")
        return False
    try:
        body = response.json()
    except (TypeError, ValueError):
        response.failure("non-JSON response")
        return False
    if not isinstance(body, dict) or body.get("code") != 200:
        code = body.get("code") if isinstance(body, dict) else "invalid"
        response.failure(f"business code {code}")
        return False
    response.success()
    return True


class HOIMUser(HttpUser):
    """混合读写操作性能测试。"""

    wait_time = between(0.2, 0.8)

    def _headers(self, role="admin"):
        return {"accesstoken": random.choice(TOKEN_POOLS[role])}

    @task(20)
    def get_department_list(self):
        self.client.get("/api/departmentManagement/getList", headers=self._headers())

    @task(15)
    def get_doctor_list(self):
        self.client.get("/api/doctorManagement/getList", headers=self._headers())

    @task(12)
    def get_patient_list(self):
        self.client.get("/api/patientManagement/getList", headers=self._headers())

    @task(10)
    def get_prescription_list(self):
        self.client.get("/api/prescriptionManagement/getList", headers=self._headers())

    @task(8)
    def get_charge_list(self):
        self.client.get("/api/chargeManagement/getList", headers=self._headers())

    @task(5)
    def get_medical_record_list(self):
        self.client.get("/api/medicalRecord/getList", headers=self._headers())

    @task(3)
    def get_log_list(self):
        self.client.post("/api/log/getList", headers=self._headers(), json={"page": 1, "page_size": 20})

    @task(2)
    def get_log_stats(self):
        self.client.get("/api/log/stats", headers=self._headers())

    @task(2)
    def create_appointment(self):
        with self.client.post(
            "/api/appointmentManagement/create",
            headers=self._headers("patient"),
            json={
                "id": random.randint(1, 12),
                "date": "2026-07-15",
                "department_id": 1,
                "doctor_id": 1,
                "time": "上午",
                "specialist": 1,
            },
            catch_response=True,
        ) as response:
            mark_business_result(response)

    @task(1)
    def create_prescription(self):
        with self.client.post(
            "/api/prescriptionManagement/create",
            headers=self._headers("doctor"),
            json={
                "patient": 1,
                "phas": [{"id": 1, "number": 1}],
            },
            catch_response=True,
        ) as response:
            mark_business_result(response)
