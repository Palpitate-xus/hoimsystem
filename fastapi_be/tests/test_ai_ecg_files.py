"""Synthetic WFDB bytes test calibration/integrity; no disease or model accuracy claims."""

import hashlib
import io
import shutil
import struct
import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException, UploadFile

from app.ai.ecg_files import ecg_directory, inspect_signal, open_verified_ecg, parse_header, signal_window, stage_ecg
from app.config import settings


def wfdb_bytes(rows=None, *, rate="500", names=("I", "II"), gain="1000", baseline=10, unit="mV", format_code="16"):
    rows = rows if rows is not None else [(1010, -990), (2010, -32768), (-32768, 1010), (-990, 10)]
    data = struct.pack("<" + "h" * sum(len(row) for row in rows), *(item for row in rows for item in row))
    lines = [f"fixture {len(names)} {rate} {len(rows)}"]
    for channel, name in enumerate(names):
        checksum = sum(row[channel] for row in rows) & 0xFFFF
        checksum = checksum - 65536 if checksum >= 32768 else checksum
        lines.append(f"fixture.dat {format_code} {gain}({baseline})/{unit} 16 0 {rows[0][channel]} {checksum} 0 {name}")
    lines.append("# 原文件可能有姓名、联系电话13812345678等，不进入模型元数据")
    return ("\n".join(lines) + "\n").encode(), data


def uploads(header, signal):
    return UploadFile(filename="fixture.hea", file=io.BytesIO(header)), UploadFile(filename="fixture.dat", file=io.BytesIO(signal))


@pytest.fixture(autouse=True)
def private_root(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "AI_ECG_STORAGE_DIR", str(tmp_path / "private"))


def test_real_bytes_preserve_calibration_order_missing_values_and_private_originals():
    header, raw = wfdb_bytes()
    directory, data = stage_ecg(*uploads(header, raw))
    assert (directory / "source.hea").read_bytes() == header and (directory / "source.dat").read_bytes() == raw
    assert directory.stat().st_mode & 0o777 == 0o700
    assert (directory / "source.dat").stat().st_mode & 0o777 == 0o600
    assert data["signal_hash"] == hashlib.sha256(raw).hexdigest()
    assert [lead["name"] for lead in data["metadata"]["leads"]] == ["I", "II"]
    assert [lead["missing_samples"] for lead in data["metadata"]["leads"]] == [1, 1]
    assert all(lead["checksum_matches"] for lead in data["metadata"]["leads"])
    assert "13812345678" not in str(data) and "fixture" not in str(data)
    with (directory / "source.dat").open("rb") as stream:
        window = signal_window(stream, data["metadata"], 0, 4, 50)
    first = window["leads"][0]["points"]
    assert [point["sample"] for point in first] == [0, 1, 2, 3]
    assert [point["value_mv"] for point in first] == [1.0, 2.0, None, -1.0]
    assert window["decimated"] is False and window["end_sample_exclusive"] == 4
    shutil.rmtree(directory)


@pytest.mark.parametrize("unit,gain,expected", [("uV", "1", 1.0), ("µV", "1", 1.0), ("μV", "1", 1.0), ("mV", "1000", 1.0), ("V", "1000000", 1.0)])
def test_explicit_physical_units_are_converted_to_mv_without_guessing(unit, gain, expected):
    header, raw = wfdb_bytes(rows=[(1010,)], names=("II",), gain=gain, unit=unit)
    directory, data = stage_ecg(*uploads(header, raw))
    with (directory / "source.dat").open("rb") as stream:
        result = signal_window(stream, data["metadata"], 0, 1, 50)
    assert result["leads"][0]["points"][0]["value_mv"] == pytest.approx(expected)
    shutil.rmtree(directory)


@pytest.mark.parametrize("format_code", ["16", "16x1", "16:0", "16+0", "16x1:0+0", "16x1+0"])
def test_zero_modifiers_keep_interleaved_little_endian_samples(format_code):
    header, raw = wfdb_bytes(format_code=format_code)
    directory, data = stage_ecg(*uploads(header, raw))
    assert data["metadata"]["sample_count"] == 4
    shutil.rmtree(directory)


@pytest.mark.parametrize(
    "variant",
    [
        "length",
        "checksum",
        "unknown_lead",
        "duplicate_lead",
        "unit",
        "gain",
        "missing_gain",
        "skew",
        "offset",
        "frequency_multiplier",
        "packed212",
        "remote_file",
        "traversal",
        "multiple_files",
        "multi_segment",
        "frequency_default",
        "sample_count_default",
        "trailing_line",
        "wrong_pair",
    ],
)
def test_unsupported_or_inconsistent_inputs_are_rejected_and_stage_is_cleaned(variant):
    header, raw = wfdb_bytes()
    text = header.decode()
    if variant == "length":
        raw += b"\0\0"
    elif variant == "checksum":
        raw = struct.pack("<h", 1011) + raw[2:]
    elif variant == "unknown_lead":
        text = text.replace(" 0 I\n", " 0 unknown\n")
    elif variant == "duplicate_lead":
        text = text.replace(" 0 II\n", " 0 I\n")
    elif variant == "unit":
        text = text.replace("/mV", "/unknown")
    elif variant == "gain":
        text = text.replace("1000(10)", "0(10)")
    elif variant == "missing_gain":
        text = text.replace("1000(10)/mV", "1000")
    elif variant in {"skew", "offset", "frequency_multiplier", "packed212"}:
        text = text.replace(".dat 16 ", ".dat " + {"skew": "16:1", "offset": "16+1", "frequency_multiplier": "16x2", "packed212": "212"}[variant] + " ")
    elif variant in {"remote_file", "traversal"}:
        text = text.replace("fixture.dat", "https://unapproved.invalid/fixture.dat" if variant == "remote_file" else "../fixture.dat")
    elif variant == "multiple_files":
        text = text.replace("fixture.dat", "another.dat", 1)
    elif variant == "multi_segment":
        text = text.replace("fixture 2 ", "fixture/2 2 ")
    elif variant == "frequency_default":
        text = text.replace("fixture 2 500 4", "fixture 2")
    elif variant == "sample_count_default":
        text = text.replace("fixture 2 500 4", "fixture 2 500 0")
    elif variant == "trailing_line":
        text += "not a comment\n"
    else:
        pass
    header_file, signal_file = uploads(text.encode(), raw)
    if variant == "wrong_pair":
        signal_file.filename = "other.dat"
    with pytest.raises(HTTPException) as exc:
        stage_ecg(header_file, signal_file)
    assert exc.value.status_code in {413, 422}
    from app.ai.ecg_files import ecg_root

    assert not list(ecg_root().iterdir())


def test_ceil_duration_does_not_truncate_the_original_sample_count():
    header, _ = wfdb_bytes(rows=[(10,), (11,)], names=("II",), rate="62.5")
    metadata = parse_header(header, "fixture.hea", "fixture.dat")
    assert metadata["duration_ms"] == 32 and metadata["sample_rate_hz"] == "62.5" and metadata["sample_count"] == 2


def test_size_and_duration_limits_reject_instead_of_shortening_native_signal(monkeypatch):
    header, raw = wfdb_bytes(rows=[(10,)] * 501, names=("II",))
    monkeypatch.setattr(settings, "AI_ECG_MAX_DURATION_SECONDS", 1)
    with pytest.raises(HTTPException) as exc:
        stage_ecg(*uploads(header, raw))
    assert exc.value.status_code == 413


def test_zero_checksum_is_checked_for_records_with_an_explicit_sample_count():
    header, raw = wfdb_bytes(rows=[(0,), (0,)], names=("II",), baseline=0)
    directory, data = stage_ecg(*uploads(header, raw))
    assert data["metadata"]["leads"][0]["declared_checksum"] == 0
    (directory / "source.dat").write_bytes(struct.pack("<hh", 0, 1))
    with pytest.raises(HTTPException, match="校验和"):
        inspect_signal(directory / "source.dat", data["metadata"])
    shutil.rmtree(directory)


def test_missing_is_not_zero_and_constant_observation_is_unknown_when_all_samples_are_missing():
    header, raw = wfdb_bytes(rows=[(-32768,)] * 3, names=("II",))
    directory, data = stage_ecg(*uploads(header, raw))
    lead = data["metadata"]["leads"][0]
    assert lead["minimum_adc"] is None and lead["maximum_adc"] is None and lead["constant_observed_values"] is None
    with (directory / "source.dat").open("rb") as stream:
        window = signal_window(stream, data["metadata"], 0, 3, 50)
    assert all(point["value_mv"] is None for point in window["leads"][0]["points"])
    shutil.rmtree(directory)


def test_overview_preserves_spikes_and_never_connects_over_omitted_missing_samples():
    rows = [(10,)] * 2000
    rows[44] = (20010,)
    rows[1500] = (-20000,)
    rows[45], rows[47] = (-32768,), (-32768,)
    header, raw = wfdb_bytes(rows=rows, names=("II",))
    directory, data = stage_ecg(*uploads(header, raw))
    with (directory / "source.dat").open("rb") as stream:
        overview = signal_window(stream, data["metadata"], 0, 2000, 50)
        full = signal_window(stream, data["metadata"], 30, 30, 50)
    points = overview["leads"][0]["points"]
    assert overview["decimated"] is True and len(points) <= 50
    assert any(point["sample"] == 44 and point["value_mv"] == 20 for point in points)
    assert any(point["sample"] == 1500 and point["value_mv"] == pytest.approx(-20.01) for point in points)
    for previous, current in zip(points, points[1:]):
        if any(rows[index][0] == -32768 for index in range(previous["sample"] + 1, current["sample"] + 1)):
            assert current["break_before"]
    assert full["decimated"] is False and len(full["leads"][0]["points"]) == 30
    shutil.rmtree(directory)


@pytest.mark.parametrize("variant", ["bytes", "header", "symlink_file", "symlink_directory"])
def test_verified_handles_refuse_changed_bytes_and_links(variant, tmp_path):
    header, raw = wfdb_bytes()
    staged, data = stage_ecg(*uploads(header, raw))
    asset = SimpleNamespace(asset_id=str(uuid.uuid4()), **{key: value for key, value in data.items() if key != "metadata"})
    destination = ecg_directory(asset.asset_id)
    staged.rename(destination)
    with_handles = open_verified_ecg(asset)
    assert with_handles[1].read() == raw
    for stream in with_handles:
        stream.close()
    if variant == "bytes":
        (destination / "source.dat").write_bytes(b"x" * len(raw))
    elif variant == "header":
        (destination / "source.hea").write_bytes(b"x" * len(header))
    elif variant == "symlink_file":
        path = destination / "source.dat"
        path.rename(tmp_path / "outside.dat")
        path.symlink_to(tmp_path / "outside.dat")
    else:
        destination.rename(tmp_path / "outside")
        destination.symlink_to(tmp_path / "outside", target_is_directory=True)
    with pytest.raises(HTTPException) as exc:
        open_verified_ecg(asset)
    assert exc.value.status_code == 409
