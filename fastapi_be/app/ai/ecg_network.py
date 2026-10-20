"""Reviewed local adaptation of the Apache-2.0 SSL-ECG CNN; no remote-code loading.

Sources and fixed revisions: third_party/ssl-ecg/NOTICE. Modified to remove
Transformers, load only verified safetensors and expose original sigmoid scores.
"""

from app.ai.ecg_model import verify_model


def normalize_input(values):
    import numpy as np

    samples = np.asarray(values, dtype=np.float32)
    if samples.shape != (12, 1000) or not np.isfinite(samples).all():
        raise ValueError("须提供有限的12导联、100Hz、1000原样本，不裁剪、填充或补齐")
    with np.errstate(over="raise", invalid="raise", divide="raise"):
        try:
            result = (samples - samples.mean(-1, keepdims=True)) / np.maximum(samples.std(-1, keepdims=True), 1e-6)
        except FloatingPointError as exc:
            raise ValueError("心电数值超出归一化适用范围") from exc
    if not np.isfinite(result).all():
        raise ValueError("心电归一化不能得到有限输入")
    return np.ascontiguousarray(result[None])


def create_network():
    # These six reviewed blocks preserve the exact published state-dict keys.
    from torch import nn

    class ConvBlock(nn.Module):
        def __init__(self, incoming, outgoing, kernel, stride):
            super().__init__()
            self.block = nn.Sequential(nn.Conv1d(incoming, outgoing, kernel, stride, padding=kernel // 2, bias=False), nn.BatchNorm1d(outgoing), nn.ReLU(inplace=True))

        def forward(self, values):
            return self.block(values)

    class Encoder(nn.Module):
        def __init__(self):
            super().__init__()
            self.features = nn.Sequential(*(ConvBlock(*spec) for spec in ((12, 64, 11, 2), (64, 64, 7, 1), (64, 128, 7, 2), (128, 128, 5, 1), (128, 256, 5, 2), (256, 256, 3, 1))))

        def forward(self, values):
            return self.features(values)

    class Classifier(nn.Module):
        def __init__(self):
            super().__init__()
            self.encoder = Encoder()
            self.pool = nn.AdaptiveAvgPool1d(1)
            self.head = nn.Linear(256, 5)

        def forward(self, values):
            return self.head(self.pool(self.encoder(values)).squeeze(-1))

    return Classifier()


def load_network(directory, cpu_threads=4):
    import hashlib
    from pathlib import Path

    import torch
    from safetensors.torch import load

    from app.ai.ecg_model import RELEASE_FILES

    directory = Path(directory)
    verify_model(directory)
    raw = (directory / "model.safetensors").read_bytes()
    expected_size, expected_digest = RELEASE_FILES["model.safetensors"]
    if len(raw) != expected_size or hashlib.sha256(raw).hexdigest() != expected_digest:
        raise ValueError("读取到的实际权重与已审查模型不一致")
    torch.set_num_threads(cpu_threads)
    model = create_network().cpu()
    model.load_state_dict(load(raw), strict=True)
    model.eval()
    return model
