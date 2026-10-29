"""Current engine pins, immutable old identities and synthetic CPU library compatibility."""

import copy
import hashlib
import io
import wave
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.ai import ecg_config, imaging_config, speech_config
from app.ai.imaging_probe import ImagingCapabilities
from app.ai.schemas import LocalECGRuntime, LocalImagingRuntime
from tests.test_ai_imaging_probe import capabilities
from tests.test_ai_imaging_processing import make_case

CURRENT = {"torch": "2.15.0+cpu", "numpy": "2.5.4", "safetensors": "0.8.0"}
HISTORICAL = {"torch": "2.14.1+cpu", "numpy": "2.4.4", "safetensors": "0.8.0"}


def ecg_runtime(versions):
    from app.ai.ecg_model import LABELS, LEADS, PREPROCESSING, canonical_json

    return {
        "engine": "ssl-ecg-cnn",
        "engine_versions": dict(versions),
        "model_repository": "Tumo505/SSL-ECG-Classification-model-card",
        "model_revision": "6ec2ee1a1badd9508f9c1219fb07de38f3f6936b",
        "model_digest": "a" * 64,
        "runtime_digest": "b" * 64,
        "preprocessing_digest": hashlib.sha256(canonical_json(PREPROCESSING).encode()).hexdigest(),
        "required_leads": list(LEADS),
        "sample_rate_hz": 100,
        "samples_per_lead": 1000,
        "labels": list(LABELS),
        "missing_sample_policy": "reject",
        "prompt_handling": "signal_only",
        "clinical_validation": "not_provided",
        "population_applicability": "not_verified",
    }


@pytest.mark.parametrize("versions", [HISTORICAL, CURRENT], ids=["historical", "current"])
def test_frozen_runtime_versions_and_digests_are_preserved_without_rewriting(versions):
    ecg = ecg_runtime(versions)
    image = make_case()[1]["image_analysis"]["processing"]["local_runtime"]
    image["engine_versions"] = dict(versions)
    originals = copy.deepcopy((ecg, image))
    assert LocalECGRuntime.model_validate(ecg).model_dump() == ecg
    assert LocalImagingRuntime.model_validate(image).model_dump() == image
    assert (ecg, image) == originals
    report = capabilities()
    report["engine_versions"] = dict(versions)
    assert ImagingCapabilities.model_validate(report).model_dump()["engine_versions"] == versions


@pytest.mark.parametrize("package", ["torch", "numpy", "safetensors"])
@pytest.mark.parametrize("change", ["mixed", "future", "gpu"])
def test_unadopted_runtime_combinations_are_rejected(package, change):
    versions = dict(CURRENT)
    if change == "mixed":
        versions[package] = HISTORICAL[package] if package != "safetensors" else "0.7.0"
    elif change == "future":
        versions[package] = "999.0.0"
    else:
        versions[package] += "+cu128"
    with pytest.raises(ValidationError):
        LocalECGRuntime.model_validate(ecg_runtime(versions))
    image = make_case()[1]["image_analysis"]["processing"]["local_runtime"]
    image["engine_versions"] = versions
    with pytest.raises(ValidationError):
        LocalImagingRuntime.model_validate(image)


@pytest.mark.parametrize("module,settings", [(ecg_config, ecg_config.ECGSettings), (imaging_config, imaging_config.ImagingSettings)])
def test_new_services_enforce_the_current_exact_cpu_combination(module, settings, tmp_path, monkeypatch):
    manifest = SimpleNamespace(digest="a" * 64, repository="synthetic/repository", revision="b" * 40)
    monkeypatch.setattr(module, "verify_model", lambda _: manifest)
    monkeypatch.setattr(module, "version", CURRENT.__getitem__)
    secret_name = "AI_PROVIDER_LOCAL_ECG_API_KEY" if module is ecg_config else "AI_PROVIDER_LOCAL_IMAGING_API_KEY"
    config = settings(model_dir=tmp_path, **{secret_name: "synthetic-current-engine-key-" + "x" * 32})
    assert module.runtime_descriptor(config)["engine_versions"] == CURRENT
    monkeypatch.setattr(module, "version", HISTORICAL.__getitem__)
    with pytest.raises(ValueError, match="CPU"):
        module.runtime_descriptor(config)


def test_speech_service_uses_the_current_compatible_released_dependencies(tmp_path, monkeypatch):
    versions = {"faster-whisper": "1.2.1", "ctranslate2": "4.8.4", "onnxruntime": "1.31.1", "av": "18.1.0", "tokenizers": "0.23.3", "numpy": "2.5.4"}
    monkeypatch.setattr(speech_config, "verify_model", lambda _: SimpleNamespace(digest="a" * 64, repository="synthetic/repository", revision="b" * 40))
    monkeypatch.setattr(speech_config, "version", versions.__getitem__)
    config = speech_config.SpeechSettings(model_dir=tmp_path, AI_PROVIDER_LOCAL_SPEECH_API_KEY="synthetic-current-engine-key-" + "x" * 32)
    descriptor = speech_config.runtime_descriptor(config)
    assert descriptor["engine_versions"] == versions
    original_identity = descriptor["model_version"]
    versions["av"] = "19.0.2"
    with pytest.raises(ValueError, match="依赖"):
        speech_config.runtime_descriptor(config)
    assert descriptor["model_version"] == original_identity


@pytest.mark.parametrize("kind", ["ecg", "imaging"])
def test_synthetic_safetensors_pass_the_actual_strict_cpu_loader_and_forward(kind, tmp_path, monkeypatch):
    """Exercise real libraries and architecture; synthetic weights are not release evidence."""
    torch = pytest.importorskip("torch")
    pytest.importorskip("numpy")
    from safetensors.torch import save

    if kind == "ecg":
        from app.ai import ecg_model as packaging
        from app.ai import ecg_network as network
    else:
        from app.ai import imaging_model as packaging
        from app.ai import imaging_network as network

    torch.set_num_threads(1)
    torch.manual_seed(183)
    original = network.create_network().cpu().eval()
    original_state = original.state_dict()
    weights = save(original_state)
    contents = {name: (weights if name == "model.safetensors" else ("synthetic fixture: " + name).encode()) for name in packaging.RELEASE_FILES}
    files = {name: (len(raw), hashlib.sha256(raw).hexdigest()) for name, raw in contents.items()}
    monkeypatch.setattr(packaging, "RELEASE_FILES", files)
    for name, raw in contents.items():
        (tmp_path / name).write_bytes(raw)
    packaging.create_manifest(tmp_path)
    restored = network.load_network(tmp_path, cpu_threads=1)
    assert not restored.training
    assert set(restored.state_dict()) == set(original_state)
    assert all(torch.equal(value, restored.state_dict()[name]) for name, value in original_state.items())
    values = torch.linspace(-1, 1, 12 * 1000).reshape(1, 12, 1000) if kind == "ecg" else torch.linspace(-1024, 1024, 224 * 224).reshape(1, 1, 224, 224)
    before = values.clone()
    with torch.inference_mode():
        expected, actual = original(values), restored(values)
    assert tuple(actual.shape) == ((1, 5) if kind == "ecg" else (1, 18))
    assert torch.isfinite(actual).all().item()
    torch.testing.assert_close(actual, expected, rtol=0, atol=0)
    assert torch.equal(values, before)
    if kind == "imaging":
        assert network.predict_scores(restored, values) == torch.sigmoid(expected)[0].tolist()
    # Hash checks still reject changed weights even though this is a synthetic fixture.
    (tmp_path / "model.safetensors").write_bytes(b"x" * len(weights))
    with pytest.raises(ValueError):
        network.load_network(tmp_path, cpu_threads=1)


def test_released_faster_whisper_decodes_synthetic_wav_with_the_compatible_pyav():
    np = pytest.importorskip("numpy")
    pytest.importorskip("faster_whisper")
    from faster_whisper.audio import decode_audio

    samples = (np.sin(np.arange(8000, dtype=np.float64) * (2 * np.pi * 440 / 8000)) * 12000).astype("<i2")
    data = io.BytesIO()
    with wave.open(data, "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(8000)
        stream.writeframes(samples.tobytes())
    data.seek(0)
    decoded = decode_audio(data, sampling_rate=16000)
    assert decoded.dtype == np.float32 and decoded.shape == (16000,)
    assert np.isfinite(decoded).all() and np.max(np.abs(decoded)) > 0.3
