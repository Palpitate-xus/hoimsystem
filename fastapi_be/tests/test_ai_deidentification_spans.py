"""Independent literal edit oracle, not a claim to identify every patient."""

import copy
import hashlib

import pytest

from app.ai.deidentification_spans import apply_edits, document, verify_document


def edit(original, start, end, action="mask"):
    return dict(document_source_id=original["source_id"], text_hash=original["text_hash"], start=start, end=end, quote=original["text"][start:end], action=action)


def test_actual_bom_crlf_emoji_combining_and_utc6_survive_except_explicit_codepoints():
    raw = "\ufeff张三\r\n😀é 2026-10-21T12:30:00.123456Z，电话13800138000"
    original = document("technical:one", "symptom", raw)
    selected = [edit(original, 1, 3), edit(original, raw.index("138"), len(raw), "remove")]
    result = apply_edits([original, document("technical:null", "result", None), document("technical:empty", "result", "")], selected)
    expected = "\ufeff[已遮蔽]\r\n😀é 2026-10-21T12:30:00.123456Z，电话"
    assert result["documents"][0]["text"] == expected
    assert result["documents"][0]["text_hash"] == hashlib.sha256(expected.encode("utf-8")).hexdigest()
    assert result["documents"][0]["utf8_bytes"] == len(expected.encode("utf-8"))
    assert result["documents"][0]["codepoint_length"] == len(expected)
    assert result["documents"][1]["text"] is None and result["documents"][1]["text_hash"] is None
    assert result["documents"][2]["text"] == "" and result["documents"][2]["utf8_bytes"] == 0
    assert result["documents"][2]["text_hash"] == hashlib.sha256(b"").hexdigest()
    assert result["anonymity_guaranteed"] is False
    assert original["text"] == raw


def test_independent_reverse_splice_oracle_over_every_tiny_unicode_single_and_disjoint_pair():
    # Independent oracle edits from right to left, instead of production's
    # ascending concatenation; tests every bounded interval and pair.
    checked = 0
    for raw in ("a", "ab", "汉😀é", "\ufeffa\r\n😀", "👨‍👩‍👧‍👦"):
        original = document("technical:one", "symptom", raw)
        intervals = [(a, b) for a in range(len(raw)) for b in range(a + 1, len(raw) + 1)]
        selections = [[span] for span in intervals] + [[x, y] for x in intervals for y in intervals if x[1] <= y[0]] + [[]]
        for spans in selections:
            for action, replacement in (("mask", "[已遮蔽]"), ("remove", "")):
                actual = apply_edits([original], [edit(original, *span, action) for span in spans])
                oracle = list(raw)
                for start, end in sorted(spans, reverse=True):
                    oracle[start:end] = list(replacement)
                assert actual["documents"][0]["text"] == "".join(oracle)
                checked += 1
    assert checked > 200


@pytest.mark.parametrize("change", ["quote", "hash", "unknown_document", "negative", "out_of_range", "empty", "bool_start", "arbitrary_replacement", "overlap", "reverse", "duplicate"])
def test_invalid_or_ambiguous_ranges_are_not_silently_repaired(change):
    original = document("technical:one", "symptom", "甲😀乙丙")
    values = [edit(original, 0, 2)]
    if change == "quote":
        values[0]["quote"] = "甲X"
    elif change == "hash":
        values[0]["text_hash"] = "f" * 64
    elif change == "unknown_document":
        values[0]["document_source_id"] = "foreign"
    elif change == "negative":
        values[0]["start"] = -1
    elif change == "out_of_range":
        values[0]["end"] = 10
    elif change == "empty":
        values[0]["end"] = 0
    elif change == "bool_start":
        values[0]["start"] = False
    elif change == "arbitrary_replacement":
        values[0]["action"] = "new_patient_name"
    elif change == "overlap":
        values.append(edit(original, 1, 3))
    elif change == "reverse":
        values = [edit(original, 2, 4), edit(original, 0, 2)]
    else:
        values.append(copy.deepcopy(values[0]))
    with pytest.raises(ValueError):
        apply_edits([original], values)


def test_null_original_and_false_numeric_metadata_never_become_empty_known_text():
    original = document("technical:one", "result", None)
    assert verify_document(original)
    empty = document("technical:empty", "result", "")
    empty["utf8_bytes"] = False
    assert not verify_document(empty)
    with pytest.raises(ValueError):
        apply_edits([original], [dict(document_source_id="technical:one", text_hash="a" * 64, start=0, end=1, quote="x", action="mask")])


def test_whole_actual_8mib_body_limit_includes_json_framing_and_refuses_no_truncation():
    original = document("technical:one", "symptom", "汉" * (8 * 1024 * 1024 // 3))
    with pytest.raises(ValueError, match="8MiB"):
        apply_edits([original], [])
    assert original["text"].endswith("汉")


def test_invalid_surrogate_is_not_replaced_or_normalized():
    with pytest.raises(UnicodeError):
        document("technical:one", "symptom", "bad\ud800")
