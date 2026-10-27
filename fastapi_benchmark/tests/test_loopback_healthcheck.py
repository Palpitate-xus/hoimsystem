"""Compose health commands must probe localhost even with an external proxy."""

import json
import subprocess
import sys
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@contextmanager
def server(status):
    calls = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            calls.append(self.path)
            self.send_response(status)
            self.end_headers()
            self.wfile.write(b'{"status":"synthetic"}')

        def log_message(self, *_args):
            pass

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield httpd.server_port, calls
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=3)


@pytest.mark.parametrize("compose", ["docker-compose.yml", "fastapi_benchmark/docker-compose.yml"])
@pytest.mark.parametrize("status", [200, 503])
def test_actual_compose_probe_uses_local_response_and_never_the_proxy(compose, status):
    probes = [line.split("test:", 1)[1].strip() for line in (ROOT / compose).read_text().splitlines() if line.strip().startswith("test:") and "/health/ready" in line]
    assert len(probes) == 1
    command = json.loads(probes[0])
    assert command[:3] == ["CMD", "python", "-c"]
    url = "http://127.0.0.1:8000/health/ready"
    assert command[3].count(url) == 1
    with server(status) as (health_port, health_calls), server(502) as (proxy_port, proxy_calls):
        # Run the actual checked-in command against an ephemeral local health
        # endpoint. A separate real proxy listener catches accidental routing.
        proxy = f"http://127.0.0.1:{proxy_port}"
        env = {"HTTP_PROXY": proxy, "http_proxy": proxy, "HTTPS_PROXY": proxy, "https_proxy": proxy, "NO_PROXY": "", "no_proxy": ""}
        probe = command[3].replace(url, f"http://127.0.0.1:{health_port}/health/ready")
        result = subprocess.run([sys.executable, "-c", probe], env=env, capture_output=True, text=True, timeout=10)
        assert (result.returncode == 0) is (status == 200), result.stderr
        assert health_calls == ["/health/ready"]
        assert proxy_calls == []
