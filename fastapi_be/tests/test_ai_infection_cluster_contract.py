"""Synthetic pure contracts only; no SQL, Source authority or clinical evidence."""

import copy
import json
import subprocess
import sys

import pytest
from pydantic import ValidationError

from app.ai import infection_cluster_contract as c

CAPTURED = "2026-10-21T12:00:00.123456Z"
BASIS = "\ufeff明确本次人工复核依据\r\n原值不得归一化😀e\u0301。"


def identifier(value):
    return f"00000000-0000-0000-0000-{value:012d}"


def stamp(assessed=False):
    return (
        {"reviewed_by": 7, "reviewed_at": "2026-10-21T11:00:00.123456Z", "basis_note": BASIS, "basis_hash": c.text_digest(BASIS)}
        if assessed
        else dict.fromkeys(("reviewed_by", "reviewed_at", "basis_note", "basis_hash"))
    )


def row(case_id=1, patient_id=2147483001, **overrides):
    value = {
        "case_id": identifier(case_id),
        "patient_id": patient_id,
        "department_id": 2147483002,
        "infection_type": "\ufeff原感染私有标签\r\n😀",
        "pathogen": "原病原私有标签e\u0301",
        "onset_date": "2026-10-15",
        "severity": 3,
        "status": 2,
        "description": "PRIVATE_CLINICAL_DESCRIPTION\ufeff\r\n姓名与联系方式不进入模型😀",
        "reporter_id": 2147483003,
        "create_time": {"text": "2026-10-15T09:00:00.123456", "basis": "stored_naive_timezone_unknown"},
        "update_time": {"text": "2026-10-16T10:00:00", "basis": "stored_naive_timezone_unknown"},
    }
    value.update(overrides)
    return value


def definition():
    payload = {
        "definition_id": identifier(7800),
        "version_label": "本地人工声明版本\ufeffv1",
        "definition_text": "SYNTHETIC_LOCAL_DEFINITION\r\n非官方监测定义，不是临床确诊。",
        "infection_type_codes": ["LOCAL_TYPE"],
        "pathogen_codes": ["LOCAL_PATHOGEN"],
        "authored_by": 5,
        "recorded_at": "2026-10-21T09:00:00.123456Z",
        "authority_basis": "local_human_declaration_not_official_or_clinically_validated",
    }
    governance = {
        "status": "published",
        "revision": 2,
        "published_by": 6,
        "published_at": "2026-10-21T10:00:00.123456Z",
        "publication_basis_note": BASIS,
        "publication_basis_hash": c.text_digest(BASIS),
        "verification_basis": "declared_actor_and_clock_structure_only_not_current_authority",
    }
    return {"payload": payload, "content_hash": c.digest(payload), "governance": governance, "governance_hash": c.digest(governance)}


def mapping(name, raw, mapped=False):
    return {
        "field": name,
        "original_state": c.value_state(raw),
        "original_value_hash": c.digest(raw),
        "assessment": "mapped" if mapped else "not_assessed",
        "reviewed_code": ("LOCAL_TYPE" if name == "infection_type" else "LOCAL_PATHOGEN") if mapped else None,
        "review": stamp(mapped),
    }


def collection(rows=None, assessment="not_assessed"):
    rows = [row()] if rows is None else rows
    d = definition()
    originals = [{"original": r, "content_hash": c.digest(r)} for r in rows]
    reviews = [
        {
            "case_id": r["case_id"],
            "original_content_hash": p["content_hash"],
            "definition_content_hash": d["content_hash"],
            "definition_governance_hash": d["governance_hash"],
            "assessment": assessment,
            "review": stamp(assessment != "not_assessed"),
            "infection_type": mapping("infection_type", r["infection_type"]),
            "pathogen": mapping("pathogen", r["pathogen"]),
        }
        for r, p in zip(rows, originals)
    ]
    return {
        "schema_version": "infection_cluster_private_collection_v1",
        "collection_id": identifier(78),
        "captured_at": CAPTURED,
        "patient_ids": [2147483001, 2147483004],
        "window": {"date_from": "2026-10-01", "date_to": "2026-10-31", "coordinate_basis": "recorded_onset_date_inclusive_no_event_timezone"},
        "definition": d,
        "originals": originals,
        "reviews": reviews,
        "declared_capture_scope": "all_infection_case_rows_for_explicit_patients_and_onset_window_all_statuses",
        "completeness_basis": "caller_declared_requires_later_server_current_collection_proof",
    }


def test_full_private_row_roundtrip_keeps_all_twelve_fields_bom_crlf_and_naive_precision():
    value = collection()
    checked = c.verify_private_collection(c.canonical(value).encode())
    actual = checked.originals[0].original.model_dump(mode="json")
    assert actual == value["originals"][0]["original"] and len(actual) == 12
    assert actual["description"].encode() == row()["description"].encode()
    assert actual["create_time"]["text"].endswith(".123456")
    assert actual["update_time"]["text"] == "2026-10-16T10:00:00"
    assert checked.model_dump(mode="json") == value


@pytest.mark.parametrize("field", ["description", "pathogen", "department_id"])
def test_null_is_distinct_from_empty_or_a_recorded_value(field):
    a = row(**{field: None})
    b = row(**{field: "" if field != "department_id" else 1})
    assert c.verify_private_collection(collection([a])).originals[0].content_hash != c.verify_private_collection(collection([b])).originals[0].content_hash


@pytest.mark.parametrize("value", [0, 1, 2, -1, 99])
def test_raw_workflow_status_never_assigns_a_case_classification(value):
    checked = c.verify_private_collection(collection([row(status=value)]))
    assert checked.originals[0].original.status == value and checked.reviews[0].assessment == "not_assessed"


@pytest.mark.parametrize("assessment", ["meets_definition", "does_not_meet", "undetermined", "not_assessed"])
def test_each_explicit_human_assessment_is_retained_independently(assessment):
    assert c.verify_private_collection(collection(assessment=assessment)).reviews[0].assessment == assessment


@pytest.mark.parametrize("mutation", ["duplicate_root", "missing_review", "extra_review", "duplicate_review", "root_change", "definition_change", "governance_change"])
def test_complete_root_and_review_membership_is_not_silently_repaired(mutation):
    value = collection()
    if mutation == "duplicate_root":
        value["originals"].append(copy.deepcopy(value["originals"][0]))
    if mutation == "missing_review":
        value["reviews"] = []
    if mutation == "extra_review":
        extra = copy.deepcopy(value["reviews"][0])
        extra["case_id"] = identifier(2)
        value["reviews"].append(extra)
    if mutation == "duplicate_review":
        value["reviews"].append(copy.deepcopy(value["reviews"][0]))
    if mutation == "root_change":
        value["originals"][0]["original"]["description"] += "正文已变"
    if mutation == "definition_change":
        value["definition"]["payload"]["definition_text"] += "新版"
    if mutation == "governance_change":
        value["definition"]["governance"]["publication_basis_note"] += "新依据"
    with pytest.raises(ValueError):
        c.verify_private_collection(value)


def test_rehashing_a_changed_root_does_not_rebind_the_old_review():
    value = collection()
    value["originals"][0]["original"]["status"] = 1
    value["originals"][0]["content_hash"] = c.digest(value["originals"][0]["original"])
    with pytest.raises(ValueError, match="Every case review binds"):
        c.verify_private_collection(value)


@pytest.mark.parametrize("field", ["patient_id", "department_id", "reporter_id", "severity", "status"])
def test_sql_integer_fields_reject_bool_string_or_float(field):
    for raw in [True, "1", 1.0]:
        with pytest.raises(ValueError):
            c.verify_private_collection(collection([row(**{field: raw})]))


@pytest.mark.parametrize("mutation", ["patient", "window", "unmatched_definition", "self_publish", "future_publish", "future_review", "unknown_code", "normalize_label"])
def test_scope_definition_and_literal_taxonomy_are_exact(mutation):
    value = collection()
    if mutation == "patient":
        value["patient_ids"] = [2]
    if mutation == "window":
        value["window"]["date_to"] = "2026-10-14"
    if mutation == "unmatched_definition":
        value["reviews"][0]["definition_content_hash"] = "0" * 64
    if mutation == "self_publish":
        d = value["definition"]
        d["governance"]["published_by"] = 5
        d["governance_hash"] = c.digest(d["governance"])
    if mutation == "future_publish":
        d = value["definition"]
        d["governance"]["published_at"] = "2026-10-21T13:00:00.123456Z"
        d["governance_hash"] = c.digest(d["governance"])
        value["reviews"][0]["definition_governance_hash"] = d["governance_hash"]
    if mutation == "future_review":
        value["reviews"][0]["review"] = stamp(True)
        value["reviews"][0]["review"]["reviewed_at"] = "2026-10-21T13:00:00.123456Z"
    if mutation == "unknown_code":
        value["reviews"][0]["pathogen"] = mapping("pathogen", row()["pathogen"], True)
        value["reviews"][0]["pathogen"]["reviewed_code"] = "UNDECLARED_CODE"
    if mutation == "normalize_label":
        value["reviews"][0]["infection_type"]["original_value_hash"] = c.digest(row()["infection_type"].replace("\ufeff", "").replace("\r\n", "\n"))
    with pytest.raises(ValueError):
        c.verify_private_collection(value)


@pytest.mark.parametrize("raw", [None, ""])
def test_null_empty_pathogen_cannot_be_mapped_to_a_detected_pathogen(raw):
    value = collection([row(pathogen=raw)])
    value["reviews"][0]["pathogen"] = mapping("pathogen", raw, True)
    with pytest.raises(ValueError, match="NULL or empty"):
        c.verify_private_collection(value)


def test_naive_clock_never_acquires_utc_or_historical_availability():
    checked = c.verify_private_collection(collection([row(create_time={"text": "2099-01-01T00:00:00", "basis": "stored_naive_timezone_unknown"})]))
    assert checked.originals[0].original.create_time.text.startswith("2099")
    value = collection()
    value["originals"][0]["original"]["create_time"]["text"] += "Z"
    value["originals"][0]["content_hash"] = c.digest(value["originals"][0]["original"])
    with pytest.raises(ValueError, match="naive"):
        c.verify_private_collection(value)


def test_calendar_bool_duplicate_json_and_nonfinite_are_rejected():
    for bad in ["2026-02-30", "2026-1-01", "2026-01-01T00:00:00Z"]:
        with pytest.raises(ValueError):
            c.verify_private_collection(collection([row(onset_date=bad)]))
    for raw in ['{"schema_version":"x","schema_version":"y"}', '{"value":NaN}', '{"value":Infinity}']:
        with pytest.raises(ValueError):
            c.verify_private_collection(raw)
    for revision in [2.0, "2", True]:
        with pytest.raises(ValidationError):
            c.DefinitionGovernance.model_validate({**definition()["governance"], "revision": revision})


def test_description_uses_codepoints_and_rejects_invalid_unicode():
    assert c.verify_private_collection(collection([row(description="😀" * 500)])).originals[0].original.description == "😀" * 500
    with pytest.raises(ValueError):
        c.verify_private_collection(collection([row(description="😀" * 501)]))
    with pytest.raises((ValueError, UnicodeError)):
        c.verify_private_collection(collection([row(description="\ud800")]))


def test_mutating_an_existing_model_is_revalidated():
    checked = c.verify_private_collection(collection())
    checked.originals[0].original.status = -9
    with pytest.raises(ValueError):
        c.verify_private_collection(checked)


def test_no_defaults_extras_or_silent_empty_patient_scope():
    value = collection()
    for name in ["reviews", "definition", "captured_at"]:
        bad = copy.deepcopy(value)
        del bad[name]
        with pytest.raises(ValueError):
            c.verify_private_collection(bad)
    for delta in [{"as_of": CAPTURED}, {"patient_ids": []}, {"patient_ids": [2147483001, 2147483001]}, {"denominator": 2}]:
        with pytest.raises(ValueError):
            c.verify_private_collection({**value, **delta})
    assert c.verify_private_collection(collection([])).originals == []


def test_whole_json_and_root_caps_refuse_instead_of_clipping():
    value = collection()
    value["originals"] *= c.MAX_ROOTS + 1
    with pytest.raises(ValueError):
        c.verify_private_collection(value)
    with pytest.raises(ValueError, match="8MiB"):
        c.verify_private_collection(b" " * (c.MAX_BYTES + 1))
    value = collection()
    value["definition"]["payload"]["definition_text"] = "😀" * (c.MAX_BYTES // 4)
    with pytest.raises(ValueError, match="8MiB"):
        c.verify_private_collection(value)
    with pytest.raises(ValueError, match="nesting"):
        c.verify_private_collection("[" * 33 + "0" + "]" * 33)


def test_import_is_pure_without_database_models_settings_or_network_clients():
    code = "import sys; import app.ai.infection_cluster_contract; assert not any(k in sys.modules for k in ('app.config','app.database','app.models','sqlalchemy','httpx','requests'))"
    p = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=False)
    assert p.returncode == 0, p.stderr
    assert json.loads(c.canonical(c.verify_private_collection(collection())))["schema_version"] == "infection_cluster_private_collection_v1"
