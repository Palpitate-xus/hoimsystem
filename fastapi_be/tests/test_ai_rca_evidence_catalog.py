"""Actual native RCA catalog boundary and dependency-free frozen Prompt export."""

import json
import subprocess
import sys
from pathlib import Path

from app.ai.catalog import FEATURE_BY_KEY, FEATURES, describe_feature
from app.ai.feature_prompts import system_prompt_for_feature
from app.ai.governance import describe_config
from app.ai.rca_evidence_task_prompt import PROMPT_VERSION, SYSTEM_PROMPT, TASK_PROMPT


def test_native_rca_has_only_its_explicit_case_scope_super_role_and_sensitive_provider_permission(db_session):
    spec = FEATURE_BY_KEY["incident_rca"]
    assert spec.scope == "input" and spec.default_roles == ("super_admin",)
    assert spec.requires_patient_data_permission is True and spec.requires_knowledge is False
    assert describe_feature(spec)["source_reference_keys"] == ["rca_evidence_case_id"]
    data = describe_config(db_session, spec, None, management=True)
    assert data["input_mode"] == "rca_evidence" and data["enabled"] is False and data["provider_configured"] is False
    assert data["allowed_roles"] == ["super_admin"] and data["implementation_status"] == "gateway"
    assert system_prompt_for_feature(spec) == SYSTEM_PROMPT
    assert spec.task_prompt.endswith(TASK_PROMPT) and PROMPT_VERSION in spec.task_prompt
    assert spec.instruction in spec.task_prompt and "最多64项" in spec.instruction
    assert len(FEATURES) == 80
    for other in FEATURES:
        if other.number != 77:
            assert "rca_evidence_case_id" not in describe_feature(other)["source_reference_keys"]


def test_native_rca_offline_export_needs_only_stdlib_and_retains_actual_complete_default_prompt(tmp_path):
    backend = Path(__file__).resolve().parents[1]
    code = """
import json, pathlib, runpy, sys
root=pathlib.Path(sys.argv[1]);sys.path.insert(0,str(root))
module=runpy.run_path(str(root/'scripts/export_ai_catalog.py'))
artifacts=module['artifacts']()
for forbidden in ('pydantic','pydantic_settings','sqlalchemy','app.config','app.database','app.models'):
 assert forbidden not in sys.modules, forbidden
print(artifacts['ai-prompts.json'])
"""
    process = subprocess.run([sys.executable, "-I", "-S", "-c", code, str(backend)], capture_output=True, text=True, check=True, cwd=tmp_path)
    exported = json.loads(process.stdout)
    assert len(exported["features"]) == 80
    row = next(item for item in exported["features"] if item["key"] == "incident_rca")
    assert row["task_prompt"] == FEATURE_BY_KEY["incident_rca"].task_prompt and row["source_reference_keys"] == ["rca_evidence_case_id"]
    assert row["default_roles"] == ["super_admin"] and row["requires_patient_data_permission"] is True
    assert exported["system_prompt_overrides"]["incident_rca"] == SYSTEM_PROMPT
