"""Source-bound local classifier output checks; synthetic scores carry no diagnostic evidence."""

import copy
import hashlib
import json

import pytest

from app.ai.ecg_model import LABELS, LEADS, PREPROCESSING, RELEASE_FILES, ECGModelManifest
from app.ai.gateway import AIExecutionError, validate_generation
from tests.test_ai_ecg_server import native_case

RUNTIME = "c" * 64
MODEL = "ssl-ecg:" + RUNTIME
INSTRUCTIONS = hashlib.sha256(b"frozen original signal instructions for isolated validation").hexdigest()
FIXED_LABELS = ["NORM", "CD", "HYP", "MI", "STTC"]
FIXED_LEADS = ["I", "II", "III", "aVR", "aVL", "aVF", "V1", "V2", "V3", "V4", "V5", "V6"]


def json_hash(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


@pytest.fixture
def case():
    _, source = native_case(reordered=True)
    manifest = ECGModelManifest(files={name: {"size": size, "sha256": digest} for name, (size, digest) in RELEASE_FILES.items()})
    local = {
        "engine": "ssl-ecg-cnn",
        "engine_versions": {"torch": "2.14.1+cpu", "numpy": "2.4.4", "safetensors": "0.8.0"},
        "model_repository": "Tumo505/SSL-ECG-Classification-model-card",
        "model_revision": "6ec2ee1a1badd9508f9c1219fb07de38f3f6936b",
        "model_digest": manifest.digest,
        "runtime_digest": RUNTIME,
        "preprocessing_digest": json_hash(PREPROCESSING),
        "required_leads": list(FIXED_LEADS),
        "sample_rate_hz": 100,
        "samples_per_lead": 1000,
        "labels": list(FIXED_LABELS),
        "missing_sample_policy": "reject",
        "prompt_handling": "signal_only",
        "clinical_validation": "not_provided",
        "population_applicability": "not_verified",
    }
    value = {
        "summary": "合成分数的接口验证，不构成识别效果或临床适用性证据",
        "sections": [],
        "warnings": ["整段分数不是患病概率或诊断结论"],
        "missing_data": ["经核实的采集人群与临床验证"],
        "ecg_analysis": {
            "asset_id": source["asset_id"],
            "content_hash": source["content_hash"],
            "signal_hash": source["signal_hash"],
            "time_basis": "relative_samples",
            "processing": {
                "instructions_digest": INSTRUCTIONS,
                "input_sample_count": 1000,
                "input_sample_rate_hz": "100",
                "input_leads": [lead["name"] for lead in source["signal_metadata"]["leads"]],
                "used_leads": list(FIXED_LEADS),
                "processed_original_sample_count": 1000,
                "complete_input": True,
                "missing_sample_handling": "none_present",
                "preprocessing_notes": ["按实际原导联名重排，未生成导联、重采样、裁剪或补值"],
                "local_runtime": local,
            },
            "findings": [
                {
                    "category": "other",
                    "label": label,
                    "description": "合成整段模型分数，无诊断阈值或临床含义",
                    "leads": list(FIXED_LEADS),
                    "location": "recording",
                    "start_sample": None,
                    "end_sample_exclusive": None,
                    "score": score,
                    "score_kind": "model_score",
                    "source_id": source["source_id"],
                }
                for label, score in zip(FIXED_LABELS, (0.0, 0.2, 0.4, 0.6, 1.0), strict=True)
            ],
        },
    }
    return source, value


def validate(case, *, model=MODEL):
    source, value = case
    return validate_generation(value, [{"source_id": source["source_id"]}], ecg_source=source, instructions_digest=INSTRUCTIONS, model_version=model)


def test_fixed_local_report_preserves_all_five_raw_scores_zero_and_original_lead_order(case):
    assert LABELS == FIXED_LABELS and LEADS == FIXED_LEADS
    source, value = case
    frozen = copy.deepcopy(value)
    result = validate(case)
    analysis = result.ecg_analysis
    assert [finding.label for finding in analysis.findings] == FIXED_LABELS
    assert [finding.score for finding in analysis.findings] == [0.0, 0.2, 0.4, 0.6, 1.0]
    assert analysis.findings[0].score is not None and analysis.findings[0].score == 0
    assert analysis.processing.input_leads == [lead["name"] for lead in source["signal_metadata"]["leads"]]
    assert analysis.processing.input_leads != FIXED_LEADS and analysis.processing.used_leads == FIXED_LEADS
    assert analysis.processing.local_runtime.population_applicability == "not_verified"
    assert all(finding.location == "recording" and finding.start_sample is None and finding.end_sample_exclusive is None for finding in analysis.findings)
    assert value == frozen


@pytest.mark.parametrize(
    "change",
    [
        "runtime_absent",
        "runtime_null",
        "runtime_digest",
        "weight_digest",
        "recipe_digest",
        "revision",
        "repository",
        "engine",
        "package_missing",
        "package_extra",
        "package_version",
        "cuda_dependency",
        "safetensors_version",
        "required_lead_order",
        "runtime_labels",
        "runtime_rate",
        "runtime_samples",
        "missing_policy",
        "prompt_handling",
        "clinical_claim",
        "population_claim",
        "extra_runtime",
        "used_lead_order",
        "used_lead_subset",
        "time_basis",
        "localized_class",
        "recording_positions",
        "class_missing",
        "class_duplicated",
        "class_reordered",
        "score_none",
        "score_missing",
        "score_negative",
        "score_above_one",
        "score_bool",
        "score_nan",
        "score_infinite",
        "score_probability",
        "finding_lead_order",
        "foreign_source",
        "wrong_instructions",
        "partial_input",
    ],
)
def test_changed_local_model_contract_or_five_score_semantics_are_rejected(change, case):
    _, value = case
    analysis = value["ecg_analysis"]
    processing, findings = analysis["processing"], analysis["findings"]
    runtime = processing["local_runtime"]
    if change == "runtime_absent":
        processing.pop("local_runtime")
    elif change == "runtime_null":
        processing["local_runtime"] = None
    elif change in {"runtime_digest", "weight_digest", "recipe_digest"}:
        runtime[{"runtime_digest": "runtime_digest", "weight_digest": "model_digest", "recipe_digest": "preprocessing_digest"}[change]] = "0" * 64
    elif change == "revision":
        runtime["model_revision"] = "0" * 40
    elif change == "repository":
        runtime["model_repository"] = "unreviewed/model"
    elif change == "engine":
        runtime["engine"] = "different-network"
    elif change == "package_missing":
        runtime["engine_versions"].pop("safetensors")
    elif change == "package_extra":
        runtime["engine_versions"]["remote_code"] = "unreviewed"
    elif change == "package_version":
        runtime["engine_versions"]["numpy"] = "2.4.4\nuntrusted-declaration"
    elif change == "cuda_dependency":
        runtime["engine_versions"]["torch"] = "2.14.1+cu128"
    elif change == "safetensors_version":
        runtime["engine_versions"]["safetensors"] = "0.7.0"
    elif change == "required_lead_order":
        runtime["required_leads"].reverse()
    elif change == "runtime_labels":
        runtime["labels"].reverse()
    elif change == "runtime_rate":
        runtime["sample_rate_hz"] = 100.0
    elif change == "runtime_samples":
        runtime["samples_per_lead"] = "1000"
    elif change == "missing_policy":
        runtime["missing_sample_policy"] = "zero_fill"
    elif change == "prompt_handling":
        runtime["prompt_handling"] = "question_conditioned"
    elif change == "clinical_claim":
        runtime["clinical_validation"] = "validated"
    elif change == "population_claim":
        runtime["population_applicability"] = "verified"
    elif change == "extra_runtime":
        runtime["api_key"] = "untrusted secret declaration"
    elif change == "used_lead_order":
        processing["used_leads"].reverse()
    elif change == "used_lead_subset":
        processing["used_leads"].pop()
    elif change == "time_basis":
        analysis["time_basis"] = "absolute_capture_time"
    elif change == "localized_class":
        findings[0].update(location="sample_interval", start_sample=0, end_sample_exclusive=1000)
    elif change == "recording_positions":
        findings[0].update(start_sample=0, end_sample_exclusive=1000)
    elif change == "class_missing":
        findings.pop()
    elif change == "class_duplicated":
        findings[1]["label"] = findings[0]["label"]
    elif change == "class_reordered":
        findings.reverse()
    elif change in {"score_none", "score_negative", "score_above_one", "score_bool", "score_nan", "score_infinite"}:
        findings[0]["score"] = {"score_none": None, "score_negative": -0.01, "score_above_one": 1.01, "score_bool": True, "score_nan": float("nan"), "score_infinite": float("inf")}[change]
    elif change == "score_missing":
        findings[0].pop("score")
    elif change == "score_probability":
        findings[0]["score_kind"] = "disease_probability"
    elif change == "finding_lead_order":
        findings[0]["leads"].reverse()
    elif change == "foreign_source":
        findings[0]["source_id"] = "ecg:other:forged"
    elif change == "wrong_instructions":
        processing["instructions_digest"] = "0" * 64
    else:
        processing["processed_original_sample_count"] = 999
    with pytest.raises(AIExecutionError):
        validate(case)


@pytest.mark.parametrize("model", ["ssl-ecg:" + "0" * 64, "different-local-prefix:" + RUNTIME, "external-model", None])
def test_local_processing_cannot_be_returned_under_a_different_registered_model(model, case):
    with pytest.raises(AIExecutionError, match="运行版本"):
        validate(case, model=model)


@pytest.mark.parametrize("change", ["rate", "sample_count", "missing", "masked", "MLII", "input_lead_order"])
def test_consistent_but_unsupported_original_input_cannot_be_claimed_as_local_scope(change, case):
    source, value = case
    metadata, processing = source["signal_metadata"], value["ecg_analysis"]["processing"]
    if change == "rate":
        metadata["sample_rate_hz"] = processing["input_sample_rate_hz"] = "100.1"
    elif change == "sample_count":
        metadata["sample_count"] = processing["input_sample_count"] = processing["processed_original_sample_count"] = 1001
    elif change == "missing":
        metadata["leads"][0]["missing_samples"] = 1
    elif change == "masked":
        processing["missing_sample_handling"] = "masked"
    elif change == "MLII":
        index = next(index for index, lead in enumerate(metadata["leads"]) if lead["name"] == "II")
        metadata["leads"][index]["name"] = processing["input_leads"][index] = "MLII"
        processing["used_leads"][1] = "MLII"
    else:
        # The model cannot silently replace the original native interleaving order.
        processing["input_leads"].reverse()
    with pytest.raises(AIExecutionError):
        validate(case)


def test_equivalent_original_decimal_frequency_remains_bound_verbatim_without_resampling(case):
    source, value = case
    source["signal_metadata"]["sample_rate_hz"] = value["ecg_analysis"]["processing"]["input_sample_rate_hz"] = "1.00E+2"
    result = validate(case)
    assert result.ecg_analysis.processing.input_sample_rate_hz == "1.00E+2"


def test_external_v3_adapter_without_local_processing_keeps_optional_score_and_valid_sample_localization(case):
    _, value = case
    analysis = value["ecg_analysis"]
    analysis["processing"].pop("local_runtime")
    analysis["findings"] = analysis["findings"][:2]
    analysis["findings"][0].update(label="external test zero", location="sample_interval", start_sample=100, end_sample_exclusive=900)
    analysis["findings"][1].update(label="external test no score", score=None)
    result = validate(case, model="independent-specialist-version")
    assert result.ecg_analysis.processing.local_runtime is None
    assert result.ecg_analysis.findings[0].score == 0.0 and result.ecg_analysis.findings[1].score is None
    assert result.ecg_analysis.findings[0].start_sample == 100 and result.ecg_analysis.findings[0].end_sample_exclusive == 900
