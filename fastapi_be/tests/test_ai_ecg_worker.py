"""Independent native-calibration checks use synthetic ECG, not diagnostic labels or torch."""

import copy
from decimal import Decimal

import pytest

from app.ai.ecg_model import LEADS
from app.ai.ecg_worker import decode_native
from tests.test_ai_ecg_server import bind_source, native_case

np = pytest.importorskip("numpy")


def test_native_decode_preserves_little_endian_samples_and_calibrates_original_reordered_leads(tmp_path):
    raw, source = native_case(reordered=True)
    path = tmp_path / "signal.dat"
    path.write_bytes(raw)
    frozen_source = copy.deepcopy(source)
    actual = decode_native(path, source)
    expected = []
    by_name = {lead["name"]: (index, lead) for index, lead in enumerate(source["signal_metadata"]["leads"])}
    unit_scale = {"mV": Decimal(1), "uV": Decimal("0.001"), "V": Decimal(1000)}
    for name in LEADS:
        channel, lead = by_name[name]
        calibrated = []
        for sample in range(1000):
            start = (sample * 12 + channel) * 2
            adc = int.from_bytes(raw[start : start + 2], byteorder="little", signed=True)
            calibrated.append(float((Decimal(adc) - lead["baseline"]) / Decimal(lead["gain"]) * unit_scale[lead["unit"]]))
        expected.append(calibrated)
    assert actual.shape == (12, 1000) and actual.dtype == np.float32
    np.testing.assert_array_equal(actual, np.asarray(expected, dtype=np.float32))
    assert source == frozen_source and path.read_bytes() == raw
    assert source["signal_metadata"]["leads"][0]["name"] != LEADS[0]
    assert not np.array_equal(actual[0], actual[1])


@pytest.mark.parametrize("unit", ["uV", "µV", "μV"])
def test_all_supported_microvolt_spellings_preserve_physical_scaling(unit, tmp_path):
    raw, source = native_case()
    path = tmp_path / "signal.dat"
    path.write_bytes(raw)
    original = decode_native(path, source)
    # Lead II was registered as uV; changing only its spelling must preserve every sample.
    source["signal_metadata"]["leads"][1]["unit"] = unit
    np.testing.assert_array_equal(decode_native(path, source), original)


def test_actual_missing_marker_is_rejected_even_when_metadata_claims_no_missing_and_hash_is_correct(tmp_path):
    raw, source = native_case()
    changed = bytearray(raw)
    position = (999 * 12 + 11) * 2
    changed[position : position + 2] = (-32768).to_bytes(2, byteorder="little", signed=True)
    source = bind_source(changed, source)
    assert all(lead["missing_samples"] == 0 for lead in source["signal_metadata"]["leads"])
    path = tmp_path / "signal.dat"
    path.write_bytes(changed)
    with pytest.raises(ValueError, match="实际含缺失"):
        decode_native(path, source)


@pytest.mark.parametrize(
    "change",
    [
        "hash",
        "short",
        "long",
        "source_id",
        "asset_id",
        "combined_hash",
        "fractional_rate",
        "other_rate",
        "sample_count",
        "duration",
        "MLII",
        "duplicate_lead",
        "missing_lead",
        "missing_declared",
        "zero_gain",
        "nan_gain",
        "infinite_gain",
        "wrong_unit",
    ],
)
def test_native_decode_rejects_changed_bytes_identity_calibration_or_unsupported_scope(change, tmp_path):
    raw, source = native_case()
    metadata = source["signal_metadata"]
    if change == "hash":
        raw = b"x" * len(raw)
    elif change == "short":
        raw = raw[:-1]
    elif change == "long":
        raw += b"\0\0"
    elif change == "source_id":
        source["source_id"] = "ecg:other:forged"
    elif change == "asset_id":
        source["asset_id"] = "not-a-canonical-waveform-identifier!!!"
    elif change == "combined_hash":
        source["content_hash"] = "0" * 64
        source["source_id"] = f"ecg:{source['asset_id']}:{source['content_hash'][:12]}"
    elif change in {"fractional_rate", "other_rate"}:
        metadata["sample_rate_hz"] = "100.000001" if change == "fractional_rate" else "500"
    elif change == "sample_count":
        metadata["sample_count"] = 2000
    elif change == "duration":
        metadata["duration_ms"] = 10001
    elif change == "MLII":
        metadata["leads"][1]["name"] = "MLII"
    elif change == "duplicate_lead":
        metadata["leads"][1]["name"] = metadata["leads"][0]["name"]
    elif change == "missing_lead":
        metadata["leads"].pop()
    elif change == "missing_declared":
        metadata["leads"][0]["missing_samples"] = 1
    elif change in {"zero_gain", "nan_gain", "infinite_gain"}:
        metadata["leads"][0]["gain"] = {"zero_gain": "0", "nan_gain": "NaN", "infinite_gain": "Infinity"}[change]
    else:
        metadata["leads"][0]["unit"] = "unknown"
    path = tmp_path / "signal.dat"
    path.write_bytes(raw)
    with pytest.raises(ValueError):
        decode_native(path, source)


def test_equivalent_explicit_decimal_frequency_is_accepted_without_resampling(tmp_path):
    raw, source = native_case()
    path = tmp_path / "signal.dat"
    path.write_bytes(raw)
    expected = decode_native(path, source)
    source["signal_metadata"]["sample_rate_hz"] = "1.00E+2"
    actual = decode_native(path, source)
    np.testing.assert_array_equal(actual, expected)
    assert source["signal_metadata"]["sample_rate_hz"] == "1.00E+2"
