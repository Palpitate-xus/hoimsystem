"""One offline chest-image research forward pass; no clinical write or generated localization."""

import json
import logging
import os
import sys

from app.ai.imaging_config import ImagingSettings, runtime_descriptor
from app.ai.imaging_contract import ImageSource
from app.ai.imaging_model import LABELS
from app.ai.imaging_network import load_network, predict_scores
from app.ai.imaging_preprocessing import decode_and_prepare


def classify(job):
    config = ImagingSettings(**job["config"])
    descriptor = runtime_descriptor(config)
    if descriptor["model_version"] != job["model_version"]:
        raise ValueError("影像模型、实现、预处理或运行环境已变化")
    source = ImageSource.model_validate(job["source"]).model_dump()
    prepared, report = decode_and_prepare(job["image_path"], source)
    model = load_network(config.model_dir, config.cpu_threads)
    scores = predict_scores(model, prepared)
    local_runtime = {key: value for key, value in descriptor.items() if key not in {"schema_version", "feature_key", "model_version", "max_bytes", "timeout_seconds"}}
    findings = [
        {
            "label": label,
            "description": f"原研究模型标签 {label} 的独立sigmoid输出，未做患病概率校准或诊断阈值判断；图像级分类不提供病灶定位，不能据此确认或排除疾病。",
            "location": "image",
            "region": None,
            "score": float(score),
            "score_kind": "model_score",
            "source_id": source["source_id"],
        }
        for label, score in zip(LABELS, scores, strict=True)
    ]
    keys = (
        "normalization_maxval",
        "input_pixel_count",
        "cropped_pixel_count",
        "discarded_pixel_count",
        "padding_pixels_in_input",
        "padding_pixels_in_crop",
        "valid_pixels_in_crop",
        "prepared_shape",
        "prepared_min",
        "prepared_max",
    )
    return {
        "schema_version": "4",
        "feature_key": "imaging_detection",
        "model_version": descriptor["model_version"],
        "applicable": True,
        "result": {
            "summary": "已计算所选单帧胸片中心区域的18项研究模型分数，须结合完整原图及临床资料复核",
            "sections": [],
            "warnings": [
                "仅完成研究模型工程接入，未核实采集时人群或本院诊断性能",
                "采用原存储值范围研究预处理，未应用DICOM VOI窗；不能与阅片显示或训练输入等同",
                "仅处理明确居中裁剪区域，裁剪区外未分析；单图不代表完整检查",
                "18项分数不是患病概率，未设置诊断阈值，也不自动确认诊断或推荐治疗",
            ],
            "missing_data": ["经核实的采集时年龄、适用人群、独立临床验证与完整检查资料"],
        },
        "image_analysis": {
            **{key: source[key] for key in ("asset_id", "content_hash", "original_hash", "pixel_hash")},
            "coordinate_space": "source_pixels",
            "processing": {
                "instructions_digest": job["instructions_digest"],
                "input_rows": source["image_metadata"]["rows"],
                "input_columns": source["image_metadata"]["columns"],
                "input_frames": 1,
                "processed_frames": [0],
                "analysis_region": report["analysis_region"],
                "preprocessing_notes": [
                    "按原BitsStored最大存储范围以float32归一化；MONOCHROME1在归一化前反转一次，不做自动minmax、Modality rescale或VOI窗映射",
                    "按原作者行/列整数中心公式裁成正方形，再用固定PyTorch双线性antialias缩至224×224（已224不重采样）；不旋转或猜测左右",
                    "padding保持原始背景数值，不掩盖、不填补或标作病灶；只报告原图与实际裁剪区中的数量",
                    "仅原像素参与固定网络；完整Prompt摘要用于任务溯源，问题和临床文字不作为病变证据",
                    "此公开研究预处理不代表统一训练等价、DICOM诊断显示或临床已验证",
                ],
                "local_runtime": local_runtime,
                "local_preprocessing": {key: report[key] for key in keys},
            },
            "findings": findings,
        },
    }


def main():
    logging.disable(logging.CRITICAL)
    try:
        raw = sys.stdin.buffer.read(131073)
        if len(raw) > 131072:
            raise ValueError("job too large")
        result = classify(json.loads(raw))
        encoded = json.dumps(result, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()
        if len(encoded) > 512 * 1024:
            raise ValueError("response too large")
    except (ValueError, TypeError, KeyError, OSError, RuntimeError, ImportError):
        sys.stdout.write('{"error":"IMAGE_PROCESSING_FAILED"}')
        return 1
    sys.stdout.buffer.write(encoded)
    return 0


if __name__ == "__main__":
    os.environ["HF_HUB_OFFLINE"] = "1"
    sys.exit(main())
