"""HOIM System 只读性能测试（运行时 token 池）。"""

import os
import random

from benchmark_auth import load_tokens_or_stop
from locust import HttpUser, between, events, task

ADMIN_CREDENTIALS = {
    "admin": ((os.getenv("BENCHMARK_ADMIN_USERNAME", "admin"), os.getenv("BENCHMARK_ADMIN_PASSWORD", "admin123")),),
}
TOKEN_POOLS: dict[str, tuple[str, ...]] = {}


@events.test_start.add_listener
def prepare_runtime_tokens(environment, **_kwargs):
    """Refresh tokens at the beginning of every local or worker test run."""
    TOKEN_POOLS.clear()
    TOKEN_POOLS.update(load_tokens_or_stop(environment, ADMIN_CREDENTIALS))


class HOIMReadOnlyPoolUser(HttpUser):
    """只读操作(无登录开销)。"""

    wait_time = between(0.1, 0.3)

    def _headers(self):
        return {"accesstoken": random.choice(TOKEN_POOLS["admin"])}

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
