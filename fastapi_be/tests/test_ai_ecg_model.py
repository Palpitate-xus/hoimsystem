"""Synthetic release files verify immutable ECG packaging, never diagnostic weights."""

import hashlib
import io
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.ai import ecg_config, ecg_model
from app.ai.ecg_config import ECGSettings, runtime_descriptor
from scripts import prepare_ecg_model


@pytest.fixture
def release(tmp_path, monkeypatch):
    contents = {
        "model.safetensors": b"synthetic weight bytes, never loaded as a classifier",
        "config.json": b'{"test": "synthetic release"}\n',
        "LICENSE": b"synthetic license fixture\n",
        "README.md": b"synthetic provenance fixture\n",
        "provenance.json": b'{"test": "no clinical data or validation"}\n',
    }
    files = {name: (len(data), hashlib.sha256(data).hexdigest()) for name, data in contents.items()}
    monkeypatch.setattr(ecg_model, "RELEASE_FILES", files)
    monkeypatch.setattr(prepare_ecg_model, "RELEASE_FILES", files)
    source = tmp_path / "original-release"
    source.mkdir()
    for name, data in contents.items():
        (source / name).write_bytes(data)
    return source, contents


def test_offline_preparation_preserves_original_bytes_and_destination_independent_identity(release, tmp_path, monkeypatch):
    source, contents = release

    def forbidden_network(*args, **kwargs):
        raise AssertionError("offline preparation must not access the network")

    monkeypatch.setattr(prepare_ecg_model.urllib.request, "urlopen", forbidden_network)
    first, second = tmp_path / "first", tmp_path / "elsewhere" / "second"
    one = prepare_ecg_model.prepare_model(first, source=source)
    two = prepare_ecg_model.prepare_model(second, source=source)
    assert one["model_digest"] == two["model_digest"]
    assert one["repository"] == ecg_model.REPOSITORY and one["revision"] == ecg_model.REVISION
    manifest = ecg_model.verify_model(first)
    assert manifest.digest == one["model_digest"] == ecg_model.verify_model(second).digest
    assert {path.name for path in first.iterdir()} == set(contents) | {ecg_model.MANIFEST_NAME}
    for name, data in contents.items():
        assert (first / name).read_bytes() == (second / name).read_bytes() == data
    assert str(first) not in json.dumps(manifest.model_dump())
    assert str(second) not in json.dumps(manifest.model_dump())
    assert not list(tmp_path.rglob(".ecg-model-*"))


@pytest.mark.parametrize("change", ["repository", "mutable_revision", "other_commit"])
def test_unreviewed_repository_or_revision_is_rejected_before_filesystem_or_network(change, monkeypatch):
    def forbidden_io(*args, **kwargs):
        raise AssertionError("unreviewed identity must fail before any filesystem or network access")

    monkeypatch.setattr(prepare_ecg_model, "Path", forbidden_io)
    monkeypatch.setattr(prepare_ecg_model.urllib.request, "urlopen", forbidden_io)
    options = {"repository": "unreviewed/model"} if change == "repository" else {"revision": "main" if change == "mutable_revision" else "0" * 40}
    with pytest.raises(ValueError, match="固定"):
        prepare_ecg_model.prepare_model("must-not-be-created", **options)


@pytest.mark.parametrize("change", ["weight_bytes", "missing", "extra", "file_symlink", "manifest_symlink", "manifest_hash", "manifest_revision", "oversized_manifest"])
def test_verification_rejects_changed_incomplete_extra_or_indirect_artifacts(change, release, tmp_path):
    source, contents = release
    ecg_model.create_manifest(source)
    weight, manifest_path = source / "model.safetensors", source / ecg_model.MANIFEST_NAME
    if change == "weight_bytes":
        weight.write_bytes(b"x" * len(contents[weight.name]))
    elif change == "missing":
        (source / "LICENSE").unlink()
    elif change == "extra":
        (source / "remote_model.py").write_text("raise RuntimeError('must never execute')\n")
    elif change == "file_symlink":
        external = tmp_path / "external-weights"
        external.write_bytes(weight.read_bytes())
        weight.unlink()
        weight.symlink_to(external)
    elif change == "manifest_symlink":
        external = tmp_path / "external-manifest"
        external.write_bytes(manifest_path.read_bytes())
        manifest_path.unlink()
        manifest_path.symlink_to(external)
    elif change in {"manifest_hash", "manifest_revision"}:
        value = json.loads(manifest_path.read_bytes())
        if change == "manifest_hash":
            value["files"]["model.safetensors"]["sha256"] = "0" * 64
        else:
            value["revision"] = "main"
        manifest_path.write_text(json.dumps(value))
    else:
        manifest_path.write_bytes(b" " * 16385)
    with pytest.raises(ValueError):
        ecg_model.verify_model(source)


@pytest.mark.parametrize("change", ["missing", "mutated", "symlink"])
def test_failed_offline_preparation_removes_partial_stage_without_publishing_destination(change, release, tmp_path):
    source, contents = release
    # The final release file fails after preceding files have already been copied.
    name = next(reversed(contents))
    path = source / name
    if change == "missing":
        path.unlink()
    elif change == "mutated":
        path.write_bytes(b"x" * len(contents[name]))
    else:
        original = tmp_path / "external-provenance"
        original.write_bytes(path.read_bytes())
        path.unlink()
        path.symlink_to(original)
    destination = tmp_path / "prepared" / "model"
    with pytest.raises(ValueError):
        prepare_ecg_model.prepare_model(destination, source=source)
    assert not destination.exists() and not list(destination.parent.glob(".ecg-model-*"))
    assert source.exists()


def test_existing_destination_is_preserved_even_if_source_is_valid(release, tmp_path):
    source, _ = release
    destination = tmp_path / "existing"
    destination.mkdir()
    marker = destination / "keep"
    marker.write_bytes(b"original version")
    with pytest.raises(ValueError, match="已存在"):
        prepare_ecg_model.prepare_model(destination, source=source)
    assert list(destination.iterdir()) == [marker] and marker.read_bytes() == b"original version"


@pytest.mark.parametrize("failure", [None, "oversize", "short", "network"])
def test_download_is_pinned_bounded_and_atomically_published_only_after_verification(failure, release, tmp_path, monkeypatch):
    _, contents = release
    urls = []
    last_name = next(reversed(contents))

    def download(url, *, timeout):
        assert timeout == 30
        urls.append(url)
        name = url.rsplit("/", 1)[-1]
        assert url == f"https://huggingface.co/{ecg_model.REPOSITORY}/resolve/{ecg_model.REVISION}/{name}"
        data = contents[name]
        if name == last_name:
            if failure == "network":
                raise OSError("isolated download failure")
            if failure == "oversize":
                data += b"unexpected"
            elif failure == "short":
                data = data[:-1]
        return io.BytesIO(data)

    monkeypatch.setattr(prepare_ecg_model.urllib.request, "urlopen", download)
    destination = tmp_path / "downloaded"
    if failure is None:
        report = prepare_ecg_model.prepare_model(destination)
        assert report["model_digest"] == ecg_model.verify_model(destination).digest
        assert len(urls) == len(contents)
    else:
        with pytest.raises((ValueError, OSError)):
            prepare_ecg_model.prepare_model(destination)
        assert not destination.exists()
    assert not list(tmp_path.glob(".ecg-model-*")) and all(not url.endswith(".py") for url in urls)


@pytest.fixture
def descriptor_runtime(monkeypatch):
    manifest = SimpleNamespace(repository=ecg_model.REPOSITORY, revision=ecg_model.REVISION, digest="a" * 64)
    versions = dict(ecg_config.CPU_ENGINE_VERSIONS)
    implementation = {name: ("synthetic reviewed source: " + name).encode() for name in ("ecg_model.py", "ecg_network.py", "ecg_worker.py")}
    paths, reads = [], []
    original_read = Path.read_bytes

    def verify(directory):
        paths.append(directory)
        return manifest

    def source_bytes(path):
        if path.name in implementation:
            reads.append(path.name)
            return implementation[path.name]
        return original_read(path)

    monkeypatch.setattr(ecg_config, "verify_model", verify)
    monkeypatch.setattr(ecg_config, "version", lambda name: versions[name])
    monkeypatch.setattr(Path, "read_bytes", source_bytes)
    return manifest, versions, implementation, paths, reads


def settings_for(directory, **options):
    return ECGSettings(model_dir=directory, AI_PROVIDER_LOCAL_ECG_API_KEY="isolated-service-key-never-used-" + "x" * 32, **options)


def test_settings_resolve_relative_model_path_before_worker_changes_directory(tmp_path, monkeypatch, descriptor_runtime):
    monkeypatch.chdir(tmp_path)
    config = settings_for("models/reviewed")
    assert config.model_dir == tmp_path / "models" / "reviewed"
    report = runtime_descriptor(config)
    assert descriptor_runtime[3] == [config.model_dir]
    assert set(descriptor_runtime[4]) == {"ecg_model.py", "ecg_network.py", "ecg_worker.py"}
    assert report["model_version"] == "ssl-ecg:" + report["runtime_digest"]
    assert report["clinical_validation"] == "not_provided" and report["missing_sample_policy"] == "reject"
    assert str(tmp_path) not in json.dumps(report) and "isolated-service-key" not in json.dumps(report)


def test_short_service_key_fails_before_model_or_dependency_access(tmp_path, monkeypatch):
    def forbidden(*args):
        raise AssertionError("short credential must fail before model/dependency access")

    monkeypatch.setattr(ecg_config, "verify_model", forbidden)
    monkeypatch.setattr(ecg_config, "version", forbidden)
    config = ECGSettings(model_dir=tmp_path, AI_PROVIDER_LOCAL_ECG_API_KEY="too-short")
    with pytest.raises(ValueError, match="32"):
        runtime_descriptor(config)


@pytest.mark.parametrize("package,value", [("torch", "2.15.0+cu128"), ("torch", "2.15.0"), ("torch", "2.14.1+cpu"), ("safetensors", "0.7.0"), ("numpy", "2.4.4")])
def test_runtime_rejects_unpinned_cpu_dependencies(package, value, tmp_path, descriptor_runtime):
    descriptor_runtime[1][package] = value
    with pytest.raises(ValueError, match="CPU"):
        runtime_descriptor(settings_for(tmp_path))


@pytest.mark.parametrize("change", ["model", "recipe", "numpy", "model_source", "network_source", "worker_source", "cpu_threads"])
def test_runtime_identity_tracks_model_recipe_implementation_dependencies_and_inference_options(change, tmp_path, monkeypatch, descriptor_runtime):
    config = settings_for(tmp_path)
    before = runtime_descriptor(config)
    if change == "model":
        descriptor_runtime[0].digest = "b" * 64
    elif change == "recipe":
        monkeypatch.setattr(ecg_config, "PREPROCESSING", {**ecg_config.PREPROCESSING, "normalization_epsilon": 1e-5})
    elif change == "numpy":
        # Simulate a later explicitly adopted version, never an unpinned runtime.
        descriptor_runtime[1]["numpy"] = "2.5.5"
        monkeypatch.setattr(ecg_config, "CPU_ENGINE_VERSIONS", dict(descriptor_runtime[1]))
    elif change.endswith("_source"):
        descriptor_runtime[2]["ecg_" + change.removesuffix("_source") + ".py"] += b"\nchanged implementation"
    else:
        config = settings_for(tmp_path, cpu_threads=2)
    after = runtime_descriptor(config)
    assert before["runtime_digest"] != after["runtime_digest"] and before["model_version"] != after["model_version"]
    if change == "recipe":
        assert before["preprocessing_digest"] != after["preprocessing_digest"]


def test_runtime_identity_is_independent_of_model_destination_service_secret_and_request_limits(tmp_path, descriptor_runtime):
    first = runtime_descriptor(settings_for(tmp_path / "first", max_bytes=1024, timeout_seconds=3))
    second_config = ECGSettings(model_dir=tmp_path / "second", AI_PROVIDER_LOCAL_ECG_API_KEY="another-isolated-key-" + "y" * 32, max_bytes=2048, timeout_seconds=60)
    second = runtime_descriptor(second_config)
    assert first["runtime_digest"] == second["runtime_digest"] and first["model_digest"] == second["model_digest"]
    assert first["max_bytes"] != second["max_bytes"] and first["timeout_seconds"] != second["timeout_seconds"]
