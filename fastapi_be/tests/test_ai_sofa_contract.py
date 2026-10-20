"""Pure source contract: no hospital configuration, fixtures or live database."""

import copy
import hashlib
import uuid

import pytest
from pydantic import ValidationError

from app.ai.sofa_contract import AXES, ExactRational, GcsComponents, Quantity, SofaSource, canonical_json, hash_content, policy_digest, recipe_digest


def sha(value):
    return hashlib.sha256(str(value).encode()).hexdigest()


def identifier(value):
    return str(uuid.uuid5(uuid.NAMESPACE_URL, str(value)))


def review(status="confirmed"):
    return {"status": status, "basis_hash": sha(status), "exclusion_reason": "measurement_error" if status == "excluded" else None}


def quantity(value, unit):
    return {"value": value, "unit": unit, "absent_reason": "unknown" if value is None else None}


def binding(prefix, value, recorded="2026-10-20T00:00:00.000000Z"):
    digest = sha(value)
    return {"source_id": f"{prefix}:{identifier(value)}:{digest[:12]}", "content_hash": digest, "governance_hash": sha(str(value) + "governance"), "recorded_at": recorded}


def empty_source():
    aid, pid = identifier("assessment"), identifier("profile")
    return {
        "schema_version": "sofa1_source_v1",
        "assessment_id": aid,
        "source_id": f"sofa_assessment:{aid}:{sha('assessment')[:12]}",
        "content_hash": sha("assessment"),
        "assessment_governance_hash": sha("assessment-governance"),
        "start_at": "2026-10-19T00:00:00.000000Z",
        "end_at": "2026-10-20T00:00:00.000000Z",
        "as_of": "2026-10-20T00:00:00.000000Z",
        "evaluation_at": "2026-10-20T01:00:00.000000Z",
        "rule_profile_id": pid,
        "rule_profile_source_id": f"risk_rule_profile:{pid}:{sha('profile')[:12]}",
        "rule_profile_content_hash": sha("profile"),
        "rule_profile_governance_hash": sha("profile-governance"),
        "rule_id": "sofa1_native_observed_v1",
        "recipe_digest": recipe_digest(),
        "policy_digest": policy_digest(),
        "source_set_digest": sha("all-members"),
        "population": {"age_at_period_years": 50, "adult": "yes", "care_setting": "icu", "applicability_confirmed": True, "basis_hash": sha("population")},
        "coverage": {axis: {"source_inventory": "complete", "clinical_protocol": "adequate", "basis_hash": sha(axis)} for axis in AXES},
        "lab_observations": [],
        "respiratory_observations": [],
        "respiratory_support_observations": [],
        "map_observations": [],
        "gcs_observations": [],
        "vasoactive_groups": [],
        "urine_intervals": [],
        "circulation_review": {"drug_exposure": "none", "no_other_unrepresented_exposure_confirmed": True, "basis_hash": sha("circulation")},
        "conflict_groups": [],
        "member_issues": [],
    }


def lab(analyte="creatinine", value="0", unit="mg/dL", name=None):
    name = name or analyte
    return {
        **binding("inpatient_lab", name),
        "lab_source_id": identifier(name),
        "collected_at_utc": "2026-10-19T12:00:00.000000Z",
        "registered_at": "2026-10-20T00:00:00.000000Z",
        "available_at": "2026-10-20T00:00:00.000000Z",
        "mapping_id": identifier(name + "mapping"),
        "mapping_content_hash": sha(name + "mapping"),
        "mapping_governance_hash": sha(name + "mapping-governance"),
        "identity_hash": sha(name + "identity"),
        "analyte": analyte,
        "quantity": {**quantity(value, unit), "value_kind": "numeric", "original_unit_hash": hash_content(unit)},
        "review": review(),
    }


def test_empty_is_typed_but_not_imputed_and_canonical_roundtrip():
    source = SofaSource.model_validate(empty_source())
    assert source.model_dump() == empty_source()
    assert canonical_json(source.model_dump()).find('"lab_observations":[]') >= 0


@pytest.mark.parametrize("field,value", [("value", 0), ("value", "1e-3"), ("value", "-1"), ("value", "NaN"), ("value", "0.000000001"), ("value", "01"), ("absent_reason", False)])
def test_quantity_rejects_coercion_and_precision_loss(field, value):
    data = quantity("0", "mm[Hg]")
    data[field] = value
    with pytest.raises(ValidationError):
        Quantity.model_validate(data)


@pytest.mark.parametrize("value", ["0", "0.00000000", "9999999999999999.99999999", "1.99999999"])
def test_quantity_preserves_exact_lexeme(value):
    assert Quantity.model_validate(quantity(value, "original-unknown")).value == value


@pytest.mark.parametrize("numerator,denominator", [("0", "2"), ("-0", "1"), ("2", "4"), ("1", "0"), ("01", "1")])
def test_derived_rational_canonical_not_rounded(numerator, denominator):
    with pytest.raises(ValidationError):
        ExactRational.model_validate({"numerator": numerator, "denominator": denominator, "unit": "1"})


@pytest.mark.parametrize(
    "mutation",
    [
        lambda s: s.update(end_at="2026-10-19T23:59:59.999999Z"),
        lambda s: s.update(as_of="2026-10-19T23:59:59.999999Z"),
        lambda s: s.update(evaluation_at="2026-10-19T23:59:59.999999Z"),
        lambda s: s.update(start_at="2026-02-30T00:00:00.000000Z"),
        lambda s: s.update(start_at="2026-10-19T00:00:00Z"),
        lambda s: s.update(source_id="other:" + s["assessment_id"]),
        lambda s: s.update(recipe_digest=sha("wrong")),
        lambda s: s.update(policy_digest=sha("wrong")),
        lambda s: s["population"].update(adult="yes", age_at_period_years=17),
        lambda s: s["population"].update(adult="yes", age_at_period_years=None),
        lambda s: s["population"].update(applicability_confirmed=1),
    ],
)
def test_source_time_scope_identity_policy_not_coerced(mutation):
    data = empty_source()
    mutation(data)
    with pytest.raises(ValidationError):
        SofaSource.model_validate(data)


@pytest.mark.parametrize(
    "field,value", [("source_id", "lab:forged"), ("registered_at", "2026-10-20T00:00:00.000001Z"), ("available_at", "2026-10-20T00:00:00.000001Z"), ("collected_at_utc", "2026-10-20T00:00:00.000001Z")]
)
def test_lab_full_identity_and_original_available_cutoff(field, value):
    data = empty_source()
    data["lab_observations"] = [lab()]
    data["lab_observations"][0][field] = value
    with pytest.raises(ValidationError):
        SofaSource.model_validate(data)


def test_same_original_cannot_be_two_different_raw_quantities():
    data = empty_source()
    first = lab()
    other = copy.deepcopy(first)
    other["quantity"]["value"] = "4"
    data["lab_observations"] = [first, other]
    with pytest.raises(ValidationError):
        SofaSource.model_validate(data)


@pytest.mark.parametrize("eye,verbal,motor", [(5, 5, 6), (4, 6, 6), (True, 5, 6)])
def test_gcs_no_component_range_or_boolean_proxy(eye, verbal, motor):
    with pytest.raises(ValidationError):
        GcsComponents.model_validate({key: {"score": value, "absent_reason": None} for key, value in zip(("eye", "verbal", "motor"), (eye, verbal, motor))})


def test_identical_original_root_cannot_appear_twice_even_if_hash_agrees():
    data = empty_source()
    data["lab_observations"] = [lab(), lab()]
    with pytest.raises(ValidationError):
        SofaSource.model_validate(data)


def test_member_issue_cannot_point_to_an_unprojected_source():
    data = empty_source()
    data["member_issues"] = [{"axis": "renal", "code": "unresolved_conflict", "source_ids": ["unprojected"]}]
    with pytest.raises(ValidationError):
        SofaSource.model_validate(data)


def test_lis_arbitrary_original_unit_cannot_be_sent_in_public_packet():
    data = empty_source()
    item = lab()
    item["quantity"].update(unit="synthetic-private-name-question-as-unit", original_unit_hash=hash_content("synthetic-private-name-question-as-unit"))
    data["lab_observations"] = [item]
    with pytest.raises(ValidationError):
        SofaSource.model_validate(data)
    item["quantity"]["unit"] = "unsupported"
    source = SofaSource.model_validate(data)
    assert "synthetic-private-name-question-as-unit" not in canonical_json(source.model_dump())
    assert source.lab_observations[0].quantity.original_unit_hash == hash_content("synthetic-private-name-question-as-unit")


@pytest.mark.parametrize("unit,original", [("unknown", None), ("unsupported", ""), ("unsupported", "mg / dL")])
def test_lis_null_or_unsupported_unit_keeps_full_original_hash(unit, original):
    data = empty_source()
    item = lab()
    item["quantity"].update(unit=unit, original_unit_hash=hash_content(original))
    data["lab_observations"] = [item]
    assert SofaSource.model_validate(data).lab_observations[0].quantity.original_unit_hash == hash_content(original)
