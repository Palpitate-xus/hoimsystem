import datetime
from decimal import Decimal

import pytest

from app.models import Admission, DrgRule, HomeIcdBinding, MedicalRecordHome


@pytest.mark.asyncio
async def test_automatic_grouping_uses_primary_icd_and_highest_priority_rule(async_client, seed_data, auth_headers, db_session):
    admission = Admission(
        patient_id=seed_data["patient"].patient_id,
        doctor_id=seed_data["doctor"].doctor_id,
        department_id=seed_data["department"].department_id,
        status=2,
        admission_time=datetime.datetime.now() - datetime.timedelta(days=3),
        discharge_time=datetime.datetime.now(),
        create_time=datetime.datetime.now() - datetime.timedelta(days=3),
    )
    db_session.add(admission)
    db_session.flush()
    home = MedicalRecordHome(
        admission_id=admission.admission_id,
        patient_id=seed_data["patient"].patient_id,
        doctor_id=seed_data["doctor"].doctor_id,
        admission_diagnosis="肺炎",
        discharge_diagnosis="细菌性肺炎",
        total_fee=Decimal("8000.00"),
        status=1,
        creator_id=seed_data["doctor_user"].user_id,
        create_time=datetime.datetime.now(),
        update_time=datetime.datetime.now(),
    )
    db_session.add(home)
    db_session.flush()
    db_session.add(HomeIcdBinding(
        home_id=home.home_id,
        kind="diagnosis",
        icd_code="J15.9",
        icd_name="细菌性肺炎",
        is_primary=1,
        coder_id=seed_data["doctor_user"].user_id,
        code_time=datetime.datetime.now(),
    ))
    db_session.add_all([
        DrgRule(payment_method="DRG", group_code="DRG-J", group_name="呼吸系统普通组", diagnosis_prefix="J", expected_amount=Decimal("9000"), priority=1, version="2026", status=1, creator_id=seed_data["admin_user"].user_id, create_time=datetime.datetime.now(), update_time=datetime.datetime.now()),
        DrgRule(payment_method="DRG", group_code="DRG-J15", group_name="细菌性肺炎组", diagnosis_prefix="J15", expected_amount=Decimal("10000"), priority=10, version="2026", status=1, creator_id=seed_data["admin_user"].user_id, create_time=datetime.datetime.now(), update_time=datetime.datetime.now()),
    ])
    db_session.commit()

    response = await async_client.post(
        "/api/insurance/drg/autoGroup",
        headers=auth_headers(seed_data["admin_user"].username),
        json={"home_id": home.home_id},
    )

    assert response.status_code == 200
    assert response.json()["data"]["group_code"] == "DRG-J15"
    assert float(response.json()["data"]["profit"]) == 2000.0
