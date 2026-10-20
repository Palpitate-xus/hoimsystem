"""Native DICOM semantics verified against pydicom's independent pixel decoder."""

import io
import struct

import pydicom
import pytest
from fastapi import HTTPException
from pydicom.dataset import Dataset
from pydicom.sequence import Sequence
from pydicom.uid import CTImageStorage, ImplicitVRLittleEndian

from app.ai.image_files import parse_dicom
from app.config import settings
from tests.test_ai_image_sources import dicom_bytes


def save(tmp_path, change=None, *, data=None):
    source = pydicom.dcmread(io.BytesIO(data or dicom_bytes()[0]))
    if change:
        change(source)
    for field in ("PixelPaddingValue", "PixelPaddingRangeLimit"):
        if field in source:
            source[field].VR = "SS" if source.PixelRepresentation else "US"
    path = tmp_path / "synthetic.dcm"
    source.save_as(path, enforce_file_format=True)
    return path, source


def test_signed_stored_sample_decoder_matches_pydicom_and_excludes_unused_overlay_bits(tmp_path):
    path, ds = save(tmp_path)
    metadata, raw = parse_dicom(path)
    assert list(struct.unpack("<6i", raw)) == ds.pixel_array.ravel().tolist() == [-1024, -1, 0, 1, 1023, 2047]
    assert metadata["valid_min_stored"] == -1024 and metadata["valid_max_stored"] == 2047
    assert metadata["coordinate_space"] == "source_pixels" and metadata["orientation"] == "stored_row_column_unmodified"
    assert "PRIVATE" not in str(metadata) and metadata["burned_in_annotation"] == "NO"
    assert len(metadata["instance_uid_hash"]) == 64
    assert not any(key in metadata for key in ("PatientName", "AccessionNumber", "StudyDate", "filename"))


@pytest.mark.parametrize("signed", [0, 1])
@pytest.mark.parametrize("allocated,stored", [(8, 7), (16, 12), (16, 16)])
@pytest.mark.parametrize("implicit", [False, True])
def test_native_integer_variants_match_independent_decoder(tmp_path, signed, allocated, stored, implicit):
    expected = [0, 1, (1 << (stored - 1)) - 1, -(1 << (stored - 1)) if signed else (1 << stored) - 1, -1 if signed else 2, 0]

    def change(ds):
        ds.BitsAllocated, ds.BitsStored, ds.HighBit, ds.PixelRepresentation = allocated, stored, stored - 1, signed
        ds.PixelData = struct.pack("<6" + ("B" if allocated == 8 else "H"), *(value & ((1 << stored) - 1) for value in expected))
        if implicit:
            ds.file_meta.TransferSyntaxUID = ImplicitVRLittleEndian

    path, ds = save(tmp_path, change)
    metadata, raw = parse_dicom(path)
    assert struct.unpack("<6i", raw) == tuple(expected)
    assert list(expected) == ds.pixel_array.ravel().tolist()
    assert metadata["bits_stored"] == stored


def test_odd_8bit_data_only_removes_dicom_zero_pad_byte(tmp_path):
    def change(ds):
        ds.Rows, ds.Columns, ds.BitsAllocated, ds.BitsStored, ds.HighBit, ds.PixelRepresentation = 1, 3, 8, 8, 7, 0
        ds.PixelData = bytes([1, 2, 255])

    path, ds = save(tmp_path, change)
    metadata, raw = parse_dicom(path)
    assert len(raw) == 12 and struct.unpack("<3i", raw) == (1, 2, 255)
    assert metadata["valid_pixel_count"] == 3


def test_padding_range_and_presentation_invert_resolve_once_without_touching_stored_pixels(tmp_path):
    def change(ds):
        ds.PhotometricInterpretation = "MONOCHROME1"
        ds.PresentationLUTShape = "INVERSE"
        ds.PixelPaddingValue, ds.PixelPaddingRangeLimit = -1024, -1
        ds.PixelSpacing = [0.2, 0.3]
        ds.ImagerPixelSpacing = [0.4, 0.5]
        ds.WindowCenter, ds.WindowWidth = [0, 1024], [1, 2048]

    path, ds = save(tmp_path, change)
    metadata, raw = parse_dicom(path)
    assert metadata["invert_display"] is True
    assert metadata["padding"] == {"value": -1024, "range_limit": -1}
    assert metadata["valid_pixel_count"] == 4 and metadata["valid_min_stored"] == 0
    assert metadata["pixel_spacing_mm"] == [0.2, 0.3] and metadata["imager_pixel_spacing_mm"] == [0.4, 0.5]
    assert len(metadata["window_presets"]) == 2 and struct.unpack("<6i", raw)[0] == -1024


def test_ct_negative_intercept_kept_as_technical_mapping_not_applied_to_canonical_stored_values(tmp_path):
    def change(ds):
        ds.SOPClassUID = ds.file_meta.MediaStorageSOPClassUID = CTImageStorage
        ds.Modality = "CT"
        ds.RescaleSlope, ds.RescaleIntercept, ds.RescaleType = "2", "-1024", "HU"

    path, _ = save(tmp_path, change)
    metadata, raw = parse_dicom(path)
    assert metadata["rescale_intercept"] == -1024 and metadata["rescale_type"] == "HU"
    assert struct.unpack("<6i", raw)[2] == 0


@pytest.mark.parametrize(
    "changes",
    [
        {"NumberOfFrames": 2},
        {"SamplesPerPixel": 3},
        {"BitsAllocated": 32},
        {"HighBit": 12},
        {"BitsStored": 17},
        {"PixelRepresentation": 2},
        {"PhotometricInterpretation": "RGB"},
        {"WindowWidth": 0},
        {"VOILUTFunction": "CUSTOM"},
        {"PresentationLUTShape": "INVERSE"},
        {"PresentationIntentType": "FOR PROCESSING"},
        {"Modality": "CT"},
        {"RescaleSlope": 2},
        {"PixelPaddingValue": -3000},
        {"PixelPaddingRangeLimit": 0},
        {"RescaleSlope": "NaN"},
    ],
)
def test_unsupported_or_contradictory_native_metadata_rejected(tmp_path, changes):
    path, _ = save(tmp_path, lambda ds: [setattr(ds, key, value) for key, value in changes.items()])
    with pytest.raises(HTTPException) as error:
        parse_dicom(path)
    assert error.value.status_code == 422


@pytest.mark.parametrize("name", ["ModalityLUTSequence", "VOILUTSequence", "PresentationLUTSequence", "RealWorldValueMappingSequence"])
def test_unimplemented_lut_is_never_ignored_even_with_an_existing_window(tmp_path, name):
    item = Dataset()
    item.add_new((0x0011, 0x1010), "LO", "SYNTHETIC")
    path, _ = save(tmp_path, lambda ds: setattr(ds, name, Sequence([item])))
    with pytest.raises(HTTPException) as error:
        parse_dicom(path)
    assert error.value.status_code == 422


def test_truncation_duplicate_elements_and_pixel_limit_are_bounded(tmp_path, monkeypatch):
    path, _ = save(tmp_path)
    original = path.read_bytes()
    for raw in (original[:-1], original + struct.pack("<HH2sH", 0x0028, 0x0010, b"US", 2) + b"\x02\x00", b"not a DICOM"):
        path.write_bytes(raw)
        with pytest.raises(HTTPException):
            parse_dicom(path)
    path.write_bytes(original)
    monkeypatch.setattr(settings, "AI_IMAGE_MAX_PIXELS", 5)
    with pytest.raises(HTTPException) as error:
        parse_dicom(path)
    assert error.value.status_code == 413
