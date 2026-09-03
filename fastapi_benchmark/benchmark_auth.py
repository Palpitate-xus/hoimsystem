"""Runtime authentication helpers for Locust benchmark scenarios."""

import time
from collections.abc import Mapping, Sequence

import jwt
import requests
from locust.exception import StopTest
from locust.runners import MasterRunner

Credential = tuple[str, str]
CredentialPools = Mapping[str, Sequence[Credential]]
TokenPools = dict[str, tuple[str, ...]]

MIN_TOKEN_TTL_SECONDS = 300
MAX_TOKEN_AGE_SECONDS = 300
LOGIN_TIMEOUT_SECONDS = 10


class BenchmarkAuthError(RuntimeError):
    """Raised when benchmark credentials cannot produce a fresh token."""


def validate_fresh_token(
    token: str,
    expected_username: str,
    *,
    now: float | None = None,
    minimum_ttl: int = MIN_TOKEN_TTL_SECONDS,
) -> None:
    """Validate freshness claims without requiring the server's signing key."""
    current_time = time.time() if now is None else now
    try:
        claims = jwt.decode(
            token,
            options={
                "verify_signature": False,
                "verify_exp": True,
                "verify_iat": True,
                "require": ["sub", "iat", "exp"],
            },
            algorithms=["HS256"],
        )
    except jwt.PyJWTError as exc:
        raise BenchmarkAuthError("login returned an invalid or expired access token") from exc

    if claims.get("sub") != expected_username:
        raise BenchmarkAuthError("login token subject does not match the requested account")

    issued_at = claims.get("iat")
    expires_at = claims.get("exp")
    if not isinstance(issued_at, (int, float)) or not isinstance(expires_at, (int, float)):
        raise BenchmarkAuthError("login token timestamps are invalid")
    if issued_at < current_time - MAX_TOKEN_AGE_SECONDS:
        raise BenchmarkAuthError("login returned a stale access token")
    if expires_at < current_time + minimum_ttl:
        raise BenchmarkAuthError("login token expires before the benchmark can complete")


def request_runtime_tokens(
    base_url: str,
    credential_pools: CredentialPools,
    *,
    session: requests.Session | None = None,
    now: float | None = None,
) -> TokenPools:
    """Log in benchmark identities and return freshly validated role pools."""
    if not base_url or not base_url.startswith(("http://", "https://")):
        raise BenchmarkAuthError("Locust --host must be an absolute HTTP(S) URL")
    if not credential_pools:
        raise BenchmarkAuthError("at least one benchmark credential pool is required")

    client = session or requests.Session()
    owns_session = session is None
    token_pools: TokenPools = {}
    try:
        for role, credentials in credential_pools.items():
            role_tokens = []
            for username, password in credentials:
                try:
                    response = client.post(
                        f"{base_url.rstrip('/')}/api/login",
                        json={"username": username, "password": password},
                        timeout=LOGIN_TIMEOUT_SECONDS,
                    )
                except requests.RequestException as exc:
                    raise BenchmarkAuthError(f"{role} benchmark login request failed") from exc

                if response.status_code != 200:
                    raise BenchmarkAuthError(f"{role} benchmark login returned HTTP {response.status_code}")
                try:
                    body = response.json()
                    token = body["data"]["accesstoken"]
                except (KeyError, TypeError, ValueError) as exc:
                    raise BenchmarkAuthError(f"{role} benchmark login returned an invalid response") from exc
                if body.get("code") != 200 or not isinstance(token, str) or not token:
                    raise BenchmarkAuthError(f"{role} benchmark login was rejected")

                validate_fresh_token(token, username, now=now)
                role_tokens.append(token)

            if not role_tokens:
                raise BenchmarkAuthError(f"{role} benchmark token pool is empty")
            token_pools[role] = tuple(role_tokens)
    finally:
        if owns_session:
            client.close()
    return token_pools


def load_tokens_or_stop(environment, credential_pools: CredentialPools) -> TokenPools:
    """Load fresh tokens on workers and stop Locust immediately on failure."""
    if isinstance(environment.runner, MasterRunner):
        return {}
    try:
        return request_runtime_tokens(environment.host, credential_pools)
    except BenchmarkAuthError as exc:
        environment.process_exit_code = 1
        raise StopTest(str(exc)) from exc
