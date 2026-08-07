import pytest


@pytest.mark.asyncio
async def test_low_privilege_patient_listing_masks_identity_and_phone(async_client, seed_data, auth_headers):
    response = await async_client.get(
        "/api/patientManagement/getList", headers=auth_headers(seed_data["guide_user"].username)
    )
    assert response.status_code == 200
    row = next(item for item in response.json()["data"] if item["id"] == seed_data["patient"].patient_id)
    assert row["identity"] == "370101********1234"
    assert row["phone"] == "138****8000"


@pytest.mark.asyncio
async def test_authorized_staff_and_patient_keep_full_identity(async_client, seed_data, auth_headers):
    admin_response = await async_client.get(
        "/api/patientManagement/getList", headers=auth_headers(seed_data["admin_user"].username)
    )
    patient_response = await async_client.get(
        "/api/patientManagement/getList", headers=auth_headers(seed_data["patient_user"].username)
    )
    admin_row = next(item for item in admin_response.json()["data"] if item["id"] == seed_data["patient"].patient_id)
    patient_row = next(item for item in patient_response.json()["data"] if item["id"] == seed_data["patient"].patient_id)
    assert admin_row["identity"] == seed_data["patient"].identity
    assert patient_row["identity"] == seed_data["patient"].identity
