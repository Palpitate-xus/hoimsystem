"""Bounded WFDB amplitude decoding with explicit calibration and private original files.

Supported profile: one segment, one interleaved format-16 file, one sample/frame,
no skew/preamble, explicit frequency/sample count/calibration and ECG lead names.
No URLs, archives, device instructions or external filenames are opened.
"""

import hashlib
import json
import os
import re
import shutil
import stat
import sys
import tempfile
import uuid
from array import array
from decimal import ROUND_CEILING, Decimal, InvalidOperation, localcontext
from pathlib import Path

from fastapi import HTTPException

from app.config import settings

HEADER_MAX_BYTES = 65536
INVALID_SAMPLE = -32768
LEADS = ("I", "II", "III", "aVR", "aVL", "aVF", "V1", "V2", "V3", "V4", "V5", "V6", "MLII", "MCL1", "VX", "VY", "VZ")
CANONICAL_LEADS = {name.casefold(): name for name in LEADS}
UNITS_TO_MV = {"mV": Decimal("1"), "uV": Decimal("0.001"), "µV": Decimal("0.001"), "μV": Decimal("0.001"), "V": Decimal("1000")}
NUMBER = r"[+]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?"


def canonical_json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def ecg_root():
    from app.routers.upload import UPLOAD_DIR

    root = Path(settings.AI_ECG_STORAGE_DIR).expanduser().resolve()
    public = Path(UPLOAD_DIR).resolve()
    if root == public or public in root.parents:
        raise HTTPException(503, "心电原文件须位于通用上传目录之外")
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(root, 0o700)
    return root


def ecg_directory(asset_id):
    try:
        if str(uuid.UUID(asset_id)) != asset_id:
            raise ValueError()
    except (ValueError, TypeError, AttributeError) as exc:
        raise HTTPException(422, "心电原记录标识无效") from exc
    return ecg_root() / asset_id


def _positive_decimal(value):
    if len(value) > 40 or not re.fullmatch(NUMBER, value):
        raise ValueError("numeric field")
    number = Decimal(value)
    if not number.is_finite() or number <= 0 or not -12 <= number.adjusted() <= 12:
        raise ValueError("bounded calibration")
    return number


def parse_header(raw, header_name, signal_name):
    """Require declared data, not WFDB's optional defaults for unknown calibration."""
    try:
        if not raw or len(raw) > HEADER_MAX_BYTES:
            raise ValueError("header size")
        text = raw.decode("utf-8-sig")
        lines = text.splitlines()
        if any(len(line.encode()) > 254 or "\0" in line for line in lines):
            raise ValueError("header line")
        lines = [line.strip() for line in lines if line.strip() and not line.lstrip().startswith("#")]
        record = lines[0].split()
        if not 4 <= len(record) <= 6 or not re.fullmatch(r"[A-Za-z0-9_]{1,80}", record[0]):
            raise ValueError("single segment record")
        channels, sample_count = int(record[1]), int(record[3])
        rate = _positive_decimal(record[2])
        if not 1 <= channels <= 16 or not 50 <= rate <= 10000 or sample_count < 1 or len(lines) != channels + 1:
            raise ValueError("supported sampling profile")
        if sample_count * channels * 2 + len(raw) > settings.AI_ECG_MAX_BYTES or Decimal(sample_count) > rate * settings.AI_ECG_MAX_DURATION_SECONDS:
            raise HTTPException(413, "心电原记录超出当前大小或时长范围")

        # Original filenames are checked for pairing, then discarded from the metadata.
        def basename(value):
            return (value or "").replace("\\", "/").rsplit("/", 1)[-1]

        if basename(header_name) != record[0] + ".hea":
            raise ValueError("paired header filename")
        if len(record) >= 5 and not re.fullmatch(r"[0-9]{1,2}:[0-9]{1,2}:[0-9]{1,2}(?:\.[0-9]{1,6})?", record[4]):
            raise ValueError("header clock")
        if len(record) == 6 and not re.fullmatch(r"[0-9]{1,2}/[0-9]{1,2}/[0-9]{4}", record[5]):
            raise ValueError("header date")
        leads, file_name = [], None
        for line in lines[1:]:
            fields = line.split(maxsplit=8)
            if len(fields) != 9 or not re.fullmatch(r"[A-Za-z0-9_]{1,80}\.dat", fields[0]) or not re.fullmatch(r"16(?:x1)?(?::0)?(?:\+0)?", fields[1]):
                raise ValueError("one format16 file, no skew or preamble")
            if file_name is not None and fields[0] != file_name:
                raise ValueError("multiple signal files")
            file_name = fields[0]
            calibration = re.fullmatch(rf"({NUMBER})(?:\((-?[0-9]{{1,10}})\))?/(mV|uV|µV|μV|V)", fields[2])
            if not calibration:
                raise ValueError("explicit gain and unit")
            gain = _positive_decimal(calibration[1])
            resolution, adc_zero, initial, checksum, block = (int(item) for item in fields[3:8])
            baseline = int(calibration[2]) if calibration[2] is not None else adc_zero
            lead = CANONICAL_LEADS.get(fields[8].casefold())
            if not lead or any(item["name"] == lead for item in leads) or not 1 <= resolution <= 16 or block != 0 or not -32768 <= checksum <= 65535:
                raise ValueError("lead or ADC fields")
            if any(abs(value) > 2147483647 for value in (adc_zero, initial, baseline)):
                raise ValueError("ADC numeric bounds")
            leads.append(
                {
                    "name": lead,
                    "gain": str(gain),
                    "baseline": baseline,
                    "unit": calibration[3],
                    "adc_resolution_bits": resolution,
                    "adc_zero": adc_zero,
                    "declared_initial_value": initial,
                    "declared_checksum": checksum,
                }
            )
        if basename(signal_name) != file_name:
            raise ValueError("paired signal filename")
        with localcontext() as context:
            context.prec = 60
            duration = int((Decimal(sample_count) * 1000 / rate).to_integral_value(rounding=ROUND_CEILING))
        return {
            "format": "wfdb16",
            "sample_rate_hz": str(rate),
            "sample_count": sample_count,
            "channels": channels,
            "duration_ms": duration,
            "missing_sample_value": INVALID_SAMPLE,
            "leads": leads,
            "header_clock": " ".join(record[4:]) or None,
            "header_clock_timezone": "not_declared",
        }
    except HTTPException:
        raise
    except (ValueError, TypeError, IndexError, UnicodeError, InvalidOperation) as exc:
        raise HTTPException(422, "须提供同一WFDB记录的单文件16位小端波形及完整头文件，明确导联、采样率、样本数、增益/单位/基线和校验字段；不推测缺失元数据") from exc


def _samples(raw):
    values = array("h")
    values.frombytes(raw)
    if sys.byteorder != "little":
        values.byteswap()
    return values


def inspect_signal(path, metadata):
    channels, count = metadata["channels"], metadata["sample_count"]
    if path.stat().st_size != channels * count * 2:
        raise HTTPException(422, "原始采样字节数与头文件声明不一致，不截断或补齐样本")
    stats = [{"sum": 0, "missing_samples": 0, "minimum_adc": None, "maximum_adc": None, "observed_initial_value": None} for _ in range(channels)]
    with path.open("rb") as stream:
        while raw := stream.read(channels * 2 * 4096):
            values = _samples(raw)
            for channel, item in enumerate(stats):
                samples = values[channel::channels]
                if item["observed_initial_value"] is None:
                    item["observed_initial_value"] = samples[0]
                item["sum"] += sum(samples)
                item["missing_samples"] += samples.count(INVALID_SAMPLE)
                valid = [value for value in samples if value != INVALID_SAMPLE]
                if valid:
                    item["minimum_adc"] = min(min(valid), item["minimum_adc"]) if item["minimum_adc"] is not None else min(valid)
                    item["maximum_adc"] = max(max(valid), item["maximum_adc"]) if item["maximum_adc"] is not None else max(valid)
    for lead, item in zip(metadata["leads"], stats, strict=True):
        checksum = item.pop("sum") & 0xFFFF
        if checksum != lead["declared_checksum"] & 0xFFFF:
            raise HTTPException(422, "原波形与头文件校验和不一致，请重新核对原始文件")
        lead.update(item, checksum_matches=True, initial_value_matches=item["observed_initial_value"] == lead["declared_initial_value"])
        lead["constant_observed_values"] = item["minimum_adc"] == item["maximum_adc"] if item["minimum_adc"] is not None else None
    return metadata


def _copy_upload(upload, target, limit):
    size, digest = 0, hashlib.sha256()
    with target.open("xb") as output:
        os.chmod(target, 0o600)
        while block := upload.file.read(65536):
            size += len(block)
            if size > limit:
                raise HTTPException(413, "心电原文件超过当前大小限制")
            output.write(block)
            digest.update(block)
    if not size:
        raise HTTPException(422, "心电原文件为空")
    return size, digest.hexdigest()


def stage_ecg(header, signal):
    directory = Path(tempfile.mkdtemp(prefix=".stage-", dir=ecg_root()))
    try:
        header_size, header_hash = _copy_upload(header, directory / "source.hea", min(HEADER_MAX_BYTES, settings.AI_ECG_MAX_BYTES))
        metadata = parse_header((directory / "source.hea").read_bytes(), header.filename, signal.filename)
        signal_size, signal_hash = _copy_upload(signal, directory / "source.dat", settings.AI_ECG_MAX_BYTES - header_size)
        metadata = inspect_signal(directory / "source.dat", metadata)
        identity = {"format": "wfdb16", "header_hash": header_hash, "signal_hash": signal_hash}
        return directory, {
            "byte_size": header_size + signal_size,
            "header_byte_size": header_size,
            "signal_byte_size": signal_size,
            **identity,
            "content_hash": hashlib.sha256(canonical_json(identity).encode()).hexdigest(),
            "metadata": metadata,
        }
    except BaseException:
        shutil.rmtree(directory)
        raise


def open_verified_ecg(asset):
    """Verify both original files and keep these very handles for reading/transmission."""
    directory = ecg_directory(asset.asset_id)
    opened = []
    directory_fd = None
    try:
        directory_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        for name, size, expected in (("source.hea", asset.header_byte_size, asset.header_hash), ("source.dat", asset.signal_byte_size, asset.signal_hash)):
            descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory_fd)
            stream = os.fdopen(descriptor, "rb")
            opened.append(stream)
            record = os.fstat(stream.fileno())
            if not stat.S_ISREG(record.st_mode) or record.st_size != size or size > settings.AI_ECG_MAX_BYTES:
                raise OSError("file changed")
            digest = hashlib.sha256()
            while block := stream.read(65536):
                digest.update(block)
            if digest.hexdigest() != expected:
                raise OSError("bytes changed")
            stream.seek(0)
        return tuple(opened)
    except BaseException as exc:
        for stream in opened:
            stream.close()
        if isinstance(exc, OSError):
            raise HTTPException(409, "原心电文件不可用或已变化，请核对私有存储和原版本") from exc
        raise
    finally:
        if directory_fd is not None:
            os.close(directory_fd)


def signal_window(stream, metadata, start, count, max_points, names=None):
    """Return actual sample indices and mV, preserving peaks and gaps in bounded overviews."""
    total, channels = metadata["sample_count"], metadata["channels"]
    if not 0 <= start < total or not 1 <= count <= 50000 or not 50 <= max_points <= 2000:
        raise HTTPException(422, "波形窗口或显示点数超出范围")
    leads = metadata["leads"]
    names = names or [lead["name"] for lead in leads]
    if len(set(names)) != len(names) or not set(names) <= {lead["name"] for lead in leads}:
        raise HTTPException(422, "请求的导联不在原记录中")
    end = min(total, start + count)
    stream.seek(start * channels * 2)
    values = _samples(stream.read((end - start) * channels * 2))
    if len(values) != (end - start) * channels:
        raise HTTPException(409, "原波形在读取期间已变化")
    result = []
    for channel, lead in enumerate(leads):
        if lead["name"] not in names:
            continue
        samples = values[channel::channels]
        step = max(1, (len(samples) + max(1, max_points // 5) - 1) // max(1, max_points // 5)) if len(samples) > max_points else 1
        chosen = set()
        for offset in range(0, len(samples), step):
            indices = range(offset, min(offset + step, len(samples)))
            chosen.update((indices.start, indices.stop - 1))
            valid = [index for index in indices if samples[index] != INVALID_SAMPLE]
            if valid:
                chosen.update((min(valid, key=samples.__getitem__), max(valid, key=samples.__getitem__)))
            missing = next((index for index in indices if samples[index] == INVALID_SAMPLE), None)
            if missing is not None:
                chosen.add(missing)
        scale = float(UNITS_TO_MV[lead["unit"]] / Decimal(lead["gain"]))
        points, previous = [], -1
        for index in sorted(chosen):
            value = samples[index]
            gap = INVALID_SAMPLE in samples[previous + 1 : index + 1]
            points.append({"sample": start + index, "value_mv": None if value == INVALID_SAMPLE else (value - lead["baseline"]) * scale, "break_before": gap})
            previous = index
        result.append({"name": lead["name"], "points": points, "missing_samples_in_window": samples.count(INVALID_SAMPLE)})
    return {
        "start_sample": start,
        "end_sample_exclusive": end,
        "sample_rate_hz": metadata["sample_rate_hz"],
        "display_unit": "mV",
        "decimated": end - start > max_points,
        "leads": result,
        "scope_note": "显示值由原增益/基线和单位换算；概览保留极值并断开缺失区间，不能替代全部原始采样，需缩小窗口检查细节。格式校验不代表生理信号质量或诊断已验证",
    }
