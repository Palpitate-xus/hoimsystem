"""Native synthetic pixels; no clinical cohort or preprocessing-validity claim.

Contracts collect without NumPy, torch, pydicom or hospital settings imports.
Numerical tests skip when the explicitly optional ML runtime is unavailable.
"""

import hashlib
import os
import struct
import subprocess
import sys
import uuid
from copy import deepcopy
from pathlib import Path

import pytest

from app.ai.imaging_contract import CR_SOP, DX_SOP, ImageSource
from app.ai.imaging_model import canonical_json
from app.ai.imaging_preprocessing import PREPROCESSING, center_crop, decode_and_prepare


def synthetic_source(rows=3, columns=4, *, bits=12, mono="MONOCHROME2", padding=None, values=None):
    """A canonical stored-sample source, never a fabricated patient DICOM."""
    values = list(range(rows * columns)) if values is None else [int(value) for value in values]
    raw = struct.pack(f"<{rows * columns}i", *values)
    valid = [value for value in values if padding is None or not min(padding) <= value <= max(padding)]
    metadata = {
        "format": "dicom_i32le_v1",
        "rows": rows,
        "columns": columns,
        "frames": 1,
        "bits_allocated": 8 if bits == 8 else 16,
        "bits_stored": bits,
        "high_bit": bits - 1,
        "pixel_representation": 0,
        "photometric_interpretation": mono,
        "transfer_syntax_uid": "1.2.840.10008.1.2.1",
        "sop_class_uid": DX_SOP,
        "rescale_slope": 1.0,
        "rescale_intercept": 0.0,
        "rescale_declared": True,
        "rescale_type": "US",
        "window_presets": [{"center": 8.0, "width": 3.0}],
        "voi_lut_function": "LINEAR",
        "padding": None if padding is None else {"value": padding[0], "range_limit": padding[1]},
        "presentation_lut_shape": "INVERSE" if mono == "MONOCHROME1" else "IDENTITY",
        "invert_display": mono == "MONOCHROME1",
        "presentation_intent_type": "FOR PRESENTATION",
        "valid_min_stored": min(valid) if valid else None,
        "valid_max_stored": max(valid) if valid else None,
        "valid_pixel_count": len(valid),
        "modality": "DX",
        "body_part_examined": "CHEST",
        "view_position": "PA",
        "image_laterality": "unknown",
        "burned_in_annotation": "NO",
        "coordinate_space": "source_pixels",
        "orientation": "stored_row_column_unmodified",
        "study_uid_hash": "1" * 64,
        "series_uid_hash": "2" * 64,
        "instance_uid_hash": "3" * 64,
        "pixel_spacing_mm": [0.2, 0.3],
        "imager_pixel_spacing_mm": None,
    }
    original_hash = hashlib.sha256(b"synthetic original identifier, not real DICOM").hexdigest()
    pixel_hash = hashlib.sha256(raw).hexdigest()
    content_hash = hashlib.sha256(canonical_json({"format": metadata["format"], "original_hash": original_hash, "pixel_hash": pixel_hash}).encode()).hexdigest()
    asset = str(uuid.uuid4())
    return raw, {
        "asset_id": asset,
        "original_hash": original_hash,
        "pixel_hash": pixel_hash,
        "content_hash": content_hash,
        "original_byte_size": 128,
        "pixel_byte_size": len(raw),
        "byte_size": 128 + len(raw),
        "source_id": f"image:{asset}:{content_hash[:12]}",
        "imaging_order_id": str(uuid.uuid4()),
        "order_status": 2,
        "image_metadata": metadata,
    }


def rebind_bytes(source, raw):
    source = deepcopy(source)
    source["pixel_hash"] = hashlib.sha256(raw).hexdigest()
    source["content_hash"] = hashlib.sha256(
        canonical_json({"format": source["image_metadata"]["format"], "original_hash": source["original_hash"], "pixel_hash": source["pixel_hash"]}).encode()
    ).hexdigest()
    source["source_id"] = f"image:{source['asset_id']}:{source['content_hash'][:12]}"
    return source


@pytest.fixture
def numerical_runtime():
    numpy = pytest.importorskip("numpy")
    torch = pytest.importorskip("torch")
    torch.set_num_threads(4)
    return numpy, torch


def test_contract_and_preprocessing_import_no_ml_decoder_or_hospital_settings():
    code = """
import sys
from app.ai.imaging_contract import ImageSource
from app.ai.imaging_preprocessing import PREPROCESSING, center_crop
assert all(name not in sys.modules for name in ('torch','numpy','pydicom','app.config','app.database'))
assert PREPROCESSING['profile'] == 'xrv_stored_range_v1'
assert center_crop(3,4) == {'x':1,'y':0,'width':3,'height':3}
"""
    subprocess.run([sys.executable, "-c", code], cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, check=True)


@pytest.mark.parametrize("rows,columns,expected", [(3, 4, (1, 0, 3)), (4, 3, (0, 1, 3)), (3, 8, (3, 0, 3)), (225, 226, (1, 0, 225)), (224, 225, (0, 0, 224)), (5, 7, (1, 0, 5))])
def test_crop_uses_author_integer_center_including_odd_even_tie(rows, columns, expected):
    x, y, side = expected
    assert center_crop(rows, columns) == {"x": x, "y": y, "width": side, "height": side}


@pytest.mark.parametrize("rows,columns", [(0, 3), (3, -1), (True, 4), (3.0, 4), (3, "4")])
def test_crop_requires_explicit_positive_integer_geometry(rows, columns):
    with pytest.raises(ValueError):
        center_crop(rows, columns)


@pytest.mark.parametrize(
    "field,value",
    [
        ("format", "png"),
        ("frames", 2),
        ("frames", True),
        ("bits_allocated", 12),
        ("bits_stored", 7),
        ("high_bit", 12),
        ("pixel_representation", 1),
        ("pixel_representation", False),
        ("transfer_syntax_uid", "1.2.840.10008.1.2.4.90"),
        ("sop_class_uid", CR_SOP),
        ("rescale_slope", 2.0),
        ("rescale_intercept", -1024.0),
        ("rescale_slope", True),
        ("presentation_lut_shape", "INVERSE"),
        ("invert_display", True),
        ("invert_display", 0),
        ("presentation_intent_type", "FOR PROCESSING"),
        ("modality", "CT"),
        ("body_part_examined", "unknown"),
        ("view_position", "LL"),
        ("view_position", "unknown"),
        ("valid_pixel_count", 13),
        ("valid_min_stored", None),
        ("valid_max_stored", 65535),
        ("pixel_spacing_mm", [0.2, float("nan")]),
        ("pixel_spacing_mm", [True, 0.2]),
        ("orientation", "guessed_anatomical"),
        ("coordinate_space", "resized_pixels"),
    ],
)
def test_contract_rejects_unsupported_or_contradictory_metadata(field, value):
    _, source = synthetic_source()
    source["image_metadata"][field] = value
    with pytest.raises(ValueError):
        ImageSource.model_validate(source)


@pytest.mark.parametrize(
    "field,value",
    [
        ("asset_id", "not-a-uuid"),
        ("imaging_order_id", "not-a-uuid"),
        ("order_status", 5),
        ("order_status", True),
        ("pixel_byte_size", 4),
        ("byte_size", 4),
        ("original_hash", "0" * 64),
        ("source_id", "image:other:unbound"),
    ],
)
def test_source_binds_uuid_hash_bytes_and_uncancelled_original_order(field, value):
    _, source = synthetic_source()
    source[field] = value
    with pytest.raises(ValueError):
        ImageSource.model_validate(source)


def test_known_cr_unsigned_scope_ignores_outer_extras_but_never_guesses_views():
    _, source = synthetic_source()
    source.update(PatientName="MUST NOT ENTER MODEL CONTRACT", unreviewed_extra="ignored")
    metadata = source["image_metadata"]
    metadata.update(modality="CR", sop_class_uid=CR_SOP, rescale_declared=False, presentation_intent_type="not_declared", presentation_lut_shape="not_declared", view_position="AP")
    validated = ImageSource.model_validate(source).model_dump()
    assert "PatientName" not in validated and "unreviewed_extra" not in validated
    assert validated["image_metadata"]["view_position"] == "AP"
    source["image_metadata"]["unsupported_lut"] = [0, 1]
    with pytest.raises(ValueError):
        ImageSource.model_validate(source)


@pytest.mark.parametrize("kind", ["same_length_mutation", "truncated", "symlink", "fifo"])
def test_actual_file_is_regular_bounded_and_hash_verified_before_ml_imports(kind, tmp_path):
    raw, source = synthetic_source()
    path = tmp_path / "pixels.i32le"
    if kind == "same_length_mutation":
        path.write_bytes(b"x" * len(raw))
    elif kind == "truncated":
        path.write_bytes(raw[:-1])
    elif kind == "symlink":
        external = tmp_path / "external"
        external.write_bytes(raw)
        path.symlink_to(external)
    else:
        os.mkfifo(path)
    with pytest.raises(ValueError):
        decode_and_prepare(path, source)


@pytest.mark.parametrize(
    "bits,mono,rows,columns",
    [(8, "MONOCHROME2", 3, 4), (8, "MONOCHROME1", 4, 3), (12, "MONOCHROME2", 225, 226), (12, "MONOCHROME1", 226, 225), (16, "MONOCHROME2", 257, 256), (16, "MONOCHROME1", 256, 257)],
)
def test_actual_native_range_polarity_odd_crop_and_tensor_report(bits, mono, rows, columns, tmp_path, numerical_runtime):
    numpy, torch = numerical_runtime
    maxval = (1 << bits) - 1
    values = [(index * 97) % (maxval + 1) for index in range(rows * columns)]
    raw, source = synthetic_source(rows, columns, bits=bits, mono=mono, values=values)
    path = tmp_path / "pixels.i32le"
    path.write_bytes(raw)
    original_source = deepcopy(source)
    prepared, report = decode_and_prepare(path, source)
    assert prepared.dtype == torch.float32 and prepared.device.type == "cpu" and list(prepared.shape) == [1, 1, 224, 224]
    assert report["analysis_region"] == center_crop(rows, columns)
    assert report["normalization_maxval"] == maxval and report["input_pixel_count"] == rows * columns
    assert report["cropped_pixel_count"] == min(rows, columns) ** 2
    assert report["discarded_pixel_count"] == rows * columns - min(rows, columns) ** 2
    assert report["prepared_shape"] == [1, 1, 224, 224] and -1024 <= report["prepared_min"] <= report["prepared_max"] <= 1024
    assert report["single_inversion_applied"] == (mono == "MONOCHROME1") and report["voi_window_applied"] is False
    assert report["padding_pixels_in_input"] == report["padding_pixels_in_crop"] == 0
    assert report["valid_pixels_in_crop"] == report["cropped_pixel_count"]
    assert path.read_bytes() == raw and source == original_source
    assert not numpy.shares_memory(prepared.numpy(), numpy.frombuffer(raw, dtype="<i4"))


def test_native_224_bypasses_resize_and_uses_full_bits_range_not_observed_minmax(tmp_path, numerical_runtime, monkeypatch):
    numpy, torch = numerical_runtime
    values = numpy.full((224, 224), 2000, dtype=numpy.int32)
    values[0, 0], values[-1, -1] = 1000, 3000
    raw, source = synthetic_source(224, 224, values=values.ravel())
    path = tmp_path / "pixels.i32le"
    path.write_bytes(raw)

    def forbidden_resize(*args, **kwargs):
        raise AssertionError("author fix_resolution leaves a native 224 square unchanged")

    monkeypatch.setattr(torch.nn.functional, "interpolate", forbidden_resize)
    prepared, report = decode_and_prepare(path, source)
    assert report["resize_applied"] is False and report["normalization_maxval"] == 4095
    assert -525 < prepared[0, 0, 0, 0].item() < -523
    assert 475 < prepared[0, 0, -1, -1].item() < 477
    assert report["prepared_min"] > -1024 and report["prepared_max"] < 1024


def test_voi_presets_and_original_padding_are_preserved_not_applied_or_imputed(tmp_path, numerical_runtime):
    _, torch = numerical_runtime
    values = [0, 1, 2, 3, 4, 5, 0, 30, 80, 255, 4, 50, 150, 220, 0]
    raw, source = synthetic_source(3, 5, bits=8, values=values, padding=(3, 1))
    path = tmp_path / "pixels.i32le"
    path.write_bytes(raw)
    prepared, report = decode_and_prepare(path, source)
    alternative = deepcopy(source)
    alternative["image_metadata"].update(voi_lut_function="SIGMOID", window_presets=[{"center": -20.0, "width": 0.1}])
    changed_window, changed_report = decode_and_prepare(path, alternative)
    assert torch.equal(prepared, changed_window)
    assert report["padding_pixels_in_input"] == 3 and report["padding_pixels_in_crop"] == 3
    assert report["valid_pixels_in_crop"] == 6 and report["padding_policy"] == "preserved_as_original_background"
    assert report["voi_window_applied"] is changed_report["voi_window_applied"] is False
    assert "未应用原VOI/窗" in "".join(report["preprocessing_notes"])
    # Top-left of this exact author crop is stored value 1 (padding), rather
    # than an imputed black value 0. Bilinear upsampling preserves the corner.
    assert prepared[0, 0, 0, 0].item() > -1024


@pytest.mark.parametrize("side,background", [(256, 0), (256, 4095), (3907, 4095), (4092, 4095)])
def test_author_float32_resize_roundoff_is_preserved_without_clipping(side, background, tmp_path, numerical_runtime):
    numpy, torch = numerical_runtime
    columns = 257 if side == 256 else side
    values = numpy.full((side, columns), background, dtype=numpy.int32)
    values[side // 2, columns // 2] = 4095 - background
    raw = values.astype("<i4").tobytes()
    _, source = synthetic_source()
    source["image_metadata"].update(rows=side, columns=columns, valid_min_stored=0, valid_max_stored=4095, valid_pixel_count=side * columns)
    source.update(pixel_byte_size=len(raw), byte_size=128 + len(raw))
    source = rebind_bytes(source, raw)
    path = tmp_path / "pixels.i32le"
    path.write_bytes(raw)
    prepared, report = decode_and_prepare(path, source)
    # This independent direct torch path includes the actual float32 kernel's
    # rounding. An apparently harmless clamp would change the author's output.
    normalized = (2 * (values.astype(numpy.float32) / 4095) - 1.0) * 1024
    expected = torch.nn.functional.interpolate(torch.from_numpy(normalized[:, :side].copy())[None, None], size=(224, 224), mode="bilinear", align_corners=False, antialias=True)
    assert torch.equal(prepared, expected)
    assert report["prepared_min"] == float(expected.min()) and report["prepared_max"] == float(expected.max())
    assert -1024.01 <= report["prepared_min"] <= report["prepared_max"] <= 1024.01
    assert PREPROCESSING["resize_roundoff_tolerance"] == 0.01


def test_resize_result_outside_fixed_roundoff_tolerance_is_rejected(tmp_path, numerical_runtime, monkeypatch):
    _, torch = numerical_runtime
    raw, source = synthetic_source()
    path = tmp_path / "pixels.i32le"
    path.write_bytes(raw)
    monkeypatch.setattr(torch.nn.functional, "interpolate", lambda *args, **kwargs: torch.full((1, 1, 224, 224), 1024.1, dtype=torch.float32))
    with pytest.raises(ValueError, match="范围"):
        decode_and_prepare(path, source)


@pytest.mark.parametrize("change", ["below_range", "above_range", "valid_count", "valid_min", "valid_max", "all_padding_crop", "constant_valid_crop"])
def test_actual_stored_pixels_and_crop_must_match_metadata_and_have_valid_variation(change, tmp_path, numerical_runtime):
    raw, source = synthetic_source()
    if change in {"below_range", "above_range"}:
        raw = struct.pack("<12i", *([-1 if change == "below_range" else 4096] + list(range(1, 12))))
        source = rebind_bytes(source, raw)
    elif change in {"valid_count", "valid_min", "valid_max"}:
        source["image_metadata"]["padding"] = {"value": 0, "range_limit": 0}
        source["image_metadata"]["valid_pixel_count"] = 11
        source["image_metadata"]["valid_min_stored"] = 1
        if change == "valid_count":
            source["image_metadata"]["valid_pixel_count"] = 10
        elif change == "valid_min":
            source["image_metadata"]["valid_min_stored"] = 2
        else:
            source["image_metadata"]["valid_max_stored"] = 10
    elif change == "all_padding_crop":
        raw, source = synthetic_source(values=[1, 0, 0, 0, 2, 0, 0, 0, 3, 0, 0, 0], padding=(0, 0))
    else:
        raw, source = synthetic_source(values=[43, 42, 0, 42, 44, 42, 42, 0, 45, 42, 0, 42], padding=(0, 0))
    path = tmp_path / "pixels.i32le"
    path.write_bytes(raw)
    with pytest.raises(ValueError):
        decode_and_prepare(path, source)


def test_real_public_weights_can_consume_prepared_synthetic_native_pixels_only_when_requested(tmp_path, numerical_runtime):
    directory = os.environ.get("HOIM_IMAGING_REAL_MODEL")
    if not directory:
        pytest.skip("set HOIM_IMAGING_REAL_MODEL for optional public-model synthetic inference")
    from app.ai.imaging_network import load_network, predict_scores

    values = [(index * 31) % 4096 for index in range(225 * 226)]
    raw, source = synthetic_source(225, 226, values=values)
    path = tmp_path / "pixels.i32le"
    path.write_bytes(raw)
    prepared, report = decode_and_prepare(path, source)
    scores = predict_scores(load_network(directory), prepared)
    assert len(scores) == 18 and all(0 <= score <= 1 for score in scores)
    assert report["analysis_region"] == {"x": 1, "y": 0, "width": 225, "height": 225}
    assert PREPROCESSING["training_distribution_equivalence"] == "not_established"
    assert PREPROCESSING["input_profile"]["clinical_validation"] == "not_provided"
