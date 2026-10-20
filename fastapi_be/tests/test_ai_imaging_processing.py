"""Strict source-bound research output checks; synthetic scores are not clinical evidence."""

import copy
import hashlib

import pytest

from app.ai.gateway import AIExecutionError, validate_generation
from app.ai.imaging_model import LABELS, RELEASE_FILES, ImagingModelManifest, canonical_json
from app.ai.imaging_preprocessing import PREPROCESSING
from tests.test_ai_imaging_server import native_case

RUNTIME = "c" * 64
MODEL = "xrv:" + RUNTIME
INSTRUCTIONS = hashlib.sha256(b"frozen complete original image instructions for isolated validation").hexdigest()
FIXED_LABELS = [
    "Atelectasis",
    "Consolidation",
    "Infiltration",
    "Pneumothorax",
    "Edema",
    "Emphysema",
    "Fibrosis",
    "Effusion",
    "Pneumonia",
    "Pleural_Thickening",
    "Cardiomegaly",
    "Nodule",
    "Mass",
    "Hernia",
    "Lung Lesion",
    "Fracture",
    "Lung Opacity",
    "Enlarged Cardiomediastinum",
]


def make_case(*, rows=224, columns=225):
    _, source = native_case(rows=rows, columns=columns)
    side = min(rows, columns)
    # Independent explicit author formula; includes the odd-dimension edge.
    region = {"x": columns // 2 - side // 2, "y": rows // 2 - side // 2, "width": side, "height": side}
    manifest = ImagingModelManifest(files={name: {"size": size, "sha256": value} for name, (size, value) in RELEASE_FILES.items()})
    local = {
        "engine": "torchxrayvision-densenet121",
        "engine_versions": {"torch": "2.14.1+cpu", "numpy": "2.4.4", "safetensors": "0.8.0"},
        "model_repository": "torchxrayvision/densenet121-res224-all",
        "model_revision": "588eadcc6a744da71f8dce768bc974ec629443f5",
        "model_digest": manifest.digest,
        "runtime_digest": RUNTIME,
        "preprocessing_digest": hashlib.sha256(canonical_json(PREPROCESSING).encode()).hexdigest(),
        "profile": "xrv_stored_range_v1",
        "preprocessing": copy.deepcopy(PREPROCESSING),
        "labels": list(FIXED_LABELS),
        "prompt_handling": "pixels_only",
        "clinical_validation": "not_provided",
        "population_applicability": "not_verified",
    }
    native = {
        "normalization_maxval": 4095,
        "input_pixel_count": rows * columns,
        "cropped_pixel_count": side * side,
        "discarded_pixel_count": rows * columns - side * side,
        "padding_pixels_in_input": 0,
        "padding_pixels_in_crop": 0,
        "valid_pixels_in_crop": side * side,
        "prepared_shape": [1, 1, 224, 224],
        "prepared_min": -1024.0,
        "prepared_max": 1024.0,
    }
    value = {
        "summary": "合成分数接口测试，不是实际模型识别效果或临床证据",
        "sections": [],
        "warnings": ["单帧、图像级研究分数，不代表完整检查"],
        "missing_data": ["采集时年龄、人群适用性及独立临床验证"],
        "image_analysis": {
            **{key: source[key] for key in ("asset_id", "content_hash", "original_hash", "pixel_hash")},
            "coordinate_space": "source_pixels",
            "processing": {
                "instructions_digest": INSTRUCTIONS,
                "input_rows": rows,
                "input_columns": columns,
                "input_frames": 1,
                "processed_frames": [0],
                "analysis_region": region,
                "preprocessing_notes": ["固定stored-range研究预处理，实际作者中心裁剪；无阈值、定位或训练等价声明"],
                "local_runtime": local,
                "local_preprocessing": native,
            },
            "findings": [
                {
                    "label": label,
                    "description": "合成原始sigmoid分数，没有疾病阈值或临床含义",
                    "location": "image",
                    "region": None,
                    "score": index / 17,
                    "score_kind": "model_score",
                    "source_id": source["source_id"],
                }
                for index, label in enumerate(FIXED_LABELS)
            ],
        },
    }
    return source, value


@pytest.fixture
def case():
    return make_case()


def validate(case, *, model=MODEL):
    source, value = case
    return validate_generation(value, [{"source_id": source["source_id"]}], image_source=source, instructions_digest=INSTRUCTIONS, model_version=model)


def test_fixed_report_preserves_all_18_independent_raw_scores_and_actual_crop(case):
    assert LABELS == FIXED_LABELS
    frozen = copy.deepcopy(case)
    result = validate(case)
    analysis = result.image_analysis
    assert [finding.label for finding in analysis.findings] == FIXED_LABELS
    assert [finding.score for finding in analysis.findings] == [index / 17 for index in range(18)]
    assert analysis.findings[0].score == 0.0 and analysis.findings[-1].score == 1.0
    assert all(finding.location == "image" and finding.region is None for finding in analysis.findings)
    assert analysis.processing.analysis_region.model_dump() == {"x": 0, "y": 0, "width": 224, "height": 224}
    assert analysis.processing.local_preprocessing.input_pixel_count == 224 * 225
    assert analysis.processing.local_preprocessing.discarded_pixel_count == 224
    assert analysis.processing.local_runtime.prompt_handling == "pixels_only"
    assert analysis.processing.local_runtime.population_applicability == "not_verified"
    assert analysis.processing.local_runtime.clinical_validation == "not_provided"
    assert case == frozen


@pytest.mark.parametrize("rows,columns,expected", [(225, 226, {"x": 1, "y": 0, "width": 225, "height": 225}), (226, 225, {"x": 0, "y": 1, "width": 225, "height": 225})])
def test_odd_dimension_author_crop_is_not_naive_half_difference(rows, columns, expected):
    source, value = make_case(rows=rows, columns=columns)
    assert validate((source, value)).image_analysis.processing.analysis_region.model_dump() == expected
    value["image_analysis"]["processing"]["analysis_region"] = {"x": (columns - 225) // 2, "y": (rows - 225) // 2, "width": 225, "height": 225}
    with pytest.raises(AIExecutionError) as invalid:
        validate((source, value))
    assert invalid.value.code == "IMAGE_LOCAL_CROP_MISMATCH"


@pytest.mark.parametrize(
    "change",
    [
        "runtime_absent",
        "runtime_null",
        "native_absent",
        "runtime_digest",
        "weight_digest",
        "recipe_digest",
        "recipe_contents",
        "revision",
        "repository",
        "engine",
        "package_missing",
        "package_extra",
        "package_version",
        "cuda_dependency",
        "safetensors_version",
        "runtime_labels",
        "profile",
        "prompt_handling",
        "clinical_claim",
        "population_claim",
        "extra_runtime",
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
        "fake_box",
        "foreign_source",
        "wrong_asset",
        "wrong_pixel_hash",
        "wrong_original_hash",
        "wrong_combined_hash",
        "instructions",
        "coordinates",
        "normalization",
        "input_count",
        "crop_count",
        "discard_count",
        "padding_count",
        "crop_padding_count",
        "crop_valid_count",
        "prepared_shape",
        "shape_bool",
        "shape_float",
        "range_reversed",
        "range_low",
        "range_high",
        "range_nan",
        "frame_bool",
        "frame_float",
        "frame_outside",
    ],
)
def test_contradictory_local_reports_cannot_be_used_as_research_candidates(change, case):
    source, value = case
    analysis = value["image_analysis"]
    processing = analysis["processing"]
    runtime, native, finding = processing["local_runtime"], processing["local_preprocessing"], analysis["findings"][0]
    if change == "runtime_absent":
        processing.pop("local_runtime")
    elif change == "runtime_null":
        processing["local_runtime"] = None
    elif change == "native_absent":
        processing.pop("local_preprocessing")
    elif change in {"runtime_digest", "weight_digest", "recipe_digest"}:
        runtime[{"runtime_digest": "runtime_digest", "weight_digest": "model_digest", "recipe_digest": "preprocessing_digest"}[change]] = "0" * 64
    elif change == "recipe_contents":
        runtime["preprocessing"]["unapproved_policy"] = True
        runtime["preprocessing_digest"] = hashlib.sha256(canonical_json(runtime["preprocessing"]).encode()).hexdigest()
    elif change in {"revision", "repository", "engine", "profile", "prompt_handling", "clinical_claim", "population_claim"}:
        key = {
            "revision": "model_revision",
            "repository": "model_repository",
            "engine": "engine",
            "profile": "profile",
            "prompt_handling": "prompt_handling",
            "clinical_claim": "clinical_validation",
            "population_claim": "population_applicability",
        }[change]
        runtime[key] = "unsupported_or_unverified_claim"
    elif change == "package_missing":
        runtime["engine_versions"].pop("numpy")
    elif change == "package_extra":
        runtime["engine_versions"]["unapproved_package"] = "1.0"
    elif change in {"package_version", "cuda_dependency", "safetensors_version"}:
        key = "numpy" if change == "package_version" else "torch" if change == "cuda_dependency" else "safetensors"
        runtime["engine_versions"][key] = "2.5.4" if key == "numpy" else "2.14.1+cu128" if key == "torch" else "0.7.0"
    elif change == "runtime_labels":
        runtime["labels"].reverse()
    elif change == "extra_runtime":
        runtime["verified_patient_age"] = 42
    elif change == "class_missing":
        analysis["findings"].pop()
    elif change == "class_duplicated":
        analysis["findings"][-1]["label"] = analysis["findings"][0]["label"]
    elif change == "class_reordered":
        analysis["findings"].reverse()
    elif change == "score_missing":
        finding.pop("score")
    elif change.startswith("score_"):
        key = "score_kind" if change == "score_probability" else "score"
        finding[key] = {
            "score_none": None,
            "score_negative": -0.01,
            "score_above_one": 1.01,
            "score_bool": True,
            "score_nan": float("nan"),
            "score_infinite": float("inf"),
            "score_probability": "disease_probability",
        }[change]
    elif change == "fake_box":
        finding.update(location="bounding_box", region={"x": 0, "y": 0, "width": 1, "height": 1})
    elif change == "foreign_source":
        finding["source_id"] = "other-image-source"
    elif change.startswith("wrong_"):
        key = {"wrong_asset": "asset_id", "wrong_pixel_hash": "pixel_hash", "wrong_original_hash": "original_hash", "wrong_combined_hash": "content_hash"}[change]
        analysis[key] = "00000000-0000-4000-8000-000000000000" if key == "asset_id" else "0" * 64
    elif change == "instructions":
        processing["instructions_digest"] = "0" * 64
    elif change == "coordinates":
        analysis["coordinate_space"] = "resized_model_tensor"
    elif change in {"normalization", "input_count", "crop_count", "discard_count", "padding_count", "crop_padding_count", "crop_valid_count"}:
        key = {
            "normalization": "normalization_maxval",
            "input_count": "input_pixel_count",
            "crop_count": "cropped_pixel_count",
            "discard_count": "discarded_pixel_count",
            "padding_count": "padding_pixels_in_input",
            "crop_padding_count": "padding_pixels_in_crop",
            "crop_valid_count": "valid_pixels_in_crop",
        }[change]
        native[key] += 1
    elif change == "prepared_shape":
        native["prepared_shape"] = [1, 1, 225, 224]
    elif change in {"shape_bool", "shape_float"}:
        native["prepared_shape"][0] = True if change == "shape_bool" else 1.0
    elif change == "range_reversed":
        native["prepared_min"], native["prepared_max"] = 1024.0, -1024.0
    elif change in {"range_low", "range_high", "range_nan"}:
        native["prepared_min" if change != "range_high" else "prepared_max"] = -1024.02 if change == "range_low" else 1024.02 if change == "range_high" else float("nan")
    elif change in {"frame_bool", "frame_float", "frame_outside"}:
        processing["processed_frames"] = [{"frame_bool": False, "frame_float": 0.0, "frame_outside": 1}[change]]
    with pytest.raises(AIExecutionError):
        validate((source, value))


@pytest.mark.parametrize("change", ["CT", "lateral", "unknown_body", "signed", "low_bits", "high_bit", "slope", "intercept", "canceled", "float_rows", "float_frames", "false_count"])
def test_fixed_model_namespace_requires_supported_real_native_source_metadata(change, case):
    source, value = case
    metadata = source["image_metadata"]
    if change == "CT":
        metadata["modality"], metadata["sop_class_uid"] = "CT", "1.2.840.10008.5.1.4.1.1.2"
    elif change == "lateral":
        metadata["view_position"] = "LL"
    elif change == "unknown_body":
        metadata["body_part_examined"] = "unknown"
    elif change == "signed":
        metadata["pixel_representation"] = 1
    elif change == "low_bits":
        metadata["bits_stored"], metadata["high_bit"] = 7, 6
    elif change == "high_bit":
        metadata["high_bit"] = 12
    elif change in {"slope", "intercept"}:
        metadata["rescale_" + change] = 2.0
    elif change == "canceled":
        source["order_status"] = 5
    elif change == "float_rows":
        metadata["rows"] = float(metadata["rows"])
    elif change == "float_frames":
        metadata["frames"] = 1.0
    else:
        metadata["valid_pixel_count"] -= 1
    with pytest.raises(AIExecutionError):
        validate((source, value))


@pytest.mark.parametrize("roundoff", [0.0005, 0.0015, 0.01])
def test_float32_resize_roundoff_is_reported_without_clipping_to_exact_endpoints(roundoff, case):
    native = case[1]["image_analysis"]["processing"]["local_preprocessing"]
    native["prepared_min"], native["prepared_max"] = -1024.0 - roundoff, 1024.0 + roundoff
    result = validate(case)
    assert result.image_analysis.processing.local_preprocessing.prepared_min == -1024.0 - roundoff
    assert result.image_analysis.processing.local_preprocessing.prepared_max == 1024.0 + roundoff


def test_unrelated_model_cannot_attach_a_local_runtime_identity(case):
    with pytest.raises(AIExecutionError) as invalid:
        validate(case, model="independent-specialist-version")
    assert invalid.value.code == "IMAGE_RUNTIME_MISMATCH"


def test_independent_specialist_keeps_generic_source_bound_v4_contract(case):
    processing = case[1]["image_analysis"]["processing"]
    processing.pop("local_runtime")
    processing.pop("local_preprocessing")
    case[1]["image_analysis"]["findings"] = case[1]["image_analysis"]["findings"][:1]
    result = validate(case, model="independent-specialist-version")
    assert len(result.image_analysis.findings) == 1
    assert result.image_analysis.processing.local_runtime is None
