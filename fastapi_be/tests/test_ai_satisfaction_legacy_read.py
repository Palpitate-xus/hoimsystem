"""Only identified pre-Case feedback history may use its old read authorizer.

Classification is not permission or inference. These are synthetic actual SQL
Run rows; Root owns the legacy read authorization and execution prohibition.
"""

import copy
import uuid

import pytest

from app.ai.catalog import COMMON_SYSTEM_PROMPT
from app.ai.models import AIRun
from app.ai.satisfaction_draft import canonical_json, source_hash
from app.ai.satisfaction_storage import is_satisfaction_run
from tests.test_ai_satisfaction_sources import satisfaction_case as satisfaction_case  # noqa: F401
from tests.test_ai_satisfaction_storage import configured_run


def legacy_snapshot():
    return {
        "system_prompt": COMMON_SYSTEM_PROMPT,
        "task_prompt": "合成旧反馈历史任务，仅分类不授予新推理权限。",
        "payload": {"context": {"source_domain": "feedback"}, "input": {}, "tools": {}, "evidence": []},
    }


def legacy_run(db, user):
    snapshot = legacy_snapshot()
    row = AIRun(
        run_id=str(uuid.uuid4()),
        feature_key="feedback_analysis",
        requested_by=user.user_id,
        input_json=canonical_json(snapshot),
        result_json="{}",
        prompt_hash=source_hash([snapshot["system_prompt"], snapshot["task_prompt"]]),
        context_digest=source_hash(snapshot["payload"]["context"]),
    )
    db.add(row)
    db.commit()
    return row


def test_only_actual_explicit_legacy_feedback_without_artifact_is_not_dedicated(db_session, seed_data):
    run = legacy_run(db_session, seed_data["admin_user"])
    assert is_satisfaction_run(db_session, run) is False
    # Without a DB identity check this cannot prove absence of the durable FK.
    assert is_satisfaction_run(None, run) is True


@pytest.mark.parametrize(
    "place,key",
    [
        ("context", "satisfaction_binding"),
        ("context", "satisfaction_source"),
        ("context", "satisfaction_case"),
        ("input", "satisfaction_case_id"),
        ("nested", "satisfaction_source"),
        ("result", "satisfaction_analysis"),
        ("ref", "schema_version"),
    ],
)
def test_even_null_retained_markers_override_a_forged_legacy_body(db_session, seed_data, place, key):
    run = legacy_run(db_session, seed_data["admin_user"])
    snapshot = legacy_snapshot()
    if place in {"context", "input"}:
        snapshot["payload"][place][key] = None
    elif place == "nested":
        snapshot["payload"]["unrecognized"] = {key: None}
    else:
        run.result_json = canonical_json({key: "satisfaction_result_ref_v1" if place == "ref" else None})
    run.input_json = canonical_json(snapshot)
    db_session.commit()
    assert is_satisfaction_run(db_session, run) is True


@pytest.mark.parametrize(
    "bad",
    [
        None,
        [],
        {},
        {"system_prompt": COMMON_SYSTEM_PROMPT},
        {"system_prompt": "forged", "payload": {"context": {"source_domain": "feedback"}, "input": {}}},
        {"system_prompt": COMMON_SYSTEM_PROMPT, "payload": {"context": {"source_domain": "another"}, "input": {}}},
    ],
)
def test_nonexplicit_or_damaged_feature70_never_falls_back(db_session, seed_data, bad):
    run = legacy_run(db_session, seed_data["admin_user"])
    run.input_json = canonical_json(bad)
    db_session.commit()
    assert is_satisfaction_run(db_session, run) is True


@pytest.mark.parametrize("raw", ["{", '{"system_prompt":NaN}', '{"payload":{},"payload":{"context":{"source_domain":"feedback"}}}'])
def test_nonfinite_duplicate_and_unreadable_feature70_stays_strict(db_session, seed_data, raw):
    run = legacy_run(db_session, seed_data["admin_user"])
    run.input_json = raw
    db_session.commit()
    assert is_satisfaction_run(db_session, run) is True


def test_actual_artifact_fk_overrides_erased_markers_even_when_legacy_common_body_is_forged(db_session, satisfaction_case):
    case = configured_run(db_session, satisfaction_case)
    run = case["run"]
    run.input_json, run.result_json = canonical_json(legacy_snapshot()), "{}"
    db_session.commit()
    assert is_satisfaction_run(db_session, run) is True
    run.feature_key = "another-feature"
    db_session.commit()
    assert is_satisfaction_run(db_session, run) is True


def test_plain_text_mention_is_not_a_structural_dedicated_marker(db_session, seed_data):
    run = legacy_run(db_session, seed_data["admin_user"])
    snapshot = copy.deepcopy(legacy_snapshot())
    snapshot["payload"]["input"]["question"] = 'literal text "satisfaction_case_id" is not a source binding'
    run.input_json = canonical_json(snapshot)
    db_session.commit()
    assert is_satisfaction_run(db_session, run) is False


def test_escaped_invalid_unicode_cannot_make_a_damaged_body_look_legacy(db_session, seed_data):
    import json

    run = legacy_run(db_session, seed_data["admin_user"])
    snapshot = legacy_snapshot()
    snapshot["payload"]["input"]["question"] = "invalid" + chr(0xD800)
    run.input_json = json.dumps(snapshot, ensure_ascii=True)
    db_session.commit()
    assert is_satisfaction_run(db_session, run) is True
