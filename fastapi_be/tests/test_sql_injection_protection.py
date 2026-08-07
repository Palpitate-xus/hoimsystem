from pathlib import Path

import pytest


@pytest.mark.asyncio
async def test_query_filters_use_bound_parameters(async_client, seed_data, auth_headers):
    """SQL metacharacters stay query data and never become executable SQL."""
    headers = auth_headers(seed_data["admin_user"].username)
    attack = "%' OR 1=1; DROP TABLE hoimsystem_patient; --"

    responses = [
        await async_client.get("/api/patientManagement/getList", headers=headers, params={"keyword": attack}),
        await async_client.get("/api/insurance/catalog/list", headers=headers, params={"keyword": attack}),
        await async_client.get("/api/prescriptionManagement/getList", headers=headers, params={"keyword": attack}),
        await async_client.post(
            "/api/log/getList",
            headers=headers,
            json={"page": 1, "page_size": 10, "username": attack, "action": attack},
        ),
    ]

    assert all(response.status_code == 200 for response in responses)
    assert all("syntax error" not in response.text.lower() for response in responses)
    assert all("no such table" not in response.text.lower() for response in responses)


def test_raw_sql_identifiers_are_static_allowlisted_values():
    source = Path(__file__).parents[1].joinpath("app/schema_compat.py").read_text()
    assert 'table_name = "hoimsystem_operation_log"' in source
    assert "OPERATION_LOG_COLUMNS" in source
    assert 'request.' not in source
