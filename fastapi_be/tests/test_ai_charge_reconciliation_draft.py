"""Synthetic literal-ledger proofs; no patient access or financial validation."""

import copy
import json

import pytest

from app.ai.charge_reconciliation_draft import MAX_OBSERVATIONS, ChargeReconciliationDraft, parse_draft, source_hash, structural_counts, validate_draft
from app.ai.charge_reconciliation_prompt import CHARGE_RECONCILIATION_SYSTEM_PROMPT
from app.ai.charge_reconciliation_result import result_for_draft, validate_result


def example():
    identifier = "charge_charge:" + "a" * 64
    source = {
        "schema_version": "charge_ledger_source_v1",
        "source_id": "charge_case:synthetic",
        "charges": [
            {"source_id": identifier, "item_name": "\ufeff合成🙂\r\n服务名称", "quantity": {"value_text": "0.1"}, "total_amount": "12.00", "status": "settled", "order_association": "not_recorded"}
        ],
        "orders": [],
        "order_items": [],
        "executions": [],
        "administrations": [],
    }
    reply = {
        "schema_version": "charge_reconciliation_draft_v1",
        "source_id": source["source_id"],
        "source_projection_hash": source_hash(source),
        "coverage": "partial_questions_no_completeness_or_correctness_claim",
        "observations": [
            {
                "kind": "association_question",
                "referenced_source_ids": [identifier],
                "review_note": "请人工核实这项原记录的关联依据。",
                "clarification_question": "是否存在尚未提供的实际医嘱关联依据？",
                "citations": [{"source_id": identifier, "field": "item_name", "start": 6, "end": 10, "quote": "服务名称"}],
            }
        ],
    }
    return source, reply


def accept(source, reply):
    return validate_draft(source, parse_draft(json.dumps(reply, ensure_ascii=False)), source_hash(source))


def test_exact_bom_crlf_emoji_codepoint_reference_without_source_mutation():
    source, reply = example()
    original = copy.deepcopy(source)
    assert accept(source, reply).observations[0].citations[0].quote == "服务名称"
    assert source == original
    result = result_for_draft(source, accept(source, reply), source_hash(source))
    assert "尚未确认财务结论" in result.summary
    assert validate_result(result.model_dump(mode="json"), source, source_hash(source)) == result
    assert len(result.sections) == 2 and len(result.warnings) == 3 and len(result.missing_data) == 4


@pytest.mark.parametrize(
    "key,value",
    [
        ("source_id", "charge_charge:" + "b" * 64),
        ("field", "patient_id"),
        ("field", "quantity"),
        ("start", True),
        ("start", "6"),
        ("start", -1),
        ("end", 500),
        ("end", 6),
        ("quote", "其他名称"),
        ("quote", "\ud800"),
    ],
)
def test_wrong_or_noncanonical_literal_reference_rejected(key, value):
    source, reply = example()
    reply["observations"][0]["citations"][0][key] = value
    with pytest.raises((ValueError, UnicodeError)):
        accept(source, reply)


def test_utf16_offset_cannot_replace_codepoint_offset():
    source, reply = example()
    reply["observations"][0]["citations"][0].update(start=7, end=11)
    with pytest.raises(ValueError):
        accept(source, reply)


@pytest.mark.parametrize(
    "mutation",
    [
        "wrong_source",
        "wrong_hash",
        "unknown_kind",
        "new_amount",
        "new_charge",
        "foreign_member",
        "duplicate_member",
        "duplicate_observation",
        "duplicate_citation",
        "missing_citation",
        "blank_question",
        "full_coverage",
    ],
)
def test_foreign_members_and_financial_execution_fields_are_closed(mutation):
    source, reply = example()
    observation = reply["observations"][0]
    if mutation == "wrong_source":
        reply["source_id"] = "charge_case:other"
    elif mutation == "wrong_hash":
        reply["source_projection_hash"] = "f" * 64
    elif mutation == "unknown_kind":
        observation["kind"] = "confirmed_duplicate_charge"
    elif mutation in {"new_amount", "new_charge"}:
        observation[mutation] = "not permitted"
    elif mutation == "foreign_member":
        observation["referenced_source_ids"] = ["charge_charge:" + "f" * 64]
    elif mutation == "duplicate_member":
        observation["referenced_source_ids"] *= 2
    elif mutation == "duplicate_observation":
        reply["observations"].append(copy.deepcopy(observation))
    elif mutation == "duplicate_citation":
        observation["citations"] *= 2
    elif mutation == "missing_citation":
        observation["citations"] = []
    elif mutation == "blank_question":
        observation["clarification_question"] = "    "
    else:
        reply["coverage"] = "all_charges_correct"
    with pytest.raises(ValueError):
        accept(source, reply)


def test_changed_source_field_invalidates_frozen_projection_even_when_uncited():
    source, reply = example()
    frozen_hash = source_hash(source)
    source["charges"][0]["total_amount"] = "13.00"
    with pytest.raises(ValueError):
        validate_draft(source, ChargeReconciliationDraft.model_validate(reply), frozen_hash)


@pytest.mark.parametrize("mutation", ["missing_collection", "wrong_collection_type", "duplicate_token", "wrong_token_kind", "unknown_token"])
def test_complete_projected_member_collections_required(mutation):
    source, _ = example()
    if mutation == "missing_collection":
        del source["administrations"]
    elif mutation == "wrong_collection_type":
        source["orders"] = None
    elif mutation == "duplicate_token":
        source["charges"] *= 2
    elif mutation == "wrong_token_kind":
        source["orders"] = [source["charges"][0]]
    else:
        source["charges"][0]["source_id"] = "guessed:name"
    with pytest.raises(ValueError):
        structural_counts(source)


def test_empty_questions_never_claim_complete_or_financial_correctness():
    source, reply = example()
    reply["observations"] = []
    draft = accept(source, reply)
    result = result_for_draft(source, draft, source_hash(source))
    assert "0项" in result.summary and "覆盖范围不完整" in result.summary
    counts = structural_counts(source)
    assert counts["charges_count"] == 1
    assert counts["charge_order_association_counts"]["not_recorded"] == 1
    assert counts["cash_receipt"] == counts["cash_refund"] == "not_provided"
    assert counts["billing_entitlement"] == "unknown"
    assert counts["automatic_charge_or_refund"] is False


def test_insufficient_basis_still_requires_actual_members_and_explicit_question():
    source, reply = example()
    reply["observations"][0].update(kind="insufficient_evidence", citations=[])
    assert accept(source, reply).observations[0].kind == "insufficient_evidence"


@pytest.mark.parametrize("field,value", [("quantity.value_text", "0.1"), ("total_amount", "12.00"), ("status", "settled")])
def test_exact_stored_string_reference_does_not_prove_cash_or_decimal_precision(field, value):
    source, reply = example()
    reply["observations"][0]["citations"][0].update(field=field, start=0, end=len(value), quote=value)
    assert accept(source, reply)
    assert structural_counts(source)["cash_receipt"] == "not_provided"


def test_null_and_number_are_never_formatted_into_literal_quotes():
    for value in (None, 12, 12.0, True):
        source, reply = example()
        source["charges"][0]["total_amount"] = value
        reply["source_projection_hash"] = source_hash(source)
        reply["observations"][0]["citations"][0].update(field="total_amount", start=0, end=2, quote="12")
        with pytest.raises(ValueError):
            accept(source, reply)


def test_duplicate_json_keys_nonfinite_fences_and_surrogates_rejected():
    _, reply = example()
    text = json.dumps(reply)
    for bad in (text.replace('"source_id":', '"source_id":"duplicate","source_id":', 1), text.replace('"start": 6', '"start": NaN'), "```json\n" + text + "\n```", text + "\ud800"):
        with pytest.raises((ValueError, UnicodeError)):
            parse_draft(bad)


def test_observation_output_limit_and_fixed_result_text_cannot_be_overridden():
    source, reply = example()
    reply["observations"] *= MAX_OBSERVATIONS + 1
    with pytest.raises(ValueError):
        accept(source, reply)
    source, reply = example()
    result = result_for_draft(source, accept(source, reply), source_hash(source)).model_dump(mode="json")
    for field, value in (("summary", "全部收费正确"), ("warnings", []), ("missing_data", []), ("sections", [])):
        bad = copy.deepcopy(result)
        bad[field] = value
        with pytest.raises(ValueError):
            validate_result(bad, source, source_hash(source))


def test_dedicated_prompt_binds_partial_questions_and_no_business_execution():
    assert "charge_reconciliation_draft_v1" in CHARGE_RECONCILIATION_SYSTEM_PROMPT
    assert "partial_questions_no_completeness_or_correctness_claim" in CHARGE_RECONCILIATION_SYSTEM_PROMPT
    assert "实际收款" in CHARGE_RECONCILIATION_SYSTEM_PROMPT
    assert "MySQL" in CHARGE_RECONCILIATION_SYSTEM_PROMPT
    assert "不产生新收费项目" in CHARGE_RECONCILIATION_SYSTEM_PROMPT
