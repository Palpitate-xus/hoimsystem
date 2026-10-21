"""Finite explicit Source requests, not an export or model permission grant."""

import pytest
from pydantic import ValidationError

from app.ai.deidentification_contract import CaptureRequest, ReleaseCreate, ReviewCreate

ID = "00000000-0000-0000-0000-000000000075"
SHA = "a" * 64
BASIS = "明确核对当前所选文字和范围，未知依据不被替换为已确认。"


def test_supported_legacy_exact_locator_does_not_require_legacy_pk_to_be_uuid():
    value = dict(
        scope_id=ID,
        scope_content_hash=SHA,
        scope_governance_hash=SHA,
        patient_id=1,
        documents=[dict(family="medical_records", record_id="legacy-exact-id", field="symptom", expected_original_hash=SHA)],
    )
    assert CaptureRequest.model_validate(value).model_dump() == value
    value["documents"][0]["field"] = "patient_name"
    with pytest.raises(ValidationError):
        CaptureRequest.model_validate(value)


@pytest.mark.parametrize("confirmation", [1, "true", False, None])
def test_explicit_selection_cannot_be_numeric_or_string_truthiness(confirmation):
    with pytest.raises(ValidationError):
        ReviewCreate(case_id=ID, expected_content_hash=SHA, expected_governance_hash=SHA, edits=[], selection_confirmed=confirmation, unselected_fields_not_covered=True, basis_note=BASIS)


def test_unknown_export_authority_and_unknown_validity_remain_unknown():
    value = ReleaseCreate(
        review_id=ID,
        expected_content_hash=SHA,
        expected_governance_hash=SHA,
        authority_status="unknown",
        authority_reference=None,
        original_authority_text=None,
        recipient_scope="internal_named_recipient",
        recipient_reference="synthetic-project-reader",
        declared_purpose=BASIS,
        valid_from=None,
        valid_until=None,
        maximum_downloads=1,
        residual_risk_acknowledged=True,
        basis_note=BASIS,
    )
    assert value.valid_from is None and value.authority_status == "unknown"
    # SQL/API eligibility must separately reject this record for export.
    with pytest.raises(ValidationError):
        ReleaseCreate.model_validate({**value.model_dump(), "valid_until": "2026-10-21T12:00:00.123456Z"})
