"""Local fixture bytes test immutable packaging, not speech model quality."""

import json

import pytest

from app.ai.speech_model import MANIFEST_NAME, create_manifest, verify_model
from scripts.prepare_speech_model import prepare_model


@pytest.fixture
def model_files(tmp_path):
    directory = tmp_path / "source"
    directory.mkdir()
    for name in ("config.json", "model.bin", "tokenizer.json", "vocabulary.txt"):
        (directory / name).write_bytes(("fixture-not-weights:" + name).encode())
    return directory


def test_manifest_is_destination_independent_and_preserves_original_snapshot(model_files, tmp_path):
    first = prepare_model("example/model", "a" * 40, tmp_path / "first", source=model_files)
    second = prepare_model("example/model", "a" * 40, tmp_path / "second", source=model_files)
    assert first["model_digest"] == second["model_digest"]
    assert verify_model(tmp_path / "first").digest == first["model_digest"]
    assert not list(tmp_path.glob(".speech-model-*"))
    with pytest.raises(ValueError, match="已存在"):
        prepare_model("example/model", "a" * 40, tmp_path / "first", source=model_files)


@pytest.mark.parametrize("change", ["bytes", "missing", "extra", "symlink", "manifest_path"])
def test_modified_runtime_files_cannot_keep_original_identity(change, model_files, tmp_path):
    create_manifest(model_files, "example/model", "a" * 40)
    if change == "bytes":
        path = model_files / "model.bin"
        path.write_bytes(b"x" * path.stat().st_size)
    elif change == "missing":
        (model_files / "tokenizer.json").unlink()
    elif change == "extra":
        (model_files / "vocabulary.json").write_text("{}")
    elif change == "symlink":
        path = model_files / "model.bin"
        path.rename(tmp_path / "outside")
        path.symlink_to(tmp_path / "outside")
    else:
        body = json.loads((model_files / MANIFEST_NAME).read_text())
        body["files"]["../outside"] = body["files"]["model.bin"]
        (model_files / MANIFEST_NAME).write_text(json.dumps(body))
    with pytest.raises(ValueError):
        verify_model(model_files)


def test_mutable_revision_or_incomplete_snapshot_never_publishes_directory(model_files, tmp_path):
    with pytest.raises(ValueError, match="40位"):
        prepare_model("example/model", "main", tmp_path / "output", source=model_files)
    assert not (tmp_path / "output").exists()
    (model_files / "tokenizer.json").unlink()
    with pytest.raises(ValueError):
        prepare_model("example/model", "b" * 40, tmp_path / "output", source=model_files)
    assert not (tmp_path / "output").exists() and not list(tmp_path.glob(".speech-model-*"))
