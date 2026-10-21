"""Pure view schemas and immutable SQL anchor boundaries, without hospital imports."""

import subprocess
import sys

import pytest
from pydantic import ValidationError

from app.ai import document_extraction_view_contract as v


def anchor():
    return {
        "run_id": "00000000-0000-0000-0000-000000000071",
        "original_id": "00000000-0000-0000-0000-000000000072",
        "requested_by": 1,
        "schema_version": "document_extraction_run_anchor_v1",
        "recorded_at": "2026-10-21T12:00:00.123456Z",
        **{name: "a" * 64 for name in ("original_content_hash", "original_governance_hash", "source_digest", "prompt_hash", "context_digest", "input_hash", "evidence_hash", "metadata_hash")},
    }


def test_anchor_preserves_all_eight_separate_hashes_actual_utc6_and_complete_identity():
    body = anchor()
    for index, name in enumerate(tuple(body)[5:]):
        body[name] = str(index) * 64
    value = v.DocumentExtractionAnchorRecord.model_validate(body)
    assert value.model_dump() == body
    assert v.DocumentExtractionAnchorRecord.model_validate_json(value.model_dump_json()) == value
    assert value.recorded_at.endswith(".123456Z")


@pytest.mark.parametrize(
    "field,value",
    [
        ("run_id", "not-a-run"),
        ("original_id", "00000000-0000-0000-0000-00000000007A"),
        ("requested_by", True),
        ("requested_by", 0),
        ("requested_by", "1"),
        ("recorded_at", "2026-02-30T12:00:00.123456Z"),
        ("recorded_at", "2026-10-21T12:00:00Z"),
        ("schema_version", "document_extraction_run_anchor_v2"),
        ("input_hash", "A" * 64),
        ("metadata_hash", None),
    ],
)
def test_anchor_rejects_ambiguous_ids_boolean_authors_false_dates_or_unsupported_hashes(field, value):
    body = anchor()
    body[field] = value
    with pytest.raises(ValidationError):
        v.DocumentExtractionAnchorRecord.model_validate(body)


def test_anchor_rejects_missing_digest_and_unknown_mutable_source_field():
    body = anchor()
    del body["evidence_hash"]
    with pytest.raises(ValidationError):
        v.DocumentExtractionAnchorRecord.model_validate(body)
    body = {**anchor(), "text": "caller-controlled original replacement"}
    with pytest.raises(ValidationError):
        v.DocumentExtractionAnchorRecord.model_validate(body)


def test_frozen_provider_retains_real_float_and_original_effective_limit_semantics():
    body = dict(
        provider_id=1,
        revision=1,
        name="synthetic",
        kind="chat",
        api_base="https://synthetic.invalid/v1",
        model="synthetic-only",
        timeout_seconds=30,
        max_output_tokens=256,
        validation_report="",
        temperature=0.0,
        allows_patient_data=True,
        effective_output_limit=256,
    )
    value = v.DocumentFrozenProvider.model_validate(body)
    assert type(value.temperature) is float and value.temperature == 0.0
    body["effective_output_limit"] = 257
    with pytest.raises(ValueError):
        v.DocumentFrozenProvider.model_validate(body)


def test_frozen_validation_preserves_original_naive_utc_string_not_relabelled_utc6():
    body = dict(status="pilot", note="synthetic", validated_by=1, validated_at="2026-10-21 12:00:00.123456", feature_revision=1)
    assert v.DocumentFrozenValidation.model_validate(body).validated_at == body["validated_at"]
    for clock in ("2026-10-21T12:00:00.123456", "2026-10-21 12:00:00.123456+00:00", None):
        with pytest.raises(ValueError):
            v.DocumentFrozenValidation.model_validate({**body, "validated_at": clock})


def test_all_view_schemas_generate_without_hospital_settings_database_models_or_transport():
    for name in ("DocumentExtractionBinding", "DocumentExtractionContext", "DocumentFrozenProvider", "DocumentFrozenValidation", "DocumentExtractionAnchorRecord"):
        assert getattr(v, name).model_json_schema()["additionalProperties"] is False
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; import app.ai.document_extraction_view_contract as v; v.DocumentExtractionContext.model_json_schema(); assert not any(n in sys.modules for n in ('app.config','app.database','app.models','sqlalchemy','httpx'))",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
