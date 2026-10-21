"""Independent literal candidate checks; pure fixtures are not SQL permission."""

import copy
import hashlib

import pytest

from app.ai import deidentification_prompt as prompt
from app.ai.deidentification_contract import LIMITATIONS
from app.ai.deidentification_draft import CATEGORIES, DeidentificationDraft, DeidentificationPublicSource, SourceDocument, checked_source, parse_provider_reply, validate_draft
from app.ai.deidentification_result import build_result, validate_result
from app.ai.deidentification_spans import digest, document


@pytest.fixture
def public_source():
    case = "00000000-0000-4000-8000-000000000075"
    texts = ["\ufeff张三\r\n😀é标识2026-10-21T12:00:00.123456Z", "", None]
    return dict(
        schema_version="deidentification_public_source_v1",
        source_id="deidentification_case:" + case + ":" + "a" * 12,
        source_content_hash="a" * 64,
        source_governance_hash="b" * 64,
        documents=[document("deid_document:" + case + ":" + str(index), "symptom", value) for index, value in enumerate(texts)],
        coverage="complete_selected_fields_only",
        original_time_basis="legacy_naive_calendar_dates_timezone_unknown",
        limitations=list(LIMITATIONS),
        anonymity_guaranteed=False,
    )


def draft_for(source, *, start=1, end=3, category="direct_identifier"):
    original = source["documents"][0]
    candidate = dict(
        document_source_id=original["source_id"],
        text_hash=original["text_hash"],
        start=start,
        end=end,
        quote=original["text"][start:end],
        category=category,
        review_note="仅为待人工核对的原文位置，不认定已经匿名。",
    )
    return dict(schema_version="deidentification_draft_v1", source_id=source["source_id"], source_projection_hash=digest(source), coverage="partial_candidates_only", candidates=[candidate])


def test_visible_source_three_literal_null_states_and_candidate_are_not_authorization(public_source):
    assert checked_source(public_source) == public_source
    draft = draft_for(public_source)
    assert validate_draft(public_source, draft) == draft
    assert [doc["text"] for doc in public_source["documents"]][1:] == ["", None]
    assert public_source["documents"][1]["text_hash"] == hashlib.sha256(b"").hexdigest()
    assert public_source["documents"][2]["text_hash"] is None


def test_independent_all_codepoint_intervals_including_combining_and_crlf_have_exact_quotes(public_source):
    text = public_source["documents"][0]["text"]
    count = 0
    # Independent bounds/quote construction, no native edit/model checker used
    # as the expected slicing oracle.
    points = list(text)
    for start in range(len(points)):
        for end in range(start + 1, len(points) + 1):
            draft = draft_for(public_source, start=start, end=end)
            expected = "".join(points[start:end])
            assert draft["candidates"][0]["quote"] == expected
            assert validate_draft(public_source, draft)["candidates"][0]["quote"] == expected
            count += 1
    assert count > 500


@pytest.mark.parametrize("category", CATEGORIES)
def test_only_fixed_candidate_categories_do_not_choose_an_action(public_source, category):
    draft = validate_draft(public_source, draft_for(public_source, category=category))
    assert draft["candidates"][0]["category"] == category
    assert not {"action", "replacement", "anonymous", "probability", "review_id", "release_id"} & draft["candidates"][0].keys()


def test_empty_candidates_are_partial_and_server_counts_null_empty_and_recorded_fields(public_source):
    draft = draft_for(public_source)
    draft["candidates"] = []
    result = build_result(public_source, draft, "e" * 64)
    assert result["candidate_count"] == 0 and result["coverage"] == "partial_candidates_only"
    assert result["selected_field_counts"] == dict(total=3, null=1, empty=1, nonempty=1)
    assert result["anonymity_guaranteed"] is False and result["manual_selection_required"] is True
    assert result["review_created"] is False and result["release_created"] is False
    assert "零候选不代表" in result["partial_notice"]
    assert validate_result(public_source, result, "e" * 64) == result


@pytest.mark.parametrize(
    "mutation", ["source_id", "projection", "foreign_field", "hash", "utf16", "quote", "past_end", "negative", "bool", "empty", "null", "extra", "category", "coverage", "duplicate", "129"]
)
def test_missing_foreign_or_self_rehashed_span_claims_are_rejected(public_source, mutation):
    draft = draft_for(public_source)
    candidate = draft["candidates"][0]
    if mutation == "source_id":
        draft["source_id"] += "x"
    elif mutation == "projection":
        draft["source_projection_hash"] = "c" * 64
    elif mutation == "foreign_field":
        candidate["document_source_id"] += "x"
    elif mutation == "hash":
        candidate["text_hash"] = "c" * 64
    elif mutation == "utf16":
        start = public_source["documents"][0]["text"].index("e")
        candidate.update(start=start + 1, end=start + 3, quote="é")
    elif mutation == "quote":
        candidate["quote"] = "张四"
    elif mutation == "past_end":
        candidate["end"] = 100000
    elif mutation == "negative":
        candidate["start"] = -1
    elif mutation == "bool":
        candidate["start"] = False
    elif mutation in {"empty", "null"}:
        candidate["document_source_id"] = public_source["documents"][1 if mutation == "empty" else 2]["source_id"]
        candidate["text_hash"] = public_source["documents"][1]["text_hash"]
    elif mutation == "extra":
        candidate["replacement"] = "伪造替换建议"
    elif mutation == "category":
        candidate["category"] = "clinically_confirmed"
    elif mutation == "coverage":
        draft["coverage"] = "all_identifiers_removed"
    elif mutation == "duplicate":
        draft["candidates"].append(copy.deepcopy(candidate))
    else:
        draft["candidates"] *= 129
    with pytest.raises((ValueError, TypeError)):
        validate_draft(public_source, draft)


def test_overlapping_candidates_require_later_manual_choice_and_never_automatically_apply(public_source):
    draft = draft_for(public_source)
    draft["candidates"].append(draft_for(public_source, start=1, end=4, category="uncertain")["candidates"][0])
    assert len(validate_draft(public_source, draft)["candidates"]) == 2
    result = build_result(public_source, draft, "e" * 64)
    assert result["manual_selection_required"] and result["review_created"] is False
    assert public_source["documents"][0]["text"].startswith("\ufeff张三")


@pytest.mark.parametrize("mutation", ["source_extra", "token", "hash_prefix", "raw_hash", "byte_count", "cp_count", "null_to_empty", "bool_cp", "false_zero", "limitations"])
def test_public_shape_cannot_be_widened_or_normalized_by_rehash(public_source, mutation):
    forged = copy.deepcopy(public_source)
    if mutation == "source_extra":
        forged["patient_id"] = 1
    elif mutation == "token":
        forged["documents"][0]["source_id"] += "x"
    elif mutation == "hash_prefix":
        forged["source_content_hash"] = "c" * 64
    elif mutation == "raw_hash":
        forged["documents"][0]["text_hash"] = "c" * 64
    elif mutation == "byte_count":
        forged["documents"][0]["utf8_bytes"] -= 1
    elif mutation == "cp_count":
        forged["documents"][0]["codepoint_length"] -= 1
    elif mutation == "null_to_empty":
        forged["documents"][2]["text"] = ""
    elif mutation == "bool_cp":
        forged["documents"][1]["codepoint_length"] = False
    elif mutation == "false_zero":
        forged["anonymity_guaranteed"] = 0
    else:
        forged["limitations"][0] = "任意扩充的覆盖保证"
    with pytest.raises((ValueError, TypeError)):
        validate_draft(forged, draft_for(forged))


@pytest.mark.parametrize("mutation", ["count", "unknown_zero", "review", "release", "anonymous", "extra", "instruction", "category_count"])
def test_result_cannot_self_rehash_false_counts_or_claim_review_release(public_source, mutation):
    result = build_result(public_source, draft_for(public_source), "e" * 64)
    if mutation == "count":
        result["candidate_count"] = 0
    elif mutation == "unknown_zero":
        result["selected_field_counts"]["null"] = 0
    elif mutation in {"review", "release"}:
        result[mutation + "_created"] = True
    elif mutation == "anonymous":
        result["anonymity_guaranteed"] = True
    elif mutation == "extra":
        result["export_authorized"] = True
    elif mutation == "instruction":
        result["instructions_digest"] = "a" * 64
    else:
        result["candidate_category_counts"][0]["count"] = True
    with pytest.raises(ValueError):
        validate_result(public_source, result, "e" * 64)


def test_prompt_two_digest_conventions_are_actual_full_prompt_not_interchangeable(public_source):
    task = prompt.TASK_PROMPT + "\n实际独立版本化Task末尾\r\n🧪"
    assert prompt.prompt_hash(task) == digest([prompt.SYSTEM_PROMPT, task])
    assert prompt.instructions_digest(task) == hashlib.sha256((prompt.SYSTEM_PROMPT + "\n\n" + task).encode()).hexdigest()
    assert prompt.prompt_hash(task) != prompt.instructions_digest(task)
    assert prompt.TASK_VERSION in {"deidentification_literal_candidates_v1"}


@pytest.mark.parametrize("body", [b'{"x":1,"x":2}', b'{"x":"\\ud800"}', b'{"x":NaN}', b'{"x":1e999}', b"```json\n{}\n```"])
def test_provider_text_must_be_whole_strict_json_without_repair(public_source, body):
    with pytest.raises((ValueError, TypeError)):
        parse_provider_reply(body.decode(), public_source)


def test_constructed_models_do_not_bypass_visible_literal_checks(public_source):
    model = DeidentificationPublicSource.model_construct(**public_source)
    with pytest.warns(UserWarning, match="Pydantic serializer warnings"):
        assert checked_source(model) == public_source
    forged_doc = SourceDocument.model_construct(**{**public_source["documents"][0], "codepoint_length": False})
    forged = {**public_source, "documents": [forged_doc, *public_source["documents"][1:]]}
    with pytest.raises((ValueError, TypeError)):
        checked_source(forged)
    draft = DeidentificationDraft.model_construct(**{**draft_for(public_source), "coverage": "anonymous"})
    with pytest.warns(UserWarning, match="Pydantic serializer warnings"), pytest.raises(ValueError):
        validate_draft(public_source, draft)
