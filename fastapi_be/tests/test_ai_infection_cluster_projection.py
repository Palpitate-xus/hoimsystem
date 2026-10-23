"""Independent literal/HMAC/count tests; synthetic pure facts, not Source authority."""

import hashlib
import hmac
import json
import subprocess
import sys

import pytest

from app.ai import infection_cluster_contract as c
from app.ai import infection_cluster_projection as p
from tests.test_ai_infection_cluster_contract import BASIS, collection, mapping, row, stamp

KEY = bytes(range(32))


def values(value):
    if isinstance(value, dict):
        return [v for item in value.values() for v in values(item)]
    if isinstance(value, list):
        return [v for item in value for v in values(item)]
    return [value]


def keys(value):
    if isinstance(value, dict):
        return set(value) | set().union(*(keys(v) for v in value.values()))
    if isinstance(value, list):
        return set().union(*(keys(v) for v in value))
    return set()


def mapped_collection():
    value = collection(assessment="meets_definition")
    for name in ("infection_type", "pathogen"):
        value["reviews"][0][name] = mapping(name, value["originals"][0]["original"][name], True)
    return value


def test_public_whitelist_excludes_all_private_ids_labels_notes_and_clinical_text():
    private = mapped_collection()
    source = p.project_source(private, KEY).model_dump(mode="json")
    flattened = values(source)
    raw = private["originals"][0]["original"]
    for name in ("case_id", "patient_id", "department_id", "reporter_id", "description", "infection_type", "pathogen"):
        assert raw[name] not in flattened
    for text in (BASIS, private["definition"]["payload"]["version_label"], private["definition"]["payload"]["definition_text"], KEY.hex()):
        assert text not in c.canonical(source)
    assert not {"description", "reporter_id", "patient_id", "department_id", "case_id", "reviewed_by", "basis_note", "private_key", "create_time", "update_time", "severity"} & keys(source)
    assert p.verify_public_source(source, private, KEY)


def test_hmac_is_independently_recomputed_and_domain_separated():
    private = collection()
    source = p.project_source(private, KEY)
    message = json.dumps(
        ["infection_cluster_mapping_v1", private["collection_id"], hashlib.sha256(c.canonical(private).encode()).hexdigest(), "patient", private["patient_ids"][0]],
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    expected = hmac.new(KEY, message, hashlib.sha256).hexdigest()
    assert source.reports[0].patient_token == source.scope.patient_tokens[0] == expected
    assert source.reports[0].patient_token != source.reports[0].department_token != source.reports[0].case_token
    assert source.source_id.startswith("infection_reports:") and private["collection_id"] not in source.source_id


def test_mapping_key_changes_all_tokens_and_projection_but_not_private_hash():
    private = collection()
    a, b = p.project_source(private, KEY), p.project_source(private, b"X" * 32)
    assert a.private_collection_hash == b.private_collection_hash
    assert a.source_id != b.source_id and a.definition.definition_token != b.definition.definition_token
    assert a.reports[0].patient_token != b.reports[0].patient_token and a.reports[0].case_token != b.reports[0].case_token
    assert p.projection_digest(a) != p.projection_digest(b)
    assert not p.verify_public_source(a, private, b"X" * 32)


@pytest.mark.parametrize("key", [None, "X" * 32, b"X" * 31, b"X" * 33, bytearray(32)])
def test_key_has_exact_private_byte_contract(key):
    with pytest.raises(ValueError, match="private bytes"):
        p.project_source(collection(), key)


def test_multiple_reports_for_one_subject_are_never_merged_or_a_denominator():
    private = collection([row(1), row(2), row(3, patient_id=2147483004)])
    source = p.project_source(private, KEY)
    assert len(source.reports) == source.counts.distinct_records == 3
    assert source.counts.distinct_subjects_with_records == source.counts.declared_subjects == 2
    assert source.reports[0].patient_token == source.reports[1].patient_token != source.reports[2].patient_token
    assert len({v.case_token for v in source.reports}) == 3
    assert source.denominator.model_dump() == {"status": "not_provided", "reason": "legacy_infection_case_has_no_surveillance_population_denominator"}
    assert not {"rate", "probability", "normal", "outbreak", "diagnosis", "intervention"} & keys(source.model_dump())
    assert source.automatic_actions is False


def test_subjects_without_a_report_remain_scope_not_surveillance_population():
    source = p.project_source(collection([]), KEY)
    assert source.counts.distinct_records == source.counts.distinct_subjects_with_records == 0
    assert source.counts.declared_subjects == 2 and len(source.scope.patient_tokens) == 2
    assert source.denominator.status == "not_provided" and source.clinical_interpretation == "not_a_diagnosis_or_outbreak_determination"


@pytest.mark.parametrize("status,meaning", [(0, "reported"), (1, "investigating"), (2, "closed_recorded"), (-1, "unknown"), (17, "unknown")])
def test_workflow_status_never_decides_human_case_definition_or_detection(status, meaning):
    source = p.project_source(collection([row(status=status, pathogen=None)]), KEY)
    report = source.reports[0]
    assert report.recorded_status == status and report.recorded_status_meaning == meaning
    assert report.human_assessment == "not_assessed" and report.pathogen.reviewed_code is None
    assert "pathogen_null" in report.missing_basis
    assert source.counts.not_assessed == 1 and source.counts.meets_definition == 0
    assert "未检出" not in c.canonical(source)


def test_null_empty_whitespace_and_combining_labels_remain_distinct_without_normalization():
    rows = [row(1, pathogen=None, department_id=None), row(2, pathogen=""), row(3, pathogen=" "), row(4, pathogen="é"), row(5, pathogen="e\u0301")]
    source = p.project_source(collection(rows), KEY)
    assert [r.pathogen.original_state for r in source.reports] == ["null", "empty", "present", "present", "present"]
    assert source.reports[0].department_token is None and "department_not_recorded" in source.reports[0].missing_basis
    assert "pathogen_null" in source.reports[0].missing_basis and "pathogen_empty" in source.reports[1].missing_basis
    assert source.reports[3].original_content_hash != source.reports[4].original_content_hash
    assert all(r.pathogen.reviewed_code is None for r in source.reports)


def test_manually_mapped_codes_and_case_assessment_keep_separate_basis_hashes():
    private = mapped_collection()
    source = p.project_source(private, KEY)
    r = source.reports[0]
    assert r.human_assessment == "meets_definition" and r.infection_type.reviewed_code == "LOCAL_TYPE" and r.pathogen.reviewed_code == "LOCAL_PATHOGEN"
    assert r.assessment_basis_hash == c.text_digest(BASIS)
    assert r.case_review_hash == c.digest(private["reviews"][0])
    assert r.pathogen.review_hash == c.digest(private["reviews"][0]["pathogen"])
    assert source.counts.meets_definition == 1 and source.counts.not_assessed == 0


@pytest.mark.parametrize("assessment", ["does_not_meet", "undetermined", "not_assessed"])
def test_human_categories_have_exact_independent_counts(assessment):
    source = p.project_source(collection(assessment=assessment), KEY)
    assert getattr(source.counts, assessment) == 1 and source.reports[0].human_assessment == assessment
    assert source.counts.meets_definition == 0


@pytest.mark.parametrize("mutation", ["count", "patient", "case", "date", "classification", "status", "denominator", "note", "raw_id", "action"])
def test_self_rehashed_public_changes_cannot_verify_without_exact_private_reprojection(mutation):
    private = collection()
    source = p.project_source(private, KEY).model_dump(mode="json")
    if mutation == "count":
        source["counts"]["distinct_records"] = 2
    if mutation == "patient":
        source["reports"][0]["patient_token"] = "f" * 64
    if mutation == "case":
        source["reports"][0]["case_token"] = "f" * 64
    if mutation == "date":
        source["reports"][0]["onset_date"] = "2026-10-14"
    if mutation == "classification":
        source["reports"][0]["human_assessment"] = "undetermined"
        source["reports"][0]["assessment_basis_hash"] = "f" * 64
        source["counts"]["undetermined"] = 1
        source["counts"]["not_assessed"] = 0
    if mutation == "status":
        source["reports"][0]["recorded_status"] = 0
        source["reports"][0]["recorded_status_meaning"] = "reported"
    if mutation == "denominator":
        source["denominator"] = {"status": "provided", "population": 2}
    if mutation == "note":
        source["limitations"] = []
    if mutation == "raw_id":
        source["reports"][0]["patient_id"] = private["patient_ids"][0]
    if mutation == "action":
        source["automatic_actions"] = True
    assert len(c.digest(source)) == 64  # A new SHA alone cannot certify the numbers or bindings.
    assert not p.verify_public_source(source, private, KEY)


def test_reused_private_capture_uuid_still_does_not_expose_original_case_uuid():
    private = collection()
    private["collection_id"] = private["originals"][0]["original"]["case_id"]
    source = p.project_source(private, KEY)
    assert private["collection_id"] not in c.canonical(source)


def test_original_review_change_after_projection_requires_a_different_complete_source():
    private = collection()
    source = p.project_source(private, KEY)
    private["reviews"][0]["assessment"] = "undetermined"
    private["reviews"][0]["review"] = stamp(True)
    assert not p.verify_public_source(source, private, KEY)
    updated = p.project_source(private, KEY)
    assert updated.private_collection_hash != source.private_collection_hash
    assert updated.reports[0].case_token != source.reports[0].case_token and updated.counts.undetermined == 1


def test_4096_actual_distinct_roots_below_whole_cap_are_all_retained_with_no_threshold():
    private = collection([row(i + 1, department_id=None, infection_type="", pathogen=None, description=None, status=i % 4 - 1) for i in range(c.MAX_ROOTS)])
    raw = c.canonical(private)
    assert len(raw.encode()) < c.MAX_BYTES
    checked = c.verify_private_collection(raw.encode())
    source = p.project_source(checked, KEY)
    assert len(checked.originals) == len(checked.reviews) == len(source.reports) == source.counts.distinct_records == 4096
    assert source.counts.distinct_subjects_with_records == 1 and source.counts.not_assessed == 4096
    assert source.denominator.status == "not_provided" and len(c.canonical(source).encode()) < c.MAX_BYTES
    assert source.reports[0].case_token != source.reports[-1].case_token


def test_exact_8mib_private_canonical_is_accepted_but_one_extra_byte_is_refused():
    private = collection()
    private["definition"]["payload"]["definition_text"] = "X"
    private["definition"]["content_hash"] = c.digest(private["definition"]["payload"])
    private["definition"]["governance"]["definition_content_hash"] = private["definition"]["content_hash"]
    private["definition"]["governance_hash"] = c.digest(private["definition"]["governance"])
    private["reviews"][0]["definition_governance_hash"] = private["definition"]["governance_hash"]
    private["reviews"][0]["definition_content_hash"] = private["definition"]["content_hash"]
    spare = c.MAX_BYTES - len(c.canonical(private).encode())
    private["definition"]["payload"]["definition_text"] += "X" * spare
    private["definition"]["content_hash"] = c.digest(private["definition"]["payload"])
    private["definition"]["governance"]["definition_content_hash"] = private["definition"]["content_hash"]
    private["definition"]["governance_hash"] = c.digest(private["definition"]["governance"])
    private["reviews"][0]["definition_governance_hash"] = private["definition"]["governance_hash"]
    private["reviews"][0]["definition_content_hash"] = private["definition"]["content_hash"]
    raw = c.canonical(private).encode()
    assert len(raw) == c.MAX_BYTES
    checked = c.verify_private_collection(raw)
    source = p.project_source(checked, KEY)
    assert checked.definition.payload.definition_text == private["definition"]["payload"]["definition_text"]
    assert source.private_collection_hash == hashlib.sha256(raw).hexdigest()
    with pytest.raises(ValueError, match="8MiB"):
        c.verify_private_collection(raw + b" ")


def test_public_scalar_types_remain_literal_and_models_are_not_trusted_after_mutation():
    private = collection()
    source = p.project_source(private, KEY)
    altered = source.model_dump()
    altered["automatic_actions"] = 0
    assert not p.verify_public_source(altered, private, KEY)
    source.counts.not_assessed = 0
    assert not p.verify_public_source(source, private, KEY)


def test_projection_import_does_not_load_any_hospital_db_permission_or_network_module():
    code = "import sys; import app.ai.infection_cluster_projection; assert not any(k in sys.modules for k in ('app.config','app.database','app.models','app.dependencies','sqlalchemy','httpx','requests'))"
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    assert p.InfectionClusterSource.model_json_schema()["additionalProperties"] is False
