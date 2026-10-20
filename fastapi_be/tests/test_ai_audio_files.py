"""Actual native audio parsing and private byte provenance, without a speech service."""

import hashlib
import io
import subprocess
import uuid
import wave
from pathlib import Path
from types import SimpleNamespace

import pytest
from alembic.config import Config
from fastapi import HTTPException, UploadFile
from sqlalchemy import create_engine, inspect, text

from alembic import command
from app.ai.audio_files import audio_path, open_verified_audio, stage_audio
from app.config import settings


@pytest.fixture
def audio_store(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "AI_AUDIO_STORAGE_DIR", str(tmp_path / "private"))
    return tmp_path / "private"


@pytest.fixture(scope="module")
def recordings(tmp_path_factory):
    directory = tmp_path_factory.mktemp("audio-fixtures")
    raw = io.BytesIO()
    with wave.open(raw, "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(8000)
        writer.writeframes(b"\0" * 4000)
    wav = directory / "generated.wav"
    wav.write_bytes(raw.getvalue())
    values = {".wav": raw.getvalue()}
    for extension, codec in ((".mp3", "libmp3lame"), (".m4a", "aac"), (".ogg", "libopus"), (".webm", "libopus")):
        target = directory / ("generated" + extension)
        subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-i", str(wav), "-c:a", codec, str(target)], check=True, capture_output=True, timeout=10)
        values[extension] = target.read_bytes()
    values[".oga"] = values[".ogg"]
    # Browser MediaRecorder commonly produces a nonseekable WebM without a duration field.
    values["streaming-webm"] = subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-i", str(wav), "-c:a", "libopus", "-f", "webm", "pipe:1"], check=True, capture_output=True, timeout=10).stdout
    return values


@pytest.mark.parametrize("extension", [".wav", ".mp3", ".m4a", ".ogg", ".oga", ".webm", "streaming-webm"])
def test_real_supported_audio_and_browser_webm_are_decoded_without_retaining_filename(extension, audio_store, recordings):
    suffix = ".webm" if extension == "streaming-webm" else extension
    upload = UploadFile(filename="姓名手机号-不应保留" + suffix, file=io.BytesIO(recordings[extension]))
    path, metadata = stage_audio(upload)
    assert path.parent == audio_store and "姓名" not in path.name
    assert metadata["byte_size"] == len(recordings[extension]) and metadata["content_hash"] == hashlib.sha256(recordings[extension]).hexdigest()
    assert 100 <= metadata["duration_ms"] <= 500 and metadata["sample_rate"] >= 8000 and metadata["channels"] == 1
    assert path.stat().st_mode & 0o777 == 0o600 and audio_store.stat().st_mode & 0o777 == 0o700
    assert path.read_bytes() == recordings[extension]


@pytest.mark.parametrize("filename,payload", [("remote.m3u8", b"#EXTM3U\nhttps://example.com/private"), ("fake.wav", b"RIFF\0\0\0\0WAVEgarbage"), ("renamed.wav", b"OggSfake"), ("empty.mp3", b"")])
def test_playlists_mismatched_or_invalid_files_are_rejected_and_staging_is_cleaned(filename, payload, audio_store):
    with pytest.raises(HTTPException) as error:
        stage_audio(UploadFile(filename=filename, file=io.BytesIO(payload)))
    assert error.value.status_code == 422
    assert not audio_store.exists() or list(audio_store.iterdir()) == []


def test_size_and_actual_decoded_duration_limits_clean_failed_uploads(audio_store, recordings, monkeypatch):
    monkeypatch.setattr(settings, "AI_AUDIO_MAX_BYTES", 1024)
    with pytest.raises(HTTPException) as error:
        stage_audio(UploadFile(filename="large.wav", file=io.BytesIO(recordings[".wav"])))
    assert error.value.status_code == 413 and list(audio_store.iterdir()) == []
    monkeypatch.setattr(settings, "AI_AUDIO_MAX_BYTES", 1024 * 1024)
    monkeypatch.setattr(settings, "AI_AUDIO_MAX_DURATION_SECONDS", 1)
    raw = io.BytesIO()
    with wave.open(raw, "wb") as writer:
        writer.setparams((1, 2, 8000, 16000, "NONE", "not compressed"))
        writer.writeframes(b"\0" * 32000)
    with pytest.raises(HTTPException) as error:
        stage_audio(UploadFile(filename="too-long.wav", file=io.BytesIO(raw.getvalue())))
    assert error.value.status_code == 422 and list(audio_store.iterdir()) == []


def test_verified_handle_rejects_same_size_changes_missing_files_and_symlinks(audio_store, recordings, tmp_path):
    staged, metadata = stage_audio(UploadFile(filename="test.wav", file=io.BytesIO(recordings[".wav"])))
    asset = SimpleNamespace(asset_id=str(uuid.uuid4()), **metadata)
    path = audio_path(asset.asset_id)
    staged.rename(path)
    with open_verified_audio(asset) as handle:
        assert handle.read() == recordings[".wav"]
    path.write_bytes(recordings[".wav"][:-1] + b"x")
    with pytest.raises(HTTPException) as error:
        open_verified_audio(asset)
    assert error.value.status_code == 409
    path.unlink()
    outside = tmp_path / "outside.wav"
    outside.write_bytes(recordings[".wav"])
    path.symlink_to(outside)
    with pytest.raises(HTTPException) as error:
        open_verified_audio(asset)
    assert error.value.status_code == 409
    path.unlink()
    with pytest.raises(HTTPException) as error:
        open_verified_audio(asset)
    assert error.value.status_code == 409


@pytest.mark.parametrize("reference", ["../secret", "/tmp/file", "0" * 36, "", str(uuid.uuid4()).upper()])
def test_disk_path_uses_only_canonical_server_identifiers(reference, audio_store):
    with pytest.raises(HTTPException) as error:
        audio_path(reference)
    assert error.value.status_code == 422


def test_audio_migration_roundtrip_preserves_existing_patient_rows(tmp_path):
    database = tmp_path / "audio-migration.db"
    engine = create_engine("sqlite:///" + str(database))
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE hoimsystem_patient (patient_id INTEGER PRIMARY KEY, name TEXT)")
        connection.exec_driver_sql("CREATE TABLE hoimsystem_users (user_id INTEGER PRIMARY KEY)")
        connection.exec_driver_sql("INSERT INTO hoimsystem_patient VALUES (1, '原患者资料')")
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", "sqlite:///" + str(database))
    command.stamp(config, "20261020_pathway_revision")
    command.upgrade(config, "20261020_ai_audio_assets")
    assert "hoimsystem_ai_audio_asset" in inspect(engine).get_table_names()
    assert {row["name"] for row in inspect(engine).get_indexes("hoimsystem_ai_audio_asset")} == {"idx_ai_audio_patient_owner", "idx_ai_audio_status"}
    command.downgrade(config, "20261020_pathway_revision")
    assert "hoimsystem_ai_audio_asset" not in inspect(engine).get_table_names()
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT name FROM hoimsystem_patient")) == "原患者资料"
    engine.dispose()
