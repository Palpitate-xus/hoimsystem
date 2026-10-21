"""Pure finite research declarations, not a cohort performance evaluation."""

import copy

import pytest
from pydantic import ValidationError

from app.ai.research_cohort_contract import AuthorizationReview, CohortCriteria, PatientAuthorizationCreate, ScopeCreate, SourceReview, SourceRevoke, canonical_json

BASIS = "隔离合成项目目的和人工授权记录核查依据，非真实患者许可或医院伦理验证。"


def scope_request():
    return dict(
        protocol_key="synthetic-protocol-v1",
        title="隔离合成有限研究范围",
        purpose=BASIS,
        patient_ids=[1, 2],
        proposed_user_ids=[1, 2],
        data_families=["medical_records", "patient_demographics"],
        permitted_uses=["cohort_criteria_review"],
        record_window={"date_from": "2026-10-01", "date_to": "2026-10-21", "time_basis": "legacy_naive_calendar_dates_timezone_unknown"},
        valid_from="2026-10-21T00:00:00.000000Z",
        valid_until="2026-10-22T00:00:00.000000Z",
        external_model_use="unknown",
        external_model_use_basis=BASIS,
        authority_reference=None,
        authorization_basis=BASIS,
    )


def leaf():
    return {"op": "recorded_scalar_equal", "family": "patient_demographics", "field": "sex", "expected": 1, "quantifier": "any_record"}


def test_exact_finite_scope_requires_explicit_processing_permission_and_canonical_complete_members():
    request = ScopeCreate.model_validate(scope_request())
    assert request.external_model_use == "unknown" and request.patient_ids == [1, 2]
    assert request.model_dump() == scope_request()
    for mutation in ({"patient_ids": []}, {"patient_ids": [2, 1]}, {"patient_ids": [1, 1]}, {"proposed_user_ids": []}, {"data_families": ["all_clinical_tables"]}, {"irb_certified": True}):
        with pytest.raises(ValidationError):
            ScopeCreate.model_validate({**scope_request(), **mutation})
    missing = scope_request()
    del missing["external_model_use"]
    with pytest.raises(ValidationError):
        ScopeCreate.model_validate(missing)


@pytest.mark.parametrize(
    "mutation",
    [
        {"valid_from": "2026-02-30T00:00:00.000000Z"},
        {"valid_from": "2026-10-21T00:00:00Z"},
        {"valid_until": "2026-10-21T00:00:00.000000Z"},
        {"patient_ids": [True]},
        {"purpose": "\u0085" * 20},
        {"purpose": "汉" * 1334},
    ],
)
def test_scope_rejects_invalid_calendar_boolean_members_meaningless_or_oversized_basis(mutation):
    with pytest.raises(ValidationError):
        ScopeCreate.model_validate({**scope_request(), **mutation})


@pytest.mark.parametrize("model", [SourceReview, AuthorizationReview])
def test_governance_cas_revision_never_accepts_boolean_alias(model):
    value = {"expected_revision": True, "decision": "publish", "basis_note": BASIS}
    if model is AuthorizationReview:
        value.update(expected_content_hash="a" * 64, decision="recorded_reviewed", review_scope="documentary_authorization_review_not_irb_certification")
    with pytest.raises(ValidationError):
        model.model_validate(value)


def test_revoke_preserves_1000_codepoints_with_4000_utf8_boundary():
    assert SourceRevoke.model_validate({"expected_revision": 2, "basis_note": "🧪" * 1000}).basis_note == "🧪" * 1000
    with pytest.raises(ValidationError):
        SourceRevoke.model_validate({"expected_revision": 2, "basis_note": "x" * 1001})


def test_unknown_withdrawn_denied_and_original_authority_text_remain_literal():
    raw = "\ufeff原始人工记录\r\n🧪：否定或退出必须保留"
    for status in ("unknown", "withdrawn", "denied", "waiver_recorded", "permission_recorded"):
        request = PatientAuthorizationCreate.model_validate(
            dict(
                scope_id="00000000-0000-4000-8000-000000000001",
                scope_content_hash="a" * 64,
                scope_governance_hash="b" * 64,
                patient_id=1,
                authorization_kind=status,
                access_basis="explicit_project_acl",
                valid_from=None,
                valid_until=None,
                authority_reference=None,
                original_authority_text=raw,
                basis_note=BASIS,
            )
        )
        assert request.authorization_kind == status and request.valid_from is None and request.original_authority_text == raw


def test_ast_is_closed_finite_and_does_not_accept_sql_arbitrary_families_or_unknown_fields():
    assert CohortCriteria.model_validate({"schema_version": "research_recorded_criteria_v1", "root": leaf()}).root.expected == 1
    for node in ({"op": "sql", "query": "select * from patients"}, {**leaf(), "family": "all_tables"}, {**leaf(), "field": "identity"}, {**leaf(), "expected": True}, {**leaf(), "raw_sql": "1=1"}):
        with pytest.raises(ValidationError):
            CohortCriteria.model_validate({"schema_version": "research_recorded_criteria_v1", "root": node})
    value = {"op": "not", "child": leaf()}
    for _ in range(7):
        value = {"op": "not", "child": value}
    with pytest.raises(ValidationError):
        CohortCriteria.model_validate({"schema_version": "research_recorded_criteria_v1", "root": value})
    value = {"op": "all", "children": [copy.deepcopy(leaf()) for _ in range(64)]}
    with pytest.raises(ValidationError):
        CohortCriteria.model_validate({"schema_version": "research_recorded_criteria_v1", "root": value})


def test_literal_text_and_calendar_predicates_remain_recorded_statements_only():
    text = {"op": "recorded_text_contains", "family": "medical_records", "field": "symptom", "literal": "无发热\r\n🧪", "quantifier": "every_record"}
    date = {
        "op": "recorded_date_compare",
        "family": "admissions",
        "field": "discharge_time",
        "comparison": "before",
        "expected": "2026-10-21",
        "quantifier": "any_record",
        "time_basis": "legacy_naive_calendar_dates_timezone_unknown",
    }
    assert CohortCriteria.model_validate({"schema_version": "research_recorded_criteria_v1", "root": {"op": "all", "children": [text, date]}}).root.children[0].literal == text["literal"]
    with pytest.raises(ValidationError):
        CohortCriteria.model_validate({"schema_version": "research_recorded_criteria_v1", "root": {**date, "expected": "2026-02-30"}})


def test_canonical_original_rejects_nonfinite_and_unpaired_unicode_without_normalization():
    text = "\ufeff人工原文\r\n🧪"
    assert text in canonical_json({"text": text}).replace("\\r\\n", "\r\n")
    for value in ({"text": chr(0xD800)}, {"value": float("nan")}):
        with pytest.raises((ValueError, UnicodeError)):
            canonical_json(value)
