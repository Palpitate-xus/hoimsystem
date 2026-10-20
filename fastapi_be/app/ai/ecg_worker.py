"""One offline CPU inference over the complete supported original ECG, never a clinical write."""

import hashlib
import json
import logging
import os
import sys
from decimal import Decimal
from pathlib import Path

from app.ai.ecg_config import ECGSettings, runtime_descriptor
from app.ai.ecg_contract import ECGSource
from app.ai.ecg_model import LABELS, LEADS
from app.ai.ecg_network import load_network, normalize_input

UNITS_TO_MV = {"mV": Decimal("1"), "uV": Decimal("0.001"), "µV": Decimal("0.001"), "μV": Decimal("0.001"), "V": Decimal("1000")}


def decode_native(path, source):
    import numpy as np

    source = ECGSource.model_validate(source)
    raw = Path(path).read_bytes()
    if len(raw) != source.signal_byte_size or hashlib.sha256(raw).hexdigest() != source.signal_hash:
        raise ValueError("实际心电原采样与登记字节数或哈希不一致")
    values = np.frombuffer(raw, dtype="<i2").reshape(1000, 12)
    if np.any(values == -32768):
        raise ValueError("原波形实际含缺失标记，该模型没有经核实的缺失补值策略")
    calibrated = []
    by_name = {lead.name: (index, lead) for index, lead in enumerate(source.signal_metadata.leads)}
    for name in LEADS:
        index, lead = by_name[name]
        scale = float(UNITS_TO_MV[lead.unit] / Decimal(lead.gain))
        calibrated.append((values[:, index].astype(np.float64) - lead.baseline) * scale)
    result = np.asarray(calibrated, dtype=np.float32)
    if not np.isfinite(result).all():
        raise ValueError("心电校准不能得到有限mV输入")
    return result


def classify(job):
    import numpy as np
    import torch

    config = ECGSettings(**job["config"])
    descriptor = runtime_descriptor(config)
    if descriptor["model_version"] != job["model_version"]:
        raise ValueError("心电模型、预处理或运行环境已变化")
    source = ECGSource.model_validate(job["source"]).model_dump()
    values = decode_native(job["waveform_path"], source)
    prepared = normalize_input(values)
    model = load_network(config.model_dir, config.cpu_threads)
    with torch.inference_mode():
        logits = model(torch.from_numpy(prepared))
        scores = logits.sigmoid().cpu().numpy()
    if scores.shape != (1, 5) or not np.isfinite(scores).all() or not np.isfinite(logits.cpu().numpy()).all():
        raise ValueError("模型没有返回完整有限的五类分数")
    local_runtime = {key: value for key, value in descriptor.items() if key not in {"schema_version", "feature_key", "model_version", "max_bytes", "timeout_seconds"}}
    local_runtime["population_applicability"] = "not_verified"
    titles = {"NORM": "NORM 模型类别（不构成正常结论）", "CD": "CD 传导异常类别", "HYP": "HYP 肥厚类别", "MI": "MI 心肌梗死类别", "STTC": "STTC ST/T变化类别"}
    findings = [
        {
            "category": "other",
            "label": label,
            "description": f"{titles[label]}：原始研究模型标签{label}的独立sigmoid输出，未应用诊断阈值或概率校准；仅整段分类，不提供病变起止定位，不能据此确认或排除疾病。",
            "leads": LEADS,
            "location": "recording",
            "start_sample": None,
            "end_sample_exclusive": None,
            "score": float(score),
            "score_kind": "model_score",
            "source_id": source["source_id"],
        }
        for label, score in zip(LABELS, scores[0], strict=True)
    ]
    return {
        "schema_version": "3",
        "feature_key": "ecg_analysis",
        "model_version": descriptor["model_version"],
        "applicable": True,
        "result": {
            "summary": "已计算所选10秒原心电的五类研究模型分数，须结合原波形及临床资料复核",
            "sections": [],
            "warnings": ["本地模型仅完成工程接入，未在本院验证信号质量、适用人群或诊断效果", "五类分数不是患病概率；NORM高分或其他低分均不证明正常、排除疾病或确定治疗"],
            "missing_data": ["经核实的采集年龄、适用人群及设备校准", "独立临床验证、疾病阈值和实际诊疗复核"],
        },
        "ecg_analysis": {
            "asset_id": source["asset_id"],
            "content_hash": source["content_hash"],
            "signal_hash": source["signal_hash"],
            "time_basis": "relative_samples",
            "processing": {
                "instructions_digest": job["instructions_digest"],
                "input_sample_count": 1000,
                "input_sample_rate_hz": source["signal_metadata"]["sample_rate_hz"],
                "input_leads": [lead["name"] for lead in source["signal_metadata"]["leads"]],
                "used_leads": LEADS,
                "processed_original_sample_count": 1000,
                "complete_input": True,
                "missing_sample_handling": "none_present",
                "preprocessing_notes": [
                    "按原增益、基线和单位换算mV，再按明确原导联名重排至模型顺序；未生成导联",
                    "每条原导联以float32按整段均值和总体标准差归一化，标准差下限1e-6；无滤波、重采样、填充或裁剪",
                    "完整10秒、1000原样本一次前向推理，输出五类整段独立分数；完整处理不证明信号质量或识别准确",
                    "仅原信号参与神经网络；完整Prompt摘要用于任务核对，问题、原头注释和其他病史不用于补造信号",
                ],
                "local_runtime": local_runtime,
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
        sys.stdout.write('{"error":"ECG_PROCESSING_FAILED"}')
        return 1
    sys.stdout.buffer.write(encoded)
    return 0


if __name__ == "__main__":
    os.environ["HF_HUB_OFFLINE"] = "1"
    sys.exit(main())
