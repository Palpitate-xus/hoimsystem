"""Discover valid write targets before a Locust benchmark starts."""

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date

import requests

TokenPools = Mapping[str, Sequence[str]]

SETUP_TIMEOUT_SECONDS = 10


class BenchmarkSetupError(RuntimeError):
    """Raised when the benchmark database lacks required write targets."""


@dataclass(frozen=True)
class WriteTargets:
    appointment_payloads: tuple[dict, ...]
    patient_ids: tuple[int, ...]
    pharmaceutical_ids: tuple[int, ...]


def _request_list(client, base_url: str, path: str, token: str) -> list:
    try:
        response = client.get(
            f"{base_url.rstrip('/')}{path}",
            headers={"accesstoken": token},
            timeout=SETUP_TIMEOUT_SECONDS,
        )
    except requests.RequestException as exc:
        raise BenchmarkSetupError(f"benchmark setup request failed for {path}") from exc
    if response.status_code != 200:
        raise BenchmarkSetupError(f"benchmark setup returned HTTP {response.status_code} for {path}")
    try:
        body = response.json()
    except ValueError as exc:
        raise BenchmarkSetupError(f"benchmark setup returned non-JSON data for {path}") from exc
    if not isinstance(body, dict) or body.get("code") != 200 or not isinstance(body.get("data"), list):
        raise BenchmarkSetupError(f"benchmark setup returned invalid business data for {path}")
    return body["data"]


def discover_write_targets(
    base_url: str,
    token_pools: TokenPools,
    *,
    session: requests.Session | None = None,
) -> WriteTargets:
    """Load IDs and build valid, non-duplicated appointment payloads."""
    try:
        patient_token = token_pools["patient"][0]
        doctor_token = token_pools["doctor"][0]
    except (KeyError, IndexError, TypeError) as exc:
        raise BenchmarkSetupError("patient and doctor token pools are required") from exc

    client = session or requests.Session()
    owns_session = session is None
    try:
        schedules = _request_list(
            client,
            base_url,
            "/api/appointmentManagement/appointmentList",
            patient_token,
        )
        owners = _request_list(client, base_url, "/api/patientManagement/getList", patient_token)
        family_members = _request_list(client, base_url, "/api/familyMember/list", patient_token)
        pharmaceuticals = _request_list(
            client,
            base_url,
            "/api/pharmaceuticalManagement/getList",
            doctor_token,
        )
    finally:
        if owns_session:
            client.close()

    patient_ids = tuple(
        dict.fromkeys(item.get("patient_id", item.get("id")) for item in [*owners, *family_members] if isinstance(item, dict) and isinstance(item.get("patient_id", item.get("id")), int))
    )
    if not patient_ids:
        raise BenchmarkSetupError("benchmark patient target pool is empty")

    schedule_groups: dict[tuple, list[dict]] = defaultdict(list)
    for schedule in schedules:
        if not isinstance(schedule, dict) or not all(schedule.get(key) is not None for key in ("id", "date", "doctor_id", "department_id", "specialist", "time")):
            continue
        if not isinstance(schedule.get("stock"), int) or schedule["stock"] <= 0:
            continue
        group_key = (
            schedule["date"],
            schedule["doctor_id"],
            schedule["department_id"],
            schedule["specialist"],
        )
        schedule_groups[group_key].append(schedule)
    if not schedule_groups:
        raise BenchmarkSetupError("benchmark appointment schedule pool is empty")

    appointment_payloads = []
    for patient_index, patient_id in enumerate(patient_ids):
        for group in schedule_groups.values():
            schedule = group[patient_index % len(group)]
            appointment_payloads.append(
                {
                    "id": schedule["id"],
                    "date": schedule["date"],
                    "department_id": schedule["department_id"],
                    "doctor_id": schedule["doctor_id"],
                    "time": schedule["time"],
                    "specialist": schedule["specialist"],
                    "patient_id": patient_id,
                }
            )

    today = date.today()
    pharmaceutical_ids = []
    for item in pharmaceuticals:
        if not isinstance(item, dict) or item.get("status") != 0:
            continue
        if not isinstance(item.get("stock"), int) or item["stock"] <= 0:
            continue
        try:
            expiry = date.fromisoformat(item["expireddate"])
        except (TypeError, ValueError):
            continue
        if expiry >= today and isinstance(item.get("id"), int):
            pharmaceutical_ids.append(item["id"])
    if not pharmaceutical_ids:
        raise BenchmarkSetupError("benchmark pharmaceutical target pool is empty")

    return WriteTargets(
        appointment_payloads=tuple(appointment_payloads),
        patient_ids=patient_ids,
        pharmaceutical_ids=tuple(pharmaceutical_ids),
    )


def load_write_targets_or_stop(environment, token_pools: TokenPools) -> WriteTargets:
    """Discover targets or fail the Locust run before users are spawned."""
    from locust.exception import StopTest

    try:
        return discover_write_targets(environment.host, token_pools)
    except BenchmarkSetupError as exc:
        environment.process_exit_code = 1
        raise StopTest(str(exc)) from exc
