"""HOIM System 最终性能测试。"""

import os
import random
from collections import deque

from benchmark_auth import load_tokens_or_stop
from benchmark_http import mark_business_result
from benchmark_metadata import register_metadata_hooks
from benchmark_profiles import PROFILES, patient_identity, portal_owner_offsets
from benchmark_setup import load_write_targets_or_stop
from locust import HttpUser, between, events, task
from locust.exception import StopUser


def patient_credentials():
    password = os.getenv("BENCHMARK_PATIENT_PASSWORD", "123456")
    if os.getenv("BENCHMARK_PATIENT_USERNAME"):
        return ((os.environ["BENCHMARK_PATIENT_USERNAME"], password),)
    profile = PROFILES[os.getenv("BENCHMARK_PROFILE", "smoke")]
    return tuple((patient_identity(offset), password) for offset in portal_owner_offsets(profile))


BENCHMARK_CREDENTIALS = {
    "admin": ((os.getenv("BENCHMARK_ADMIN_USERNAME", "admin"), os.getenv("BENCHMARK_ADMIN_PASSWORD", "admin123")),),
    "doctor": ((os.getenv("BENCHMARK_DOCTOR_USERNAME", "doc01"), os.getenv("BENCHMARK_DOCTOR_PASSWORD", "123456")),),
    "patient": patient_credentials(),
}
TOKEN_POOLS: dict[str, tuple[str, ...]] = {}
APPOINTMENT_TARGETS: deque[dict] = deque()
APPOINTMENT_TOKENS: dict[int, str] = {}
PRESCRIPTION_PATIENT_IDS: tuple[int, ...] = ()
PRESCRIPTION_PHARMACEUTICAL_IDS: tuple[int, ...] = ()

register_metadata_hooks(events)


@events.test_start.add_listener
def prepare_runtime_tokens(environment, **_kwargs):
    """Refresh tokens at the beginning of every local or worker test run."""
    global PRESCRIPTION_PATIENT_IDS, PRESCRIPTION_PHARMACEUTICAL_IDS

    TOKEN_POOLS.clear()
    TOKEN_POOLS.update(load_tokens_or_stop(environment, BENCHMARK_CREDENTIALS))
    APPOINTMENT_TARGETS.clear()
    APPOINTMENT_TOKENS.clear()
    PRESCRIPTION_PATIENT_IDS = ()
    PRESCRIPTION_PHARMACEUTICAL_IDS = ()
    if not TOKEN_POOLS:  # Distributed master; workers discover their own targets.
        return
    targets = load_write_targets_or_stop(environment, TOKEN_POOLS)
    appointment_payloads = list(targets.appointment_payloads)
    random.shuffle(appointment_payloads)
    APPOINTMENT_TARGETS.extend(appointment_payloads)
    APPOINTMENT_TOKENS.update(targets.appointment_tokens)
    PRESCRIPTION_PATIENT_IDS = targets.patient_ids
    PRESCRIPTION_PHARMACEUTICAL_IDS = targets.pharmaceutical_ids


class HOIMUser(HttpUser):
    """混合读写操作性能测试。"""

    wait_time = between(0.2, 0.8)

    def _measurement_context(self):
        measurement = getattr(self.environment, "benchmark_measurement_id", None)
        if measurement:
            self.environment.benchmark_in_flight += 1
        return {"benchmark_measurement_id": measurement}

    def _headers(self, role="admin"):
        return {"accesstoken": random.choice(TOKEN_POOLS[role])}

    def _get(self, path, *, role="admin", params=None):
        with self.client.get(
            path,
            headers=self._headers(role),
            params=params,
            catch_response=True,
            timeout=30,
            context=self._measurement_context(),
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
            timeout=30,
            context=self._measurement_context(),
        ) as response:
            mark_business_result(response)

    @task(2)
    def get_log_stats(self):
        self._get("/api/log/stats")

    @task(2)
    def create_appointment(self):
        try:
            payload = APPOINTMENT_TARGETS.popleft()
        except IndexError:
            # Exhaustion invalidates the configured read/write mixture.
            import gevent

            self.environment.process_exit_code = 4
            gevent.spawn(self.environment.runner.quit)
            raise StopUser() from None
        with self.client.post(
            "/api/appointmentManagement/create",
            headers={"accesstoken": APPOINTMENT_TOKENS[payload["patient_id"]]},
            json=payload,
            catch_response=True,
            timeout=30,
            context=self._measurement_context(),
        ) as response:
            mark_business_result(response)

    @task(1)
    def create_prescription(self):
        with self.client.post(
            "/api/prescriptionManagement/create",
            headers=self._headers("doctor"),
            json={
                "patient": random.choice(PRESCRIPTION_PATIENT_IDS),
                "phas": [{"id": random.choice(PRESCRIPTION_PHARMACEUTICAL_IDS), "number": 1}],
            },
            catch_response=True,
            timeout=30,
            context=self._measurement_context(),
        ) as response:
            mark_business_result(response)
