"""Explicit bounded JSON for the larger comparison Case and unverified drafts.

This is independent of the earlier 71 single-original parser. The current closed
Case has at most 8192 combined dependencies: each Original/Target/Link uses fewer
than 256 key+value/container nodes; a Publication/Candidate/Knowledge triple uses
fewer than 3*256 even with all 80 allowed feature keys. Reserve 4096 covers root,
request, governance and all 256 explicit target references. Raw target JSON and
free notes stay strings, never recursively parsed. This is an additional software
capacity policy, not acceptance of every arbitrary 8MiB JSON tree.
"""

import json
import math

from app.ai.document_evidence_contract import reject_constant, unique_pairs, utf8

MAX_JSON_BYTES = 8 * 1024 * 1024
MAX_JSON_NODES = 8192 * 256 + 4096
MAX_JSON_DEPTH = 32


def _entries(value, depth):
    for key, child in value.items():
        yield key, depth
        yield child, depth


def _children(value, depth):
    for child in value:
        yield child, depth


def validate_structure(value, *, maximum_nodes=MAX_JSON_NODES, maximum_depth=MAX_JSON_DEPTH, maximum_utf8_bytes=MAX_JSON_BYTES):
    if type(value) is not dict:
        raise ValueError("A complete comparison JSON object is required")
    if type(maximum_nodes) is not int or maximum_nodes < 1 or type(maximum_depth) is not int or maximum_depth < 1:
        raise ValueError("Internal JSON structural limits must be explicit positive integers")
    # Iterator frames keep auxiliary memory proportional to depth, not to a
    # malicious wide array/dictionary that happens to fit the wire byte cap.
    frames = [iter(((value, 1),))]
    nodes = 0
    string_bytes = 0
    while frames:
        try:
            item, depth = next(frames[-1])
        except StopIteration:
            frames.pop()
            continue
        nodes += 1
        if nodes > maximum_nodes or depth > maximum_depth:
            raise ValueError("Comparison JSON exceeds the explicit whole-tree node or depth budget")
        if type(item) is str:
            if len(item) > maximum_utf8_bytes:
                raise ValueError("Complete comparison JSON exceeds 8MiB UTF8")
            string_bytes += len(utf8(item))
            if string_bytes > maximum_utf8_bytes:
                raise ValueError("Complete comparison JSON exceeds 8MiB UTF8")
        elif type(item) is float and not math.isfinite(item):
            raise ValueError("Nonfinite comparison JSON values are forbidden")
        elif type(item) is dict:
            if any(type(key) is not str for key in item):
                raise ValueError("JSON object keys must be actual strings")
            frames.append(_entries(item, depth + 1))
        elif type(item) is list:
            frames.append(_children(item, depth + 1))
        elif item is not None and type(item) not in {bool, int, float}:
            raise ValueError("Only complete JSON primitives and containers are accepted")
    return nodes


def require_case_json(value):
    """Same byte/structure limits used before persistence and on stored reads."""
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    # Check structural shape before serialization; the canonical byte check is
    # exact and never returns a truncated object or altered original string.
    validate_structure(value, maximum_utf8_bytes=MAX_JSON_BYTES)
    encoder = json.JSONEncoder(ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    chunks, size = [], 0
    for chunk in encoder.iterencode(value):
        size += len(utf8(chunk))
        if size > MAX_JSON_BYTES:
            raise ValueError("Complete comparison JSON exceeds 8MiB UTF8")
        chunks.append(chunk)
    return "".join(chunks)


def parse_case_json(raw, *, maximum_nodes=MAX_JSON_NODES, maximum_depth=MAX_JSON_DEPTH):
    if type(raw) is bytes:
        if len(raw) > MAX_JSON_BYTES:
            raise ValueError("Complete comparison JSON exceeds 8MiB UTF8")
        raw = raw.decode("utf-8", errors="strict")
    if type(raw) is not str or len(raw) > MAX_JSON_BYTES or len(utf8(raw)) > MAX_JSON_BYTES:
        raise ValueError("Complete comparison JSON must be valid UTF8 within 8MiB")
    try:
        value = json.loads(raw, object_pairs_hook=unique_pairs, parse_constant=reject_constant)
        validate_structure(value, maximum_nodes=maximum_nodes, maximum_depth=maximum_depth)
    except (RecursionError, OverflowError) as exc:
        raise ValueError("Comparison JSON nesting is excessive") from exc
    return value
