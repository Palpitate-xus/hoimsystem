"""Bounded single-frame native DICOM intake; private originals and tag-free stored samples.

No compression plugins, network resources, volume selection, hidden frame selection,
windowing, interpolation or anatomical orientation inference occurs during intake.
"""

import hashlib
import math
import os
import shutil
import stat
import struct
import sys
import tempfile
import uuid
from array import array
from pathlib import Path

import pydicom
from fastapi import HTTPException
from pydicom.multival import MultiValue
from pydicom.uid import UID

from app.ai.ecg_files import canonical_json
from app.config import settings

FORMAT = "dicom_i32le_v1"
EXPLICIT_LE = "1.2.840.10008.1.2.1"
IMPLICIT_LE = "1.2.840.10008.1.2"
# Finite, native grayscale images only. Enhanced/multi-frame/secondary capture/WSI
# require their own explicit interpretation and are not silently reduced to one image.
SOP_CLASSES = frozenset(
    str(getattr(pydicom.uid, name))
    for name in ("ComputedRadiographyImageStorage", "DigitalXRayImageStorageForPresentation", "CTImageStorage", "MRImageStorage", "DigitalMammographyXRayImageStorageForPresentation")
)
LONG_VR = {b"OB", b"OD", b"OF", b"OL", b"OV", b"OW", b"SQ", b"UC", b"UN", b"UR", b"UT"}
UNSUPPORTED_TAGS = {0x00283000, 0x00283010, 0x20500010, 0x00409096, 0x00281101, 0x00281102, 0x00281103, 0x7FE00008, 0x7FE00009}
TECHNICAL_TAGS = (
    "SOPClassUID",
    "SOPInstanceUID",
    "StudyInstanceUID",
    "SeriesInstanceUID",
    "Modality",
    "Rows",
    "Columns",
    "NumberOfFrames",
    "SamplesPerPixel",
    "PhotometricInterpretation",
    "BitsAllocated",
    "BitsStored",
    "HighBit",
    "PixelRepresentation",
    "PixelData",
    "RescaleSlope",
    "RescaleIntercept",
    "RescaleType",
    "WindowCenter",
    "WindowWidth",
    "VOILUTFunction",
    "PixelPaddingValue",
    "PixelPaddingRangeLimit",
    "PixelSpacing",
    "ImagerPixelSpacing",
    "BodyPartExamined",
    "ViewPosition",
    "ImageLaterality",
    "BurnedInAnnotation",
    "PresentationLUTShape",
    "PresentationIntentType",
)


def image_root():
    from app.routers.upload import UPLOAD_DIR

    root = Path(settings.AI_IMAGE_STORAGE_DIR).expanduser().resolve()
    public = Path(UPLOAD_DIR).resolve()
    if root == public or public in root.parents:
        raise HTTPException(503, "影像私有存储须位于通用上传目录之外")
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(root, 0o700)
    return root


def image_directory(asset_id):
    try:
        if str(uuid.UUID(asset_id)) != asset_id:
            raise ValueError()
    except (ValueError, TypeError, AttributeError) as exc:
        raise HTTPException(422, "影像原记录标识无效") from exc
    return image_root() / asset_id


def _scan_native(path):
    """Bound parser work before pydicom: finite top-level elements, no nested walking.

    Unknown defined-length values (including private tags) are seeked over without
    parsing. Undefined-length sequences/items are outside this intake profile.
    Duplicate tags, truncation, trailing data and unsupported LUTs fail closed.
    """
    total = path.stat().st_size
    with path.open("rb") as source:
        if source.read(132)[128:] != b"DICM":
            raise ValueError("Part 10 required")
        syntax, seen, pixel_offset = None, set(), None
        for _ in range(25000):
            offset = source.tell()
            if offset == total:
                if syntax is None or pixel_offset is None:
                    raise ValueError("missing syntax or pixels")
                return syntax
            prefix = source.read(8)
            if len(prefix) != 8:
                raise ValueError("truncated element")
            group, element = struct.unpack("<HH", prefix[:4])
            tag = group << 16 | element
            if tag in seen or group == 0xFFFE:
                raise ValueError("duplicate tag or item outside sequence")
            seen.add(tag)
            explicit = group == 2 or syntax == EXPLICIT_LE
            if group != 2 and syntax is None:
                raise ValueError("transfer syntax not declared before data")
            if explicit:
                vr = prefix[4:6]
                if not (len(vr) == 2 and vr.isalpha() and vr.isupper()):
                    raise ValueError("invalid VR")
                if vr in LONG_VR:
                    raw_length = source.read(4)
                    if len(raw_length) != 4 or prefix[6:8] != b"\0\0":
                        raise ValueError("invalid long VR")
                    length = struct.unpack("<I", raw_length)[0]
                else:
                    length = struct.unpack("<H", prefix[6:8])[0]
            else:
                length = struct.unpack("<I", prefix[4:8])[0]
            if length == 0xFFFFFFFF or length % 2 or source.tell() + length > total or tag in UNSUPPORTED_TAGS:
                raise ValueError("undefined/truncated element or unsupported LUT")
            if tag == 0x00020010:
                if length > 64:
                    raise ValueError("transfer syntax length")
                syntax = source.read(length).rstrip(b"\0 ").decode("ascii")
                if syntax not in {EXPLICIT_LE, IMPLICIT_LE}:
                    raise ValueError("native little endian only")
            else:
                if tag == 0x7FE00010:
                    pixel_offset = source.tell()
                source.seek(length, 1)
        raise ValueError("too many elements")


def _finite(value, *, positive=False):
    value = float(value)
    if not math.isfinite(value) or abs(value) > 1e12 or (positive and value <= 0):
        raise ValueError("finite technical number")
    return value


def _values(value):
    return list(value) if isinstance(value, (list, tuple, MultiValue)) else [value]


def _enum(ds, field, allowed):
    value = str(getattr(ds, field, "")).strip()
    return value if value in allowed else "unknown"


def _uid_hash(ds, field):
    value = str(getattr(ds, field, ""))
    if not value or not UID(value).is_valid:
        raise ValueError("explicit valid image UIDs required")
    return hashlib.sha256(value.encode("ascii")).hexdigest()


def parse_dicom(path):
    """Extract logical stored samples, clearing unused high/overlay bits, with no PHI tags."""
    try:
        syntax = _scan_native(path)
        ds = pydicom.dcmread(path, specific_tags=TECHNICAL_TAGS, force=False)
        if (
            str(ds.file_meta.TransferSyntaxUID) != syntax
            or str(ds.SOPClassUID) not in SOP_CLASSES
            or str(ds.file_meta.MediaStorageSOPClassUID) != str(ds.SOPClassUID)
            or str(ds.file_meta.MediaStorageSOPInstanceUID) != str(ds.SOPInstanceUID)
        ):
            raise ValueError("supported SOP and file-meta identity")
        rows, columns = int(ds.Rows), int(ds.Columns)
        if not 1 <= rows <= 16384 or not 1 <= columns <= 16384 or rows * columns > settings.AI_IMAGE_MAX_PIXELS:
            raise HTTPException(413, "原影像像素数超出当前限制")
        if int(getattr(ds, "NumberOfFrames", 1)) != 1 or int(ds.SamplesPerPixel) != 1 or str(ds.PhotometricInterpretation) not in {"MONOCHROME1", "MONOCHROME2"}:
            raise ValueError("single frame monochrome only")
        allocated, stored, high, signed = int(ds.BitsAllocated), int(ds.BitsStored), int(ds.HighBit), int(ds.PixelRepresentation)
        if allocated not in {8, 16} or not 1 <= stored <= allocated or high != stored - 1 or signed not in {0, 1}:
            raise ValueError("unsupported pixel packing")
        raw = ds.PixelData
        expected = rows * columns * allocated // 8
        if len(raw) != expected + expected % 2 or (expected % 2 and raw[-1] != 0):
            raise ValueError("pixel byte count or pad byte")
        packed = array("B" if allocated == 8 else "H")
        packed.frombytes(raw[:expected])
        if allocated == 16 and sys.byteorder != "little":
            packed.byteswap()
        mask, sign = (1 << stored) - 1, 1 << (stored - 1)
        pixels = array("i", (((value & mask) ^ sign) - sign if signed else value & mask for value in packed))
        if pixels.itemsize != 4:
            raise RuntimeError("32-bit canonical sample array required")
        lower, upper = (-(1 << (stored - 1)), (1 << (stored - 1)) - 1) if signed else (0, mask)
        padding = None
        if hasattr(ds, "PixelPaddingRangeLimit") and not hasattr(ds, "PixelPaddingValue"):
            raise ValueError("padding range without value")
        if hasattr(ds, "PixelPaddingValue"):
            pv = int(ds.PixelPaddingValue)
            limit = int(getattr(ds, "PixelPaddingRangeLimit", pv))
            if not lower <= pv <= upper or not lower <= limit <= upper:
                raise ValueError("padding stored range")
            padding = {"value": pv, "range_limit": limit}
        valid = (value for value in pixels if padding is None or not min(padding.values()) <= value <= max(padding.values()))
        minimum, maximum, valid_count = None, None, 0
        for value in valid:
            minimum = value if minimum is None else min(minimum, value)
            maximum = value if maximum is None else max(maximum, value)
            valid_count += 1
        if hasattr(ds, "RescaleSlope") != hasattr(ds, "RescaleIntercept"):
            raise ValueError("paired rescale required")
        slope, intercept = _finite(getattr(ds, "RescaleSlope", 1)), _finite(getattr(ds, "RescaleIntercept", 0))
        if slope == 0 or abs(slope) < 1e-12:
            raise ValueError("nonzero rescale")
        modality = str(getattr(ds, "Modality", ""))
        expected_modality = {
            str(getattr(pydicom.uid, name)): code
            for name, code in (
                ("ComputedRadiographyImageStorage", "CR"),
                ("DigitalXRayImageStorageForPresentation", "DX"),
                ("CTImageStorage", "CT"),
                ("MRImageStorage", "MR"),
                ("DigitalMammographyXRayImageStorageForPresentation", "MG"),
            )
        }
        if modality != expected_modality[str(ds.SOPClassUID)] or (modality in {"DX", "MG"} and (slope != 1 or intercept != 0)):
            raise ValueError("SOP modality consistency and DX identity rescale")
        function = str(getattr(ds, "VOILUTFunction", "LINEAR"))
        if function not in {"LINEAR", "LINEAR_EXACT", "SIGMOID"} or hasattr(ds, "WindowCenter") != hasattr(ds, "WindowWidth"):
            raise ValueError("unsupported or incomplete VOI")
        presets = []
        if hasattr(ds, "WindowCenter"):
            centers, widths = _values(ds.WindowCenter), _values(ds.WindowWidth)
            if not 1 <= len(centers) <= 16 or len(centers) != len(widths):
                raise ValueError("paired alternative windows")
            for center, width in zip(centers, widths, strict=True):
                center, width = _finite(center), _finite(width, positive=True)
                if function == "LINEAR" and width < 1:
                    raise ValueError("linear width at least 1")
                presets.append({"center": center, "width": width})
        mono = str(ds.PhotometricInterpretation)
        shape = str(getattr(ds, "PresentationLUTShape", ""))
        if shape and shape != ("INVERSE" if mono == "MONOCHROME1" else "IDENTITY"):
            raise ValueError("inconsistent presentation shape")
        intent = str(getattr(ds, "PresentationIntentType", ""))
        if intent not in {"", "FOR PRESENTATION"}:
            raise ValueError("for-processing images need an explicit processing pipeline")
        metadata = {
            "format": FORMAT,
            "rows": rows,
            "columns": columns,
            "frames": 1,
            "bits_allocated": allocated,
            "bits_stored": stored,
            "high_bit": high,
            "pixel_representation": signed,
            "photometric_interpretation": mono,
            "transfer_syntax_uid": syntax,
            "sop_class_uid": str(ds.SOPClassUID),
            "rescale_slope": slope,
            "rescale_intercept": intercept,
            "rescale_declared": hasattr(ds, "RescaleSlope"),
            "rescale_type": _enum(ds, "RescaleType", {"HU", "US", "OD"}),
            "window_presets": presets,
            "voi_lut_function": function,
            "padding": padding,
            "presentation_lut_shape": shape or "not_declared",
            "invert_display": mono == "MONOCHROME1",
            "presentation_intent_type": intent or "not_declared",
            "valid_min_stored": minimum,
            "valid_max_stored": maximum,
            "valid_pixel_count": valid_count,
            "modality": _enum(ds, "Modality", {"CR", "DX", "CT", "MR", "MG"}),
            "body_part_examined": _enum(ds, "BodyPartExamined", {"CHEST", "ABDOMEN", "HEAD", "PELVIS", "SPINE", "BREAST", "EXTREMITY"}),
            "view_position": _enum(ds, "ViewPosition", {"AP", "PA", "LL", "RL", "LLD", "RLD", "RLO", "LLO"}),
            "image_laterality": _enum(ds, "ImageLaterality", {"R", "L", "B", "U"}),
            "burned_in_annotation": _enum(ds, "BurnedInAnnotation", {"YES", "NO"}),
            "coordinate_space": "source_pixels",
            "orientation": "stored_row_column_unmodified",
            **{field: _uid_hash(ds, name) for field, name in (("study_uid_hash", "StudyInstanceUID"), ("series_uid_hash", "SeriesInstanceUID"), ("instance_uid_hash", "SOPInstanceUID"))},
        }
        for field, name in (("pixel_spacing_mm", "PixelSpacing"), ("imager_pixel_spacing_mm", "ImagerPixelSpacing")):
            value = getattr(ds, name, None)
            metadata[field] = None if value is None else [_finite(item, positive=True) for item in _values(value)]
            if metadata[field] is not None and len(metadata[field]) != 2:
                raise ValueError("row and column spacing required")
        if sys.byteorder != "little":
            pixels.byteswap()
        return metadata, pixels.tobytes()
    except HTTPException:
        raise
    except (ValueError, TypeError, KeyError, IndexError, AttributeError, OverflowError, OSError) as exc:
        raise HTTPException(
            422, "当前支持带完整UID的DICOM Part10：单帧、单样本灰阶、8/16位原生小端、有限长度元素及线性重标定/窗参数；不选取压缩、多帧或容积的首帧，不推测缺失参数，不忽略未实现的LUT"
        ) from exc


def stage_image(upload):
    directory = Path(tempfile.mkdtemp(prefix=".stage-", dir=image_root()))
    try:
        size, digest = 0, hashlib.sha256()
        with (directory / "source.dcm").open("xb") as output:
            os.chmod(output.name, 0o600)
            while block := upload.file.read(65536):
                size += len(block)
                if size > settings.AI_IMAGE_MAX_BYTES:
                    raise HTTPException(413, "DICOM原文件超过当前大小限制")
                output.write(block)
                digest.update(block)
        metadata, pixels = parse_dicom(directory / "source.dcm")
        with (directory / "pixels.i32le").open("xb") as output:
            os.chmod(output.name, 0o600)
            output.write(pixels)
        identity = {"format": FORMAT, "original_hash": digest.hexdigest(), "pixel_hash": hashlib.sha256(pixels).hexdigest()}
        return directory, {
            "byte_size": size + len(pixels),
            "original_byte_size": size,
            "pixel_byte_size": len(pixels),
            **{key: value for key, value in identity.items() if key != "format"},
            "content_hash": hashlib.sha256(canonical_json(identity).encode()).hexdigest(),
            "metadata": metadata,
        }
    except BaseException:
        shutil.rmtree(directory)
        raise


def open_verified_image(asset):
    opened, directory_fd = [], None
    try:
        directory_fd = os.open(image_directory(asset.asset_id), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        for name, size, expected, limit in (
            ("source.dcm", asset.original_byte_size, asset.original_hash, settings.AI_IMAGE_MAX_BYTES),
            ("pixels.i32le", asset.pixel_byte_size, asset.pixel_hash, settings.AI_IMAGE_MAX_PIXELS * 4),
        ):
            descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory_fd)
            source = os.fdopen(descriptor, "rb")
            opened.append(source)
            actual = os.fstat(source.fileno())
            if not stat.S_ISREG(actual.st_mode) or not 0 < size <= limit or actual.st_size != size:
                raise OSError("source changed")
            digest = hashlib.sha256()
            while block := source.read(65536):
                digest.update(block)
            if digest.hexdigest() != expected:
                raise OSError("source hash changed")
            source.seek(0)
        return tuple(opened)
    except BaseException as exc:
        for source in opened:
            source.close()
        if isinstance(exc, OSError):
            raise HTTPException(409, "影像原文件或派生像素不可用或已变化，请核对私有存储") from exc
        raise
    finally:
        if directory_fd is not None:
            os.close(directory_fd)
