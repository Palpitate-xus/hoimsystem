"""Exact internal receipt references; public draft content remains unchanged."""

import copy

import pytest

from app.ai import document_evidence_contract as c
from app.ai.document_extraction_run_record import encode_record, parse_record, record_marker
from tests.test_ai_document_extraction_result import result

CID = "00000000-0000-0000-0000-000000000071"


def record():
    value, _ = result()
    return c.parse_json(encode_record(value, 7))


def test_receipt_and_saved_reference_preserve_full_typed_result_and_stable_result_hash():
    value, _ = result()
    first = encode_record(value, 7)
    saved = encode_record(value, 7, {"0": {"candidate_id": CID, "audit_event_id": 8}})
    assert first != saved
    assert parse_record(saved).result == value
    assert c.digest(parse_record(first).result) == c.digest(parse_record(saved).result) == c.digest(value)
    assert parse_record(saved).receipt_event_id == 7
    assert parse_record(saved).saved_candidates["0"].audit_event_id == 8
    assert parse_record(encode_record(None, 9)).result is None
    assert record_marker(c.parse_json(saved)) and not record_marker(value.model_dump(mode="json"))


@pytest.mark.parametrize("receipt", [None, False, True, 0, -1, 1.0, "1", 2147483648])
def test_receipt_requires_actual_positive_database_integer(receipt):
    changed = record()
    changed["receipt_event_id"] = receipt
    with pytest.raises(ValueError):
        parse_record(c.canonical_json(changed))


@pytest.mark.parametrize(
    "mutation", ["extra", "missing", "ordinal", "noncanonical_ordinal", "null_result", "duplicate_candidate", "duplicate_audit", "receipt_as_save", "save_extra", "boolean_audit", "bad_uuid"]
)
def test_closed_ordinals_actual_draft_members_and_distinct_audit_identities(mutation):
    value = record()
    value["saved_candidates"] = {"0": {"candidate_id": CID, "audit_event_id": 8}}
    if mutation == "extra":
        value["other_analysis"] = {}
    elif mutation == "missing":
        del value["saved_candidates"]
    elif mutation == "ordinal":
        value["saved_candidates"]["2"] = value["saved_candidates"].pop("0")
    elif mutation == "noncanonical_ordinal":
        value["saved_candidates"]["00"] = value["saved_candidates"].pop("0")
    elif mutation == "null_result":
        value["result"] = None
    elif mutation in {"duplicate_candidate", "duplicate_audit"}:
        value["saved_candidates"]["1"] = {"candidate_id": CID if mutation == "duplicate_candidate" else CID[:-1] + "2", "audit_event_id": 9 if mutation == "duplicate_candidate" else 8}
    elif mutation == "receipt_as_save":
        value["saved_candidates"]["0"]["audit_event_id"] = 7
    elif mutation == "save_extra":
        value["saved_candidates"]["0"]["arbitrary_path"] = "private"
    elif mutation == "boolean_audit":
        value["saved_candidates"]["0"]["audit_event_id"] = True
    else:
        value["saved_candidates"]["0"]["candidate_id"] = "not-a-uuid"
    with pytest.raises(ValueError):
        parse_record(c.canonical_json(value))


def test_whole_utf8_capacity_duplicate_keys_and_noncanonical_scalars_reject():
    value = encode_record(None, 1)
    with pytest.raises(ValueError, match="UTF8 TEXT"):
        parse_record(value + "😀" * 16384)
    with pytest.raises(ValueError):
        parse_record(value.replace('"receipt_event_id":1', '"receipt_event_id":1,"receipt_event_id":2'))
    with pytest.raises(ValueError):
        parse_record(value + " ")
    changed = copy.deepcopy(record())
    del changed["result"]["warnings"]
    with pytest.raises(ValueError):
        parse_record(c.canonical_json(changed))
