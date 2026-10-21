"""Pure literal codepoint editing; it grants no access and detects no identity."""

import hashlib
import json

from app.ai.deidentification_contract import LIMITATIONS, MASKS, MAX_BYTES, MAX_DOCUMENTS, MAX_EDITS, SpanEdit


def utf8(value):
    return value.encode("utf-8", errors="strict")


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256(utf8(canonical(value))).hexdigest()


def text_digest(value):
    return hashlib.sha256(utf8(value)).hexdigest()


def document(source_id, field, text):
    if type(source_id) is not str or not source_id or type(field) is not str or type(text) not in {str, type(None)}:
        raise ValueError("An explicit actual text or null is required")
    if len(source_id) > 160 or len(field) > 100:
        raise ValueError("Explicit bounded technical document fields required")
    utf8(source_id)
    utf8(field)
    if text is None:
        return dict(source_id=source_id, field=field, text=None, text_hash=None, utf8_bytes=None, codepoint_length=None, absent_reason="not_recorded")
    raw = utf8(text)
    if len(raw) > MAX_BYTES:
        raise ValueError("Whole original document exceeds the UTF8 budget")
    return dict(source_id=source_id, field=field, text=text, text_hash=hashlib.sha256(raw).hexdigest(), utf8_bytes=len(raw), codepoint_length=len(text), absent_reason=None)


def verify_document(value):
    try:
        expected = document(value["source_id"], value["field"], value["text"])
        return type(value) is dict and expected == value and all(type(value[k]) is type(v) for k, v in expected.items())
    except (ValueError, TypeError, KeyError, UnicodeError):
        return False


def apply_edits(documents, edits):
    """Return every selected document, including null/empty/unmodified fields.

    Sorted, nonoverlapping ranges use original Python Unicode codepoints. No
    normalization, automatic merging, arbitrary replacement or date shifting.
    """
    if type(documents) is not list or not 1 <= len(documents) <= MAX_DOCUMENTS or any(not verify_document(x) for x in documents):
        raise ValueError("Whole selected originals are required")
    ids = [x["source_id"] for x in documents]
    if len(set(ids)) != len(ids) or type(edits) is not list or len(edits) > MAX_EDITS:
        raise ValueError("The complete explicit edit list must be finite and distinct")
    checked = [SpanEdit.model_validate(x).model_dump() for x in edits]
    keys = [(x["document_source_id"], x["start"], x["end"]) for x in checked]
    if keys != sorted(set(keys)):
        raise ValueError("Sort every explicit edit; never choose an overlapping winner")
    by_id = {x["source_id"]: x for x in documents}
    grouped = {identifier: [] for identifier in ids}
    for edit in checked:
        original = by_id.get(edit["document_source_id"])
        if original is None or original["text"] is None or original["text_hash"] != edit["text_hash"]:
            raise ValueError("The edit must bind the full actual original")
        text = original["text"]
        if edit["end"] > len(text) or text[edit["start"] : edit["end"]] != edit["quote"]:
            raise ValueError("The exact original codepoint quote differs")
        group = grouped[edit["document_source_id"]]
        if group and group[-1]["end"] > edit["start"]:
            raise ValueError("Overlapping ranges require a new explicit human choice")
        group.append(edit)
    output = []
    for original in documents:
        if original["text"] is None:
            text = None
        else:
            parts, cursor = [], 0
            for edit in grouped[original["source_id"]]:
                parts.extend((original["text"][cursor : edit["start"]], MASKS[edit["action"]]))
                cursor = edit["end"]
            parts.append(original["text"][cursor:])
            text = "".join(parts)
        output.append(document(original["source_id"], original["field"], text))
    value = {"schema_version": "deidentification_selected_output_v1", "documents": output, "limitations": list(LIMITATIONS), "anonymity_guaranteed": False}
    if len(utf8(canonical(value))) > MAX_BYTES:
        raise ValueError("Whole edited output exceeds8MiB; no truncation")
    return value
