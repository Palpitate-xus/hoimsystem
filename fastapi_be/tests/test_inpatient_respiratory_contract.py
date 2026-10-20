"""Strict source contracts preserve real quantities, clocks, missingness and intervals."""

import datetime

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy.dialects import mysql
from sqlalchemy.schema import CreateTable

from app import inpatient_respiratory_sources as sources
from app.inpatient_respiratory_models import InpatientArterialPairSource, InpatientMapSource, InpatientRespiratorySource

NOTE = "合成原资料核实依据；保留实际原始测量和明确区间，没有从文字猜测连续支持或推导临床评分。"
NOW = datetime.datetime(2026, 10, 20, 12, 30, 45, 123456)


def map_payload(**changes):
    return {
        "observed_at": "2026-10-20T20:00:00.123456+08:00",
        "map": {"value": "0.00000000", "unit": "mm[Hg]", "absent_reason": None},
        "measurement_method": "unknown",
        "measurement_basis_note": NOTE,
        "note": "",
        **changes,
    }


def support_payload(**changes):
    return {
        "start_at": "2026-10-20T11:00:00.111111Z",
        "verified_until_at": "2026-10-20T12:00:00.123456Z",
        "ended_at": None,
        "delivery_mode": "unknown",
        "continuity_confirmed": False,
        "continuity_basis_note": None,
        "device_description": None,
        "note": "",
        **changes,
    }


def pair_payload(**changes):
    return {
        "pao2": {"lab_source_id": "11111111-1111-4111-8111-111111111111", "expected_content_hash": "a" * 64},
        "fio2": {"observation_id": "22222222-2222-4222-8222-222222222222", "expected_content_hash": "b" * 64},
        "support": {"support_source_id": "33333333-3333-4333-8333-333333333333", "expected_content_hash": "c" * 64},
        "arterial_sample_confirmed": False,
        "same_sampling_state_confirmed": False,
        "fio2_applicability_confirmed": False,
        "review_note": NOTE,
        "note": "",
        **changes,
    }


def test_map_preserves_native_zero_decimal_microseconds_and_original_method():
    data = sources.MapPayload.model_validate(map_payload()).model_dump(mode="json")
    assert data["observed_at"] == "2026-10-20T12:00:00.123456Z"
    assert data["map"] == {"value": "0.00000000", "unit": "mm[Hg]", "absent_reason": None}
    event, refs = sources.prepare_map(None, 1, "original-admission", data, NOW)
    assert event == datetime.datetime(2026, 10, 20, 12, 0, 0, 123456) and refs == {}
    assert "score" not in data and "systolic_bp" not in data


@pytest.mark.parametrize("value", [True, False, 0, 1.2, "-0.1", "1e2", "NaN", "Infinity", "1.123456789", "10000000000000000", " 2", "01"])
def test_map_never_coerces_or_rounds_original_measurement(value):
    with pytest.raises(ValidationError):
        sources.MapPayload.model_validate(map_payload(map={"value": value, "unit": "mm[Hg]", "absent_reason": None}))


@pytest.mark.parametrize("reason", ["unknown", "not_performed", "measurement_error"])
def test_map_unknown_is_retained_without_normal_imputation(reason):
    original = {"value": None, "unit": "mm[Hg]", "absent_reason": reason}
    assert sources.MapPayload.model_validate(map_payload(map=original)).model_dump()["map"] == original


@pytest.mark.parametrize(
    "measurement",
    [
        {"value": None, "unit": "mm[Hg]", "absent_reason": None},
        {"value": "0", "unit": "mm[Hg]", "absent_reason": "unknown"},
        {"value": "1", "unit": "kPa", "absent_reason": None},
        {"value": None, "unit": "mm[Hg]", "absent_reason": "not_recorded"},
    ],
)
def test_map_unit_and_missingness_are_explicit(measurement):
    with pytest.raises(ValidationError):
        sources.MapPayload.model_validate(map_payload(map=measurement))


@pytest.mark.parametrize("clock", ["2026-10-20T12:00:00", "2026-10-20T12:00:00.1234567Z", "2026-10-20T12:00:00+01:60", "0999-12-31T23:59:59Z", True, None])
def test_clocks_require_explicit_valid_utc_and_mysql_precision(clock):
    with pytest.raises(ValidationError):
        sources.MapPayload.model_validate(map_payload(observed_at=clock))
    with pytest.raises(ValidationError):
        sources.RespiratorySupportPayload.model_validate(support_payload(start_at=clock))


@pytest.mark.parametrize("mode", ["none", "invasive_mechanical", "noninvasive_positive_pressure", "high_flow_nasal", "low_flow_oxygen", "other", "unknown"])
def test_all_explicit_support_modes_record_original_without_scoring(mode):
    data = sources.RespiratorySupportPayload.model_validate(support_payload(delivery_mode=mode)).model_dump(mode="json")
    assert data["delivery_mode"] == mode and data["continuity_confirmed"] is False
    assert data["continuity_basis_note"] is data["ended_at"] is data["device_description"] is None
    event, refs = sources.prepare_respiratory_support(None, 1, "original-admission", data, NOW)
    assert event == datetime.datetime(2026, 10, 20, 11, 0, 0, 111111) and refs == {}
    assert set(data) == set(support_payload())


@pytest.mark.parametrize(
    "changes",
    [
        {"start_at": "2026-10-20T12:00:00.123456Z"},
        {"start_at": "2026-10-20T12:00:00.123457Z"},
        {"ended_at": "2026-10-20T12:00:00.123455Z"},
        {"continuity_confirmed": True},
        {"continuity_basis_note": NOTE},
        {"continuity_confirmed": 1},
        {"continuity_confirmed": "true"},
        {"continuity_confirmed": True, "continuity_basis_note": " " * 20},
    ],
)
def test_support_never_invents_duration_stop_or_continuity(changes):
    with pytest.raises(ValidationError):
        sources.RespiratorySupportPayload.model_validate(support_payload(**changes))


def test_actual_stop_is_same_instant_after_utc_canonicalization():
    data = sources.RespiratorySupportPayload.model_validate(support_payload(ended_at="2026-10-20T20:00:00.123456+08:00", continuity_confirmed=True, continuity_basis_note=NOTE)).model_dump(mode="json")
    assert data["ended_at"] == data["verified_until_at"] == "2026-10-20T12:00:00.123456Z"


@pytest.mark.parametrize(
    "prepare,payload",
    [(sources.prepare_map, map_payload(observed_at="2026-10-20T12:30:45.123457Z")), (sources.prepare_respiratory_support, support_payload(verified_until_at="2026-10-20T12:30:45.123457Z"))],
)
def test_measurement_and_verified_interval_cannot_extend_one_microsecond_past_registration(prepare, payload):
    with pytest.raises(HTTPException) as error:
        prepare(None, 1, "original-admission", payload, NOW)
    assert error.value.status_code == 422


def test_pair_false_declarations_are_real_unresolved_review_not_implicit_scoring_proof():
    original = pair_payload()
    assert sources.ArterialPairPayload.model_validate(original).model_dump(mode="json") == original


@pytest.mark.parametrize("field", ["arterial_sample_confirmed", "same_sampling_state_confirmed", "fio2_applicability_confirmed"])
@pytest.mark.parametrize("value", [0, 1, "false", None])
def test_pair_requires_real_boolean_clinician_declaration(field, value):
    with pytest.raises(ValidationError):
        sources.ArterialPairPayload.model_validate(pair_payload(**{field: value}))


@pytest.mark.parametrize("model,payload", [(sources.MapPayload, map_payload()), (sources.RespiratorySupportPayload, support_payload()), (sources.ArterialPairPayload, pair_payload())])
@pytest.mark.parametrize("extra", ["recorded_at", "as_of", "score", "probability"])
def test_source_payloads_reject_injected_clocks_or_derived_claims(model, payload, extra):
    with pytest.raises(ValidationError):
        model.model_validate({**payload, extra: "injected"})


@pytest.mark.parametrize("model", [InpatientMapSource, InpatientRespiratorySource, InpatientArterialPairSource])
def test_independent_mysql_source_tables_preserve_full_references_and_three_microsecond_clocks(model):
    ddl = str(CreateTable(model.__table__).compile(dialect=mysql.dialect()))
    assert ddl.count("DATETIME(6)") == 3 and "reference_snapshot_json MEDIUMTEXT NOT NULL" in ddl
    assert "event_at IS NULL OR event_at <= recorded_at" in ddl
    assert "status = 'active' AND revision = 1" in ddl and "status = 'revoked' AND revision = 2" in ddl
    assert len(model.__table__.columns) == 16
    assert {tuple(index.columns.keys()) for index in model.__table__.indexes} == {("patient_id", "admission_id", "event_at"), ("recorded_at",)}
