"""Fixed author-native stored-range research input, independent of DICOM display.

Sources: fixed TorchXRayVision utils.normalize/read_xray_dcm,
datasets.XRayCenterCrop and utils.fix_resolution. No claim of equality with
mixed dataset training conversions, skimage resize or diagnostic presentation.
"""

import hashlib
import os
import stat

from app.ai.imaging_contract import MAX_PIXELS, ImageSource

PREPROCESSING = {
    "profile": "xrv_stored_range_v1",
    "input_profile": {
        "format": "dicom_i32le_v1",
        "modalities": ["CR", "DX"],
        "body_part_examined": "CHEST",
        "view_positions": ["PA", "AP"],
        "frames": 1,
        "pixel_representation": "unsigned",
        "bits_allocated": [8, 16],
        "bits_stored_min": 8,
        "bits_stored_max": 16,
        "max_pixels": MAX_PIXELS,
        "max_pixel_bytes": MAX_PIXELS * 4,
        "rescale_slope": 1,
        "rescale_intercept": 0,
        "presentation_intent_type": ["FOR PRESENTATION", "not_declared"],
        "population_applicability": "not_verified",
        "clinical_validation": "not_provided",
    },
    "source_code_revision": "17726dd8f5e756eec3e5ae958281a289b05b1dae",
    "normalization": "(2*(stored.astype(numpy.float32)/((1<<BitsStored)-1))-1)*1024",
    "normalization_range": [-1024, 1024],
    "monochrome1": "maxval-stored before normalization; exactly one inversion",
    "crop": "center square: side=min(rows,columns); x=columns//2-side//2; y=rows//2-side//2",
    "resize": {"size": [224, 224], "mode": "bilinear", "align_corners": False, "antialias": True, "skip_if_already_224": True},
    "resize_roundoff_tolerance": 0.01,
    "padding_policy": "preserved_as_original_background",
    "constant_valid_crop_policy": "reject",
    "voi_window_policy": "ignored_for_research_input_not_diagnostic_display",
    "modality_lut": "unsupported; identity rescale only",
    "histogram_equalization": False,
    "image_minmax_normalization": False,
    "rotation": False,
    "flipping": False,
    "imputation": False,
    "training_distribution_equivalence": "not_established",
    "spatial_localization": False,
}


def center_crop(rows, columns):
    if type(rows) is not int or type(columns) is not int or rows <= 0 or columns <= 0:
        raise ValueError("原胸片行列须为正整数")
    side = min(rows, columns)
    return {"x": columns // 2 - side // 2, "y": rows // 2 - side // 2, "width": side, "height": side}


def _verified_pixel_bytes(path, source):
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(descriptor, "rb") as stream:
            actual = os.fstat(stream.fileno())
            if not stat.S_ISREG(actual.st_mode) or actual.st_size != source.pixel_byte_size:
                raise ValueError("原胸片逻辑采样文件类型或实际字节数不一致")
            raw = stream.read(source.pixel_byte_size + 1)
    except OSError as exc:
        raise ValueError("无法读取原胸片逻辑采样实际常规文件") from exc
    if len(raw) != source.pixel_byte_size or hashlib.sha256(raw).hexdigest() != source.pixel_hash:
        raise ValueError("原胸片逻辑采样实际哈希与原记录不一致")
    return raw


def decode_and_prepare(path, source):
    source = ImageSource.model_validate(source)
    raw = _verified_pixel_bytes(path, source)
    import numpy as np
    import torch

    metadata = source.image_metadata
    pixels = np.frombuffer(raw, dtype="<i4").reshape(metadata.rows, metadata.columns)
    maxval = (1 << metadata.bits_stored) - 1
    if np.any(pixels < 0) or np.any(pixels > maxval):
        raise ValueError("实际逻辑像素超出已声明的无符号BitsStored范围")
    padding = metadata.padding
    mask = np.zeros(pixels.shape, dtype=bool) if padding is None else (pixels >= min(padding.value, padding.range_limit)) & (pixels <= max(padding.value, padding.range_limit))
    valid = pixels[~mask]
    actual_min = int(valid.min()) if valid.size else None
    actual_max = int(valid.max()) if valid.size else None
    if valid.size != metadata.valid_pixel_count or actual_min != metadata.valid_min_stored or actual_max != metadata.valid_max_stored:
        raise ValueError("实际有效像素数或范围与原登记元数据不一致")
    region = center_crop(metadata.rows, metadata.columns)
    x, y, side = region["x"], region["y"], region["width"]
    crop_pixels, crop_mask = pixels[y : y + side, x : x + side], mask[y : y + side, x : x + side]
    valid_crop = crop_pixels[~crop_mask]
    if not valid_crop.size or valid_crop.min() == valid_crop.max():
        raise ValueError("中心裁剪区域没有含变化的有效原像素，不补值或推断正常")
    # Inversion in the integer stored domain precedes the author's float32
    # normalization. Padding follows that same original-pixel path unchanged.
    inverted = metadata.photometric_interpretation == "MONOCHROME1"
    values = maxval - pixels if inverted else pixels
    normalized = (2 * (values.astype(np.float32) / maxval) - 1.0) * 1024
    prepared = torch.from_numpy(np.ascontiguousarray(normalized[y : y + side, x : x + side][None, None]))
    if side != 224:
        prepared = torch.nn.functional.interpolate(prepared, size=(224, 224), mode="bilinear", align_corners=False, antialias=True)
    if tuple(prepared.shape) != (1, 1, 224, 224) or prepared.dtype != torch.float32 or prepared.device.type != "cpu" or not torch.isfinite(prepared).all().item():
        raise ValueError("胸片原存储范围预处理未生成明确的有限CPU张量")
    prepared_min, prepared_max = float(prepared.min()), float(prepared.max())
    tolerance = PREPROCESSING["resize_roundoff_tolerance"]
    if prepared_min < -1024 - tolerance or prepared_max > 1024 + tolerance:
        raise ValueError("胸片预处理结果超出固定模型范围")
    input_count = metadata.rows * metadata.columns
    report = {
        "normalization_maxval": maxval,
        "input_pixel_count": input_count,
        "cropped_pixel_count": side * side,
        "discarded_pixel_count": input_count - side * side,
        "padding_pixels_in_input": int(mask.sum()),
        "padding_pixels_in_crop": int(crop_mask.sum()),
        "valid_pixels_in_crop": int(valid_crop.size),
        "prepared_shape": list(prepared.shape),
        "prepared_min": prepared_min,
        "prepared_max": prepared_max,
        "analysis_region": region,
        "resize_applied": side != 224,
        "single_inversion_applied": inverted,
        "padding_policy": "preserved_as_original_background",
        "voi_window_applied": False,
        "preprocessing_notes": [
            "采用作者原生stored-range研究输入链；不证明与混合训练数据转换等价，不代表DICOM诊断显示。",
            "按BitsStored完整范围归一化，未按图像min/max拉伸，未应用原VOI/窗或直方图均衡。",
            "原padding按原背景采样路径保留，不补值，不视为病灶；裁剪外像素不纳入分类范围。",
            "中心方形裁剪后使用固定torch bilinear antialias路径；不冒称与skimage resize等价，不旋转或翻转。",
            "保留float32插值的实际舍入值；仅允许边界0.01以内的工程数值误差，不裁平或改写张量，不代表临床误差界限。",
        ],
    }
    return prepared, report
