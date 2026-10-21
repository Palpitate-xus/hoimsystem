"""Literal selected-excerpt themes, exact safe membership, no hospital I/O."""

import copy
import datetime as dt
import json
from pathlib import Path

import pytest

from app.ai.review_curation import create_excerpt, load_review_source, review_excerpt
from app.ai.satisfaction_draft import MAX_BYTES, MAX_THEMES, SatisfactionEvidenceDraft, parse_draft, source_hash, validate_draft, validate_source
from app.ai.satisfaction_result import result_for_draft
from app.ai.schemas import ReviewExcerptReview, ReviewExcerptWrite
from app.models import Review
from tests.test_ai_satisfaction_sources import published
from tests.test_ai_satisfaction_sources import satisfaction_case as satisfaction_case  # noqa: F401


def example():
    source = json.loads((Path(__file__).parent / "fixtures/satisfaction/actual-safe-source.json").read_text())
    excerpt = source["safe_snapshot"]["selected_excerpts"][0]
    draft = {
        "schema_version": "satisfaction_evidence_draft_v1",
        "satisfaction_source_id": source["source_id"],
        "safe_projection_hash": source["safe_projection_hash"],
        "coverage": "partial_themes_no_population_or_causality_claim",
        "themes": [
            {
                "title": "候诊顺序待核实",
                "observation": "这条人工摘录提及等候体验，相关解释仍需人工核实。",
                "clarification_question": "能否补充当次实际候诊顺序的可核实依据？",
                "cited_excerpt_tokens": [excerpt["excerpt_token"]],
                "citations": [{"excerpt_token": excerpt["excerpt_token"], "text_hash": excerpt["text_hash"], "start": 0, "end": len(excerpt["text"]), "quote": excerpt["text"]}],
            }
        ],
    }
    return source, draft


def accept(source, draft):
    return validate_draft(source, parse_draft(json.dumps(draft, ensure_ascii=False)))


def rehash(source):
    source["safe_snapshot"]["member_manifest_hash"] = source_hash(source["safe_snapshot"]["member_manifest"])
    source["safe_projection_hash"] = source_hash(source["safe_snapshot"])
    return source


def test_actual_exported_safe_source_all_versions_remain_and_neither_projection_nor_draft_mutates():
    source, draft = example()
    before = copy.deepcopy(source)
    checked = accept(source, draft)
    assert checked.themes[0].citations[0].quote == source["safe_snapshot"]["selected_excerpts"][0]["text"]
    assert len(source["safe_snapshot"]["member_manifest"]) == 6
    assert {row["status"] for row in source["safe_snapshot"]["member_manifest"]} == {"not_applicable", "published", "draft", "rejected", "retired"}
    assert validate_source(source) == source == before
    assert "patient_id" not in json.dumps(source) and "review_id" not in json.dumps(source)


def test_actual_sql_published_bom_crlf_and_emoji_are_cited_by_codepoints_without_normalization(db_session, satisfaction_case):
    db, case = db_session, satisfaction_case
    review_excerpt(
        db,
        case["super_admin_user"],
        case["excerpt"].excerpt_id,
        ReviewExcerptReview(expected_revision=2, status="retired", privacy_checked=True, faithfulness_checked=True, review_note="实际合成旧版本退役，另建包含原BOM和换行的人工版本。"),
    )
    db.commit()
    original = "\ufeff合成🧪\r\n等候说明需要核实。"
    current = load_review_source(db, case["review"].review_id)
    excerpt = create_excerpt(
        db,
        case["super_admin_user"],
        ReviewExcerptWrite(review_id=case["review"].review_id, expected_source_hash=current.fingerprint, redacted_text=original, change_note="实际合成BOM和CRLF人工摘录声明。"),
    )
    db.commit()
    case["excerpt"] = review_excerpt(
        db,
        case["super_admin_user"],
        excerpt.excerpt_id,
        ReviewExcerptReview(expected_revision=1, status="published", privacy_checked=True, faithfulness_checked=True, review_note="实际合成人工隐私及原意核查声明。"),
    )
    db.commit()
    source = published(db, case)["public_source"]
    assert source["safe_snapshot"]["selected_excerpts"][0]["text"] == original
    _, draft = example()
    selected = source["safe_snapshot"]["selected_excerpts"][0]
    draft.update(satisfaction_source_id=source["source_id"], safe_projection_hash=source["safe_projection_hash"])
    theme = draft["themes"][0]
    theme["cited_excerpt_tokens"] = [selected["excerpt_token"]]
    theme["citations"] = [{"excerpt_token": selected["excerpt_token"], "text_hash": selected["text_hash"], "start": 4, "end": 10, "quote": original[4:10]}]
    assert accept(source, draft).themes[0].citations[0].quote == "\r\n等候说明"
    # UTF16 counts the preceding emoji twice; CP4 is the original CR, not CP5.
    theme["citations"][0].update(start=5, end=11)
    with pytest.raises(ValueError):
        accept(source, draft)


def test_actual_sql_invalid_null_and_unknown_date_ratings_are_exact_independent_statistics(db_session, satisfaction_case):
    db, case = db_session, satisfaction_case
    for score, clock in ((5, None), (None, dt.datetime(2026, 10, 20)), (-4, dt.datetime(2026, 10, 20)), (9, dt.datetime(2026, 10, 20))):
        db.add(Review(doctor_id=case["doctor"].doctor_id, score=score, review_time=clock))
    db.commit()
    source = published(db, case, selected=False)["public_source"]
    _, draft = example()
    draft.update(satisfaction_source_id=source["source_id"], safe_projection_hash=source["safe_projection_hash"], themes=[])
    result = result_for_draft(source, accept(source, draft))
    actual = result.recorded_statistics
    assert actual.all_member_statistics.record_count == 5
    assert actual.all_member_statistics.valid_score_count == 2
    assert actual.all_member_statistics.null_score_count == 1
    assert actual.all_member_statistics.invalid_score_count == 2
    assert actual.all_member_statistics.mean_valid_score.model_dump() == {"numerator": 7, "denominator": 2}
    assert actual.known_period_statistics.mean_valid_score.model_dump() == {"numerator": 2, "denominator": 1}
    assert actual.unknown_date_member_count == 1 and actual.proposed_theme_count == 0


@pytest.mark.parametrize(
    "key,value",
    [
        ("start", True),
        ("start", "0"),
        ("start", 0.0),
        ("start", -1),
        ("end", 0),
        ("end", 9999),
        ("quote", "不同的原文不能充当引文"),
        ("quote", "\ud800"),
        ("text_hash", "f" * 64),
        ("excerpt_token", "f" * 64),
    ],
)
def test_wrong_literal_hash_offsets_or_scalars_never_become_themes(key, value):
    source, draft = example()
    draft["themes"][0]["citations"][0][key] = value
    with pytest.raises(ValueError):
        accept(source, draft)


@pytest.mark.parametrize(
    "mutation",
    [
        "source",
        "hash",
        "coverage",
        "summary",
        "raw_comment",
        "instructions",
        "score",
        "foreign",
        "unselected",
        "duplicate_ref",
        "missing_citation",
        "extra_ref",
        "duplicate_citation",
        "duplicate_theme",
        "blank_title",
        "blank_question",
        "surrogate",
    ],
)
def test_closed_partial_theme_contract_rejects_foreign_members_and_invented_statistics(mutation):
    source, draft = example()
    theme = draft["themes"][0]
    if mutation == "source":
        draft["satisfaction_source_id"] = "satisfaction_case:11111111-1111-1111-1111-111111111111:" + "f" * 12
    elif mutation == "hash":
        draft["safe_projection_hash"] = "f" * 64
    elif mutation == "coverage":
        draft["coverage"] = "all_people_satisfied"
    elif mutation in {"summary", "raw_comment", "instructions", "score"}:
        draft[mutation] = "not permitted"
    elif mutation in {"foreign", "unselected"}:
        value = "f" * 64 if mutation == "foreign" else next(row["member_token"] for row in source["safe_snapshot"]["member_manifest"] if row["kind"] == "excerpt" and not row["selected"])
        theme["cited_excerpt_tokens"] = [value]
        theme["citations"][0]["excerpt_token"] = value
    elif mutation == "duplicate_ref":
        theme["cited_excerpt_tokens"] *= 2
    elif mutation == "missing_citation":
        theme["citations"] = []
    elif mutation == "extra_ref":
        theme["cited_excerpt_tokens"].append("f" * 64)
    elif mutation == "duplicate_citation":
        theme["citations"] *= 2
    elif mutation == "duplicate_theme":
        draft["themes"].append(copy.deepcopy(theme))
    elif mutation == "blank_title":
        theme["title"] = "    "
    elif mutation == "blank_question":
        theme["clarification_question"] = "    "
    else:
        theme["observation"] += "\ud800"
    with pytest.raises(ValueError):
        accept(source, draft)


@pytest.mark.parametrize(
    "mutation",
    [
        "all_histogram",
        "known_histogram",
        "unknown_count",
        "parent_count",
        "duplicate_review",
        "missing_review_root",
        "duplicate_root",
        "root_content",
        "selected_missing",
        "selected_unpublished",
        "selected_version",
        "selected_text_hash",
        "selected_root_hash",
        "score_state",
        "date_state",
        "cohort_zero",
        "period",
    ],
)
def test_rehashing_safe_source_cannot_repair_false_statistics_or_incomplete_members(mutation):
    source, draft = example()
    safe = source["safe_snapshot"]
    selected = next(row for row in safe["member_manifest"] if row["selected"])
    if mutation in {"all_histogram", "known_histogram"}:
        stats = safe["all_member_statistics" if mutation == "all_histogram" else "known_period_statistics"]
        stats["histogram"]["2"], stats["histogram"]["5"] = 0, 1
        stats["mean_valid_score"] = {"numerator": 5, "denominator": 1}
    elif mutation == "unknown_count":
        safe["unknown_date_member_count"] += 1
    elif mutation == "parent_count":
        safe["unresolved_parent_count"] += 1
    elif mutation == "duplicate_review":
        safe["reviews"] *= 2
    elif mutation == "missing_review_root":
        safe["member_manifest"] = [row for row in safe["member_manifest"] if row["kind"] != "review"]
    elif mutation == "duplicate_root":
        safe["member_manifest"].append(copy.deepcopy(safe["member_manifest"][0]))
    elif mutation == "root_content":
        next(row for row in safe["member_manifest"] if row["kind"] == "review")["content_hash"] = "f" * 64
    elif mutation == "selected_missing":
        safe["selected_excerpts"] = []
    elif mutation == "selected_unpublished":
        selected["status"] = "draft"
    elif mutation == "selected_version":
        selected["version"] = safe["selected_excerpts"][0]["version"] = -1
    elif mutation == "selected_text_hash":
        safe["selected_excerpts"][0]["text"] += "extra"
    elif mutation == "selected_root_hash":
        selected["content_hash"] = "f" * 64
    elif mutation == "score_state":
        safe["reviews"][0]["score_status"] = "invalid"
    elif mutation == "date_state":
        safe["reviews"][0]["date_status"] = "unknown_legacy_clock"
    elif mutation == "cohort_zero":
        safe["doctor_cohort_size"] = 0
    else:
        safe["date_to"] = "2028-01-01"
    rehash(source)
    draft["safe_projection_hash"] = source["safe_projection_hash"]
    with pytest.raises(ValueError):
        accept(source, draft)


def test_duplicate_nested_json_members_nonfinite_fences_and_surrogates_rejected():
    _, draft = example()
    raw = json.dumps(draft)
    for value in (
        raw.replace('"themes":', '"themes":[],"themes":', 1),
        raw.replace('"start": 0', '"start":0,"start":0'),
        raw.replace('"start": 0', '"start": NaN'),
        "```json\n" + raw + "\n```",
        raw + "\ud800",
    ):
        with pytest.raises(ValueError):
            parse_draft(value)


def test_full_theme_limit_is_inclusive_and_larger_output_is_rejected_without_truncation():
    source, draft = example()
    theme = draft["themes"][0]
    draft["themes"] = [{**copy.deepcopy(theme), "title": f"合成主题第{i:03}项"} for i in range(MAX_THEMES)]
    assert len(accept(source, draft).themes) == 64
    draft["themes"].append({**copy.deepcopy(theme), "title": "第六十五项合成主题"})
    with pytest.raises(ValueError):
        accept(source, draft)
    with pytest.raises(ValueError):
        parse_draft(" " * MAX_BYTES + json.dumps(draft))


def test_mutated_typed_model_is_rechecked_and_empty_draft_cannot_imply_full_satisfaction():
    source, draft = example()
    typed = SatisfactionEvidenceDraft.model_validate(draft)
    typed.themes[0].citations[0].quote = "改写不能作为真实引文"
    with pytest.raises(ValueError):
        validate_draft(source, typed)
    draft["themes"] = []
    result = result_for_draft(source, accept(source, draft))
    assert "0项" in result.summary and "未作总体或因果结论" in result.summary
    assert result.recorded_statistics.all_member_statistics.record_count == 1


def test_a_selected_excerpt_cannot_hide_another_current_eligible_version_for_the_same_review():
    source, draft = example()
    other = next(row for row in source["safe_snapshot"]["member_manifest"] if row["kind"] == "excerpt" and not row["selected"])
    other.update(status="published", version=99, revision=2, eligibility="eligible_manual_claim", exclusion_reasons=[])
    rehash(source)
    draft["safe_projection_hash"] = source["safe_projection_hash"]
    with pytest.raises(ValueError):
        accept(source, draft)
