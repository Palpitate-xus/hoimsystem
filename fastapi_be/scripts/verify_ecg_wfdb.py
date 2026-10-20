"""Compare the production decoder against official WFDB on synthetic calibration data."""

import hashlib
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
import wfdb

from app.ai.ecg_files import inspect_signal, parse_header, signal_window


def main():
    # Fixed digital values, including format-16 missing samples. These are not a clinical ECG.
    samples = np.array([[1000, 3000, 900], [0, -32768, -100], [-1000, -1000, -1100], [-32768, 1000, 1900], [2000, 5000, -32768], [0, 1000, -100]], dtype=np.int64)
    names, units = ["I", "II", "III"], ["mV", "uV", "V"]
    with tempfile.TemporaryDirectory(prefix="hoim-wfdb-oracle-") as directory:
        wfdb.wrsamp(
            "calibration_test",
            fs=500,
            units=units,
            sig_name=names,
            d_signal=samples,
            fmt=["16"] * 3,
            adc_gain=[1000, 2, 1000000],
            baseline=[0, 1000, -100],
            comments=["Synthetic calibration values only; no patient data or disease labels"],
            write_dir=directory,
        )
        base = Path(directory) / "calibration_test"
        header, data = base.with_suffix(".hea"), base.with_suffix(".dat")
        reference = wfdb.rdrecord(str(base), physical=True)
        metadata = inspect_signal(data, parse_header(header.read_bytes(), header.name, data.name))
        with data.open("rb") as stream:
            result = signal_window(stream, metadata, 0, len(samples), 50)
        expected = reference.p_signal * np.array([1, 0.001, 1000])
        observed = np.array([[lead["points"][index]["value_mv"] if lead["points"][index]["value_mv"] is not None else np.nan for lead in result["leads"]] for index in range(len(samples))])
        np.testing.assert_allclose(observed, expected, rtol=1e-12, atol=1e-12, equal_nan=True)
        assert [lead["name"] for lead in result["leads"]] == reference.sig_name == names
        assert float(metadata["sample_rate_hz"]) == reference.fs == 500
        assert metadata["sample_count"] == reference.sig_len == len(samples)
        print(
            json.dumps(
                {
                    "wfdb_version": wfdb.__version__,
                    "scope": "synthetic calibration/interoperability only, not model or diagnostic quality",
                    "lead_order": names,
                    "samples_per_lead": len(samples),
                    "fs_hz": reference.fs,
                    "missing_mask_matched": bool(np.array_equal(np.isnan(observed), np.isnan(expected))),
                    "maximum_absolute_error_mv": float(np.nanmax(np.abs(observed - expected))),
                    "header_hash": hashlib.sha256(header.read_bytes()).hexdigest(),
                    "signal_hash": hashlib.sha256(data.read_bytes()).hexdigest(),
                    "physical_unit": "mV",
                },
                ensure_ascii=False,
                indent=2,
            )
        )


if __name__ == "__main__":
    main()
