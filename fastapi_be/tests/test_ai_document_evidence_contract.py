"""Pure exact UTF8/codepoint tests; run with --noconftest and no hospital imports."""

import base64
import hashlib
import subprocess
import sys

import pytest
from pydantic import ValidationError

from app.ai import document_evidence_contract as c

NOW = "2026-10-21T12:00:00.123456Z"
NOTE = "原文与授权范围已经逐项人工核对，仍不代表临床有效性。"


def request(text="\ufeff第一行\r\n第二行😀e\u0301\n"):
    return {
        "metadata": {
            "title": "合成文档",
            "version": "v1",
            "document_kind": "guideline",
            "declared_source_uri": "synthetic://not-an-authoritative-guideline",
            "declared_publisher": None,
            "source_available_at": NOW,
            "applicability_note": NOTE,
            "authorization_note": NOTE,
        },
        "content": {"kind": "direct_text", "text": text, "expected_bytes_hash": hashlib.sha256(text.encode()).hexdigest()},
    }


def original(text="\ufeff第一行\r\n第二行😀e\u0301\n"):
    req = c.OriginalCreate.model_validate(request(text))
    return c.OriginalImmutable(
        schema_version="document_original_immutable_v1",
        original_id="00000000-0000-0000-0000-000000000071",
        created_by=1,
        recorded_at=NOW,
        metadata=req.metadata,
        input_kind="direct_text",
        filename=None,
        raw_bytes_hash=req.content.expected_bytes_hash,
        raw_bytes_length=len(text.encode()),
        codepoint_length=len(text),
        text=text,
    )


def test_exact_original_preserves_bom_crlf_combining_emoji_and_separate_byte_hash():
    raw = "\ufeff第一行\r\n第二行😀e\u0301\n"
    value = original(raw)
    assert value.text == raw and value.codepoint_length == 13
    assert value.raw_bytes_length > value.codepoint_length
    assert value.raw_bytes_hash == hashlib.sha256(raw.encode()).hexdigest()
    assert c.digest(value) != value.raw_bytes_hash
    assert c.OriginalImmutable.model_validate_json(value.model_dump_json()) == value
    checked = subprocess.run(
        [sys.executable, "-c", "import sys; import app.ai.document_evidence_contract; assert not any(n in sys.modules for n in ('app.config','app.database','app.models','sqlalchemy'))"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert checked.returncode == 0, checked.stderr


@pytest.mark.parametrize("extension", ["txt", "md", "TXT"])
def test_utf8_file_has_exact_same_bytes_without_bom_stripping(extension):
    req = request()
    text = req["content"]["text"]
    req["content"] = {"kind": "utf8_file", "filename": "原件." + extension, "bytes_base64": base64.b64encode(text.encode()).decode(), "expected_bytes_hash": c.bytes_hash(text)}
    parsed = c.OriginalCreate.model_validate(req)
    assert parsed.content.decoded_text() == text


@pytest.mark.parametrize("raw", [b"\xff", b"\xc0\xaf", b"\xed\xa0\x80", b"\xf0\x9f\x98"])
def test_invalid_utf8_file_never_uses_replacement_decode(raw):
    req = request()
    req["content"] = {"kind": "utf8_file", "filename": "source.txt", "bytes_base64": base64.b64encode(raw).decode(), "expected_bytes_hash": hashlib.sha256(raw).hexdigest()}
    with pytest.raises(ValidationError):
        c.OriginalCreate.model_validate(req)


@pytest.mark.parametrize("filename", ["source.pdf", "source.docx", "../source.txt", "folder/source.md", "folder\\source.txt"])
def test_unsupported_format_or_path_is_not_treated_as_plaintext(filename):
    req = request()
    req["content"] = {"kind": "utf8_file", "filename": filename, "bytes_base64": "YQ==", "expected_bytes_hash": c.bytes_hash("a")}
    with pytest.raises(ValidationError):
        c.OriginalCreate.model_validate(req)


@pytest.mark.parametrize("bad", ["\ud800", "safe\udfff", "\ud83d\ude00"])
def test_json_surrogate_code_units_are_not_silently_normalized(bad):
    with pytest.raises(ValueError):
        c.utf8(bad)
    req = request()
    req["metadata"]["title"] = bad
    with pytest.raises(ValidationError):
        c.OriginalCreate.model_validate(req)


@pytest.mark.parametrize("text", ["", "a" * (c.MAX_ORIGINAL_BYTES + 1), "汉" * (c.MAX_ORIGINAL_BYTES // 3 + 1)])
def test_raw_original_limit_is_utf8_bytes_and_does_not_truncate(text):
    with pytest.raises(ValidationError):
        c.OriginalCreate.model_validate(request(text))


def test_four_mib_raw_bytes_are_not_confused_with_escaped_json_budget():
    text = "a" * c.MAX_ORIGINAL_BYTES
    assert c.OriginalCreate.model_validate(request(text)).content.text == text
    # A file may hold valid control characters, but its full JSON response must
    # still fit the explicit independent 8MiB cap rather than grow silently.
    with pytest.raises(ValidationError, match="JSON"):
        original("\0" * (c.MAX_ORIGINAL_BYTES // 2))


@pytest.mark.parametrize("value", ["2026-02-30T00:00:00.000000Z", "2026-10-21T12:00:00Z", "2026-10-21T12:00:00.123456+00:00", "0000-01-01T00:00:00.000000Z"])
def test_utc_clock_is_actual_gregorian_canonical_microseconds(value):
    with pytest.raises(ValueError):
        c.clock(value)


def test_gregorian_year_one_and_no_forecast_availability():
    assert c.utc_text(c.clock("0001-01-01T00:00:00.000000Z")) == "0001-01-01T00:00:00.000000Z"
    value = original().model_dump()
    value["metadata"]["source_available_at"] = "2026-10-22T00:00:00.000000Z"
    with pytest.raises(ValidationError):
        c.OriginalImmutable.model_validate(value)


@pytest.mark.parametrize("bad", [True, 1.0, "1", -1])
def test_span_does_not_coerce_bool_float_string_or_negative(bad):
    with pytest.raises(ValidationError):
        c.CandidateCreate(
            original={"original_id": original().original_id, "content_hash": "a" * 64, "governance_hash": "b" * 64},
            proposed_heading="候选",
            clause_kind="other",
            start=bad,
            end=2,
            quote="字",
            provenance="unverified_submission",
        )


def test_candidate_65535_utf8_boundary_is_not_a_character_limit():
    proposal = {
        "original": {"original_id": original().original_id, "content_hash": "a" * 64, "governance_hash": "b" * 64},
        "proposed_heading": "候选",
        "clause_kind": "other",
        "start": 0,
        "end": 21845,
        "quote": "汉" * 21845,
        "provenance": "unverified_submission",
    }
    assert len(c.CandidateCreate.model_validate(proposal).quote.encode()) == 65535
    proposal.update(end=21846, quote="汉" * 21846)
    with pytest.raises(ValidationError):
        c.CandidateCreate.model_validate(proposal)


@pytest.mark.parametrize("body", ['{"a":1,"a":2}', '{"outer":{"x":1,"x":2}}', '{"x":NaN}', '{"x":Infinity}', '{"x":1e999}', '{"x":"\\ud800"}'])
def test_duplicate_nonfinite_and_escaped_surrogate_json_are_rejected(body):
    with pytest.raises(ValueError):
        c.parse_json(body)


def test_approval_requires_two_actual_review_decisions_and_complete_cas():
    req = dict(
        expected_revision=1, expected_content_hash="a" * 64, expected_governance_hash="b" * 64, decision="approve", privacy_review="confirmed", faithfulness_review="not_confirmed", basis_note=NOTE
    )
    with pytest.raises(ValidationError):
        c.ReviewRequest.model_validate(req)
    req["faithfulness_review"] = "confirmed"
    assert c.ReviewRequest.model_validate(req).decision == "approve"


@pytest.mark.parametrize("suffix", ["../secret", "00000000-0000-0000-0000-000000000071?x=1", "00000000000000000000000000000071"])
def test_reserved_publication_uri_requires_exact_uuid_and_no_query(suffix):
    with pytest.raises(ValueError):
        c.publication_id_from_uri(c.URI_PREFIX + suffix)
