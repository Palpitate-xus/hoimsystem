"""Pure complete-object byte, node and depth policies for the larger Case."""

import json
import subprocess
import sys

import pytest

from app.ai import document_change_json as j


def test_no_hospital_or_71_parser_dependency_execution():
    code = "import sys;import app.ai.document_change_json;assert not any(n in sys.modules for n in ('app.config','app.database','app.models','sqlalchemy'))"
    checked = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert checked.returncode == 0, checked.stderr


@pytest.mark.parametrize("raw", ['{"a":1,"a":2}', '{"nested":{"a":1,"a":2}}', '{"n":NaN}', '{"n":Infinity}', '{"n":1e999}', '{"s":"\\ud800"}', b'{"s":"\xff"}', "```json\n{}\n```", '{"x":1} trailing'])
def test_invalid_complete_json_is_rejected_without_repair(raw):
    with pytest.raises((ValueError, UnicodeError)):
        j.parse_case_json(raw)


@pytest.mark.parametrize("raw", ["null", "false", "0", '"raw"', "[]"])
def test_top_level_is_actual_closed_object(raw):
    with pytest.raises(ValueError):
        j.parse_case_json(raw)


def test_explicit_node_boundary_counts_keys_values_and_containers():
    body = '{"x":[0,1]}'
    assert j.validate_structure(json.loads(body)) == 5
    assert j.parse_case_json(body, maximum_nodes=5) == {"x": [0, 1]}
    with pytest.raises(ValueError, match="node or depth"):
        j.parse_case_json(body, maximum_nodes=4)


def test_explicit_depth_boundary_includes_root_and_keys():
    assert j.parse_case_json('{"x":{"y":0}}', maximum_depth=3) == {"x": {"y": 0}}
    with pytest.raises(ValueError, match="node or depth"):
        j.parse_case_json('{"x":{"y":0}}', maximum_depth=2)
    with pytest.raises(ValueError):
        j.parse_case_json('{"x":' + "[" * 2000 + "0" + "]" * 2000 + "}")


def test_exact_utf8_envelope_limit_without_normalization_or_truncation():
    decoded = json.loads(json.dumps({"x": "\ufeff甲\r\n😀e\u0301"}, ensure_ascii=False))
    assert j.parse_case_json(j.require_case_json(decoded)) == decoded
    raw = '{"x":"' + "a" * (j.MAX_JSON_BYTES - len('{"x":""}')) + '"}'
    assert len(raw.encode()) == j.MAX_JSON_BYTES
    assert j.parse_case_json(raw)["x"] == "a" * (j.MAX_JSON_BYTES - len('{"x":""}'))
    with pytest.raises(ValueError, match="8MiB"):
        j.parse_case_json(raw + " ")
    with pytest.raises(ValueError):
        j.require_case_json({"x": "a" * j.MAX_JSON_BYTES})


def test_oversize_object_is_refused_before_encoding_whole_tree(monkeypatch):
    monkeypatch.setattr(j, "MAX_JSON_BYTES", 64)
    calls = []

    def forbidden(**kwargs):
        calls.append(kwargs)
        raise AssertionError("Giant serialization must not be attempted")

    monkeypatch.setattr(j.json, "JSONEncoder", forbidden)
    with pytest.raises(ValueError, match="8MiB"):
        j.require_case_json({"first": "a" * 40, "second": "b" * 40})
    assert calls == []
