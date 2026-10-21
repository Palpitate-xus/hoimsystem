"""Whole pure task/source binding; no current publication, gateway or SQL claim."""

import copy
import json
import uuid

import pytest
from pydantic import ValidationError

from app.ai import operations_support_contract as c
from app.ai import operations_support_projection as p
from app.ai import operations_support_task_contract as t
from tests.test_ai_operations_support_projection import collection, member


def setup_source(runbook=True):
    source = p.project_source(collection([member("runbook" if runbook else "diagnostic_log", "前😀X\ufeff\r\n合成材料尾部  ")]))
    selection = t.OperationsTaskSelection(operations_case_id=source.source_id, objective="prepare_reviewed_checks")
    return source, selection


def span(source):
    document = source.documents[0]
    return dict(source_id=document.source_id, start_codepoint=2, end_codepoint=3, quote="X")


def result(source, selection):
    reference = span(source)
    return dict(
        schema_version="operations_support_draft_v1",
        source_id=source.source_id,
        source_sha256=c.content_hash(source),
        objective=selection.objective,
        status="unverified_operations_draft",
        environment_status="not_observed_by_this_task",
        compatibility_status="not_verified_from_reviewed_text",
        observations=[dict(title="材料内观察", explanation="只说明已有字面依据，未观察实际系统", evidence=[reference])],
        hypotheses=[dict(title="待核查假设", explanation="不得当作真实根因", evidence=[reference], status="unverified_hypothesis_requires_admin_review")],
        manual_checks=[
            dict(
                purpose="由管理员核对原手册适用性",
                instruction_reference=reference,
                applicability="requires_current_environment_and_admin_review",
                impact="not_established_by_this_draft",
                execution="reference_only_no_automatic_execution",
            )
        ],
        gaps=[],
    )


def test_complete_source_objective_and_literal_cp_quotes_form_unverified_draft():
    source, selection = setup_source()
    value = result(source, selection)
    assert t.verify_result(json.dumps(value, ensure_ascii=False), source, selection).model_dump() == value
    assert t.verify_result(json.dumps(value, ensure_ascii=False).encode(), c.canonical_json(source), selection).hypotheses[0].status == "unverified_hypothesis_requires_admin_review"


@pytest.mark.parametrize("field,value", [("patient_id", None), ("encounter_id", None), ("question", "未审核新日志secret=abc"), ("environment_file", "/synthetic/.env"), ("objective", "execute_fix")])
def test_task_selection_cannot_carry_unreviewed_free_text_or_foreign_context(field, value):
    source, selection = setup_source()
    with pytest.raises(ValidationError):
        t.OperationsTaskSelection.model_validate({**selection.model_dump(), field: value}, strict=True)


@pytest.mark.parametrize("change", ["case", "source_hash", "objective", "root_id", "empty_span", "past_end", "wrong_quote", "utf16", "utf8"])
def test_actual_source_binding_and_unicode_positions_cannot_be_forged(change):
    source, selection = setup_source()
    value = result(source, selection)
    reference = value["observations"][0]["evidence"][0]
    if change == "case":
        value["source_id"] = str(uuid.uuid4())
    elif change == "source_hash":
        value["source_sha256"] = "0" * 64
    elif change == "objective":
        value["objective"] = "explain_observations"
    elif change == "root_id":
        reference["source_id"] = str(uuid.uuid4())
    elif change == "empty_span":
        reference["end_codepoint"] = reference["start_codepoint"]
    elif change == "past_end":
        reference["end_codepoint"] = len(source.documents[0].text) + 1
    elif change == "wrong_quote":
        reference["quote"] = "x"
    elif change == "utf16":
        reference.update(start_codepoint=3, end_codepoint=4)
    else:
        reference.update(start_codepoint=len("前😀".encode()), end_codepoint=len("前😀X".encode()))
    with pytest.raises(ValueError):
        t.verify_result(value, source, selection)


@pytest.mark.parametrize(
    "field,value", [("status", "completed_verified"), ("environment_status", "observed"), ("compatibility_status", "verified"), ("commands", ["arbitrary"]), ("patient_diagnosis", "invented")]
)
def test_result_does_not_accept_execution_or_verified_environment_status(field, value):
    source, selection = setup_source()
    candidate = result(source, selection)
    candidate[field] = value
    with pytest.raises(ValueError):
        t.verify_result(candidate, source, selection)


def test_a_log_cannot_be_used_as_an_action_runbook_and_gap_is_required():
    source, selection = setup_source(False)
    value = result(source, selection)
    with pytest.raises(ValueError):
        t.verify_result(value, source, selection)
    value["manual_checks"] = []
    with pytest.raises(ValueError):
        t.verify_result(value, source, selection)
    value["gaps"] = [dict(kind="missing_reviewed_runbook", explanation="仅有审核日志，未提供审核运维手册")]
    assert not t.verify_result(value, source, selection).manual_checks


def test_instruction_quote_must_be_from_actual_runbook_even_in_mixed_source():
    source = p.project_source(collection([member("runbook", "前😀X\ufeff\r\n手册"), member("diagnostic_log", "前😀X\ufeff\r\n日志")]))
    selection = t.OperationsTaskSelection(operations_case_id=source.source_id, objective="prepare_reviewed_checks")
    value = result(source, selection)
    log = next(item for item in source.documents if item.kind == "diagnostic_log")
    value["manual_checks"][0]["instruction_reference"]["source_id"] = log.source_id
    with pytest.raises(ValueError):
        t.verify_result(value, source, selection)


@pytest.mark.parametrize("objective", ["explain_observations", "compare_declared_versions"])
def test_other_explicit_objectives_do_not_request_action_instructions(objective):
    source, selection = setup_source()
    selection = t.OperationsTaskSelection(operations_case_id=source.source_id, objective=objective)
    value = result(source, selection)
    with pytest.raises(ValueError):
        t.verify_result(value, source, selection)
    value["manual_checks"] = []
    assert t.verify_result(value, source, selection).objective == objective


def test_repeated_same_reference_does_not_inflate_one_observation():
    source, selection = setup_source()
    value = result(source, selection)
    value["observations"][0]["evidence"] *= 2
    with pytest.raises(ValueError):
        t.verify_result(value, source, selection)


def test_constructed_and_copied_typed_spans_are_revalidated_again():
    source, selection = setup_source()
    valid = t.OperationsDraft.model_validate(result(source, selection))
    invalid = valid.observations[0].evidence[0].model_copy(update={"start_codepoint": True})
    tampered = valid.model_copy(update={"observations": [valid.observations[0].model_copy(update={"evidence": [invalid]})]})
    with pytest.raises(ValueError):
        t.verify_result(tampered, source, selection)


def test_duplicate_json_members_and_fractions_are_not_silently_reparsed():
    source, selection = setup_source()
    raw = c.canonical_json(result(source, selection))
    for packet in ['{"status":"unverified_operations_draft",' + raw[1:], raw.replace('"start_codepoint":2', '"start_codepoint":2.0')]:
        with pytest.raises(ValueError):
            t.verify_result(packet, source, selection)


def test_full_private_collection_cannot_be_substituted_for_model_public_source():
    source, selection = setup_source()
    with pytest.raises(ValueError):
        t.verify_result(result(source, selection), collection(), selection)


def test_whole_result_capacity_accepts_exact_boundary_then_rejects_plus_one():
    source, selection = setup_source()
    value = result(source, selection)
    # Real large repeated quote data remains inside the full public4MiB text
    # budget. Repetition across findings is explicit, not silently merged.
    source = p.project_source(collection([member("runbook", "a" * (1024 * 1024))]))
    selection = t.OperationsTaskSelection(operations_case_id=source.source_id, objective="prepare_reviewed_checks")
    value = result(source, selection)
    quote = dict(source_id=source.documents[0].source_id, start_codepoint=0, end_codepoint=1024 * 1024, quote="a" * (1024 * 1024))
    value["observations"] = []
    value["hypotheses"] = []
    value["manual_checks"] = [
        dict(
            purpose="逐字重复引用边界",
            instruction_reference=copy.deepcopy(quote),
            applicability="requires_current_environment_and_admin_review",
            impact="not_established_by_this_draft",
            execution="reference_only_no_automatic_execution",
        )
        for _ in range(8)
    ]
    with pytest.raises(ValueError):
        t.verify_result(value, source, selection)
    last = value["manual_checks"][-1]["instruction_reference"]
    length = 1
    for _ in range(16):
        last["quote"] = "a" * length
        last["end_codepoint"] = length
        difference = t.MAX_RESULT_BYTES - len(c.canonical_json(value).encode())
        if difference == 0:
            break
        length += difference
    assert 0 < length < 1024 * 1024
    assert len(c.canonical_json(value).encode()) == t.MAX_RESULT_BYTES
    assert len(t.verify_result(value, source, selection).manual_checks) == 8
    last["quote"] += "a"
    last["end_codepoint"] += 1
    assert len(c.canonical_json(value).encode()) == t.MAX_RESULT_BYTES + 1
    with pytest.raises(ValueError):
        t.verify_result(value, source, selection)
