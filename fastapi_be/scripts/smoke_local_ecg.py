"""Exercise the real optional offline classifier using synthetic calibration signals.

No waveform paths, patient data, downloads, database or external API are used.
The result measures engineering agreement, never diagnostic accuracy.
"""

import argparse
import asyncio
import hashlib
import json
import math
import os
import platform
import struct
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx

from app.ai.ecg_config import ECGSettings, runtime_descriptor
from app.ai.ecg_model import LABELS, LEADS, canonical_json
from app.ai.ecg_server import create_ecg_app, execute_job
from app.ai.schemas import ECGGenerationResult

SYNTHETIC_KEY = "fixed-nonclinical-ecg-smoke-not-a-production-credential"
INSTRUCTIONS = "Only calculate research model scores from this synthetic calibration signal. Do not infer patient status, diagnosis or treatment."
REORDERED_LEADS = ["V3", "I", "aVF", "V6", "II", "aVR", "V2", "III", "V4", "aVL", "V1", "V5"]


def synthetic_source(name, *, reordered=False, missing=False, rate=100):
    """Build original WFDB16 bytes and technical metadata without clinical imports.

    Each original lead has a deterministic integer delta in ADC units. Every
    explicit gain/unit pair maps that delta to exactly delta*0.001 mV, so the
    canonical and reordered/mixed-unit inputs represent the same physical data.
    """
    names = REORDERED_LEADS if reordered else LEADS
    channels, leads, lines = [], [], [f"synthetic 12 {rate} 1000"]
    for column, lead in enumerate(names):
        index = LEADS.index(lead)
        gain, unit = ((1000, "mV"), (1, "uV"), (1000000, "V"))[column % 3] if reordered else (1000, "mV")
        baseline = column * 13 - 71
        values = [((sample * (index + 3) + index * 37) % 1601) - 800 + baseline for sample in range(1000)]
        if missing and column == 0:
            values[333] = -32768
        checksum = sum(values) & 0xFFFF
        if checksum >= 32768:
            checksum -= 65536
        channels.append(values)
        # The hidden-missing rejection case intentionally declares zero here;
        # the actual worker must inspect bytes and reject the sentinel itself.
        leads.append({"name": lead, "gain": str(gain), "baseline": baseline, "unit": unit, "missing_samples": 0})
        lines.append(f"synthetic.dat 16 {gain}({baseline})/{unit} 16 0 {values[0]} {checksum} 0 {lead}")
    header = "\n".join([*lines, "# Nonclinical synthetic calibration pattern; no patient information", ""]).encode()
    raw = struct.pack("<" + "h" * 12000, *(channels[column][sample] for sample in range(1000) for column in range(12)))
    header_hash, signal_hash = hashlib.sha256(header).hexdigest(), hashlib.sha256(raw).hexdigest()
    content_hash = hashlib.sha256(canonical_json({"format": "wfdb16", "header_hash": header_hash, "signal_hash": signal_hash}).encode()).hexdigest()
    asset_id = str(uuid.uuid5(uuid.NAMESPACE_URL, "hoim-nonclinical-ecg-smoke:" + name + ":" + content_hash))
    source = {
        "asset_id": asset_id,
        "header_hash": header_hash,
        "signal_hash": signal_hash,
        "content_hash": content_hash,
        "signal_byte_size": len(raw),
        "source_id": f"ecg:{asset_id}:{content_hash[:12]}",
        "signal_metadata": {
            "format": "wfdb16",
            "sample_rate_hz": str(rate),
            "sample_count": 1000,
            "channels": 12,
            "duration_ms": 1000000 // rate,
            "missing_sample_value": -32768,
            "leads": leads,
        },
    }
    return source, raw


def checked_result(envelope, source, descriptor):
    assert envelope["schema_version"] == "3" and envelope["feature_key"] == "ecg_analysis"
    assert envelope["model_version"] == descriptor["model_version"] and envelope["applicable"] is True
    result = ECGGenerationResult.model_validate({**envelope["result"], "ecg_analysis": envelope["ecg_analysis"]})
    analysis = result.ecg_analysis
    assert analysis.asset_id == source["asset_id"] and analysis.content_hash == source["content_hash"] and analysis.signal_hash == source["signal_hash"]
    assert analysis.time_basis == "relative_samples"
    processing = analysis.processing
    assert processing.instructions_digest == hashlib.sha256(INSTRUCTIONS.encode()).hexdigest()
    assert processing.input_sample_count == processing.processed_original_sample_count == 1000
    assert processing.input_sample_rate_hz == "100" and processing.complete_input is True
    assert processing.input_leads == [lead["name"] for lead in source["signal_metadata"]["leads"]] and processing.used_leads == LEADS
    assert processing.missing_sample_handling == "none_present"
    runtime = processing.local_runtime
    assert runtime is not None and runtime.population_applicability == "not_verified" and runtime.clinical_validation == "not_provided"
    assert runtime.prompt_handling == "signal_only" and runtime.missing_sample_policy == "reject"
    for key in (
        "engine",
        "engine_versions",
        "model_repository",
        "model_revision",
        "model_digest",
        "runtime_digest",
        "preprocessing_digest",
        "required_leads",
        "sample_rate_hz",
        "samples_per_lead",
        "labels",
    ):
        assert getattr(runtime, key) == descriptor[key]
    assert [finding.label for finding in analysis.findings] == LABELS
    for finding in analysis.findings:
        assert finding.location == "recording" and finding.start_sample is None and finding.end_sample_exclusive is None
        assert finding.source_id == source["source_id"] and finding.leads == LEADS and finding.score_kind == "model_score"
        assert finding.score is not None and math.isfinite(finding.score) and 0 <= finding.score <= 1
    return {finding.label: finding.score for finding in analysis.findings}


async def smoke(model_dir):
    config = ECGSettings(model_dir=model_dir, AI_PROVIDER_LOCAL_ECG_API_KEY=SYNTHETIC_KEY)
    descriptor = runtime_descriptor(config)
    child_calls = []

    async def actual_child(job, timeout):
        child_calls.append(job["source"]["asset_id"])
        return await execute_job(job, timeout)

    # The wrapper counts real child executions; no model output is substituted.
    app = create_ecg_app(config, executor=actual_child)
    reports, valid_scores = [], []
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://localhost:8811", timeout=120) as client:
        for name, options, expected_status in (
            ("canonical_calibration", {}, 200),
            ("reordered_mixed_units_same_mv", {"reordered": True}, 200),
            ("actual_missing_sentinel_despite_zero_declared", {"missing": True}, 422),
            ("unsupported_original_500_hz", {"rate": 500}, 422),
        ):
            source, raw = synthetic_source(name, **options)
            task = {
                "schema_version": "3",
                "feature_key": "ecg_analysis",
                "engine": "signal",
                "model": descriptor["model_version"],
                "instructions": INSTRUCTIONS,
                "store": False,
                "input": {"context": {"ecg_source": source}},
            }
            before = len(child_calls)
            response = await client.post(
                "/tasks",
                headers={"Authorization": "Bearer " + SYNTHETIC_KEY},
                files={"task": (None, canonical_json(task)), "waveform": ("signal.dat", raw, "application/octet-stream")},
            )
            assert response.status_code == expected_status, (name, response.status_code, response.text)
            child_invoked = len(child_calls) == before + 1
            assert child_invoked is (name != "unsupported_original_500_hz")
            report = {
                "fixture": name,
                "http_status": response.status_code,
                "check_passed": True,
                "actual_child_invoked": child_invoked,
                "source_header_sha256": source["header_hash"],
                "source_signal_sha256": source["signal_hash"],
                "source_content_sha256": source["content_hash"],
            }
            if response.status_code == 200:
                scores = checked_result(response.json(), source, descriptor)
                valid_scores.append(scores)
                report["model_scores"] = scores
            else:
                report["error"] = response.json()["detail"]
            reports.append(report)
    maximum_error = max(abs(valid_scores[0][label] - valid_scores[1][label]) for label in LABELS)
    assert maximum_error <= 1e-6, maximum_error
    assert "app.database" not in sys.modules
    return {
        "status": "passed",
        "scope": "nonclinical synthetic calibration/lead-order and actual offline inference only; no accuracy or clinical validation",
        "clinical_validation": "not_performed",
        "runtime": descriptor,
        "python_version": platform.python_version(),
        "uid": os.getuid() if hasattr(os, "getuid") else None,
        "database_module_loaded": False,
        "actual_child_calls": len(child_calls),
        "equivalent_calibration_scores_maximum_absolute_error": maximum_error,
        "cases": reports,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", type=Path, default=os.environ.get("ECG_MODEL_DIR"), help="Prepared pinned weights; defaults to ECG_MODEL_DIR")
    args = parser.parse_args()
    if args.model_dir is None:
        parser.error("--model-dir or ECG_MODEL_DIR is required; the smoke never downloads weights")
    print(json.dumps(asyncio.run(smoke(args.model_dir)), ensure_ascii=False, allow_nan=False, indent=2))


if __name__ == "__main__":
    main()
