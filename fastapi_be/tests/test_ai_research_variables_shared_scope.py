"""Native76 scope never authorizes generic context or provider fallback."""

import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from starlette.requests import Request

from app.ai import gateway
from app.ai.catalog import CATALOG_VERSION, FEATURE_BY_KEY, FEATURES, describe_feature
from app.ai.context import patient_snapshot
from app.ai.document_extraction_prompt import system_prompt_for
from app.ai.operational_sources import operational_context, operational_options
from app.ai.research_variables_prompt import DEFAULT_TASK_PROMPT, SYSTEM_PROMPT
from app.ai.schemas import OperationalContextRequest, RunRequest
from app.routers.ai import _context_inspection, hospital_service_options, inspect_operational_context


class NoSql:
    def __getattr__(self, key):
        raise AssertionError("Foreign native scope reached SQL operation: " + key)


def test_native_catalog_uses_only_explicit_batch_with_fixed_prompt_patient_data_approval_and_no_added_care_or_knowledge_scope():
    spec = FEATURE_BY_KEY["research_extraction"]
    assert CATALOG_VERSION == "2026.10.26.1" and spec.number == 76 and spec.scope == "input"
    assert spec.requires_patient_data_permission is True and spec.requires_knowledge is False and spec.clinical is False
    assert spec.task_prompt.endswith(DEFAULT_TASK_PROMPT) and system_prompt_for({"research_variable_binding": None}) == SYSTEM_PROMPT
    assert describe_feature(spec)["source_reference_keys"] == ["research_variable_batch_id"]
    assert all("research_variable_batch_id" not in describe_feature(other)["source_reference_keys"] for other in FEATURES if other.number != 76)


@pytest.mark.parametrize("value", [None, "00000000-0000-0000-0000-000000000001"])
def test_foreign_batch_presence_including_null_rejects_all_generic_context_helpers_and_request_contracts_before_sql(value):
    db, user, other, native = NoSql(), SimpleNamespace(), FEATURE_BY_KEY["operations_qa"], FEATURE_BY_KEY["research_extraction"]
    values = {"research_variable_batch_id": value}
    calls = (
        lambda: operational_context(db, user, other, values),
        lambda: operational_context(db, user, native, {}),
        lambda: operational_options(db, user, native),
        lambda: patient_snapshot(db, user, FEATURE_BY_KEY["patient_summary"], 1, source_refs=values),
        lambda: patient_snapshot(db, user, native, 1),
        lambda: _context_inspection(db, user, "patient_summary", 1, None, values),
        lambda: inspect_operational_context(SimpleNamespace(feature_key="operations_qa", input=values), db, user),
    )
    for call in calls:
        with pytest.raises(HTTPException) as error:
            call()
        assert error.value.status_code == 422
    for model in (OperationalContextRequest, RunRequest):
        with pytest.raises(ValidationError):
            model.model_validate({"feature_key": "operations_qa", "input": values})


def test_reserved_batch_query_and_native_feature_reject_service_options_before_sql():
    request = Request({"type": "http", "method": "GET", "path": "/", "query_string": b"research_variable_batch_id="})
    for key, req in (("operations_qa", request), ("research_extraction", None)):
        with pytest.raises(HTTPException) as error:
            hospital_service_options(key, request=req, db=NoSql(), user=SimpleNamespace())
        assert error.value.status_code == 422


@pytest.mark.parametrize("preview", [0, 1, "true", "false", None])
def test_native_preview_is_actual_boolean_not_a_coerced_generic_request_value(preview):
    with pytest.raises(ValidationError):
        RunRequest.model_validate({"feature_key": "research_extraction", "preview": preview, "input": {"research_variable_batch_id": None}})


@pytest.mark.parametrize(
    "packet",
    [
        {"input": {"research_variable_batch_id": None}},
        {"context": {"research_variable_binding": None}},
        {"context": {"research_variable_source": {}}},
        {"context": {"scope": {"source_domain": "published_research_variable_literal_batch"}}},
        {"context": {"scope": {"selected_sources": {"research_variable_batch_id": None}}}},
    ],
)
def test_each_native_packet_marker_is_refused_by_generic_gateway_before_provider_endpoint_or_credentials(packet):
    with pytest.raises(gateway.AIExecutionError) as error:
        gateway._request(SimpleNamespace(), FEATURE_BY_KEY["operations_qa"], "not sent", packet)
    assert error.value.code == "VARIABLE_SOURCE_MODE"


def test_current_native_feature_never_uses_generic_gateway_even_when_caller_removes_all_markers():
    with pytest.raises(gateway.AIExecutionError) as error:
        gateway._request(SimpleNamespace(), FEATURE_BY_KEY["research_extraction"], "not sent", {})
    assert error.value.code == "VARIABLE_SOURCE_MODE"


def test_entire_catalog_and_all_actual_system_overrides_export_in_isolated_stdlib_process_without_db_settings_or_pydantic():
    root = Path(__file__).resolve().parents[1]
    code = (
        "import sys,runpy;sys.path.insert(0," + repr(str(root)) + ");"
        "module=runpy.run_path(" + repr(str(root / "scripts/export_ai_catalog.py")) + ");"
        "data=module['artifacts']();assert len(data)==2;"
        "assert 'research_extraction' in data['ai-prompts.json'];"
        "assert not {'app.database','app.config','app.models','sqlalchemy','pydantic'} & set(sys.modules);print('stdlib80')"
    )
    result = subprocess.run([sys.executable, "-I", "-S", "-c", code], capture_output=True, text=True, check=True)
    assert result.stdout.strip() == "stdlib80" and not result.stderr
