"""Check offline classifier parity against a fixed reviewed upstream implementation.

All inputs are synthetic arrays. This verifies implementation agreement only and
does not measure ECG interpretation, clinical accuracy, or calibration. The
reference Python file must be supplied locally; this script never downloads it.
"""

import argparse
import hashlib
import importlib.metadata
import importlib.util
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

REFERENCE_COMMIT = "6b82956004c0ffa7ae6e983df7867eec1b450d85"
REFERENCE_SHA256 = "bca3ca100c24ce68fefc1efb039012f84237e13812114e93a1b59ce1c9e4f8b0"
MODEL_REVISION = "6ec2ee1a1badd9508f9c1219fb07de38f3f6936b"
WEIGHTS_SHA256 = "c2497259f7f672fee5568b1906e95272f256f057a6860f3aa60acf8f8d903db8"
CONFIG_SHA256 = "36c896f1d05b92f59a0e004ef034c69ba74ea0a77936859244bf0d94d57c66ce"
LEADS = ("I", "II", "III", "aVR", "aVL", "aVF", "V1", "V2", "V3", "V4", "V5", "V6")
LABELS = ("NORM", "CD", "HYP", "MI", "STTC")


def verified_bytes(path, digest, byte_size):
    with path.open("rb") as stream:
        raw = stream.read(byte_size + 1)
    if len(raw) != byte_size:
        raise ValueError(f"Unexpected byte count for {path.name}")
    if hashlib.sha256(raw).hexdigest() != digest:
        raise ValueError(f"Unreviewed content rejected for {path.name}")
    return raw


def load_reference(source, path):
    """Execute only bytes that passed the fixed reviewed reference hash.

    Execute the checked byte snapshot, rather than reopening the supplied path
    with a source loader, so a changed file cannot bypass the preceding check.
    """
    if hashlib.sha256(source).hexdigest() != REFERENCE_SHA256:
        raise ValueError("Unreviewed reference source rejected")
    name = "hoim_reviewed_ecg_classifier_reference"
    spec = importlib.util.spec_from_loader(name, loader=None, origin=str(path))
    if spec is None:
        raise RuntimeError("Cannot create reference module specification")
    module = importlib.util.module_from_spec(spec)
    exec(compile(source, str(path), "exec"), module.__dict__)
    return module.ECGClassifier(module.ECGEncoder1DCNN(in_ch=12, width=64), n_classes=5)


def synthetic_cases(np):
    rng = np.random.default_rng(20261020)
    random = rng.normal(0, 0.4, (12, 1000)).astype(np.float32)
    # Exercise the upstream standard-deviation floor without missing samples.
    random[0] *= np.float32(1e-8)
    offsets = np.arange(12, dtype=np.float32)[:, None] / np.float32(8)
    scales = (np.arange(12, dtype=np.float32)[:, None] + np.float32(1)) / np.float32(12)
    ramp = np.linspace(-1, 1, 1000, dtype=np.float32)[None, :] * scales + offsets
    time = np.arange(1000, dtype=np.float32)[None, :] / np.float32(100)
    frequencies = np.arange(1, 13, dtype=np.float32)[:, None] / np.float32(2)
    periodic = np.sin(np.float32(2 * np.pi) * frequencies * time) * scales + offsets
    pulses = np.zeros((12, 1000), dtype=np.float32)
    for position in (100, 350, 600, 850):
        distance = (np.arange(1000, dtype=np.float32) - np.float32(position)) / np.float32(4)
        pulses += np.exp(-distance * distance)[None, :] * scales
    return (
        ("fixed_random_with_epsilon_floor", random),
        ("constant", np.broadcast_to(offsets, (12, 1000)).copy()),
        ("ramp", ramp),
        ("periodic", periodic),
        ("pulse", pulses),
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--reference-file", type=Path, required=True)
    parser.add_argument("--cpu-threads", type=int, default=4, choices=range(1, 17))
    args = parser.parse_args()

    # Verify every external input before executing reference Python or loading
    # weight tensors. The weights are decoded from these same verified bytes.
    source = verified_bytes(args.reference_file, REFERENCE_SHA256, 2823)
    config = json.loads(verified_bytes(args.model_dir / "config.json", CONFIG_SHA256, 1093))
    weights = verified_bytes(args.model_dir / "model.safetensors", WEIGHTS_SHA256, 2170628)
    if tuple(config["lead_order"]) != LEADS or tuple(config["id2label"][str(i)] for i in range(5)) != LABELS:
        raise ValueError("Pinned lead order or label order does not match this verifier")
    if (config["input_channels"], config["input_samples"], config["sampling_rate"], config["width"]) != (12, 1000, 100, 64):
        raise ValueError("Pinned input or network dimensions do not match this verifier")

    import numpy as np
    import torch
    from app.ai.ecg_network import create_network, load_network, normalize_input
    from safetensors.torch import load

    torch.set_num_threads(args.cpu_threads)
    state = load(weights)
    reference = load_reference(source, args.reference_file).cpu().eval()
    reference.load_state_dict(state, strict=True)
    fresh = create_network().cpu().eval()
    fresh.load_state_dict(state, strict=True)
    network = load_network(args.model_dir, cpu_threads=args.cpu_threads).cpu().eval()
    if set(network.state_dict()) != set(state) or set(fresh.state_dict()) != set(state):
        raise AssertionError("Production state names differ from the pinned reference weights")
    for name, expected in state.items():
        if not torch.equal(network.state_dict()[name], expected) or not torch.equal(fresh.state_dict()[name], expected):
            raise AssertionError(f"Production state differs from the pinned reference: {name}")

    cases = []
    with torch.inference_mode():
        for name, values in synthetic_cases(np):
            # Independent transcription of the reviewed upstream inference.py
            # contract. In particular, np.std uses ddof=0 and epsilon floors SD.
            raw = np.asarray(values, dtype=np.float32)[None]
            expected_input = (raw - raw.mean(-1, keepdims=True)) / np.maximum(raw.std(-1, keepdims=True), 1e-6)
            actual_input = normalize_input(values)
            if not isinstance(actual_input, np.ndarray) or actual_input.shape != (1, 12, 1000) or actual_input.dtype != np.float32:
                raise AssertionError("Production normalization must return float32 NumPy (1,12,1000)")
            if not np.isfinite(actual_input).all():
                raise AssertionError("Production normalization returned nonfinite values")
            np.testing.assert_allclose(actual_input, expected_input, atol=1e-7, rtol=0)
            expected_logits = reference(torch.from_numpy(np.ascontiguousarray(expected_input)))
            actual_logits = network(torch.from_numpy(np.ascontiguousarray(actual_input)))
            fresh_logits = fresh(torch.from_numpy(np.ascontiguousarray(actual_input)))
            if actual_logits.shape != (1, 5) or not torch.isfinite(actual_logits).all():
                raise AssertionError("Production logits must be finite with shape (1,5)")
            torch.testing.assert_close(actual_logits, expected_logits, atol=1e-6, rtol=0)
            torch.testing.assert_close(fresh_logits, expected_logits, atol=1e-6, rtol=0)
            expected_scores, actual_scores = expected_logits.sigmoid(), actual_logits.sigmoid()
            if not torch.isfinite(actual_scores).all():
                raise AssertionError("Production model scores must be finite")
            torch.testing.assert_close(actual_scores, expected_scores, atol=1e-6, rtol=0)
            cases.append(
                {
                    "fixture": name,
                    "normalized_maximum_absolute_error": float(np.max(np.abs(actual_input - expected_input))),
                    "logits_maximum_absolute_error": float((actual_logits - expected_logits).abs().max()),
                    "scores_maximum_absolute_error": float((actual_scores - expected_scores).abs().max()),
                    "model_scores": dict(zip(LABELS, actual_scores[0].tolist(), strict=True)),
                }
            )

    print(
        json.dumps(
            {
                "status": "passed",
                "scope": "synthetic implementation parity only; no clinical accuracy or calibration evaluation",
                "clinical_validation": "not_performed",
                "reference_source_commit": REFERENCE_COMMIT,
                "reference_source_sha256": REFERENCE_SHA256,
                "model_repository": "Tumo505/SSL-ECG-Classification-model-card",
                "model_revision": MODEL_REVISION,
                "weights_sha256": WEIGHTS_SHA256,
                "config_sha256": CONFIG_SHA256,
                "lead_order": list(LEADS),
                "label_order": list(LABELS),
                "samples_per_lead": 1000,
                "sample_rate_hz": 100,
                "input_dtype": "float32",
                "normalization": "per-record per-lead population SD, floor 1e-6",
                "device": "cpu",
                "cpu_threads": torch.get_num_threads(),
                "parameter_count": sum(parameter.numel() for parameter in network.parameters()),
                "state_tensor_count": len(state),
                "versions": {"torch": torch.__version__, "numpy": np.__version__, "safetensors": importlib.metadata.version("safetensors")},
                "cases": cases,
            },
            ensure_ascii=False,
            allow_nan=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
