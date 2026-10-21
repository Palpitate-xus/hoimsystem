"""Pure synthetic DTO oracle: exact spans and mechanical interval intersections."""

import copy
import subprocess
import sys

import pytest
from pydantic import ValidationError

from app.ai import document_change_contract as c
from app.ai import document_change_draft as d
from app.ai import document_change_result as r

PROMPT = c.e.bytes_hash(d.SYSTEM_PROMPT + "\n\n" + d.TASK_PROMPT)


def source(link_count=4):
    def original(index, text):
        return c.DocumentChangeOriginal(
            schema_version="document_change_original_source_v1",
            original={"original_id": f"00000000-0000-0000-0000-{index:012}", "content_hash": str(index) * 64, "governance_hash": "a" * 64},
            raw_bytes_hash=c.e.bytes_hash(text),
            raw_bytes_length=len(text.encode()),
            codepoint_length=len(text),
            text=text,
        )

    baseline, candidate = original(1, "\ufeff甲\r\n😀e\u0301乙"), original(2, "\ufeff甲\r\n😀e\u0301丙")
    targets, links = [], []
    for i in range(1, link_count + 1):
        state = ["current", "inactive", "unknown", "stale"][(i - 1) % 4]
        within = i % 4 != 2
        target = c.PublicTarget(target={"kind": "clinical_pathway", "target_id": i}, snapshot_hash=c.e.digest(["target", i]), state=state, within_declared_scope=within)
        targets.append(target)
        spans = [(0, 1), (1, 3), (4, 5), (5, 7)]
        start, end = spans[(i - 1) % 4]
        parent = candidate if i % 4 == 3 else baseline
        links.append(
            c.PublicRuleLink(
                link_id=f"00000000-0000-0000-0001-{i:012}",
                content_hash=c.e.digest(["link", i]),
                governance_hash="b" * 64,
                original=parent.original,
                start=start,
                end=end,
                quote_bytes_hash=c.e.bytes_hash(parent.text[start:end]),
                target=target.target,
                target_snapshot_hash=target.snapshot_hash if state == "current" else "f" * 64,
                dependency_kind="requires_human_review",
                current=state == "current",
                within_declared_scope=within,
            )
        )
    # Lexical target ordering is the frozen source's explicit contract.
    targets.sort(key=lambda value: c.target_key(value.target))
    return c.DocumentChangeSource(
        schema_version=c.SCHEMA_VERSION,
        scope={"scope_id": "00000000-0000-0000-0000-000000000072", "content_hash": "c" * 64, "governance_hash": "d" * 64},
        baseline=baseline,
        candidate=candidate,
        relationship_kind="comparison_only",
        same_guideline_family="unknown",
        rule_link_coverage="unknown",
        targets=targets,
        rule_links=links,
        publications=[],
        member_count=2 + 2 * link_count,
        inventory_hash="e" * 64,
        hospital_wide_rule_inventory="not_provided",
        clinical_validation="not_provided",
    )


def span(original, start, end):
    return {"start": start, "end": end, "quote": original.text[start:end]}


def change(src=None, **values):
    src = src or source()
    return {
        "kind": "paired_wording_question",
        "baseline_spans": [span(src.baseline, 0, 3)],
        "candidate_spans": [span(src.candidate, 4, 5)],
        "review_note": "这里仅提出待人工确认的问题，不推断真实影响。",
        "clarification_question": "请人工核对两段原文的适用条件是否相同？",
        **values,
    }


def build(src=None, changes=None):
    src = src or source()
    return d.parse_provider_reply(c.e.canonical_json({"changes": [change(src)] if changes is None else changes}), src, PROMPT)


def test_pure_contract_and_result_import_no_hospital_or_database():
    code = "import sys;import app.ai.document_change_draft;import app.ai.document_change_result;assert not any(n in sys.modules for n in ('app.config','app.database','app.models','sqlalchemy'))"
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_actual_codepoints_literal_equality_and_independent_half_open_overlap_oracle():
    src = source()
    result = build(src)
    expected = []
    for link in src.rule_links:
        side = 0 if link.original == src.baseline.original else 1
        intervals = result.changes[0].baseline_spans if side == 0 else result.changes[0].candidate_spans
        overlap = [i for i, value in enumerate(intervals) if max(value.start, link.start) < min(value.end, link.end)]
        if overlap:
            expected.append((link.link_id, overlap if side == 0 else [], overlap if side else []))
    observed = [(value.link.link_id, value.baseline_span_ordinals, value.candidate_span_ordinals) for value in result.changes[0].link_overlaps]
    assert observed == expected and len(observed) == 3
    assert result.changes[0].baseline_spans[0].quote == "\ufeff甲\r"
    assert result.changes[0].candidate_spans[0].quote == "😀"
    assert result.changes[0].link_overlaps[1].link.current is False
    assert result.changes[0].link_overlaps[1].target.within_declared_scope is False
    assert result.changes[0].link_overlaps[2].target.state == "unknown"
    assert all(value.meaning == d.OVERLAP_NOTE for value in result.changes[0].link_overlaps)
    assert d.validate_draft(result, src, PROMPT) == result


def test_touching_endpoints_are_not_overlap_and_omitted_overlap_is_not_no_impact():
    src = source()
    value = build(src, [change(src, baseline_spans=[span(src.baseline, 0, 1)])])
    assert [x.link.link_id for x in value.changes[0].link_overlaps] == [src.rule_links[0].link_id, src.rule_links[2].link_id]
    assert value.coverage == d.COVERAGE and value.requires_human_review is True and value.automatic_changes is False


@pytest.mark.parametrize("kind", ["baseline_excerpt_question", "candidate_excerpt_question", "insufficient_evidence"])
def test_single_side_or_no_span_does_not_claim_other_side_absent(kind):
    src = source()
    value = change(
        src,
        kind=kind,
        baseline_spans=[] if kind != "baseline_excerpt_question" else [span(src.baseline, 0, 1)],
        candidate_spans=[] if kind != "candidate_excerpt_question" else [span(src.candidate, 4, 5)],
    )
    draft = build(src, [value])
    result = r.result_for_draft(draft, src, PROMPT)
    assert result.document_change.requires_human_review is True
    assert d.COVERAGE_NOTE in result.warnings
    assert "空结果不表示没有变化" in d.COVERAGE_NOTE
    assert r.validate_result(result, src, PROMPT) == result


def test_empty_change_output_still_explicitly_unreviewed_and_incomplete():
    src = source()
    draft = build(src, [])
    result = r.result_for_draft(draft, src, PROMPT)
    assert not draft.changes and draft.requires_human_review
    assert "0项未核实" in result.summary and len(result.missing_data) == 3


@pytest.mark.parametrize("field,bad", [("start", True), ("start", 1.0), ("start", "0"), ("end", -1), ("quote", "invented"), ("quote", "\ud800")])
def test_literal_span_rejects_bool_precision_type_and_changed_quote(field, bad):
    src = source()
    body = change(src)
    body["baseline_spans"][0][field] = bad
    with pytest.raises((ValueError, ValidationError, UnicodeError)):
        build(src, [body])


@pytest.mark.parametrize(
    "raw", ['{"changes":[],"changes":[]}', '{"changes":[{"x":1,"x":2}]}', '{"changes":[],"n":NaN}', '{"changes":[],"n":1e999}', '```json\n{"changes":[]}\n```', '{"changes":', "null"]
)
def test_whole_provider_json_no_duplicates_nonfinite_fences_truncation_or_scalar(raw):
    with pytest.raises(ValueError):
        d.parse_provider_reply(raw, source(), PROMPT)


@pytest.mark.parametrize("extra", ["scope_id", "instructions_digest", "target_updates", "automatic_changes", "supersedes", "severity"])
def test_provider_cannot_set_binding_target_actions_or_automatic_claims(extra):
    with pytest.raises(ValidationError):
        d.build_draft({"changes": [], extra: "claimed"}, source(), PROMPT)


@pytest.mark.parametrize("field", ["source_projection_hash", "instructions_digest", "scope_content_hash", "scope_governance_hash", "scope_id"])
def test_frozen_binding_fields_are_checked_against_source_and_server_prompt(field):
    src = source()
    raw = build(src).model_dump(mode="json")
    raw["binding"][field] = "00000000-0000-0000-0000-000000000099" if field == "scope_id" else "0" * 64
    with pytest.raises(ValueError):
        d.validate_draft(raw, src, PROMPT)


@pytest.mark.parametrize("mutation", ["omit", "target_state", "within", "current", "ordinal", "claim"])
def test_every_derived_overlap_is_recomputed_and_none_can_be_hidden(mutation):
    src = source()
    raw = build(src).model_dump(mode="json")
    witness = raw["changes"][0]["link_overlaps"][0]
    if mutation == "omit":
        raw["changes"][0]["link_overlaps"].pop()
    elif mutation == "target_state":
        witness["target"]["state"] = "stale"
    elif mutation == "within":
        witness["target"]["within_declared_scope"] = False
    elif mutation == "current":
        witness["link"]["current"] = False
    elif mutation == "ordinal":
        witness["baseline_span_ordinals"] = [True]
    else:
        witness["meaning"] = "confirmed_impact"
    with pytest.raises(ValueError):
        d.validate_draft(raw, src, PROMPT)


def test_mutated_pydantic_instances_are_not_treated_as_already_trusted():
    src = source()
    reply = d.ProviderReply(changes=[d.ProposedChange.model_validate(change(src))])
    reply.changes[0].baseline_spans[0].start = True
    with pytest.raises(ValueError):
        d.build_draft(reply, src, PROMPT)


@pytest.mark.parametrize("flag,value", [("requires_human_review", 1), ("automatic_changes", 0), ("automatic_changes", True)])
def test_review_and_action_flags_are_actual_server_booleans(flag, value):
    src = source()
    raw = build(src).model_dump(mode="json")
    raw[flag] = value
    with pytest.raises(ValueError):
        d.validate_draft(raw, src, PROMPT)


def test_span_and_change_caps_do_not_silently_drop_excess():
    src = source()
    with pytest.raises(ValueError):
        build(src, [change(src)] * 129)
    with pytest.raises(ValueError):
        build(src, [change(src, baseline_spans=[span(src.baseline, 0, 1)] * 17)])
    with pytest.raises(ValueError):
        build(src, [change(src, baseline_spans=[span(src.baseline, 0, 1)] * 2)])


@pytest.mark.parametrize("field", ["summary", "sections", "warnings", "missing_data", "document_change"])
def test_server_fixed_result_missing_fields_and_forgery_are_not_defaulted(field):
    src = source()
    raw = r.result_for_draft(build(src), src, PROMPT).model_dump(mode="json")
    raw.pop(field)
    with pytest.raises(ValueError):
        r.validate_result(raw, src, PROMPT)


def test_false_semantic_question_remains_unverified_and_literal_binding_not_endorsement():
    src = source()
    proposal = change(src, review_note="这段相同引文是否足以证明所有院内规则必须更新？", clarification_question="请人工核对该说法，不能依据区间交叠自行改规则。")
    result = r.result_for_draft(build(src, [proposal]), src, PROMPT)
    assert result.document_change.changes[0].review_note == proposal["review_note"]
    assert proposal["review_note"] not in result.summary
    assert any("未经临床语义审核" in text for text in result.warnings)
    assert result.document_change.automatic_changes is False


def test_oversized_input_and_complete_repeated_overlap_proof_refused_not_partial():
    src = source()
    with pytest.raises(ValueError):
        d.parse_provider_reply('{"changes":[],"padding":"' + "x" * d.MAX_JSON_BYTES + '"}', src, PROMPT)
    large = source(700)
    body = change(large, baseline_spans=[span(large.baseline, 0, large.baseline.codepoint_length)], candidate_spans=[span(large.candidate, 0, large.candidate.codepoint_length)])
    before = c.e.digest(large)
    with pytest.raises(ValueError, match="overlap proof"):
        build(large, [body] * 128)
    assert c.e.digest(large) == before


@pytest.mark.parametrize("mutation", ["quote_hash", "range_end", "current_state", "within_scope"])
def test_source_link_literal_and_current_labels_cannot_be_spoofed(mutation):
    body = source().model_dump(mode="json")
    if mutation == "quote_hash":
        body["rule_links"][0]["quote_bytes_hash"] = "f" * 64
    elif mutation == "range_end":
        body["rule_links"][0]["end"] = 100
    elif mutation == "current_state":
        body["targets"][0]["state"] = "unknown"
    else:
        body["rule_links"][0]["within_declared_scope"] = False
    with pytest.raises(ValueError):
        d.build_draft({"changes": []}, body, PROMPT)


def test_result_summary_or_source_citation_cannot_be_model_assertion():
    src = source()
    raw = r.result_for_draft(build(src), src, PROMPT).model_dump(mode="json")
    altered = copy.deepcopy(raw)
    altered["summary"] = "已确认所有规则受到影响并应停用"
    with pytest.raises(ValueError):
        r.validate_result(altered, src, PROMPT)
    altered = copy.deepcopy(raw)
    altered["sections"][0]["source_ids"] = ["invented-source"]
    with pytest.raises(ValueError):
        r.validate_result(altered, src, PROMPT)
