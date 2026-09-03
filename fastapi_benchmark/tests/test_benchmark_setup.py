import sys
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import urlsplit

BENCHMARK_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BENCHMARK_DIR))

import benchmark_setup


class FakeResponse:
    status_code = 200

    def __init__(self, data):
        self.data = data

    def json(self):
        return {"code": 200, "data": self.data}


class FakeSession:
    def __init__(self, responses):
        self.responses = responses
        self.requests = []

    def get(self, url, **kwargs):
        path = urlsplit(url).path
        self.requests.append((path, kwargs))
        return FakeResponse(self.responses[path])


def test_discover_write_targets_uses_consistent_schedules_and_live_ids():
    future_expiry = (date.today() + timedelta(days=365)).isoformat()
    schedules = [
        {"id": 10, "date": "2026-09-07", "doctor_id": 1, "department_id": 4, "specialist": 1, "time": "01", "stock": 50},
        {"id": 11, "date": "2026-09-07", "doctor_id": 1, "department_id": 4, "specialist": 1, "time": "02", "stock": 50},
        {"id": 12, "date": "2026-09-08", "doctor_id": 2, "department_id": 5, "specialist": 1, "time": "01", "stock": 50},
    ]
    session = FakeSession(
        {
            "/api/appointmentManagement/appointmentList": schedules,
            "/api/patientManagement/getList": [{"id": 1}],
            "/api/familyMember/list": [{"patient_id": 2}, {"patient_id": 3}],
            "/api/pharmaceuticalManagement/getList": [
                {"id": 20, "status": 0, "stock": 100, "expireddate": future_expiry},
                {"id": 21, "status": 1, "stock": 100, "expireddate": future_expiry},
            ],
        }
    )

    targets = benchmark_setup.discover_write_targets(
        "http://benchmark.test",
        {"patient": ("patient-token",), "doctor": ("doctor-token",)},
        session=session,
    )

    assert targets.patient_ids == (1, 2, 3)
    assert targets.pharmaceutical_ids == (20,)
    assert len(targets.appointment_payloads) == 6
    unique_business_keys = {(item["patient_id"], item["doctor_id"], item["date"], item["specialist"]) for item in targets.appointment_payloads}
    assert len(unique_business_keys) == len(targets.appointment_payloads)
    schedule_by_id = {item["id"]: item for item in schedules}
    for payload in targets.appointment_payloads:
        source = schedule_by_id[payload["id"]]
        assert payload["date"] == source["date"]
        assert payload["doctor_id"] == source["doctor_id"]
        assert payload["department_id"] == source["department_id"]
        assert payload["specialist"] == source["specialist"]
        assert payload["time"] == source["time"]

    request_headers = {path: kwargs["headers"] for path, kwargs in session.requests}
    assert request_headers["/api/familyMember/list"] == {"accesstoken": "patient-token"}
    assert request_headers["/api/pharmaceuticalManagement/getList"] == {"accesstoken": "doctor-token"}
