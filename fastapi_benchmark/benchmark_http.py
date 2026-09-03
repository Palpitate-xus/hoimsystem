"""HTTP result helpers shared by Locust benchmark scenarios."""


def mark_business_result(response) -> bool:
    """Count only successful HTTP responses with the API's success code."""
    if not 200 <= response.status_code < 300:
        response.failure(f"HTTP {response.status_code}")
        return False
    try:
        body = response.json()
    except (TypeError, ValueError):
        response.failure("non-JSON response")
        return False
    if not isinstance(body, dict) or body.get("code") != 200:
        code = body.get("code") if isinstance(body, dict) else "invalid"
        response.failure(f"business code {code}")
        return False
    response.success()
    return True
