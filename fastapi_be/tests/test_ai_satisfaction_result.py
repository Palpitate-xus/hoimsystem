"""Server-owned exact statistics and pure Prompt/Result module boundaries."""

import copy
import subprocess
import sys
from pathlib import Path

import pytest

from app.ai.catalog import COMMON_SYSTEM_PROMPT
from app.ai.satisfaction_draft import validate_draft
from app.ai.satisfaction_prompt import SATISFACTION_SYSTEM_PROMPT, SATISFACTION_TASK_PROMPT, SATISFACTION_TASK_PROMPT_VERSION, system_prompt_for
from app.ai.satisfaction_result import result_for_draft, validate_result
from tests.test_ai_satisfaction_draft import example


def test_actual_safe_export_fixed_result_rebuilds_complete_exact_statistics_and_draft():
    source, draft = example()
    before = copy.deepcopy(source)
    checked = validate_draft(source, draft)
    result = result_for_draft(source, checked)
    assert result.recorded_statistics.all_member_statistics.model_dump(mode="json") == source["safe_snapshot"]["all_member_statistics"]
    assert result.recorded_statistics.known_period_statistics.model_dump(mode="json") == source["safe_snapshot"]["known_period_statistics"]
    assert result.recorded_statistics.complete_member_root_count == 6
    assert result.recorded_statistics.selected_excerpt_count == 1
    assert result.recorded_statistics.proposed_theme_count == 1
    assert validate_result(result.model_dump(mode="json"), source) == result
    assert source == before and len(result.sections) == 3
    assert "2/1" in result.sections[1].content
    assert "评分统计与人工摘录主题分别核对" in result.warnings[1]


@pytest.mark.parametrize("field,value", [("summary", "全院所有人完全满意"), ("sections", []), ("warnings", []), ("missing_data", []), ("business_write", True)])
def test_rehashed_result_cannot_replace_fixed_explanation_or_enable_business_write(field, value):
    source, draft = example()
    result = result_for_draft(source, draft).model_dump(mode="json")
    result[field] = value
    with pytest.raises(ValueError):
        validate_result(result, source)


@pytest.mark.parametrize("mutation", ["mean", "roots", "selected", "themes", "original_histogram", "theme_quote", "foreign_analysis"])
def test_exact_statistics_and_partial_draft_are_bound_independently(mutation):
    source, draft = example()
    result = result_for_draft(source, draft).model_dump(mode="json")
    if mutation == "mean":
        stats = result["recorded_statistics"]["all_member_statistics"]
        stats["histogram"]["2"], stats["histogram"]["5"] = 0, 1
        stats["mean_valid_score"] = {"numerator": 5, "denominator": 1}
    elif mutation == "roots":
        result["recorded_statistics"]["complete_member_root_count"] -= 1
    elif mutation == "selected":
        result["recorded_statistics"]["selected_excerpt_count"] = 0
    elif mutation == "themes":
        result["recorded_statistics"]["proposed_theme_count"] = 0
    elif mutation == "original_histogram":
        result["recorded_statistics"]["all_member_statistics"]["nps"] = 100
    elif mutation == "theme_quote":
        result["satisfaction_analysis"]["themes"][0]["citations"][0]["quote"] = "不对应原摘录的模型文字"
    else:
        result["inventory_analysis"] = result["satisfaction_analysis"]
    with pytest.raises(ValueError):
        validate_result(result, source)


def test_dedicated_prompt_instructs_literal_selected_excerpts_and_fixed_partial_scope():
    assert SATISFACTION_SYSTEM_PROMPT.startswith(COMMON_SYSTEM_PROMPT)
    for text in (
        "satisfaction_evidence_draft_v1",
        "partial_themes_no_population_or_causality_claim",
        "BOM",
        "CRLF",
        "emoji",
        "Unicode码点",
        "selected_excerpts",
        "时区",
        "投诉工单",
        "不执行工具",
        "不得返回summary",
    ):
        assert text in SATISFACTION_SYSTEM_PROMPT
    assert SATISFACTION_TASK_PROMPT_VERSION == "satisfaction_evidence_task_v1"
    assert "评分直方图和均分由服务器计算" in SATISFACTION_TASK_PROMPT
    assert system_prompt_for({"satisfaction_binding": {}}) == SATISFACTION_SYSTEM_PROMPT
    assert system_prompt_for({"other_binding": {}}) == COMMON_SYSTEM_PROMPT


def test_pure_modules_import_without_database_settings_dotenv_network_or_other_feature_service():
    root = Path(__file__).resolve().parents[1]
    program = r"""
import builtins,sys
original=builtins.__import__
blocked=('sqlalchemy','dotenv','socket','httpx','requests','urllib3','app.database','app.models','app.main','app.config','app.settings','app.ai.satisfaction_sources','app.ai.charge_reconciliation')
attempts=[]
def guarded(name,*args,**kwargs):
    if any(name==key or name.startswith(key+'.') for key in blocked):
        attempts.append(name)
        raise RuntimeError('Forbidden impure import: '+name)
    return original(name,*args,**kwargs)
builtins.__import__=guarded
import app.ai.satisfaction_draft
import app.ai.satisfaction_protocol
import app.ai.satisfaction_prompt
import app.ai.satisfaction_result
assert not attempts
assert not any(key in sys.modules for key in ('app.database','app.models','dotenv','sqlalchemy'))
print('pure satisfaction modules: no forbidden import')
"""
    result = subprocess.run([sys.executable, "-I", "-c", "import sys;sys.path.insert(0," + repr(str(root)) + ");" + program], cwd=root, capture_output=True, text=True, timeout=20, check=False)
    assert result.returncode == 0, result.stderr
    assert "no forbidden import" in result.stdout
