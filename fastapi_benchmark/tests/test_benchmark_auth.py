import sys
import time
from pathlib import Path

import pytest
from locust.exception import StopTest

BENCHMARK_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BENCHMARK_DIR))

import benchmark_auth


class FakeResponse:
    def __init__(self, status_code, body):
        self.status_code = status_code
        self._body = body

    def json(self):
        return self._body


class FakeSession:
    def __init__(self, response):
        self.response = response
        self.requests = []

    def post(self, url, **kwargs):
        self.requests.append((url, kwargs))
        return self.response


def make_token(username, *, issued_at, expires_at):
    return benchmark_auth.jwt.encode(
        {"sub": username, "iat": issued_at, "exp": expires_at},
        "test-key-with-at-least-thirty-two-bytes",
        algorithm="HS256",
    )


def test_request_runtime_tokens_uses_fresh_login_token():
    now = time.time()
    token = make_token("admin", issued_at=now, expires_at=now + 3600)
    session = FakeSession(FakeResponse(200, {"code": 200, "data": {"accesstoken": token}}))

    pools = benchmark_auth.request_runtime_tokens(
        "http://benchmark.test",
        {"admin": (("admin", "admin123"),)},
        session=session,
        now=now,
    )

    assert pools == {"admin": (token,)}
    assert session.requests == [
        (
            "http://benchmark.test/api/login",
            {"json": {"username": "admin", "password": "admin123"}, "timeout": benchmark_auth.LOGIN_TIMEOUT_SECONDS},
        )
    ]


@pytest.mark.parametrize(
    "issued_offset, expiry_offset",
    [
        (-benchmark_auth.MAX_TOKEN_AGE_SECONDS - 1, 3600),
        (0, -1),
        (0, benchmark_auth.MIN_TOKEN_TTL_SECONDS - 1),
    ],
)
def test_validate_fresh_token_rejects_stale_or_short_lived_tokens(issued_offset, expiry_offset):
    now = time.time()
    token = make_token("admin", issued_at=now + issued_offset, expires_at=now + expiry_offset)

    with pytest.raises(benchmark_auth.BenchmarkAuthError):
        benchmark_auth.validate_fresh_token(token, "admin", now=now)


def test_request_runtime_tokens_rejects_business_login_failure():
    session = FakeSession(FakeResponse(200, {"code": 500, "msg": "invalid credentials"}))

    with pytest.raises(benchmark_auth.BenchmarkAuthError, match="invalid response"):
        benchmark_auth.request_runtime_tokens(
            "http://benchmark.test",
            {"admin": (("admin", "wrong"),)},
            session=session,
        )


def test_load_tokens_marks_startup_failure_with_nonzero_exit(monkeypatch):
    class Environment:
        runner = None
        host = "http://benchmark.test"
        process_exit_code = 0

    def fail_auth(*_args, **_kwargs):
        raise benchmark_auth.BenchmarkAuthError("login failed")

    monkeypatch.setattr(benchmark_auth, "request_runtime_tokens", fail_auth)
    environment = Environment()

    with pytest.raises(StopTest, match="login failed"):
        benchmark_auth.load_tokens_or_stop(environment, {"admin": (("admin", "wrong"),)})
    assert environment.process_exit_code == 1
