"""Exercise the real offline classifier with synthetic DICOM-derived stored pixels.

No patient data, database, paid service, remote model code or diagnostic metric.
All multipart requests use the actual service and its isolated CPU worker.
"""

import asyncio
import hashlib
import io
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.ai.imaging_config import ImagingSettings
from app.ai.imaging_model import LABELS, canonical_json
from app.ai.imaging_server import create_imaging_app, execute_job


def synthetic_source(*, inverted=False, alternative_window=False, empty_crop=False, return_original=False):
    import numpy as np
    import pydicom
    from pydicom.dataset import FileDataset, FileMetaDataset
    from pydicom.uid import DigitalXRayImageStorageForPresentation, ExplicitVRLittleEndian, generate_uid

    rows, columns = 225, 226
    values = ((np.arange(rows * columns).reshape(rows, columns) * 7 + np.arange(columns) * 11) % 4096).astype(np.uint16)
    if empty_crop:
        values[:, 1:] = 0
        values[:, 0] = np.arange(rows) + 1
    if inverted:
        values = 4095 - values
    meta = FileMetaDataset()
    meta.TransferSyntaxUID, meta.MediaStorageSOPClassUID = ExplicitVRLittleEndian, DigitalXRayImageStorageForPresentation
    meta.MediaStorageSOPInstanceUID, meta.ImplementationClassUID = generate_uid(), generate_uid()
    ds = FileDataset(None, {}, file_meta=meta, preamble=b"\0" * 128)
    ds.SOPClassUID, ds.SOPInstanceUID = meta.MediaStorageSOPClassUID, meta.MediaStorageSOPInstanceUID
    ds.StudyInstanceUID, ds.SeriesInstanceUID = generate_uid(), generate_uid()
    ds.PatientName, ds.PatientID = "SYNTHETIC^NOT_A_PATIENT", "SYNTHETIC_ONLY"
    ds.Modality, ds.BodyPartExamined, ds.ViewPosition = "DX", "CHEST", "PA"
    ds.Rows, ds.Columns, ds.SamplesPerPixel = rows, columns, 1
    ds.BitsAllocated, ds.BitsStored, ds.HighBit, ds.PixelRepresentation = 16, 12, 11, 0
    ds.PhotometricInterpretation = "MONOCHROME1" if inverted else "MONOCHROME2"
    ds.PresentationLUTShape = "INVERSE" if inverted else "IDENTITY"
    ds.PresentationIntentType, ds.BurnedInAnnotation = "FOR PRESENTATION", "NO"
    ds.RescaleSlope, ds.RescaleIntercept = "1", "0"
    ds.WindowCenter, ds.WindowWidth = ("800", "1000") if alternative_window else ("2048", "4096")
    if empty_crop:
        ds.add_new((0x0028, 0x0120), "US", 0)
    ds.PixelData = (values | np.uint16(0x5000)).astype("<u2").tobytes()
    stream = io.BytesIO()
    ds.save_as(stream, enforce_file_format=True)
    original = stream.getvalue()
    decoded = pydicom.dcmread(io.BytesIO(original)).pixel_array
    assert np.array_equal(decoded, values)
    raw = decoded.astype("<i4").tobytes()
    valid = values[values != 0] if empty_crop else values.ravel()
    metadata = {
        "format": "dicom_i32le_v1",
        "rows": rows,
        "columns": columns,
        "frames": 1,
        "bits_allocated": 16,
        "bits_stored": 12,
        "high_bit": 11,
        "pixel_representation": 0,
        "photometric_interpretation": str(ds.PhotometricInterpretation),
        "transfer_syntax_uid": str(ExplicitVRLittleEndian),
        "sop_class_uid": str(DigitalXRayImageStorageForPresentation),
        "rescale_slope": 1.0,
        "rescale_intercept": 0.0,
        "rescale_declared": True,
        "rescale_type": "unknown",
        "window_presets": [{"center": float(ds.WindowCenter), "width": float(ds.WindowWidth)}],
        "voi_lut_function": "LINEAR",
        "padding": {"value": 0, "range_limit": 0} if empty_crop else None,
        "presentation_lut_shape": str(ds.PresentationLUTShape),
        "invert_display": inverted,
        "presentation_intent_type": "FOR PRESENTATION",
        "valid_min_stored": int(valid.min()),
        "valid_max_stored": int(valid.max()),
        "valid_pixel_count": int(valid.size),
        "modality": "DX",
        "body_part_examined": "CHEST",
        "view_position": "PA",
        "image_laterality": "unknown",
        "burned_in_annotation": "NO",
        "coordinate_space": "source_pixels",
        "orientation": "stored_row_column_unmodified",
        "pixel_spacing_mm": None,
        "imager_pixel_spacing_mm": None,
        **{
            field: hashlib.sha256(str(getattr(ds, name)).encode()).hexdigest()
            for field, name in (("study_uid_hash", "StudyInstanceUID"), ("series_uid_hash", "SeriesInstanceUID"), ("instance_uid_hash", "SOPInstanceUID"))
        },
    }
    identity = {"format": "dicom_i32le_v1", "original_hash": hashlib.sha256(original).hexdigest(), "pixel_hash": hashlib.sha256(raw).hexdigest()}
    content_hash = hashlib.sha256(canonical_json(identity).encode()).hexdigest()
    asset_id = "12345678-1234-4234-8234-123456789012"
    source = {
        **{key: value for key, value in identity.items() if key != "format"},
        "content_hash": content_hash,
        "asset_id": asset_id,
        "source_id": f"image:{asset_id}:{content_hash[:12]}",
        "imaging_order_id": "32345678-1234-4234-8234-123456789012",
        "order_status": 0,
        "byte_size": len(original) + len(raw),
        "original_byte_size": len(original),
        "pixel_byte_size": len(raw),
        "image_metadata": metadata,
    }
    return (raw, source, original) if return_original else (raw, source)


async def smoke():
    import httpx

    config = ImagingSettings()
    jobs = []

    async def observed_execution(job, timeout):
        jobs.append(job["source"]["pixel_hash"])
        return await execute_job(job, timeout)

    app = create_imaging_app(config, executor=observed_execution)
    headers = {"Authorization": "Bearer " + config.api_key.get_secret_value()}
    calls, checks = [], []
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://local-image") as client:
        response = await client.get("/capabilities", headers=headers)
        assert response.status_code == 200, response.text
        descriptor = response.json()
        assert descriptor["clinical_validation"] == "not_provided"
        reference = None
        for name, options, status in (
            ("original_mono2", {}, 200),
            ("equivalent_mono1", {"inverted": True}, 200),
            ("different_voi_ignored_explicitly", {"alternative_window": True}, 200),
            ("padding_only_author_crop", {"empty_crop": True}, 422),
            ("unsupported_lateral_view", {}, 422),
        ):
            raw, source = synthetic_source(**options)
            if name == "unsupported_lateral_view":
                source["image_metadata"]["view_position"] = "LL"
            instructions = "固定合成原图工程测试的完整Prompt，不代表临床验证或真实患者资料"
            task = {
                "schema_version": "4",
                "feature_key": "imaging_detection",
                "engine": "vision",
                "model": descriptor["model_version"],
                "instructions": instructions,
                "store": False,
                "input": {"context": {"image_source": source}, "input": {"question": "此文字不参与固定像素模型"}, "evidence": []},
            }
            response = await client.post("/tasks", headers=headers, data={"task": canonical_json(task)}, files={"image": ("pixels.i32le", raw, "application/octet-stream")})
            assert response.status_code == status, (name, response.status_code, response.text)
            if status == 200:
                output = response.json()
                analysis = output["image_analysis"]
                assert output["model_version"] == descriptor["model_version"] and output["applicable"] is True
                assert analysis["pixel_hash"] == source["pixel_hash"] and analysis["original_hash"] == source["original_hash"]
                assert analysis["processing"]["analysis_region"] == {"x": 1, "y": 0, "width": 225, "height": 225}
                assert analysis["processing"]["instructions_digest"] == hashlib.sha256(instructions.encode()).hexdigest()
                assert [finding["label"] for finding in analysis["findings"]] == LABELS
                assert all(finding["location"] == "image" and finding["region"] is None and 0 <= finding["score"] <= 1 for finding in analysis["findings"])
                scores = [finding["score"] for finding in analysis["findings"]]
                if reference is None:
                    reference = scores
                assert scores == reference, name
                calls.append(
                    {
                        "case": name,
                        "max_score_difference": max(abs(a - b) for a, b in zip(reference, scores, strict=True)),
                        "analysis_region": analysis["processing"]["analysis_region"],
                        "local_preprocessing": analysis["processing"]["local_preprocessing"],
                    }
                )
            checks.append({"case": name, "status": status})
    assert "app.database" not in sys.modules and "app.config" not in sys.modules
    return {
        "synthetic_only": True,
        "clinical_validation": False,
        "descriptor": descriptor,
        "checks": checks,
        "comparisons": calls,
        "real_worker_jobs": len(jobs),
        "reference_scores": [{"label": label, "score": score} for label, score in zip(LABELS, reference, strict=True)],
        "hospital_settings_or_database_imported": False,
    }


if __name__ == "__main__":
    print(json.dumps(asyncio.run(smoke()), ensure_ascii=False, allow_nan=False))
