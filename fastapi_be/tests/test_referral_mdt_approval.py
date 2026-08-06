import datetime

import pytest

from app.models import MdtCase, Referral


@pytest.mark.asyncio
class TestReferralMdtApproval:
    async def test_director_approves_scoped_referral_and_mdt(self, async_client, seed_data, auth_headers, db_session):
        referral = Referral(
            patient_id=seed_data["patient"].patient_id,
            from_department_id=seed_data["department"].department_id,
            to_department_id=seed_data["department"].department_id,
            referral_type="up",
            reason="需要专科评估",
            status=0,
            create_time=datetime.datetime.now(),
            applicant_id=seed_data["doctor_user"].user_id,
        )
        mdt = MdtCase(
            patient_id=seed_data["patient"].patient_id,
            diagnosis="复杂病例",
            department_ids=f"[{seed_data['department'].department_id}]",
            status=0,
            create_time=datetime.datetime.now(),
            applicant_id=seed_data["doctor_user"].user_id,
        )
        db_session.add_all([referral, mdt])
        db_session.commit()

        headers = auth_headers(seed_data["director_user"].username)
        referral_list = await async_client.get("/api/referral/approvalList", headers=headers)
        assert referral_list.json()["data"][0]["referral_id"] == referral.referral_id
        referral_result = await async_client.post(
            "/api/referral/approval",
            headers=headers,
            json={"referral_id": referral.referral_id, "status": 1, "note": "同意转诊"},
        )
        assert referral_result.json()["code"] == 200

        mdt_list = await async_client.get("/api/mdt/approvalList", headers=headers)
        assert mdt_list.json()["data"][0]["mdt_id"] == mdt.mdt_id
        mdt_result = await async_client.post(
            "/api/mdt/approval",
            headers=headers,
            json={"mdt_id": mdt.mdt_id, "status": 1, "note": "同意会诊"},
        )
        assert mdt_result.json()["code"] == 200
        db_session.refresh(referral)
        db_session.refresh(mdt)
        assert referral.status == 1 and referral.reviewer_id == seed_data["director_user"].user_id
        assert mdt.status == 1 and mdt.reviewer_id == seed_data["director_user"].user_id

    async def test_patient_cannot_approve_referral(self, async_client, seed_data, auth_headers):
        response = await async_client.get(
            "/api/referral/approvalList",
            headers=auth_headers(seed_data["patient_user"].username),
        )
        assert response.status_code == 403
