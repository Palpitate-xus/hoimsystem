"""Run a measured mixed workload, including a sustained local soak test.

Example: BENCHMARK_PROFILE=soak python run_load.py --host http://127.0.0.1:51902
         --users 100 --seconds 1800 --output benchmark_results/soak-001
The HTTP target must be a separately initialized benchmark application.
"""

# Gevent must patch networking before Locust and requests are imported.
# ruff: noqa: E402
from gevent import monkey

monkey.patch_all()

import argparse
import csv
import datetime
import json
import os
import time
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit

import gevent
import locust_final as workload
import requests
from benchmark_profiles import PROFILES
from locust import events
from locust.env import Environment
from locust.stats import RequestStats


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", required=True, help="Loopback URL of the isolated benchmark API")
    parser.add_argument("--users", type=int, default=100)
    parser.add_argument("--seconds", type=int, default=1800)
    parser.add_argument("--output", type=Path, required=True, help="New output directory; existing evidence is never overwritten")
    args = parser.parse_args()
    target = urlsplit(args.host)
    if target.scheme != "http" or target.hostname not in {"127.0.0.1", "localhost", "::1"} or target.username or target.password or target.path not in {"", "/"} or target.query or target.fragment:
        parser.error("--host must be a loopback HTTP origin for an isolated benchmark instance")
    if not 1 <= args.users <= 1000 or not 1 <= args.seconds <= 86400:
        parser.error("users must be 1..1000 and seconds must be 1..86400")
    profile = os.environ.get("BENCHMARK_PROFILE", "smoke")
    if profile not in PROFILES:
        parser.error("BENCHMARK_PROFILE must name an existing dataset profile")
    with requests.Session() as session:
        session.trust_env = False
        response = session.get(args.host.rstrip("/") + "/benchmark/info", timeout=10)
        response.raise_for_status()
        identity = response.json()
    if identity != {"schema_version": 1, "benchmark_database": "hoimsystem_benchmark", "mode": "load", "profile": profile}:
        parser.error("The target did not identify itself as the matching isolated PostgreSQL benchmark application")
    args.output.mkdir(parents=True, exist_ok=False)
    os.environ["BENCHMARK_RESULTS_DIR"] = str(args.output.resolve())
    environment = Environment(user_classes=[workload.HOIMUser], events=events, host=args.host,
                              parsed_options=SimpleNamespace(num_users=args.users), stop_timeout=35)
    runner = environment.create_local_runner()
    measured = RequestStats()
    failures = []
    environment.benchmark_measurement_id = None
    environment.benchmark_in_flight = 0

    @events.request.add_listener
    def record(request_type, name, response_time, response_length, exception, context=None, **_kwargs):
        # Each HTTP call captures this context before it starts. Warmup responses
        # completing after the boundary therefore cannot enter the measured set.
        if not context or context.get("benchmark_measurement_id") != "measured":
            return
        environment.benchmark_in_flight -= 1
        measured.log_request(request_type, name, response_time, response_length)
        if exception:
            measured.log_error(request_type, name, exception)
            failures.append({"at": datetime.datetime.now(datetime.UTC).isoformat(), "method": request_type,
                             "name": name, "response_time_ms": response_time, "error": str(exception)})

    def write(name, data):
        (args.output / name).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")

    setup_started = time.monotonic()
    runner.start(args.users, spawn_rate=min(args.users, 100))
    runner.spawning_greenlet.join(timeout=180)
    if not runner.spawning_greenlet.ready() or runner.spawning_greenlet.exception or environment.process_exit_code or runner.user_count != args.users:
        write("result.json", {"status": "setup_failed", "users": runner.user_count, "exit_code": environment.process_exit_code,
                              "exception": str(runner.spawning_greenlet.exception), "seconds": time.monotonic() - setup_started})
        runner.quit()
        raise SystemExit(2)
    gevent.sleep(2)
    setup = {"seconds": time.monotonic() - setup_started, "requests": environment.stats.total.num_requests,
             "failures": environment.stats.total.num_failures, "appointment_targets": len(workload.APPOINTMENT_TARGETS),
             "patient_targets": len(workload.PRESCRIPTION_PATIENT_IDS), "patient_accounts": len(workload.TOKEN_POOLS["patient"])}
    write("setup.json", setup)
    if setup["failures"]:
        runner.quit()
        raise SystemExit(3)

    started_at = datetime.datetime.now(datetime.UTC).isoformat()
    started = time.monotonic()
    measured.reset_all()
    environment.benchmark_measurement_id = "measured"
    exhausted = False
    with (args.output / "history.csv").open("w") as stream:
        history = csv.writer(stream)
        history.writerow(["elapsed_seconds", "users", "requests", "failures", "p50_ms", "p95_ms", "p99_ms", "in_flight", "appointment_targets"])
        while time.monotonic() - started < args.seconds:
            if not workload.APPOINTMENT_TARGETS or environment.process_exit_code or runner.user_count != args.users:
                exhausted = True
                break
            total = measured.total
            history.writerow([time.monotonic() - started, runner.user_count, total.num_requests, total.num_failures,
                              total.get_response_time_percentile(.5), total.get_response_time_percentile(.95),
                              total.get_response_time_percentile(.99), environment.benchmark_in_flight, len(workload.APPOINTMENT_TARGETS)])
            stream.flush()
            gevent.sleep(min(1, max(0, args.seconds - (time.monotonic() - started))))
    measurement_seconds = time.monotonic() - started
    environment.benchmark_measurement_id = None
    drain_started = time.monotonic()
    runner.stop()
    drain_seconds = time.monotonic() - drain_started
    total = measured.total
    entries = [{"method": row.method, "name": row.name, "requests": row.num_requests, "failures": row.num_failures,
                "average_ms": row.avg_response_time, "p50_ms": row.get_response_time_percentile(.5),
                "p95_ms": row.get_response_time_percentile(.95), "p99_ms": row.get_response_time_percentile(.99)}
               for row in measured.entries.values()]
    invalid = exhausted or environment.benchmark_in_flight != 0 or bool(runner.exceptions)
    result = {"status": "invalid" if invalid else "completed", "host": args.host, "profile": profile, "users": args.users,
              "configured_seconds": args.seconds, "measurement_seconds": measurement_seconds, "drain_seconds": drain_seconds,
              "started_at": started_at, "requests": total.num_requests, "failures": total.num_failures, "failure_ratio": total.fail_ratio,
              "rps_including_drain": total.num_requests / (measurement_seconds + drain_seconds), "average_ms": total.avg_response_time,
              "p50_ms": total.get_response_time_percentile(.5), "p95_ms": total.get_response_time_percentile(.95),
              "p99_ms": total.get_response_time_percentile(.99), "max_ms": total.max_response_time,
              "unaccounted_in_flight": environment.benchmark_in_flight, "target_pool_exhausted": exhausted,
              "remaining_appointment_targets": len(workload.APPOINTMENT_TARGETS), "exceptions": len(runner.exceptions), "entries": entries,
              "timing_note": "Only requests started during the measured window are counted; their completion includes a bounded drain. Setup, ramp and warmup excluded. HTTP and business failures both count."}
    write("result.json", result)
    write("failure-details.json", failures)
    print(json.dumps(result, ensure_ascii=False), flush=True)
    runner.quit()
    raise SystemExit(0 if not invalid and not total.num_failures else 4)


if __name__ == "__main__":
    main()
