"""Independent native-pixel contract for the fixed XRV research input profile.

No hospital settings/database, DICOM decoder, NumPy or torch is imported here.
The contract is narrower than general DICOM intake and makes no claim that
native stored ranges reproduce the mixed training datasets' presentation.
"""

import hashlib
import math
import uuid
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.ai.imaging_model import canonical_json

MAX_PIXELS = 16 * 1024 * 1024
MAX_ORIGINAL_BYTES = 128 * 1024 * 1024
CR_SOP = "1.2.840.10008.5.1.4.1.1.1"
DX_SOP = "1.2.840.10008.5.1.4.1.1.1.1"
PositiveSpacing = Annotated[float, Field(gt=0, le=1e12, strict=True, allow_inf_nan=False)]


class PixelPadding(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    value: int = Field(ge=0, le=65535, strict=True)
    range_limit: int = Field(ge=0, le=65535, strict=True)


class WindowPreset(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    center: float = Field(ge=-1e12, le=1e12, strict=True, allow_inf_nan=False)
    width: float = Field(gt=0, le=1e12, strict=True, allow_inf_nan=False)


class ImageMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, revalidate_instances="always")
    format: Literal["dicom_i32le_v1"]
    rows: int = Field(ge=1, le=16384, strict=True)
    columns: int = Field(ge=1, le=16384, strict=True)
    frames: int = Field(ge=1, le=1, strict=True)
    bits_allocated: int = Field(ge=8, le=16, strict=True)
    bits_stored: int = Field(ge=8, le=16, strict=True)
    high_bit: int = Field(ge=7, le=15, strict=True)
    pixel_representation: int = Field(ge=0, le=0, strict=True)
    photometric_interpretation: Literal["MONOCHROME1", "MONOCHROME2"]
    transfer_syntax_uid: Literal["1.2.840.10008.1.2", "1.2.840.10008.1.2.1"]
    sop_class_uid: Literal["1.2.840.10008.5.1.4.1.1.1", "1.2.840.10008.5.1.4.1.1.1.1"]
    rescale_slope: float = Field(ge=1, le=1, strict=True, allow_inf_nan=False)
    rescale_intercept: float = Field(ge=0, le=0, strict=True, allow_inf_nan=False)
    rescale_declared: bool = Field(strict=True)
    rescale_type: Literal["HU", "US", "OD", "unknown"]
    window_presets: list[WindowPreset] = Field(max_length=16)
    voi_lut_function: Literal["LINEAR", "LINEAR_EXACT", "SIGMOID"]
    padding: PixelPadding | None
    presentation_lut_shape: Literal["IDENTITY", "INVERSE", "not_declared"]
    invert_display: bool = Field(strict=True)
    presentation_intent_type: Literal["FOR PRESENTATION", "not_declared"]
    valid_min_stored: int | None = Field(ge=0, le=65535, strict=True)
    valid_max_stored: int | None = Field(ge=0, le=65535, strict=True)
    valid_pixel_count: int = Field(ge=0, le=MAX_PIXELS, strict=True)
    modality: Literal["CR", "DX"]
    body_part_examined: Literal["CHEST"]
    view_position: Literal["PA", "AP"]
    image_laterality: Literal["R", "L", "B", "U", "unknown"]
    burned_in_annotation: Literal["YES", "NO", "unknown"]
    coordinate_space: Literal["source_pixels"]
    orientation: Literal["stored_row_column_unmodified"]
    study_uid_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    series_uid_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    instance_uid_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    pixel_spacing_mm: list[PositiveSpacing] | None = Field(min_length=2, max_length=2)
    imager_pixel_spacing_mm: list[PositiveSpacing] | None = Field(min_length=2, max_length=2)

    @model_validator(mode="after")
    def explicit_native_scope(self):
        if self.rows * self.columns > MAX_PIXELS or self.valid_pixel_count > self.rows * self.columns:
            raise ValueError("胸片原像素数或有效像素数超出明确范围")
        if self.bits_allocated not in {8, 16} or self.bits_stored > self.bits_allocated or self.high_bit != self.bits_stored - 1:
            raise ValueError("胸片须有一致的8/16位无符号逻辑存储参数")
        if self.sop_class_uid != {"CR": CR_SOP, "DX": DX_SOP}[self.modality]:
            raise ValueError("胸片模态与CR/DX presentation SOP声明不一致")
        inverse = self.photometric_interpretation == "MONOCHROME1"
        if self.invert_display != inverse or self.presentation_lut_shape not in {"not_declared", "INVERSE" if inverse else "IDENTITY"}:
            raise ValueError("胸片极性或presentation形状声明矛盾，不猜测或重复反转")
        maxval = (1 << self.bits_stored) - 1
        if self.padding and max(self.padding.value, self.padding.range_limit) > maxval:
            raise ValueError("原padding值超出实际BitsStored范围")
        if self.valid_pixel_count == 0:
            if self.valid_min_stored is not None or self.valid_max_stored is not None:
                raise ValueError("没有有效像素时不能声明有效像素范围")
        elif self.valid_min_stored is None or self.valid_max_stored is None or not 0 <= self.valid_min_stored <= self.valid_max_stored <= maxval:
            raise ValueError("有效像素范围与逻辑存储范围不一致")
        if self.padding is None and self.valid_pixel_count != self.rows * self.columns:
            raise ValueError("未声明padding时有效像素数须覆盖全部原像素")
        if self.voi_lut_function == "LINEAR" and any(preset.width < 1 for preset in self.window_presets):
            raise ValueError("LINEAR窗宽须至少为1；窗虽不应用，声明仍须合法")
        for spacing in (self.pixel_spacing_mm, self.imager_pixel_spacing_mm):
            if spacing is not None:
                if any(not math.isfinite(value) or not 0 < value <= 1e12 for value in spacing):
                    raise ValueError("像素间距须为两个有限正数")
        return self


class ImageSource(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True, revalidate_instances="always")
    asset_id: str = Field(min_length=36, max_length=36)
    original_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    pixel_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    content_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    byte_size: int = Field(gt=0, le=MAX_ORIGINAL_BYTES + MAX_PIXELS * 4, strict=True)
    original_byte_size: int = Field(gt=0, le=MAX_ORIGINAL_BYTES, strict=True)
    pixel_byte_size: int = Field(gt=0, le=MAX_PIXELS * 4, strict=True)
    source_id: str = Field(min_length=1, max_length=100)
    imaging_order_id: str = Field(min_length=36, max_length=36)
    order_status: int = Field(ge=0, le=4, strict=True)
    image_metadata: ImageMetadata

    @model_validator(mode="after")
    def source_identity(self):
        if str(uuid.UUID(self.asset_id)) != self.asset_id or str(uuid.UUID(self.imaging_order_id)) != self.imaging_order_id:
            raise ValueError("原胸片及真实影像申请须为规范UUID")
        if self.source_id != f"image:{self.asset_id}:{self.content_hash[:12]}":
            raise ValueError("原胸片引用与原记录标识不一致")
        if self.pixel_byte_size != self.image_metadata.rows * self.image_metadata.columns * 4 or self.byte_size != self.original_byte_size + self.pixel_byte_size:
            raise ValueError("原胸片逻辑像素数、像素字节数或组合字节数不一致")
        identity = {"format": self.image_metadata.format, "original_hash": self.original_hash, "pixel_hash": self.pixel_hash}
        if hashlib.sha256(canonical_json(identity).encode()).hexdigest() != self.content_hash:
            raise ValueError("原胸片组合哈希与原文件哈希声明不一致")
        return self
