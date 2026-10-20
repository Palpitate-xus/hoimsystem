"""Synthetic manual-component API/DB checks, without clinical prediction claims."""

import datetime
import json
import uuid
from copy import deepcopy

import pytest

from app.clinical_scores import CALCULATION_VERSION, compute_manual_score
from app.models import Admission, IcuScoreRecord

# Independently specified editions/components: GCS official assessment aid;
# Vincent et al. 1996 SOFA; Knaus et al. 1985 APACHE II; Aldrete/Kroulik 1970
# colour-based PARS; Steward 1975 (doi:10.1007/BF03004827).
CASES = [
    ("gcs", {"eye": 3, "verbal": 4, "motor": 5}, 12, "gcs_e4_v5_m6"),
    ("sofa", {"resp_score": 2, "coag_score": 1, "liver_score": 0, "cardio_score": 3, "neuro_score": 4, "renal_score": 2}, 12, "sofa_1996"),
    ("apache2", {"aps_total": 17, "age_points": 3, "chronic_health_points": 2}, 22, "apache_ii_1985_manual_aps"),
    ("aldrete", {"activity_score": 2, "respiration_score": 2, "circulation_score": 1, "consciousness_score": 2, "color_score": 1}, 8, "aldrete_1970_color"),
    ("steward", {"wake_score": 2, "airway_score": 1, "motor_score": 2}, 5, "steward_1975"),
]


def payload(seed_data, score_type="gcs", detail=None, **extra):
    return {"patient_id": seed_data["patient"].patient_id, "score_type": score_type, "scene": "icu", "detail": {"eye": 3, "verbal": 4, "motor": 5} if detail is None else deepcopy(detail), **extra}


def add_admission(db_session, seed_data, *, other_patient=False):
    item = Admission(
        admission_id=str(uuid.uuid4()),
        admission_no="SC" + uuid.uuid4().hex[:18],
        patient_id=seed_data["patient2" if other_patient else "patient"].patient_id,
        doctor_id=seed_data["doctor"].doctor_id,
        department_id=seed_data["department"].department_id,
        status=1,
        admission_time=datetime.datetime(2026, 1, 2, 8),
        create_time=datetime.datetime(2026, 1, 2, 8),
    )
    db_session.add(item)
    db_session.commit()
    return item


async def reject_without_write(async_client, db_session, headers, request, code=400):
    before = db_session.query(IcuScoreRecord).count()
    response = await async_client.post("/api/icuScore/create", headers=headers, json=request)
    assert response.status_code == code, response.text
    assert response.json()["code"] == code, (request, response.json())
    assert db_session.query(IcuScoreRecord).count() == before
    return response.json()


@pytest.mark.asyncio
@pytest.mark.parametrize("score_type,detail,total,edition", CASES, ids=[case[0] for case in CASES])
async def test_complete_manual_components_persist_exact_source_and_sum(async_client, db_session, seed_data, auth_headers, score_type, detail, total, edition):
    admission = add_admission(db_session, seed_data)
    headers = auth_headers(seed_data["nurse_user"].username)
    assessed = "2026-01-02T16:20:30.123456+08:00"
    response = await async_client.post("/api/icuScore/create", headers=headers, json=payload(seed_data, score_type, detail, admission_id=admission.admission_id, assessed_at=assessed))
    assert response.status_code == 200 and response.json()["code"] == 200, response.text
    data = response.json()["data"]
    assert data["total_score"] == total and data["detail"] == detail
    assert data["calculation_version"] == CALCULATION_VERSION == "manual_components_v2"
    assert data["score_definition"] == edition and data["legacy_unverified"] is False
    assert data["source_verification"] == "not_independently_verified" and data["clinical_validation"] == "not_provided"
    assert data["calculation_method"] == "manual_component_sum"
    assert data["component_integrity"] == {
        "status": "complete",
        "required_keys": list(detail),
        "missing_keys": [],
        "unexpected_keys": [],
        "invalid_keys": [],
        "total_matches": True,
        "source_verification": "not_independently_verified",
    }
    assert data["assessed_at"] == "2026-01-02T08:20:30.123456Z" and data["time_basis"] == "assessed_at_declared"
    assert data["assess_time"] and data["create_time"] and "人工" in data["interpretation"]
    assert "来源未独立核实" in data["interpretation"]
    assert not any(old in data["interpretation"] for old in ("死亡风险分级：", "脏器功能：良好", "达 PACU 转出标准（≥9）", "达转出标准（≥4）"))
    saved = db_session.get(IcuScoreRecord, data["score_id"])
    assert saved.admission_id == admission.admission_id and saved.patient_id == admission.patient_id
    assert saved.assessed_at == datetime.datetime(2026, 1, 2, 8, 20, 30, 123456)
    assert saved.calculation_version == CALCULATION_VERSION and saved.total_score == total
    assert json.loads(saved.detail_json) == detail
    listed = await async_client.get("/api/icuScore/getList", headers=headers, params={"patient_id": saved.patient_id})
    row = next(item for item in listed.json()["data"] if item["score_id"] == saved.score_id)
    assert row["assessed_at"] == data["assessed_at"] and row["detail"] == detail
    if score_type == "apache2":
        assert "外部人工小计" in row["interpretation"] and "未自动评估12项" in row["interpretation"]
    if score_type == "aldrete":
        assert "肤色" in row["score_type_text"] and "1995" in row["interpretation"]


@pytest.mark.asyncio
@pytest.mark.parametrize("score_type,detail,_total,_edition", CASES, ids=[case[0] for case in CASES])
async def test_empty_partial_and_unknown_components_never_become_normal_scores(async_client, db_session, seed_data, auth_headers, score_type, detail, _total, _edition):
    headers = auth_headers("doc01")
    for invalid in ({}, None, [], False, ""):
        request = payload(seed_data, score_type, detail)
        request["detail"] = invalid
        await reject_without_write(async_client, db_session, headers, request)
    for key in detail:
        partial = {field: value for field, value in detail.items() if field != key}
        result = await reject_without_write(async_client, db_session, headers, payload(seed_data, score_type, partial))
        assert key in result["msg"]
    await reject_without_write(async_client, db_session, headers, payload(seed_data, score_type, {**detail, "arbitrary_score": 0}))


@pytest.mark.asyncio
@pytest.mark.parametrize("score_type,detail,_total,_edition", CASES, ids=[case[0] for case in CASES])
async def test_each_component_requires_a_true_integer_in_its_own_range(async_client, db_session, seed_data, auth_headers, score_type, detail, _total, _edition):
    headers = auth_headers("doc01")
    for key in detail:
        maximum = (4 if key == "eye" else 5 if key == "verbal" else 6) if score_type == "gcs" else 4 if score_type == "sofa" else 2
        if score_type == "apache2":
            maximum = {"aps_total": 60, "age_points": 6, "chronic_health_points": 5}[key]
        minimum = 1 if score_type == "gcs" else 0
        for value in (minimum - 1, maximum + 1, True, "1", 1.0, 1.5, None):
            await reject_without_write(async_client, db_session, headers, payload(seed_data, score_type, {**detail, key: value}))
    if score_type == "apache2":
        for key, values in (("age_points", (1, 4)), ("chronic_health_points", (1, 3, 4))):
            for value in values:
                await reject_without_write(async_client, db_session, headers, payload(seed_data, score_type, {**detail, key: value}))
    if score_type == "gcs":
        for key in detail:
            result = await reject_without_write(async_client, db_session, headers, payload(seed_data, score_type, {**detail, key: "NT"}))
            assert "NT" in result["msg"]


@pytest.mark.asyncio
@pytest.mark.parametrize("scene", ("icu", "pacu"))
async def test_optional_admission_and_unknown_assessment_time_stay_explicit(async_client, db_session, seed_data, auth_headers, scene):
    headers = auth_headers("doc01")
    for admission_value in (None, "", "   "):
        response = await async_client.post("/api/icuScore/create", headers=headers, json=payload(seed_data, admission_id=admission_value, scene=scene))
        assert response.json()["code"] == 200, response.text
        data = response.json()["data"]
        assert data["admission_id"] is None and data["admission_linkage"] == "not_recorded"
        assert data["assessed_at"] is None and data["time_basis"] == "assessment_time_unknown"
        assert data["assess_time"] and data["create_time"]
        assert db_session.get(IcuScoreRecord, data["score_id"]).assessed_at is None


@pytest.mark.asyncio
async def test_patient_and_supplied_admission_must_exist_and_match(async_client, db_session, seed_data, auth_headers):
    headers = auth_headers("doc01")
    other = add_admission(db_session, seed_data, other_patient=True)
    for admission in ("missing-admission", other.admission_id):
        await reject_without_write(async_client, db_session, headers, payload(seed_data, admission_id=admission))
    for invalid in (42, True, [], {}, "x" * 37):
        await reject_without_write(async_client, db_session, headers, payload(seed_data, admission_id=invalid))
    await reject_without_write(async_client, db_session, headers, payload(seed_data, patient_id=2**31 - 1), code=404)
    for invalid in ("1", True, 1.0, None, 0, -1, 2**64):
        await reject_without_write(async_client, db_session, headers, payload(seed_data, patient_id=invalid))


@pytest.mark.asyncio
async def test_request_keys_scene_and_time_do_not_coerce_unknown_values(async_client, db_session, seed_data, auth_headers):
    headers = auth_headers("doc01")
    for key in ("total_score", "interpretation", "assessor_id", "calculation_version", "create_time", "additional_score"):
        await reject_without_write(async_client, db_session, headers, payload(seed_data, **{key: 0}))
    for scene in ("ward", "ICU", "", None, True, 1, [], {}):
        await reject_without_write(async_client, db_session, headers, payload(seed_data, scene=scene))
    for score_type in ("GCS", "gcs ", "unknown", None, True, [], {}):
        await reject_without_write(async_client, db_session, headers, payload(seed_data, score_type=score_type))
    for assessed in ("", "2026-01-02", "2026-01-02T12:00:00", "not-a-time", "2026-99-02T12:00:00Z", 0, True, [], {}):
        await reject_without_write(async_client, db_session, headers, payload(seed_data, assessed_at=assessed))
    for key in ("patient_id", "score_type", "detail"):
        request = payload(seed_data)
        request.pop(key)
        await reject_without_write(async_client, db_session, headers, request)
    request = payload(seed_data)
    request.pop("scene")
    response = await async_client.post("/api/icuScore/create", headers=headers, json=request)
    assert response.status_code == 200 and response.json()["code"] == 200
    assert response.json()["data"]["scene"] == "icu" and response.json()["data"]["admission_id"] is None
    assert response.json()["data"]["time_basis"] == "assessment_time_unknown"


@pytest.mark.asyncio
@pytest.mark.parametrize("detail", ({}, {"eye": 4, "verbal": 5, "motor": 6}, {"arbitrary_score": 15}, None, "broken-json"))
async def test_legacy_records_keep_original_total_text_and_unknown_time(async_client, db_session, seed_data, auth_headers, detail):
    original = "历史原解释（未独立核实），不得改写"
    record_time = datetime.datetime(2001, 2, 3, 4, 5, 6)
    raw = "{bad" if detail == "broken-json" else json.dumps(detail)
    item = IcuScoreRecord(
        patient_id=seed_data["patient"].patient_id,
        score_type="gcs",
        scene="icu",
        total_score=7,
        detail_json=raw,
        interpretation=original,
        assessor_id=seed_data["nurse_user"].user_id,
        assess_time=record_time,
        create_time=record_time,
    )
    db_session.add(item)
    db_session.commit()
    response = await async_client.get("/api/icuScore/getList", headers=auth_headers("doc01"), params={"patient_id": item.patient_id})
    row = next(data for data in response.json()["data"] if data["score_id"] == item.score_id)
    assert row["total_score"] == 7 and row["interpretation"] == original
    assert row["calculation_version"] == "legacy_unverified" and row["legacy_unverified"] is True
    assert row["component_integrity"]["status"] == "legacy_unverified" and row["component_integrity"]["total_matches"] is None
    assert row["score_definition"] == "legacy_unverified" and row["calculation_method"] == "legacy_unverified"
    assert row["assessed_at"] is None and row["assess_time"] == "2001-02-03 04:05:06"
    assert row["time_basis"] == "assessment_time_unknown" and row["source_verification"] == "not_independently_verified"
    db_session.refresh(item)
    assert item.total_score == 7 and item.interpretation == original and item.detail_json == raw
    assert item.calculation_version == "legacy_unverified" and item.assessed_at is None


@pytest.mark.asyncio
async def test_corrupt_current_total_is_flagged_without_repairing_database(async_client, db_session, seed_data, auth_headers):
    detail = {"eye": 3, "verbal": 4, "motor": 5}
    item = IcuScoreRecord(
        patient_id=seed_data["patient"].patient_id,
        score_type="gcs",
        scene="icu",
        total_score=15,
        detail_json=json.dumps(detail),
        calculation_version=CALCULATION_VERSION,
        interpretation="原存储文本",
        assessor_id=seed_data["nurse_user"].user_id,
        assess_time=datetime.datetime(2026, 1, 2),
        create_time=datetime.datetime(2026, 1, 2),
    )
    db_session.add(item)
    db_session.commit()
    response = await async_client.get("/api/icuScore/getList", headers=auth_headers("doc01"))
    row = next(data for data in response.json()["data"] if data["score_id"] == item.score_id)
    assert row["total_score"] == 15 and row["interpretation"] == "原存储文本"
    assert row["component_integrity"]["status"] == "invalid" and row["component_integrity"]["total_matches"] is False
    db_session.refresh(item)
    assert item.total_score == 15 and json.loads(item.detail_json) == detail


@pytest.mark.parametrize(
    "score_type,detail,total",
    [
        ("gcs", {"eye": 1, "verbal": 1, "motor": 1}, 3),
        ("gcs", {"eye": 4, "verbal": 5, "motor": 6}, 15),
        ("sofa", {"resp_score": 0, "coag_score": 0, "liver_score": 0, "cardio_score": 0, "neuro_score": 0, "renal_score": 0}, 0),
        ("sofa", {"resp_score": 4, "coag_score": 4, "liver_score": 4, "cardio_score": 4, "neuro_score": 4, "renal_score": 4}, 24),
        ("apache2", {"aps_total": 0, "age_points": 0, "chronic_health_points": 0}, 0),
        ("apache2", {"aps_total": 60, "age_points": 6, "chronic_health_points": 5}, 71),
        ("aldrete", {"activity_score": 0, "respiration_score": 0, "circulation_score": 0, "consciousness_score": 0, "color_score": 0}, 0),
        ("aldrete", {"activity_score": 2, "respiration_score": 2, "circulation_score": 2, "consciousness_score": 2, "color_score": 2}, 10),
        ("steward", {"wake_score": 0, "airway_score": 0, "motor_score": 0}, 0),
        ("steward", {"wake_score": 2, "airway_score": 2, "motor_score": 2}, 6),
    ],
)
def test_explicit_boundary_components_are_valid_manual_sums(score_type, detail, total):
    assert compute_manual_score(score_type, detail)[0] == total


@pytest.mark.parametrize("score_type,detail", [(None, {}), ([], {}), ("unknown", {}), ("gcs", []), ("gcs", None)])
def test_pure_function_always_rejects_invalid_structure_with_value_error(score_type, detail):
    with pytest.raises(ValueError):
        compute_manual_score(score_type, detail)
