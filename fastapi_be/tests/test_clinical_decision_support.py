import datetime
import json
from decimal import Decimal

from app.models import PatientClinicalProfile, PrescriptionReviewRule
from app.rx_review_engine import build_patient_context, check_prescription


def test_renal_context_rule_blocks_matching_drug(seed_data, db_session):
    profile = PatientClinicalProfile(
        patient_id=seed_data["patient"].patient_id,
        pregnant=0,
        egfr=Decimal("25.00"),
        hepatic_impairment=0,
        diagnoses_json="[]",
        labs_json='{"potassium": 4.2}',
        updated_by=seed_data["doctor_user"].user_id,
        update_time=datetime.datetime.now(),
    )
    rule = PrescriptionReviewRule(
        rule_type="context",
        drug_a="二甲双胍",
        condition_json=json.dumps({"max_egfr": 30}),
        severity=3,
        message="eGFR≤30 禁用二甲双胍",
        source="院内药事委员会",
        version="2026.1",
        status=1,
        create_time=datetime.datetime.now(),
    )
    db_session.add_all([profile, rule])
    db_session.commit()

    context = build_patient_context(db_session, seed_data["patient"])
    findings = check_prescription(
        db_session,
        [{"name": "盐酸二甲双胍片", "dosage": 500, "frequency": "bid"}],
        patient_context=context,
    )

    assert context["egfr"] == 25.0
    assert findings[0]["severity"] == 3
    assert findings[0]["source"] == "院内药事委员会"
