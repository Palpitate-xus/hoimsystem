"""Immutable packaging and isolation checks; base tests never import torch.

An explicitly enabled optional smoke uses real public weights with synthetic
224-square gradient pixels. It establishes no clinical or DICOM validation.
"""

import hashlib
import io
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.ai import imaging_model, imaging_network
from scripts import convert_imaging_weights, prepare_local_imaging


@pytest.fixture
def release(tmp_path, monkeypatch):
    contents = {
        "model.safetensors": b"synthetic bytes, never used as classifier weights",
        "config.json": b'{"test":"synthetic config"}\n',
        "README.md": b"synthetic research model card\n",
        "upstream-LICENSE.txt": b"synthetic upstream license declaration\n",
        "LICENSE": b"synthetic complete license fixture\n",
        "NOTICE": b"synthetic local attribution fixture\n",
    }
    files = {name: (len(raw), hashlib.sha256(raw).hexdigest()) for name, raw in contents.items()}
    monkeypatch.setattr(imaging_model, "RELEASE_FILES", files)
    monkeypatch.setattr(prepare_local_imaging, "RELEASE_FILES", files)
    source = tmp_path / "prepared-release"
    source.mkdir()
    for name, raw in contents.items():
        (source / name).write_bytes(raw)
    imaging_model.create_manifest(source)
    return source, contents


def test_optional_modules_and_host_conversion_guard_do_not_import_torch():
    code = """
import sys
from app.ai import imaging_model, imaging_network
from scripts import prepare_local_imaging, convert_imaging_weights
assert 'torch' not in sys.modules and 'safetensors' not in sys.modules
try:
    convert_imaging_weights.convert('/does-not-exist', '/does-not-exist')
except ValueError as exc:
    assert 'container' in str(exc) or 'capabilities' in str(exc) or 'network' in str(exc)
else:
    raise AssertionError('host conversion must be rejected')
assert 'torch' not in sys.modules and 'safetensors' not in sys.modules
print('optional imports and host guard passed')
"""
    result = subprocess.run([sys.executable, "-c", code], cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, check=True)
    assert "host guard passed" in result.stdout


def test_offline_copy_preserves_bytes_and_identity_without_network_or_docker(release, tmp_path, monkeypatch):
    source, contents = release

    def forbidden(*args, **kwargs):
        raise AssertionError("verified prepared bundles need neither network nor Docker")

    monkeypatch.setattr(prepare_local_imaging.urllib.request, "urlopen", forbidden)
    monkeypatch.setattr(prepare_local_imaging.subprocess, "run", forbidden)
    first, second = tmp_path / "first", tmp_path / "elsewhere" / "second"
    one = prepare_local_imaging.prepare_model(first, source=source)
    two = prepare_local_imaging.prepare_model(second, source=source)
    assert one["model_digest"] == two["model_digest"] == imaging_model.verify_model(first).digest
    assert imaging_model.verify_model(second).digest == one["model_digest"]
    assert {p.name for p in first.iterdir()} == set(contents) | {imaging_model.MANIFEST_NAME}
    assert all((first / name).read_bytes() == (second / name).read_bytes() == raw for name, raw in contents.items())
    manifest = imaging_model.verify_model(first).model_dump()
    assert str(first) not in json.dumps(manifest) and manifest["tensor_count"] == 727
    assert not list(tmp_path.rglob(".imaging-model-*"))


@pytest.mark.parametrize("change", ["repository", "revision", "mutable_revision", "ambiguous_source", "missing_image"])
def test_preflight_rejects_unreviewed_or_ambiguous_input_before_io(change, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("invalid preparation identity must fail before I/O")

    monkeypatch.setattr(prepare_local_imaging, "Path", forbidden)
    options = {"source": "synthetic-existing-bundle"}
    if change == "repository":
        options["repository"] = "unreviewed/model"
    elif change in {"revision", "mutable_revision"}:
        options["revision"] = "0" * 40 if change == "revision" else "main"
    elif change == "ambiguous_source":
        options["image"] = "unreviewed-local-image"
    else:
        options = {}
    with pytest.raises(ValueError):
        prepare_local_imaging.prepare_model("must-not-be-created", **options)


@pytest.mark.parametrize(
    "change", ["weights", "missing", "extra_code", "weight_symlink", "manifest_symlink", "directory_symlink", "manifest_hash", "manifest_revision", "manifest_schema", "manifest_oversize", "fifo"]
)
def test_runtime_rejects_mutated_incomplete_or_indirect_release(change, release, tmp_path):
    source, contents = release
    weight, manifest = source / "model.safetensors", source / imaging_model.MANIFEST_NAME
    if change == "weights":
        weight.write_bytes(b"x" * len(contents[weight.name]))
    elif change == "missing":
        (source / "NOTICE").unlink()
    elif change == "extra_code":
        (source / "model.py").write_text("raise RuntimeError('must never execute')\n")
    elif change in {"weight_symlink", "manifest_symlink"}:
        target = weight if change == "weight_symlink" else manifest
        outside = tmp_path / "external-file"
        outside.write_bytes(target.read_bytes())
        target.unlink()
        target.symlink_to(outside)
    elif change == "directory_symlink":
        alias = tmp_path / "alias"
        alias.symlink_to(source, target_is_directory=True)
        source = alias
    elif change in {"manifest_hash", "manifest_revision", "manifest_schema"}:
        document = json.loads(manifest.read_bytes())
        if change == "manifest_hash":
            document["files"]["model.safetensors"]["sha256"] = "0" * 64
        elif change == "manifest_revision":
            document["revision"] = "main"
        else:
            document["state_schema_sha256"] = "0" * 64
        manifest.write_text(json.dumps(document))
    elif change == "fifo":
        weight.unlink()
        os.mkfifo(weight)
    else:
        manifest.write_bytes(b" " * 16385)
    with pytest.raises(ValueError):
        imaging_model.verify_model(source)


def test_weight_bytes_are_reverified_after_directory_verification(release, monkeypatch):
    source, contents = release

    def changed_after_verification(directory):
        (directory / "model.safetensors").write_bytes(b"x" * len(contents["model.safetensors"]))

    monkeypatch.setattr(imaging_network, "verify_model", changed_after_verification)
    with pytest.raises(ValueError, match="实际字节"):
        imaging_network.load_network(source)


def test_existing_destination_and_source_are_preserved_on_failed_copy(release, tmp_path):
    source, _ = release
    existing = tmp_path / "existing"
    existing.mkdir()
    (existing / "keep").write_bytes(b"existing model version")
    with pytest.raises(ValueError, match="已存在"):
        prepare_local_imaging.prepare_model(existing, source=source)
    assert (existing / "keep").read_bytes() == b"existing model version"
    (source / "NOTICE").unlink()
    target = tmp_path / "failed"
    with pytest.raises(ValueError):
        prepare_local_imaging.prepare_model(target, source=source)
    assert not target.exists() and not list(tmp_path.glob(".imaging-model-*"))
    assert (source / "model.safetensors").is_file()


@pytest.mark.parametrize("failure", [None, "short", "oversize", "hash", "network"])
def test_public_downloads_use_exact_pinned_urls_and_bounded_hashes(failure, tmp_path, monkeypatch):
    contents = {"model.pt": b"synthetic public checkpoint", "models.py": b"never imported author source", "config.json": b"{}"}
    files = {name: (len(raw), hashlib.sha256(raw).hexdigest()) for name, raw in contents.items()}
    urls = {name: f"https://public.invalid/fixed-commit/{name}" for name in contents}
    monkeypatch.setattr(prepare_local_imaging, "REFERENCE_FILES", files)
    monkeypatch.setattr(prepare_local_imaging, "REFERENCE_URLS", urls)
    seen = []

    def download(url, *, timeout):
        assert timeout == 30
        name = url.rsplit("/", 1)[-1]
        assert url == urls[name]
        seen.append(url)
        raw = contents[name]
        if name == "config.json":
            if failure == "network":
                raise OSError("isolated download failure")
            if failure == "short":
                raw = raw[:-1]
            elif failure == "oversize":
                raw += b"extra"
            elif failure == "hash":
                raw = b"x" * len(raw)
        return io.BytesIO(raw)

    monkeypatch.setattr(prepare_local_imaging.urllib.request, "urlopen", download)
    if failure is None:
        prepare_local_imaging.download_reference(tmp_path)
        assert all((tmp_path / name).read_bytes() == raw for name, raw in contents.items())
    else:
        with pytest.raises((ValueError, OSError)):
            prepare_local_imaging.download_reference(tmp_path)
    assert seen == list(urls.values())
    assert all(imaging_model.REVISION in url or imaging_model.CODE_REVISION in url for url in imaging_model.REFERENCE_URLS.values())


@pytest.mark.parametrize("failure", [None, "conversion", "timeout"])
def test_converter_uses_local_image_digest_public_mounts_and_owned_container_cleanup(failure, tmp_path, monkeypatch):
    reference, output = tmp_path / "reference", tmp_path / "converted"
    reference.mkdir()
    calls = []
    image_id = "sha256:" + "a" * 64

    def run(command, **options):
        calls.append((command, options))
        if command[:3] == ["docker", "image", "inspect"]:
            return SimpleNamespace(stdout=image_id + "\n")
        if command[:2] == ["docker", "run"]:
            if failure == "conversion":
                raise subprocess.CalledProcessError(1, command, stderr="synthetic converter failure")
            if failure == "timeout":
                raise subprocess.TimeoutExpired(command, 180)
            (output / "model.safetensors").write_bytes(b"synthetic output, never inferred")
        return SimpleNamespace(stdout="")

    monkeypatch.setattr(prepare_local_imaging.subprocess, "run", run)
    if failure:
        with pytest.raises(subprocess.SubprocessError):
            prepare_local_imaging.run_isolated_conversion(reference, output, "local-public-cpu:reviewed")
    else:
        assert prepare_local_imaging.run_isolated_conversion(reference, output, "local-public-cpu:reviewed") == image_id
    command = calls[1][0]
    pairs = {command[i]: command[i + 1] for i in range(2, len(command) - 1) if command[i].startswith("--") and command[i] not in {"--rm", "--read-only"}}
    assert pairs["--pull"] == "never" and pairs["--network"] == "none" and "--read-only" in command
    assert pairs["--cap-drop"] == "ALL" and pairs["--security-opt"] == "no-new-privileges"
    assert pairs["--user"] == "10001:10001" and pairs["--entrypoint"] == "python" and pairs["--ipc"] == "none"
    assert pairs["--memory"] == "2g" and pairs["--cpus"] == "4" and pairs["--pids-limit"] == "128"
    mounts = [command[i + 1] for i, token in enumerate(command) if token == "--mount"]
    assert mounts == [f"type=bind,source={reference},target=/reference,readonly", f"type=bind,source={output},target=/output"]
    assert "--env" not in command and "--env-file" not in command and command[-2] == image_id
    name = command[command.index("--name") + 1]
    assert name.startswith("hoim-public-imaging-convert-")
    assert calls[-1][0] == ["docker", "rm", "-f", name]
    assert calls[1][1]["timeout"] == 180 and (reference / "convert_imaging_weights.py").is_file()


def test_static_checkpoint_scanner_rejects_an_unreviewed_global_without_loading_it(tmp_path):
    # Five protocol-2 pickle streams; this only exercises the static scanner.
    safe_stream = b"\x80\x02N."
    globals_stream = (
        b"\x80\x02" + b"".join(b"c" + name.rsplit(".", 1)[0].encode() + b"\n" + name.rsplit(".", 1)[1].encode() + b"\n0" for name in sorted(convert_imaging_weights.ALLOWED_GLOBALS)) + b"N."
    )
    path = tmp_path / "synthetic-pickle-streams"
    path.write_bytes(safe_stream * 4 + globals_stream)
    assert convert_imaging_weights.scan_checkpoint(path) == convert_imaging_weights.ALLOWED_GLOBALS
    path.write_bytes(safe_stream * 4 + globals_stream[:-2] + b"cposix\nsystem\n0N.")
    with pytest.raises(ValueError, match="allowlist"):
        convert_imaging_weights.scan_checkpoint(path)


@pytest.mark.parametrize("threads", [0, 65, True, 4.0])
def test_invalid_cpu_thread_configuration_is_rejected_before_model_loading(threads):
    with pytest.raises(ValueError, match="线程"):
        imaging_network.load_network("does-not-exist", cpu_threads=threads)


def test_real_public_weights_synthetic_cpu_forward_only_when_explicitly_requested():
    directory = os.environ.get("HOIM_IMAGING_REAL_MODEL")
    if not directory:
        pytest.skip("set HOIM_IMAGING_REAL_MODEL to a prepared fixed public model; synthetic smoke only")
    import torch

    manifest = imaging_model.verify_model(directory)
    assert manifest.tensor_count == 727
    model = imaging_network.load_network(directory)
    tensor = torch.linspace(-1024, 1024, 224 * 224).reshape(1, 1, 224, 224)
    original = tensor.clone()
    scores = imaging_network.predict_scores(model, tensor)
    expected_logits = torch.tensor(
        [
            -0.5669277906417847,
            -2.077188730239868,
            -1.4341439008712769,
            -6.572443962097168,
            -2.101085662841797,
            -7.190979957580566,
            -7.114877700805664,
            -0.8063413500785828,
            -1.073768138885498,
            -4.628533840179443,
            -1.2956277132034302,
            -4.524535655975342,
            -4.743393421173096,
            -5.731822490692139,
            -2.8428945541381836,
            -3.430032253265381,
            0.013106480240821838,
            -2.4684672355651855,
        ]
    )
    assert len(scores) == 18 and all(type(score) is float and 0 <= score <= 1 for score in scores)
    torch.testing.assert_close(torch.tensor(scores), torch.sigmoid(expected_logits), rtol=1e-5, atol=1e-6)
    assert torch.equal(tensor, original)
    assert imaging_model.LABELS[0] == "Atelectasis" and imaging_model.LABELS[-1] == "Enlarged Cardiomediastinum"
    for invalid in (tensor.double(), tensor[0], torch.full_like(tensor, float("nan")), tensor * 2):
        with pytest.raises(ValueError):
            imaging_network.predict_scores(model, invalid)
