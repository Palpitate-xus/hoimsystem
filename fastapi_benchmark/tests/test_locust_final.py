import sys
from collections import deque
from pathlib import Path
from types import SimpleNamespace

import pytest

BENCHMARK_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BENCHMARK_DIR))

import locust_final  # noqa: E402


class FakeLocustResponse:
    def __init__(self, status_code=200, body=None, json_error=None):
        self.status_code = status_code
        self.body = {"code": 200} if body is None else body
        self.json_error = json_error
        self.failure_message = None
        self.was_successful = False

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def json(self):
        if self.json_error:
            raise self.json_error
        return self.body

    def failure(self, message):
        self.failure_message = message

    def success(self):
        self.was_successful = True


class FakeClient:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.posts = []

    def post(self, path, **kwargs):
        self.posts.append((path, kwargs))
        return next(self.responses)


class FakeUser:
    def __init__(self, responses):
        self.client = FakeClient(responses)
        self.environment = SimpleNamespace(benchmark_measurement_id=None, benchmark_in_flight=0)

    def _headers(self, role="admin"):
        return locust_final.HOIMUser._headers(self, role)

    def _measurement_context(self):
        return locust_final.HOIMUser._measurement_context(self)


@pytest.mark.parametrize(
    "response, expected_message",
    [
        (FakeLocustResponse(500), "HTTP 500"),
        (FakeLocustResponse(body={"code": 500}), "business code 500"),
        (FakeLocustResponse(body=[]), "business code invalid"),
        (FakeLocustResponse(json_error=ValueError("bad json")), "non-JSON response"),
    ],
)
def test_mark_business_result_rejects_transport_and_business_failures(response, expected_message):
    assert locust_final.mark_business_result(response) is False
    assert response.failure_message == expected_message
    assert response.was_successful is False


def test_mark_business_result_accepts_only_business_success():
    response = FakeLocustResponse(body={"code": 200, "data": {}})

    assert locust_final.mark_business_result(response) is True
    assert response.failure_message is None
    assert response.was_successful is True


def test_write_tasks_use_role_valid_tokens(monkeypatch):
    monkeypatch.setattr(
        locust_final,
        "TOKEN_POOLS",
        {
            "admin": ("admin-token",),
            "doctor": ("doctor-token",),
            "patient": ("patient-token",),
        },
    )
    appointment_payload = {
        "id": 17,
        "date": "2026-09-07",
        "department_id": 3,
        "doctor_id": 5,
        "time": "01",
        "specialist": 1,
        "patient_id": 11,
    }
    monkeypatch.setattr(locust_final, "APPOINTMENT_TARGETS", deque([appointment_payload]))
    monkeypatch.setattr(locust_final, "APPOINTMENT_TOKENS", {11: "patient-token"})
    monkeypatch.setattr(locust_final, "PRESCRIPTION_PATIENT_IDS", (11,))
    monkeypatch.setattr(locust_final, "PRESCRIPTION_PHARMACEUTICAL_IDS", (23,))
    appointment_response = FakeLocustResponse()
    prescription_response = FakeLocustResponse()
    user = FakeUser([appointment_response, prescription_response])

    locust_final.HOIMUser.create_appointment(user)
    locust_final.HOIMUser.create_prescription(user)

    appointment = user.client.posts[0]
    prescription = user.client.posts[1]
    assert appointment[0] == "/api/appointmentManagement/create"
    assert appointment[1]["headers"] == {"accesstoken": "patient-token"}
    assert appointment[1]["json"] == appointment_payload
    assert appointment[1]["catch_response"] is True
    assert prescription[0] == "/api/prescriptionManagement/create"
    assert prescription[1]["headers"] == {"accesstoken": "doctor-token"}
    assert prescription[1]["json"] == {"patient": 11, "phas": [{"id": 23, "number": 1}]}
    assert prescription[1]["catch_response"] is True


def test_appointment_uses_the_target_household_token(monkeypatch):
    monkeypatch.setattr(locust_final, "TOKEN_POOLS", {"patient": ("unrelated-household",)})
    monkeypatch.setattr(locust_final, "APPOINTMENT_TARGETS", deque([{"patient_id": 27}]))
    monkeypatch.setattr(locust_final, "APPOINTMENT_TOKENS", {27: "authorized-household"})
    user = FakeUser([FakeLocustResponse()])
    locust_final.HOIMUser.create_appointment(user)
    assert user.client.posts[0][1]["headers"] == {"accesstoken": "authorized-household"}


def test_credentials_follow_bounded_households_and_allow_explicit_account(monkeypatch):
    monkeypatch.delenv("BENCHMARK_PATIENT_USERNAME", raising=False)
    monkeypatch.setenv("BENCHMARK_PROFILE", "large")
    credentials = locust_final.patient_credentials()
    assert len(credentials) == 64
    assert credentials[0][0] == "370101199001011234"
    assert len(set(username for username, _ in credentials)) == 64
    monkeypatch.setenv("BENCHMARK_PATIENT_USERNAME", "custom-patient")
    assert locust_final.patient_credentials() == (("custom-patient", "123456"),)


def test_write_measurement_is_captured_before_the_response_and_uses_a_timeout(monkeypatch):
    monkeypatch.setattr(locust_final, "TOKEN_POOLS", {"doctor": ("doctor",)})
    monkeypatch.setattr(locust_final, "PRESCRIPTION_PATIENT_IDS", (1,))
    monkeypatch.setattr(locust_final, "PRESCRIPTION_PHARMACEUTICAL_IDS", (2,))
    user = FakeUser([FakeLocustResponse()])
    user.environment.benchmark_measurement_id = "measured"

    def post(_path, **kwargs):
        assert user.environment.benchmark_in_flight == 1
        user.environment.benchmark_measurement_id = None
        assert kwargs["context"] == {"benchmark_measurement_id": "measured"}
        assert kwargs["timeout"] == 30
        return FakeLocustResponse()

    user.client.post = post
    locust_final.HOIMUser.create_prescription(user)


def test_exhausted_appointment_targets_stop_the_test_instead_of_changing_its_mix(monkeypatch):
    import gevent
    from locust.exception import StopUser

    stopped = []
    user = FakeUser([])
    user.environment.runner = SimpleNamespace(quit=lambda: stopped.append(True))
    monkeypatch.setattr(locust_final, "APPOINTMENT_TARGETS", deque())
    monkeypatch.setattr(gevent, "spawn", lambda callback: callback())
    with pytest.raises(StopUser):
        locust_final.HOIMUser.create_appointment(user)
    assert user.environment.process_exit_code == 4
    assert stopped == [True]
    assert user.client.posts == []
