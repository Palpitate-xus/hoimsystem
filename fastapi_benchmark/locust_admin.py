"""HOIM System administrator benchmark scenario."""

import os
import random

from benchmark_auth import load_tokens_or_stop
from benchmark_http import mark_business_result
from locust import HttpUser, between, events, task

ADMIN_CREDENTIALS = {
    "admin": ((os.getenv("BENCHMARK_ADMIN_USERNAME", "admin"), os.getenv("BENCHMARK_ADMIN_PASSWORD", "admin123")),),
}
TOKEN_POOLS: dict[str, tuple[str, ...]] = {}


@events.test_start.add_listener
def prepare_runtime_tokens(environment, **_kwargs):
    """Refresh the administrator token for every test run."""
    TOKEN_POOLS.clear()
    TOKEN_POOLS.update(load_tokens_or_stop(environment, ADMIN_CREDENTIALS))


class HOIMAdminUser(HttpUser):
    """Simulate administrator reads and department creation."""

    wait_time = between(0.5, 1.5)

    def _headers(self):
        return {"accesstoken": random.choice(TOKEN_POOLS["admin"])}

    @task(15)
    def get_department_list(self):
        self.client.get("/api/departmentManagement/getList", headers=self._headers())

    @task(12)
    def get_doctor_list(self):
        self.client.get("/api/doctorManagement/getList", headers=self._headers())

    @task(10)
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

    @task(1)
    def create_department(self):
        with self.client.post(
            "/api/departmentManagement/create",
            headers=self._headers(),
            json={
                "name": f"BenchDept{random.randint(1, 99999)}",
                "phone": f"010{random.randint(10000000, 99999999)}",
                "location": "Bench",
            },
            catch_response=True,
        ) as response:
            mark_business_result(response)
