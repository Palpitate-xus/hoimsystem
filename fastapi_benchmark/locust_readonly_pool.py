"""HOIM System 只读性能测试（运行时 token 池）。"""

import os
import random

from benchmark_auth import load_tokens_or_stop
from benchmark_http import mark_business_result
from benchmark_metadata import register_metadata_hooks
from locust import HttpUser, between, events, task

ADMIN_CREDENTIALS = {
    "admin": ((os.getenv("BENCHMARK_ADMIN_USERNAME", "admin"), os.getenv("BENCHMARK_ADMIN_PASSWORD", "admin123")),),
}
TOKEN_POOLS: dict[str, tuple[str, ...]] = {}

register_metadata_hooks(events)


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

    def _get(self, path, *, params=None):
        with self.client.get(
            path,
            headers=self._headers(),
            params=params,
            catch_response=True,
        ) as response:
            mark_business_result(response)

    def _paged_get(self, path):
        self._get(path, params={"page": 1, "page_size": 20})

    @task(20)
    def get_department_list(self):
        self._paged_get("/api/departmentManagement/getList")

    @task(15)
    def get_doctor_list(self):
        self._paged_get("/api/doctorManagement/getList")

    @task(12)
    def get_patient_list(self):
        self._paged_get("/api/patientManagement/getList")

    @task(10)
    def get_prescription_list(self):
        self._paged_get("/api/prescriptionManagement/getList")

    @task(8)
    def get_charge_list(self):
        self._paged_get("/api/chargeManagement/getList")

    @task(5)
    def get_medical_record_list(self):
        self._paged_get("/api/medicalRecord/getList")

    @task(3)
    def get_log_list(self):
        with self.client.post(
            "/api/log/getList",
            headers=self._headers(),
            json={"page": 1, "page_size": 20},
            catch_response=True,
        ) as response:
            mark_business_result(response)

    @task(2)
    def get_log_stats(self):
        self._get("/api/log/stats")
