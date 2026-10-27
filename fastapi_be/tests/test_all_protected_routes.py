"""Exercise every declared authentication boundary through the mounted app.

These checks establish denial behavior; they do not certify each endpoint's
successful business workflow. The functional suite remains separate evidence.
"""

import json
import re
from pathlib import Path

import pytest

from app.dependencies import VALID_USER_ROLES
from app.models import User

MATRIX = json.loads((Path(__file__).resolve().parents[1] / "rbac_matrix.json").read_text())
PROTECTED = [row for row in MATRIX if row["auth"] != "PUBLIC"]
ROLE_RESTRICTED = [row for row in PROTECTED if isinstance(row["auth"], list) and set(row["auth"]) != set(VALID_USER_ROLES)]
CHUNK_SIZE = 50


def chunks(rows):
    return [rows[index:index + CHUNK_SIZE] for index in range(0, len(rows), CHUNK_SIZE)]


def target_path(template):
    # Valid path segments reach the actual router. Request-body validity must
    # never allow a caller to bypass authentication or explicit role checks.
    return re.sub(r"\{[^}]+\}", "1", template)


@pytest.mark.asyncio
@pytest.mark.parametrize("routes", chunks(PROTECTED), ids=lambda rows: rows[0]["path"])
async def test_every_protected_route_rejects_missing_identity(async_client, routes):
    for row in routes:
        response = await async_client.request(row["method"], target_path(row["path"]), json={} if row["method"] != "GET" else None)
        assert response.status_code == 401, (row["method"], row["path"], response.status_code)


@pytest.mark.asyncio
@pytest.mark.parametrize("routes", chunks(ROLE_RESTRICTED), ids=lambda rows: rows[0]["path"])
async def test_every_role_restricted_route_rejects_a_real_disallowed_role(async_client, seed_data, auth_headers, routes):
    users = {value.user_role: value for value in seed_data.values() if isinstance(value, User)}
    for row in routes:
        role = next(role for role in users if role not in row["auth"])
        user = users[role]
        response = await async_client.request(
            row["method"], target_path(row["path"]), headers=auth_headers(user.username), json={} if row["method"] != "GET" else None,
        )
        assert response.status_code == 403, (row["method"], row["path"], role, response.status_code)
