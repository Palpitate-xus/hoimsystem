"""Actual literal bindings and rejection boundaries of the pure operations contract."""

import copy
import hashlib
import uuid

import pytest
from pydantic import ValidationError

from app.ai.operations_support_contract import (
    MASK_TEXT,
    MAX_TEXT_BYTES,
    DeclaredOperationsReview,
    OperationsOriginal,
    Redaction,
    apply_redactions,
    content_hash,
    verify_declared_review,
)


def original(text="\ufeff第一行\r\npassword=合成😀SECRET\r\n末行 \x00"):
    return OperationsOriginal.model_validate(
        {
            "schema_version": "operations_support_original_v1",
            "original_id": str(uuid.uuid4()),
            "kind": "diagnostic_log",
            "title": "完整原题 \ufeff\r\n",
            "origin_note": "人工提供合成日志；不是当前服务探测",
            "declared_component": " synthetic ",
            "declared_version": None,
            "content_text": text,
            "captured_at": "2026-10-21T17:00:00.123456Z",
            "captured_by": 1,
            "clock_basis": "capture_only_not_verified_incident_occurrence",
        }
    )


def review(source, spans=None):
    if spans is None:
        spans = [Redaction(start_codepoint=source.content_text.index("password="), end_codepoint=source.content_text.index("\r\n末行"), method="mask")]
    return DeclaredOperationsReview.model_validate(
        {
            "schema_version": "operations_support_declared_review_v1",
            "review_id": str(uuid.uuid4()),
            "original_id": source.original_id,
            "original_full_sha256": content_hash(source),
            "released_title": "受审合成故障片段",
            "released_component": "synthetic",
            "released_version": None,
            "redactions": [s.model_dump() for s in spans],
            "released_text": apply_redactions(source.content_text, spans),
            "privacy_reviewed": True,
            "faithfulness_reviewed": True,
            "applicability_declaration_reviewed": True,
            "review_basis": "仅合成原件与手工区间；不是自动秘密扫描证明",
            "reviewed_at": "2026-10-21T17:01:00.654321Z",
            "reviewed_by": 2,
        }
    )


def test_exact_original_and_manual_cp_derivative_preserve_bom_crlf_emoji_nul_and_spaces():
    source = original()
    declared = review(source)
    verify_declared_review(source, declared)
    assert source.content_text.encode() == b"\xef\xbb\xbf" + "第一行\r\npassword=合成😀SECRET\r\n末行 \x00".encode()
    assert declared.released_text == "\ufeff第一行\r\n" + MASK_TEXT + "\r\n末行 \x00"
    assert source.declared_component == " synthetic " and source.declared_version is None
    assert "合成😀SECRET" not in declared.released_text
    assert hashlib.sha256(source.content_text.encode()).hexdigest() != content_hash(source)


@pytest.mark.parametrize("method,replacement", [("remove", ""), ("mask", MASK_TEXT)])
def test_scalar_offsets_do_not_use_utf8_bytes_or_utf16_units(method, replacement):
    assert apply_redactions("前😀𠮷后", [Redaction(start_codepoint=1, end_codepoint=3, method=method)]) == "前" + replacement + "后"


@pytest.mark.parametrize("field,value", [("content_text", "changed"), ("title", "changed"), ("declared_version", "v2"), ("captured_by", 3)])
def test_any_private_original_change_invalidates_old_declaration(field, value):
    source = original()
    declared = review(source)
    changed = OperationsOriginal.model_validate({**source.model_dump(), field: value})
    with pytest.raises(ValueError, match="entire exact original"):
        verify_declared_review(changed, declared)


@pytest.mark.parametrize("field,value", [("released_text", "changed"), ("reviewed_by", 1), ("reviewed_at", "2026-10-21T16:59:00.123456Z"), ("original_id", "00000000-0000-0000-0000-000000000000")])
def test_forged_transform_independence_clock_or_identity_is_rejected(field, value):
    source = original()
    declared = review(source)
    bad = DeclaredOperationsReview.model_validate({**declared.model_dump(), field: value})
    with pytest.raises(ValueError):
        verify_declared_review(source, bad)


@pytest.mark.parametrize("value", [1, 0, "true", None, False])
@pytest.mark.parametrize("field", ["privacy_reviewed", "faithfulness_reviewed", "applicability_declaration_reviewed"])
def test_review_flags_are_explicit_actual_booleans(field, value):
    raw = review(original()).model_dump()
    raw[field] = value
    with pytest.raises(ValidationError):
        DeclaredOperationsReview.model_validate(raw)


@pytest.mark.parametrize(
    "spans",
    [
        [(0, 2), (1, 3)],
        [(3, 4), (0, 1)],
        [(0, 99)],
    ],
)
def test_overlapping_out_of_order_and_outside_spans_fail_whole(spans):
    rows = [Redaction(start_codepoint=a, end_codepoint=b, method="remove") for a, b in spans]
    with pytest.raises(ValueError):
        apply_redactions("原😀文", rows)


@pytest.mark.parametrize("a,b", [(True, 2), (0, False), (1.0, 2), (1, 1), (2, 1), (-1, 1)])
def test_positions_are_real_nonempty_nonnegative_integer_spans(a, b):
    with pytest.raises(ValidationError):
        Redaction(start_codepoint=a, end_codepoint=b, method="mask")


@pytest.mark.parametrize("clock", ["2026-10-21T17:00:00Z", "2026-10-21 17:00:00.123456Z", "2026-02-30T17:00:00.123456Z", "2026-10-21T17:00:00.123456+00:00"])
def test_no_implicit_timezone_precision_or_invalid_calendar(clock):
    raw = original().model_dump()
    raw["captured_at"] = clock
    with pytest.raises(ValidationError):
        OperationsOriginal.model_validate(raw)


def test_complete_utf8_text_boundary_and_no_clipping():
    text = "字" * (MAX_TEXT_BYTES // 3) + "x" * (MAX_TEXT_BYTES % 3)
    assert len(text.encode()) == MAX_TEXT_BYTES
    source = original(text)
    assert source.content_text == text
    with pytest.raises(ValidationError):
        original(text + "x")


@pytest.mark.parametrize("field,value", [("content_text", "bad\ud800"), ("title", "bad\udfff"), ("declared_component", "bad\ud800")])
def test_surrogates_are_rejected_before_hashing_or_persistence(field, value):
    raw = copy.deepcopy(original().model_dump())
    raw[field] = value
    with pytest.raises(ValidationError):
        OperationsOriginal.model_validate(raw)


def test_complete_source_pair_at_exact_whole_budget_then_one_byte_more_is_rejected():
    from app.ai.operations_support_contract import MAX_WHOLE_BYTES, canonical_json

    one = original("x")
    declared_one = review(one, spans=[])

    def pair(a, b):
        return {"original": a.model_dump(mode="json"), "review": b.model_dump(mode="json")}

    overhead = len(canonical_json(pair(one, declared_one)).encode()) - 2
    length, remainder = divmod(MAX_WHOLE_BYTES - overhead, 2)
    source = original("x" * length)
    declared = review(source, spans=[])
    if remainder:
        declared = DeclaredOperationsReview.model_validate({**declared.model_dump(), "review_basis": declared.review_basis + "x"})
    assert len(canonical_json(pair(source, declared)).encode()) == MAX_WHOLE_BYTES
    verify_declared_review(source, declared)
    too_large = DeclaredOperationsReview.model_validate({**declared.model_dump(), "review_basis": declared.review_basis + "x"})
    with pytest.raises(ValueError, match="whole-source UTF8 budget"):
        verify_declared_review(source, too_large)


@pytest.mark.parametrize("field,value", [("captured_by", True), ("captured_by", 1.0), ("captured_by", "1"), ("original_id", " 00000000-0000-0000-0000-000000000000"), ("origin_note", "bad\ud800")])
def test_identity_and_capture_metadata_are_strict_without_coercion(field, value):
    with pytest.raises(ValidationError):
        OperationsOriginal.model_validate({**original().model_dump(), field: value})


def test_unknown_metadata_is_not_silently_accepted():
    with pytest.raises(ValidationError):
        OperationsOriginal.model_validate({**original().model_dump(), "patient_id": 1})
