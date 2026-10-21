"""Bounded HTTP model adapters with strict results and server-owned citation IDs."""

import copy
import hashlib
import json
from decimal import Decimal, InvalidOperation
from typing import BinaryIO

import httpx
from fastapi import HTTPException
from pydantic import ValidationError

from app.ai.audio_files import AUDIO_FORMATS
from app.ai.bed_protocol import BedGenerationResult
from app.ai.catalog import COMMON_SYSTEM_PROMPT, FeatureSpec
from app.ai.ecg_model import LABELS, LEADS, PREPROCESSING, RELEASE_FILES, ECGModelManifest, canonical_json
from app.ai.governance import encode_json, provider_credential, validate_endpoint
from app.ai.inventory_protocol import InventoryGenerationResult, InventoryText
from app.ai.models import AIProvider
from app.ai.schemas import (
    AkiGenerationResult,
    AudioGenerationResult,
    ECGGenerationResult,
    ForecastGenerationResult,
    GenerationResult,
    ImageGenerationResult,
    News2GenerationResult,
    QsofaGenerationResult,
    RosterGenerationResult,
    SofaChangeGenerationResult,
    SofaGenerationResult,
)
from app.ai.supply_protocol import SupplyGenerationResult
from app.ai.surgery_protocol import SurgeryGenerationResult
from app.config import settings

MAX_RESPONSE_BYTES = 512 * 1024


def _unique_response_pairs(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("模型响应不接受重复JSON字段")
        value[key] = item
    return value


def _finite_response_constant(_):
    raise ValueError("模型响应不接受非有限JSON常量")


class AIExecutionError(Exception):
    """A stable error code and safe user message without provider response bodies."""

    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        self.input_tokens = None
        self.output_tokens = None
        super().__init__(message)


def result_json_schema() -> dict:
    """Make all output properties required for strict Structured Outputs."""
    schema = copy.deepcopy(GenerationResult.model_json_schema())

    def visit(node: object) -> None:
        if isinstance(node, dict):
            node.pop("default", None)
            if node.get("type") == "object":
                node["required"] = list(node.get("properties", {}))
                node["additionalProperties"] = False
            for value in node.values():
                visit(value)
        elif isinstance(node, list):
            for value in node:
                visit(value)

    visit(schema)
    return schema


def validate_generation(
    value: object,
    evidence: list[dict],
    requires_knowledge: bool = False,
    *,
    audio_source: dict | None = None,
    ecg_source: dict | None = None,
    image_source: dict | None = None,
    forecast_source: dict | None = None,
    news2_source: dict | None = None,
    aki_source: dict | None = None,
    qsofa_source: dict | None = None,
    sofa_source: dict | None = None,
    sofa_change_source: dict | None = None,
    roster_source: dict | None = None,
    bed_source: dict | None = None,
    surgery_source: dict | None = None,
    inventory_source: dict | None = None,
    supply_source: dict | None = None,
    supply_horizon: int | None = None,
    bed_horizon: int | None = None,
    forecast_horizon: int | None = None,
    instructions_digest: str | None = None,
    model_version: str | None = None,
) -> GenerationResult:
    """Reject fabricated references and invalid structured output before UI exposure."""
    try:
        if inventory_source is not None and any(
            source is not None
            for source in (
                audio_source,
                ecg_source,
                image_source,
                forecast_source,
                news2_source,
                aki_source,
                qsofa_source,
                sofa_source,
                sofa_change_source,
                roster_source,
                bed_source,
                surgery_source,
                supply_source,
            )
        ):
            raise ValueError("库存完整场景不得与其他模型原件混用")
        if sofa_source is not None and sofa_change_source is not None:
            raise ValueError("SOFA日评估与变化结果不能混用")
        if roster_source is not None and any(
            value is not None
            for value in (audio_source, ecg_source, image_source, forecast_source, news2_source, aki_source, qsofa_source, sofa_source, sofa_change_source, bed_source, surgery_source, supply_source)
        ):
            raise ValueError("排班原件不得与其他模型原件混用")
        if bed_source is not None and any(
            value is not None
            for value in (
                audio_source,
                ecg_source,
                image_source,
                forecast_source,
                news2_source,
                aki_source,
                qsofa_source,
                sofa_source,
                sofa_change_source,
                roster_source,
                surgery_source,
                supply_source,
            )
        ):
            raise ValueError("床位原件不得与其他模型原件混用")
        if surgery_source is not None and any(
            value is not None
            for value in (audio_source, ecg_source, image_source, forecast_source, news2_source, aki_source, qsofa_source, sofa_source, sofa_change_source, roster_source, bed_source, supply_source)
        ):
            raise ValueError("手术完整场景不得与其他模型原件混用")
        if supply_source is not None and any(
            value is not None
            for value in (audio_source, ecg_source, image_source, forecast_source, news2_source, aki_source, qsofa_source, sofa_source, sofa_change_source, roster_source, bed_source, surgery_source)
        ):
            raise ValueError("物资完整原量序列不得与其他模型原件混用")
        schema = (
            InventoryGenerationResult
            if inventory_source is not None
            else SupplyGenerationResult
            if supply_source is not None
            else SurgeryGenerationResult
            if surgery_source is not None
            else BedGenerationResult
            if bed_source is not None
            else RosterGenerationResult
            if roster_source is not None
            else SofaGenerationResult
            if sofa_source is not None
            else SofaChangeGenerationResult
            if sofa_change_source is not None
            else AudioGenerationResult
            if audio_source is not None
            else ECGGenerationResult
            if ecg_source is not None
            else ImageGenerationResult
            if image_source is not None
            else ForecastGenerationResult
            if forecast_source is not None
            else News2GenerationResult
            if news2_source is not None
            else AkiGenerationResult
            if aki_source is not None
            else QsofaGenerationResult
            if qsofa_source is not None
            else GenerationResult
        )
        result = schema.model_validate(value)
    except (ValidationError, ValueError) as exc:
        raise AIExecutionError("INVALID_OUTPUT", "模型返回的结果不符合任务结构，请调整模型或重试") from exc
    allowed = {item["source_id"] for item in evidence}
    cited = {source for section in result.sections for source in section.source_ids}
    if not cited <= allowed:
        raise AIExecutionError("INVALID_CITATION", "模型引用了未提供的来源，结果已拒绝展示")
    if requires_knowledge and result.sections:
        knowledge_ids = {item["source_id"] for item in evidence if item.get("kind") == "knowledge"}
        if not cited.intersection(knowledge_ids):
            raise AIExecutionError("UNGROUNDED_OUTPUT", "该任务的回答缺少已审核知识依据，结果已拒绝展示")
    if inventory_source is not None:
        from app.ai.inventory_contract import InventorySource
        from app.ai.inventory_model import generation_result_for_analysis, validate_analysis_binding

        try:
            validate_analysis_binding(result.inventory_analysis, InventorySource.model_validate(inventory_source), instructions_digest, model_version)
            explanation = {key: getattr(result, key) for key in ("summary", "warnings", "missing_data")}
            explanation["sections"] = [item.model_dump(mode="json") for item in result.sections]
            expected_explanation = InventoryText.model_validate(generation_result_for_analysis(result.inventory_analysis)).model_dump(mode="json")
            if explanation != expected_explanation:
                raise ValueError("固定库存比较解释与完整候选、逐日账及费用不符")
        except (ValidationError, ValueError, TypeError, KeyError, OverflowError) as exc:
            raise AIExecutionError("INVENTORY_BINDING_MISMATCH", "库存原件、候选全集、数量与成本单位、逐日守恒、精确费用、运行或固定解释重算不一致，结果已拒收") from exc
        if inventory_source["source_id"] not in cited:
            raise AIExecutionError("UNGROUNDED_INVENTORY", "库存比较说明未引用明确审核的完整场景")
    if supply_source is not None:
        from app.ai.supply_contract import SupplySource
        from app.ai.supply_model import generation_result_for_analysis, validate_analysis_binding

        try:
            validate_analysis_binding(result.supply_analysis, SupplySource.model_validate(supply_source), supply_horizon, instructions_digest, model_version)
            explanation = {key: getattr(result, key) for key in ("summary", "warnings", "missing_data")}
            explanation["sections"] = [item.model_dump(mode="json") for item in result.sections]
            expected_explanation = GenerationResult.model_validate(generation_result_for_analysis(result.supply_analysis)).model_dump(mode="json")
            if explanation != expected_explanation:
                raise ValueError("固定物资预测解释与完整原量及回测不符")
        except (ValidationError, ValueError, TypeError, KeyError, OverflowError) as exc:
            raise AIExecutionError("SUPPLY_BINDING_MISMATCH", "物资原量、单位、三目标、完整回测、明确参数、运行或固定解释重算不一致，结果已拒收") from exc
        if supply_source["source_id"] not in cited:
            raise AIExecutionError("UNGROUNDED_SUPPLY", "物资预测说明未引用明确审核的完整原序列")
    if surgery_source is not None:
        from app.ai.surgery_contract import SurgerySource
        from app.ai.surgery_model import generation_result_for_analysis, validate_analysis_binding

        try:
            validate_analysis_binding(result.surgery_analysis, SurgerySource.model_validate(surgery_source), instructions_digest, model_version)
            explanation = {key: getattr(result, key) for key in ("summary", "warnings", "missing_data")}
            explanation["sections"] = [item.model_dump(mode="json") for item in result.sections]
            if explanation != generation_result_for_analysis(result.surgery_analysis):
                raise ValueError("固定手术排程解释与完整候选及搜索证明不符")
        except (ValidationError, ValueError, TypeError, KeyError, OverflowError) as exc:
            raise AIExecutionError("SURGERY_BINDING_MISMATCH", "手术完整场景、病例、阶段资源、两类搜索证明、运行或固定解释重算不一致，结果已拒收") from exc
        if surgery_source["source_id"] not in cited:
            raise AIExecutionError("UNGROUNDED_SURGERY", "手术排程说明未引用明确审核的完整原场景")
    if bed_source is not None:
        from app.ai.bed_contract import BedSource
        from app.ai.bed_model import generation_result_for_analysis, validate_analysis_binding

        try:
            validate_analysis_binding(result.bed_analysis, BedSource.model_validate(bed_source), bed_horizon, instructions_digest, model_version)
            explanation = {key: getattr(result, key) for key in ("summary", "warnings", "missing_data")}
            explanation["sections"] = [item.model_dump(mode="json") for item in result.sections]
            if explanation != generation_result_for_analysis(result.bed_analysis):
                raise ValueError("固定床位解释与完整统计证据不符")
        except (ValidationError, ValueError, TypeError, KeyError, OverflowError) as exc:
            raise AIExecutionError("BED_BINDING_MISMATCH", "床位完整原件、五项目标、原钟点、预测期、滚动回测、精确分母、容量情景或固定解释重算不一致，结果已拒收") from exc
        if bed_source["source_id"] not in cited:
            raise AIExecutionError("UNGROUNDED_BED", "床位预测说明未引用明确审核的完整原序列")
    if roster_source is not None:
        from app.ai.roster_contract import RosterSource
        from app.ai.roster_model import generation_result_for_analysis, validate_analysis_binding

        try:
            validate_analysis_binding(result.roster_analysis, RosterSource.model_validate(roster_source), instructions_digest, model_version)
            explanation = {key: getattr(result, key) for key in ("summary", "warnings", "missing_data")}
            explanation["sections"] = [item.model_dump(mode="json") for item in result.sections]
            if explanation != generation_result_for_analysis(result.roster_analysis):
                raise ValueError("固定排班解释与完整优化证明不符")
        except (ValidationError, ValueError, TypeError, KeyError) as exc:
            raise AIExecutionError("ROSTER_BINDING_MISMATCH", "排班完整原件、目标、工时、候选、两图证明、运行或固定解释重算不一致，结果已拒收") from exc
        if roster_source["source_id"] not in cited:
            raise AIExecutionError("UNGROUNDED_ROSTER", "排班说明未引用明确审核的完整原计划")
    if news2_source is not None:
        from app.ai.news2_contract import News2Source
        from app.ai.news2_model import generation_result_for_analysis, validate_analysis_binding

        try:
            validate_analysis_binding(result.news2_analysis, News2Source.model_validate(news2_source), instructions_digest, model_version)
            explanation = {key: getattr(result, key) for key in ("summary", "warnings", "missing_data")}
            explanation["sections"] = [item.model_dump(mode="json") for item in result.sections]
            if explanation != generation_result_for_analysis(result.news2_analysis):
                raise ValueError("NEWS2 explanation differs from the fixed rule result")
        except (ValidationError, ValueError, TypeError, KeyError) as exc:
            raise AIExecutionError("NEWS2_BINDING_MISMATCH", "NEWS2原来源、适用性、规则版本、分项、总数、缺项或解释与实际计算不一致，结果已拒收") from exc
        if result.sections and news2_source["source_id"] not in cited:
            raise AIExecutionError("UNGROUNDED_NEWS2", "NEWS2评分说明未引用所选原点测与适用性核实来源")
    if aki_source is not None:
        from app.ai.aki_contract import AkiSource
        from app.ai.aki_model import generation_result_for_analysis, validate_analysis_binding

        try:
            validate_analysis_binding(result.aki_analysis, AkiSource.model_validate(aki_source), instructions_digest, model_version)
            explanation = {key: getattr(result, key) for key in ("summary", "warnings", "missing_data")}
            explanation["sections"] = [item.model_dump(mode="json") for item in result.sections]
            if explanation != generation_result_for_analysis(result.aki_analysis):
                raise ValueError("KDIGO AKI explanation differs from the fixed rule result")
        except (ValidationError, ValueError, TypeError, KeyError) as exc:
            raise AIExecutionError("AKI_BINDING_MISMATCH", "KDIGO AKI原来源、适用性、规则版本、判据、分期下界、原时段、缺项或解释与实际计算不一致，结果已拒收") from exc
        if result.sections and aki_source["source_id"] not in cited:
            raise AIExecutionError("UNGROUNDED_AKI", "KDIGO AKI分期说明未引用所选原资料与人工适用性来源")
    if qsofa_source is not None:
        from app.ai.qsofa_contract import QsofaSource
        from app.ai.qsofa_model import generation_result_for_analysis, validate_analysis_binding

        try:
            validate_analysis_binding(result.qsofa_analysis, QsofaSource.model_validate(qsofa_source), instructions_digest, model_version)
            explanation = {key: getattr(result, key) for key in ("summary", "warnings", "missing_data")}
            explanation["sections"] = [item.model_dump(mode="json") for item in result.sections]
            if explanation != generation_result_for_analysis(result.qsofa_analysis):
                raise ValueError("qSOFA explanation differs from the fixed rule result")
        except (ValidationError, ValueError, TypeError, KeyError) as exc:
            raise AIExecutionError("QSOFA_BINDING_MISMATCH", "qSOFA原来源、当前回顾声明、规则版本、三分项、总数或小计、原时刻、缺项或解释与实际计算不一致，结果已拒收") from exc
        if result.sections and qsofa_source["source_id"] not in cited:
            raise AIExecutionError("UNGROUNDED_QSOFA", "qSOFA核对说明未引用所选原点测、GCS与当前临床声明来源")
    if sofa_source is not None or sofa_change_source is not None:
        from app.ai.sofa_contract import SofaChangeSource, SofaSource
        from app.ai.sofa_model import generation_result_for_analysis, generation_result_for_change_analysis, validate_analysis_binding, validate_change_analysis_binding

        is_change = sofa_change_source is not None
        original = sofa_change_source if is_change else sofa_source
        analysis = result.sofa_change_analysis if is_change else result.sofa_analysis
        try:
            source_type = SofaChangeSource if is_change else SofaSource
            validator = validate_change_analysis_binding if is_change else validate_analysis_binding
            explanation_for = generation_result_for_change_analysis if is_change else generation_result_for_analysis
            validator(analysis, source_type.model_validate(original), instructions_digest, model_version)
            explanation = {key: getattr(result, key) for key in ("summary", "warnings", "missing_data")}
            explanation["sections"] = [item.model_dump(mode="json") for item in result.sections]
            if explanation != explanation_for(analysis):
                raise ValueError("SOFA固定说明与完整重算结果不符")
        except (ValidationError, ValueError, TypeError, KeyError) as exc:
            raise AIExecutionError("SOFA_BINDING_MISMATCH", "SOFA完整原件、六轴候选、精确计算、覆盖上下界、基线或变化及固定解释不一致，结果已拒收") from exc
        if original["source_id"] not in cited:
            raise AIExecutionError("UNGROUNDED_SOFA", "SOFA说明须引用所选完整原件或变化核实来源")
    if forecast_source is not None:
        from app.ai.forecast_contract import ForecastSource
        from app.ai.forecast_model import validate_analysis_binding

        try:
            validate_analysis_binding(result.forecast_analysis, ForecastSource.model_validate(forecast_source), forecast_horizon, instructions_digest, model_version)
        except (ValidationError, ValueError, TypeError, KeyError) as exc:
            raise AIExecutionError("FORECAST_BINDING_MISMATCH", "预测来源、时间范围、固定算法数值、误差分母或Prompt版本不一致，结果已拒收") from exc
        if result.sections and forecast_source["source_id"] not in cited:
            raise AIExecutionError("UNGROUNDED_FORECAST", "预测说明未引用本次已确认的原历史来源")
    if audio_source is not None:
        transcript = result.transcription
        if transcript.asset_id != audio_source["asset_id"] or transcript.content_hash != audio_source["content_hash"]:
            raise AIExecutionError("AUDIO_SOURCE_MISMATCH", "转写结果与所选原录音不一致，结果已拒收")
        processing = transcript.processing
        if model_version and model_version.startswith("fw:") and (processing is None or model_version != "fw:" + processing.runtime_digest):
            raise AIExecutionError("SPEECH_RUNTIME_MISMATCH", "本地识别缺少登记模型的运行版本与完整处理报告")
        if processing and (abs(processing.decoded_duration_ms - audio_source["duration_ms"]) > 1 or (instructions_digest and processing.instructions_digest != instructions_digest)):
            raise AIExecutionError("SPEECH_PROCESSING_MISMATCH", "识别处理范围或任务Prompt与原录音任务不一致")
        previous_start = -1
        for segment in transcript.segments:
            if segment.end_ms > audio_source["duration_ms"] or segment.start_ms < previous_start or segment.source_id != audio_source["source_id"]:
                raise AIExecutionError("INVALID_AUDIO_SEGMENT", "转写时间、顺序或原录音引用不符合实际录音范围，结果已拒收")
            previous_start = segment.start_ms
        if result.sections and audio_source["source_id"] not in cited:
            raise AIExecutionError("UNGROUNDED_TRANSCRIPTION", "转写说明未引用所选原录音，结果已拒收")
    if ecg_source is not None:
        analysis, metadata = result.ecg_analysis, ecg_source["signal_metadata"]
        processing = analysis.processing
        if analysis.asset_id != ecg_source["asset_id"] or analysis.content_hash != ecg_source["content_hash"] or analysis.signal_hash != ecg_source["signal_hash"]:
            raise AIExecutionError("ECG_SOURCE_MISMATCH", "心电候选结果与所选原始波形不一致")
        if (
            processing.input_sample_count != metadata["sample_count"]
            or processing.input_sample_rate_hz != metadata["sample_rate_hz"]
            or processing.input_leads != [lead["name"] for lead in metadata["leads"]]
            or (instructions_digest and processing.instructions_digest != instructions_digest)
        ):
            raise AIExecutionError("ECG_PROCESSING_MISMATCH", "心电输入采样、导联顺序或任务Prompt与实际任务不符")
        local = processing.local_runtime
        if local is not None or (model_version and model_version.startswith("ssl-ecg:")):
            if local is None or model_version != "ssl-ecg:" + local.runtime_digest:
                raise AIExecutionError("ECG_RUNTIME_MISMATCH", "本地心电结果缺少所登记实际运行版本，结果已拒收")
            manifest = ECGModelManifest(files={name: {"size": size, "sha256": digest} for name, (size, digest) in RELEASE_FILES.items()})
            if local.model_digest != manifest.digest or local.preprocessing_digest != hashlib.sha256(canonical_json(PREPROCESSING).encode()).hexdigest():
                raise AIExecutionError("ECG_RUNTIME_MISMATCH", "本地心电权重发布或预处理与已审查模型不一致")
            try:
                in_scope = metadata["sample_count"] == 1000 and Decimal(metadata["sample_rate_hz"]) == 100 and set(processing.input_leads) == set(LEADS) and len(processing.input_leads) == 12
            except InvalidOperation:
                in_scope = False
            if not in_scope or processing.used_leads != LEADS or processing.missing_sample_handling != "none_present" or any(lead["missing_samples"] for lead in metadata["leads"]):
                raise AIExecutionError("ECG_LOCAL_SCOPE_MISMATCH", "本地研究模型输入超出原始12导联、100Hz、10秒无缺失范围")
            if [finding.label for finding in analysis.findings] != LABELS or any(
                finding.location != "recording" or finding.leads != LEADS or finding.score is None or not 0 <= finding.score <= 1 for finding in analysis.findings
            ):
                raise AIExecutionError("ECG_LOCAL_SCORE_MISMATCH", "本地研究模型须保留完整五类整段原始分数，不能改作诊断阈值或局部定位")
        used = {lead["name"]: lead for lead in metadata["leads"] if lead["name"] in processing.used_leads}
        has_missing = any(lead["missing_samples"] for lead in metadata["leads"])
        if has_missing and (processing.missing_sample_handling != "masked" or not processing.preprocessing_notes):
            raise AIExecutionError("ECG_MISSING_SAMPLE_MISMATCH", "原波形含缺失样本，模型须如实报告其处理与适用限制")
        if all(lead["missing_samples"] == metadata["sample_count"] for lead in used.values()):
            raise AIExecutionError("ECG_NO_USABLE_SIGNAL", "模型使用的导联没有可用采样，不能生成候选判读")
        for finding in analysis.findings:
            if not set(finding.leads) <= set(used) or finding.source_id != ecg_source["source_id"]:
                raise AIExecutionError("INVALID_ECG_FINDING", "心电候选引用了未使用的导联或其他原波形")
            if finding.location == "sample_interval" and finding.end_sample_exclusive > metadata["sample_count"]:
                raise AIExecutionError("INVALID_ECG_FINDING", "心电候选的定位超出原始采样范围")
        if result.sections and ecg_source["source_id"] not in cited:
            raise AIExecutionError("UNGROUNDED_ECG_OUTPUT", "心电判读说明未引用所选原始波形")
    if image_source is not None:
        analysis, metadata = result.image_analysis, image_source["image_metadata"]
        if any(getattr(analysis, key) != image_source[key] for key in ("asset_id", "content_hash", "original_hash", "pixel_hash")):
            raise AIExecutionError("IMAGE_SOURCE_MISMATCH", "影像候选结果与所选原文件或实际像素不一致")
        processing = analysis.processing
        if (
            processing.input_rows != metadata["rows"]
            or processing.input_columns != metadata["columns"]
            or processing.input_frames != metadata["frames"]
            or (instructions_digest and processing.instructions_digest != instructions_digest)
        ):
            raise AIExecutionError("IMAGE_PROCESSING_MISMATCH", "影像尺寸、帧数或实际任务Prompt不一致")
        if metadata["valid_pixel_count"] < 1:
            raise AIExecutionError("IMAGE_NO_USABLE_PIXELS", "影像只有padding背景，不能生成候选发现")
        local, native = processing.local_runtime, processing.local_preprocessing
        if local is not None or native is not None or (model_version and model_version.startswith("xrv:")):
            from app.ai.imaging_contract import ImageSource
            from app.ai.imaging_model import LABELS as IMAGE_LABELS
            from app.ai.imaging_model import RELEASE_FILES as IMAGE_FILES
            from app.ai.imaging_model import ImagingModelManifest
            from app.ai.imaging_preprocessing import center_crop

            if local is None or native is None or model_version != "xrv:" + local.runtime_digest:
                raise AIExecutionError("IMAGE_RUNTIME_MISMATCH", "胸片结果缺少所登记实际运行版本及真实处理报告")
            manifest = ImagingModelManifest(files={name: {"size": size, "sha256": sha} for name, (size, sha) in IMAGE_FILES.items()})
            if local.model_digest != manifest.digest:
                raise AIExecutionError("IMAGE_RUNTIME_MISMATCH", "胸片模型权重与已审查固定发布不一致")
            try:
                ImageSource.model_validate(image_source)
            except ValidationError as exc:
                raise AIExecutionError("IMAGE_LOCAL_SCOPE_MISMATCH", "原像素超出明确胸片单帧研究输入范围") from exc
            region = center_crop(metadata["rows"], metadata["columns"])
            if processing.analysis_region.model_dump() != region:
                raise AIExecutionError("IMAGE_LOCAL_CROP_MISMATCH", "胸片实际分析范围与原作者中心裁剪公式不一致")
            count = metadata["rows"] * metadata["columns"]
            if (
                native.input_pixel_count != count
                or native.cropped_pixel_count != region["width"] * region["height"]
                or native.normalization_maxval != (1 << metadata["bits_stored"]) - 1
                or native.padding_pixels_in_input != count - metadata["valid_pixel_count"]
            ):
                raise AIExecutionError("IMAGE_LOCAL_PROCESSING_MISMATCH", "胸片实际像素数量、归一化或原padding统计不一致")
            if [finding.label for finding in analysis.findings] != IMAGE_LABELS or any(
                finding.location != "image" or finding.region is not None or finding.score is None or not 0 <= finding.score <= 1 for finding in analysis.findings
            ):
                raise AIExecutionError("IMAGE_LOCAL_SCORE_MISMATCH", "胸片研究模型须保留18项原始图像级分数，不能改作诊断阈值或虚构病灶定位")
        crop = processing.analysis_region
        for finding in analysis.findings:
            region = finding.region
            if finding.source_id != image_source["source_id"] or (
                region is not None and (region.x < crop.x or region.y < crop.y or region.x + region.width > crop.x + crop.width or region.y + region.height > crop.y + crop.height)
            ):
                raise AIExecutionError("INVALID_IMAGE_FINDING", "候选影像定位超出实际分析区域或引用其他原像素")
        if result.sections and image_source["source_id"] not in cited:
            raise AIExecutionError("UNGROUNDED_IMAGE_OUTPUT", "影像识别说明未引用所选原像素")
    return result


def _request(provider: AIProvider, spec: FeatureSpec, task_prompt: str, data: dict) -> tuple[str, dict]:
    endpoint = validate_endpoint(provider.api_base)
    budget = min(provider.max_output_tokens, settings.AI_MAX_OUTPUT_TOKENS)
    if spec.number == 71 or any(key in data.get("context", {}) for key in ("document_binding", "document_source", "document_review")) or "document_original_id" in data.get("input", {}):
        from app.ai.document_extraction_context import public_payload
        from app.ai.document_extraction_contract import EXTRACTION_SYSTEM_PROMPT, DocumentExtractionReply

        if spec.number != 71 or provider.kind not in {"chat", "responses"} or not provider.allows_patient_data:
            raise AIExecutionError("DOCUMENT_SOURCE_MODE", "原文抽取仅接受指定文字服务和完整已审核原件")
        try:
            public = public_payload(data)
        except (HTTPException, ValueError, TypeError, KeyError, UnicodeError) as exc:
            raise AIExecutionError("DOCUMENT_SOURCE_REQUIRED", "须核对当前完整原文及审核后再提取未核实区间草稿") from exc
        instructions = EXTRACTION_SYSTEM_PROMPT + "\n\n" + task_prompt
        if provider.kind == "responses":
            schema = copy.deepcopy(DocumentExtractionReply.model_json_schema())

            def close(node):
                if isinstance(node, dict):
                    node.pop("default", None)
                    if node.get("type") == "object":
                        node["required"] = list(node.get("properties", {}))
                        node["additionalProperties"] = False
                    for child in node.values():
                        close(child)
                elif isinstance(node, list):
                    for child in node:
                        close(child)

            close(schema)
            return endpoint + "/responses", {
                "model": provider.model,
                "instructions": instructions,
                "input": [{"role": "user", "content": encode_json(public)}],
                "max_output_tokens": budget,
                "store": False,
                "text": {"format": {"type": "json_schema", "name": "hoim_document_spans", "strict": True, "schema": schema}},
            }
        return endpoint + "/chat/completions", {
            "model": provider.model,
            "messages": [{"role": "system", "content": instructions}, {"role": "user", "content": encode_json(public)}],
            "max_tokens": budget,
            "temperature": float(provider.temperature),
            "response_format": {"type": "json_object"},
        }
    instructions = COMMON_SYSTEM_PROMPT + "\n\n" + task_prompt
    if data.get("context", {}).get("support_source") is not None:
        from app.ai.support_context import outbound_support_payload

        if provider.kind not in {"chat", "responses"}:
            raise AIExecutionError("SUPPORT_TEXT_ADAPTER_REQUIRED", "单条交班原资料整理须由登记的文本模型接口处理")
        data = outbound_support_payload(spec, data)
    news2_mode = provider.model.startswith("news2:")
    aki_mode = provider.model.startswith("aki:")
    qsofa_mode = provider.model.startswith("qsofa:")
    sofa_mode = provider.model.startswith("sofa1:")
    roster_mode = provider.model.startswith("roster:")
    bed_mode = provider.model.startswith("bed:")
    surgery_mode = provider.model.startswith("surgery:")
    inventory_mode = provider.model.startswith("inventory:")
    if inventory_mode and (spec.number != 67 or provider.kind != "specialist"):
        raise AIExecutionError("INVENTORY_ADAPTER_REQUIRED", "完整库存场景仅由登记的独立库存候选比较服务处理")
    if {"inventory_source", "inventory_binding", "inventory_scenario"} & data.get("context", {}).keys() and not inventory_mode:
        raise AIExecutionError("INVENTORY_ADAPTER_REQUIRED", "完整库存场景不能发送给其他模式或文本模型")
    supply_mode = provider.model.startswith("supply:")
    if supply_mode and (spec.number != 66 or provider.kind != "specialist"):
        raise AIExecutionError("SUPPLY_ADAPTER_REQUIRED", "完整物资原量仅由登记的独立物资预测服务处理")
    if {"supply_source", "supply_binding", "supply_series"} & data.get("context", {}).keys() and not supply_mode:
        raise AIExecutionError("SUPPLY_ADAPTER_REQUIRED", "完整物资原量不能发送给其他模式或文本模型")
    if surgery_mode and (spec.number != 65 or provider.kind != "specialist"):
        raise AIExecutionError("SURGERY_ADAPTER_REQUIRED", "完整手术场景仅由登记的独立手术排程服务处理")
    if {"surgery_source", "surgery_binding", "surgery_scenario"} & data.get("context", {}).keys() and not surgery_mode:
        raise AIExecutionError("SURGERY_ADAPTER_REQUIRED", "完整手术场景不能发送给其他模式或文本模型")
    if bed_mode and (spec.number != 64 or provider.kind != "specialist"):
        raise AIExecutionError("BED_ADAPTER_REQUIRED", "完整床位原件仅由登记的独立床位预测服务处理")
    if {"bed_source", "bed_binding", "bed_series"} & data.get("context", {}).keys() and not bed_mode:
        raise AIExecutionError("BED_ADAPTER_REQUIRED", "完整床位原件不能发送给其他模式或文本模型")
    if roster_mode and (spec.number != 63 or provider.kind != "specialist"):
        raise AIExecutionError("ROSTER_ADAPTER_REQUIRED", "完整排班原件仅由登记的独立排班服务处理")
    if {"roster_source", "roster_binding"} & data.get("context", {}).keys() and not roster_mode:
        raise AIExecutionError("ROSTER_ADAPTER_REQUIRED", "完整排班原件不能发送给其他模式或文本模型")
    if sofa_mode and (spec.number != 42 or provider.kind != "specialist"):
        raise AIExecutionError("SOFA_ADAPTER_REQUIRED", "完整SOFA原件仅由登记的独立SOFA-1服务处理")
    sofa_context_keys = {"sofa_source", "sofa_change_source", "sofa_binding"} & data.get("context", {}).keys()
    if sofa_context_keys and not sofa_mode:
        raise AIExecutionError("SOFA_ADAPTER_REQUIRED", "完整SOFA原件不能发送给其他模式或文本模型")
    if qsofa_mode and (spec.number != 42 or provider.kind != "specialist"):
        raise AIExecutionError("QSOFA_ADAPTER_REQUIRED", "qSOFA三项核对只能由所登记的独立专用规则服务处理")
    if data.get("context", {}).get("qsofa_source") is not None and not qsofa_mode:
        raise AIExecutionError("QSOFA_ADAPTER_REQUIRED", "明确qSOFA原资料只能发送给已登记的qSOFA规则服务")
    if aki_mode and (spec.number != 43 or provider.kind != "specialist"):
        raise AIExecutionError("AKI_ADAPTER_REQUIRED", "KDIGO AKI判据只能由肾功能资料核对的专用规则服务处理")
    if data.get("context", {}).get("aki_source") is not None and not aki_mode:
        raise AIExecutionError("AKI_ADAPTER_REQUIRED", "明确AKI评估只能发送给已登记的AKI规则服务")
    if news2_mode and (spec.number != 41 or provider.kind != "specialist"):
        raise AIExecutionError("NEWS2_ADAPTER_REQUIRED", "NEWS2规则只能由病情恶化预警的专用服务处理")
    if data.get("context", {}).get("news2_source") is not None and not news2_mode:
        raise AIExecutionError("NEWS2_ADAPTER_REQUIRED", "明确NEWS2评估只能发送给已登记的NEWS2规则服务")
    if spec.number == 21 and provider.kind != "specialist":
        raise AIExecutionError("AUDIO_ADAPTER_REQUIRED", "医疗录音须通过已登记的专用语音服务处理")
    if spec.number == 37 and provider.kind != "specialist":
        raise AIExecutionError("ECG_ADAPTER_REQUIRED", "原始心电须通过已登记的专用波形模型处理")
    if spec.number == 36 and provider.kind != "specialist":
        raise AIExecutionError("IMAGE_ADAPTER_REQUIRED", "原始影像须通过已登记的专用像素模型处理")
    if spec.number == 62 and provider.kind != "specialist":
        raise AIExecutionError("FORECAST_ADAPTER_REQUIRED", "日挂号记录数须通过带固定数值契约的专用预测服务处理")
    specialist_input = data
    if inventory_mode:
        from app.ai.inventory_context import public_payload

        try:
            specialist_input = public_payload(data)
        except (HTTPException, ValidationError, ValueError, TypeError, KeyError) as exc:
            raise AIExecutionError("INVENTORY_SOURCE_REQUIRED", "须选择受审完整库存场景并核对实盘、未来数量、候选全集、共同约束、单位及配方绑定") from exc
    if supply_mode:
        from app.ai.supply_context import public_payload

        try:
            specialist_input = public_payload(data)
        except (HTTPException, ValidationError, ValueError, TypeError, KeyError) as exc:
            raise AIExecutionError("SUPPLY_SOURCE_REQUIRED", "须选择受审完整物资原量序列、明确期限并核对单位、集合及参数配方绑定") from exc
    if surgery_mode:
        from app.ai.surgery_context import public_payload

        try:
            specialist_input = public_payload(data)
        except (HTTPException, ValidationError, ValueError, TypeError, KeyError) as exc:
            raise AIExecutionError("SURGERY_SOURCE_REQUIRED", "须选择一件受审完整手术场景并核对全部公开原件、集合及规则绑定") from exc
    if bed_mode:
        from app.ai.bed_context import BedContextBinding, selection
        from app.ai.bed_contract import BedSource, hash_content

        try:
            identifier, horizon = selection(data["input"])
            source = BedSource.model_validate(data["context"]["bed_source"]).model_dump(mode="json")
            bound = BedContextBinding.model_validate(data["context"]["bed_binding"])
            if (
                identifier != bound.series_id
                or identifier != source["series_id"]
                or horizon != bound.horizon_days
                or bound.projection_hash != hash_content(source)
                or bound.series_governance_hash != source["governance_hash"]
                or any(
                    getattr(bound, key) != source[key]
                    for key in (
                        "source_id",
                        "content_hash",
                        "scope_token",
                        "member_manifest_hash",
                        "historical_collection_digest",
                        "current_membership_digest",
                        "future_scenario_collection_digest",
                        "rule_id",
                        "recipe_digest",
                        "input_policy_digest",
                    )
                )
            ):
                raise ValueError("完整床位公开原件与冻结输入或预测期不同")
            specialist_input = {"context": {"bed_source": source}, "horizon_days": horizon}
        except (HTTPException, ValidationError, ValueError, TypeError, KeyError) as exc:
            raise AIExecutionError("BED_SOURCE_REQUIRED", "须选择一件已审核完整床位序列、明确预测期并核对公开投影SHA") from exc
    if roster_mode:
        from app.ai.roster_context import RosterContextBinding, selection
        from app.ai.roster_contract import RosterSource, hash_content

        try:
            identifier = selection(data["input"])
            source = RosterSource.model_validate(data["context"]["roster_source"]).model_dump(mode="json")
            bound = RosterContextBinding.model_validate(data["context"]["roster_binding"])
            if (
                identifier != bound.plan_id
                or identifier != source["problem_id"]
                or bound.projection_hash != hash_content(source)
                or any(
                    getattr(bound, key) != source[key]
                    for key in ("source_id", "content_hash", "problem_governance_hash", "scope_binding_hash", "manifest_digest", "rule_id", "recipe_digest", "input_policy_digest")
                )
            ):
                raise ValueError("完整排班公开原件与冻结输入不同")
            specialist_input = {"context": {"roster_source": source}}
        except (HTTPException, ValidationError, ValueError, TypeError, KeyError) as exc:
            raise AIExecutionError("ROSTER_SOURCE_REQUIRED", "须选择一件已审核完整排班计划并核对公开投影SHA") from exc
    if sofa_mode:
        from app.ai.sofa_context import SofaBinding, selection
        from app.ai.sofa_contract import SofaChangeSource, SofaSource, hash_content

        try:
            kind, identifier = selection(data["input"])
            key = "sofa_source" if kind == "daily" else "sofa_change_source"
            other = "sofa_change_source" if kind == "daily" else "sofa_source"
            context = data["context"]
            if other in context:
                raise ValueError("混用SOFA来源")
            source_type = SofaSource if kind == "daily" else SofaChangeSource
            source = source_type.model_validate(context[key]).model_dump(mode="json")
            bound = SofaBinding.model_validate(context["sofa_binding"])
            rule_source = source if kind == "daily" else source["current"]
            actual_id = source["assessment_id" if kind == "daily" else "change_assessment_id"]
            if (
                bound.kind != kind
                or bound.assessment_id != identifier
                or identifier != actual_id
                or bound.source_id != source["source_id"]
                or bound.content_hash != source["content_hash"]
                or bound.projection_hash != hash_content(source)
                or bound.governance_hash != source["assessment_governance_hash"]
                or any(getattr(bound, name) != rule_source[name] for name in ("rule_id", "recipe_digest", "policy_digest"))
            ):
                raise ValueError("完整SOFA原件与冻结任务引用不符")
            specialist_input = {"context": {key: source}}
        except (HTTPException, ValidationError, ValueError, TypeError, KeyError) as exc:
            raise AIExecutionError("SOFA_SOURCE_REQUIRED", "须且只能选择一件完整SOFA日评估或独立变化核实，并核对完整公开原件SHA") from exc
    if news2_mode:
        from app.ai.news2_contract import News2Source

        try:
            source = News2Source.model_validate(data["context"]["news2_source"]).model_dump(mode="json")
            if data["input"]["news2_assessment_id"] != source["assessment_id"] or data["input"]["observation_window_id"] != source["window_id"]:
                raise ValueError("NEWS2 references differ from the verified source")
        except (ValidationError, ValueError, TypeError, KeyError) as exc:
            raise AIExecutionError("NEWS2_SOURCE_REQUIRED", "须选择当前窗口的明确原点测、已审核规则和人工适用性核实来源") from exc
        specialist_input = {"context": {"news2_source": source}}
    if aki_mode:
        from app.ai.aki_contract import AkiSource

        try:
            source = AkiSource.model_validate(data["context"]["aki_source"]).model_dump(mode="json")
            if data["input"]["aki_assessment_id"] != source["assessment_id"] or data["input"]["observation_window_id"] != source["window_id"]:
                raise ValueError("KDIGO AKI references differ from the verified source")
        except (ValidationError, ValueError, TypeError, KeyError) as exc:
            raise AIExecutionError("AKI_SOURCE_REQUIRED", "须选择当前窗口的明确肾功能资料、已审核规则和人工适用性核实来源") from exc
        specialist_input = {"context": {"aki_source": source}}
    if qsofa_mode:
        from app.ai.qsofa_contract import QsofaSource

        try:
            source = QsofaSource.model_validate(data["context"]["qsofa_source"]).model_dump(mode="json")
            if data["input"]["qsofa_assessment_id"] != source["assessment_id"] or data["input"]["observation_window_id"] != source["window_id"]:
                raise ValueError("qSOFA references differ from the verified source")
        except (ValidationError, ValueError, TypeError, KeyError) as exc:
            raise AIExecutionError("QSOFA_SOURCE_REQUIRED", "须明确选择原窗口、床旁点测、GCS来源及医生当前回顾核实的qSOFA评估") from exc
        specialist_input = {"context": {"qsofa_source": source}}
    if spec.number == 62:
        from app.ai.forecast_contract import ForecastSource

        try:
            source = ForecastSource.model_validate(data["context"]["forecast_source"]).model_dump()
            horizon = data["input"]["horizon_days"]
            if type(horizon) is not int or horizon not in {7, 14}:
                raise ValueError("invalid forecast horizon")
        except (ValidationError, ValueError, TypeError, KeyError) as exc:
            raise AIExecutionError("FORECAST_SOURCE_REQUIRED", "须提供已确认的完整原日序列和明确7或14天预测跨度") from exc
        specialist_input = {"context": {"forecast_source": source}, "horizon_days": horizon}
    if provider.kind == "responses":
        return endpoint + "/responses", {
            "model": provider.model,
            "instructions": instructions,
            "input": [{"role": "user", "content": encode_json(data)}],
            "max_output_tokens": budget,
            "store": False,
            "text": {"format": {"type": "json_schema", "name": "hoim_assistance", "strict": True, "schema": result_json_schema()}},
        }
    if provider.kind == "chat":
        return endpoint + "/chat/completions", {
            "model": provider.model,
            "messages": [{"role": "system", "content": instructions}, {"role": "user", "content": encode_json(data)}],
            "max_tokens": budget,
            "temperature": float(provider.temperature),
            "response_format": {"type": "json_object"},
            "stream": False,
        }
    if provider.kind == "specialist":
        return endpoint + "/tasks", {
            "schema_version": "14"
            if inventory_mode
            else "13"
            if supply_mode
            else "12"
            if surgery_mode
            else "11"
            if bed_mode
            else "10"
            if roster_mode
            else "9"
            if sofa_mode
            else "8"
            if qsofa_mode
            else "7"
            if aki_mode
            else "6"
            if news2_mode
            else {21: "2", 36: "4", 37: "3", 62: "5"}.get(spec.number, "1"),
            "feature_key": spec.key,
            "engine": spec.engine,
            "model": provider.model,
            "instructions": instructions,
            **(
                {"store": False}
                if spec.number in {21, 36, 37, 62} or news2_mode or aki_mode or qsofa_mode or sofa_mode or roster_mode or bed_mode or surgery_mode or supply_mode or inventory_mode
                else {}
            ),
            "input": specialist_input,
        }
    raise AIExecutionError("UNSUPPORTED_PROVIDER", "模型接口类型不受支持")


def _parse_response(provider: AIProvider, spec: FeatureSpec, value: dict) -> tuple[object, int, int]:
    if provider.model.startswith("inventory:"):
        from app.ai.inventory_protocol import parse_inventory_envelope

        if provider.kind != "specialist" or spec.number != 67:
            raise AIExecutionError("INVENTORY_ADAPTER_REQUIRED", "完整库存候选证明仅由登记的独立库存服务处理")
        try:
            return parse_inventory_envelope(value, provider.model)
        except (ValidationError, ValueError, TypeError, KeyError) as exc:
            raise AIExecutionError("ADAPTER_CONTRACT_MISMATCH", "库存独立服务的版本、完整候选证明或用量不符合严格协议") from exc
    if provider.model.startswith("supply:"):
        from app.ai.supply_protocol import parse_supply_envelope

        if provider.kind != "specialist" or spec.number != 66:
            raise AIExecutionError("SUPPLY_ADAPTER_REQUIRED", "物资完整预测证据仅由登记的独立物资服务处理")
        try:
            return parse_supply_envelope(value, provider.model)
        except (ValidationError, ValueError, TypeError, KeyError) as exc:
            raise AIExecutionError("ADAPTER_CONTRACT_MISMATCH", "物资独立服务的版本、完整预测证据或用量不符合严格协议") from exc
    if provider.model.startswith("surgery:"):
        from app.ai.surgery_protocol import parse_surgery_envelope

        if provider.kind != "specialist" or spec.number != 65:
            raise AIExecutionError("SURGERY_ADAPTER_REQUIRED", "手术完整证明仅由登记的独立手术排程服务处理")
        try:
            return parse_surgery_envelope(value, provider.model)
        except (ValidationError, ValueError, TypeError, KeyError) as exc:
            raise AIExecutionError("ADAPTER_CONTRACT_MISMATCH", "手术独立服务的版本、完整证明或用量不符合严格协议") from exc
    if provider.model.startswith("bed:"):
        from app.ai.bed_protocol import parse_bed_envelope

        if provider.kind != "specialist" or spec.number != 64:
            raise AIExecutionError("BED_ADAPTER_REQUIRED", "床位完整证据仅由登记的独立床位服务处理")
        try:
            return parse_bed_envelope(value, provider.model)
        except (ValidationError, ValueError, TypeError, KeyError) as exc:
            raise AIExecutionError("ADAPTER_CONTRACT_MISMATCH", "床位独立服务的版本、完整证据或用量不符合严格协议") from exc
    if provider.model.startswith("roster:"):
        from app.ai.roster_protocol import parse_roster_envelope

        if provider.kind != "specialist" or spec.number != 63:
            raise AIExecutionError("ROSTER_ADAPTER_REQUIRED", "排班完整证明仅由登记的独立排班服务处理")
        try:
            return parse_roster_envelope(value, provider.model)
        except (ValidationError, ValueError, TypeError, KeyError) as exc:
            raise AIExecutionError("ADAPTER_CONTRACT_MISMATCH", "排班独立服务的版本、完整证明或用量不符合严格协议") from exc
    if provider.model.startswith("sofa1:"):
        from app.ai.sofa_protocol import parse_sofa_envelope

        if provider.kind != "specialist" or spec.number != 42:
            raise AIExecutionError("SOFA_ADAPTER_REQUIRED", "完整SOFA仅由其登记的独立专用服务处理")
        try:
            return parse_sofa_envelope(value, provider.model)
        except (ValidationError, ValueError, TypeError, KeyError) as exc:
            raise AIExecutionError("ADAPTER_CONTRACT_MISMATCH", "SOFA独立服务的版本、互斥原件结果或用量回执不符合严格协议") from exc
    if provider.kind == "responses":
        if value.get("status") != "completed":
            raise AIExecutionError("INCOMPLETE_RESPONSE", "模型响应未完成，请检查输出额度或模型状态")
        content = [part for item in value.get("output", []) if item.get("type") == "message" for part in item.get("content", [])]
        if any(part.get("type") == "refusal" for part in content):
            raise AIExecutionError("MODEL_REFUSAL", "模型未提供可用结果")
        raw = "".join(part.get("text", "") for part in content if part.get("type") == "output_text")
        usage = value.get("usage") or {}
        return json.loads(raw), int(usage.get("input_tokens") or 0), int(usage.get("output_tokens") or 0)
    if provider.kind == "chat":
        choice = value["choices"][0]
        if choice.get("finish_reason") != "stop" or choice["message"].get("refusal"):
            raise AIExecutionError("INCOMPLETE_RESPONSE", "模型未返回完整结果，请检查输出额度或模型状态")
        usage = value.get("usage") or {}
        return json.loads(choice["message"]["content"]), int(usage.get("prompt_tokens") or 0), int(usage.get("completion_tokens") or 0)
    news2_mode = spec.number == 41 and provider.model.startswith("news2:")
    aki_mode = spec.number == 43 and provider.model.startswith("aki:")
    qsofa_mode = spec.number == 42 and provider.model.startswith("qsofa:")
    if (
        value.get("schema_version") != ("8" if qsofa_mode else "7" if aki_mode else "6" if news2_mode else {21: "2", 36: "4", 37: "3", 62: "5"}.get(spec.number, "1"))
        or value.get("feature_key") != spec.key
        or value.get("model_version") != provider.model
    ):
        raise AIExecutionError("ADAPTER_CONTRACT_MISMATCH", "专用模型返回的功能或模型版本与登记信息不一致")
    if news2_mode and value.get("handled") is not True:
        raise AIExecutionError("NEWS2_NOT_HANDLED", "NEWS2服务未完成结构化规则处理，不能读取评分")
    if aki_mode and value.get("handled") is not True:
        raise AIExecutionError("AKI_NOT_HANDLED", "AKI服务未完成结构化判据处理，不能读取分期")
    if qsofa_mode and value.get("handled") is not True:
        raise AIExecutionError("QSOFA_NOT_HANDLED", "qSOFA服务未完成结构化核对，不能读取计数")
    if not (news2_mode or aki_mode or qsofa_mode) and value.get("applicable") is not True:
        raise AIExecutionError("OUTSIDE_VALIDATED_SCOPE", "本次输入不在专用模型声明的适用范围内")
    if spec.number in {21, 36, 37, 62} or news2_mode or aki_mode or qsofa_mode:
        name = (
            "qsofa_analysis"
            if qsofa_mode
            else "aki_analysis"
            if aki_mode
            else "news2_analysis"
            if news2_mode
            else {21: "transcription", 36: "image_analysis", 37: "ecg_analysis", 62: "forecast_analysis"}[spec.number]
        )
        if not isinstance(value["result"], dict) or name in value["result"]:
            raise ValueError("native result belongs to the versioned envelope")
        usage = value.get("usage") or {}
        return {**value["result"], name: value[name]}, int(usage.get("input_tokens") or 0), int(usage.get("output_tokens") or 0)
    return value["result"], 0, 0


async def generate(
    provider: AIProvider,
    spec: FeatureSpec,
    task_prompt: str,
    data: dict,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
    audio: BinaryIO | None = None,
    ecg: BinaryIO | None = None,
    image: BinaryIO | None = None,
) -> tuple[GenerationResult, int, int]:
    """Call only a configured endpoint; never retry billable tasks or follow redirects."""
    inputs = outputs = None
    try:
        endpoint, payload = _request(provider, spec, task_prompt, data)
        credential = provider_credential(provider)
    except HTTPException as exc:
        raise AIExecutionError("PROVIDER_CONFIGURATION", str(exc.detail)) from exc
    headers = {"Accept": "application/json"}
    if credential:
        headers["Authorization"] = "Bearer " + credential
    source = data.get("context", {}).get("audio_source") if spec.number == 21 else None
    ecg_source = data.get("context", {}).get("ecg_source") if spec.number == 37 else None
    image_source = data.get("context", {}).get("image_source") if spec.number == 36 else None
    forecast_source = data.get("context", {}).get("forecast_source") if spec.number == 62 else None
    news2_source = data.get("context", {}).get("news2_source") if spec.number == 41 and provider.model.startswith("news2:") else None
    aki_source = data.get("context", {}).get("aki_source") if spec.number == 43 and provider.model.startswith("aki:") else None
    qsofa_source = data.get("context", {}).get("qsofa_source") if spec.number == 42 and provider.model.startswith("qsofa:") else None
    extraction_mode = spec.number == 71
    sofa_mode = spec.number == 42 and provider.kind == "specialist" and provider.model.startswith("sofa1:")
    sofa_source = data.get("context", {}).get("sofa_source") if sofa_mode else None
    sofa_change_source = data.get("context", {}).get("sofa_change_source") if sofa_mode else None
    roster_mode = spec.number == 63 and provider.kind == "specialist" and provider.model.startswith("roster:")
    roster_source = data.get("context", {}).get("roster_source") if roster_mode else None
    bed_mode = spec.number == 64 and provider.kind == "specialist" and provider.model.startswith("bed:")
    bed_source = data.get("context", {}).get("bed_source") if bed_mode else None
    surgery_mode = spec.number == 65 and provider.kind == "specialist" and provider.model.startswith("surgery:")
    surgery_source = data.get("context", {}).get("surgery_source") if surgery_mode else None
    inventory_mode = spec.number == 67 and provider.kind == "specialist" and provider.model.startswith("inventory:")
    inventory_source = data.get("context", {}).get("inventory_source") if inventory_mode else None
    supply_mode = spec.number == 66 and provider.kind == "specialist" and provider.model.startswith("supply:")
    supply_source = data.get("context", {}).get("supply_source") if supply_mode else None
    response_limit = MAX_RESPONSE_BYTES
    if inventory_mode:
        from app.ai.inventory_contract import MAX_BYTES

        response_limit = MAX_BYTES
        if len(encode_json(payload).encode("utf-8")) > MAX_BYTES:
            raise AIExecutionError("INVENTORY_REQUEST_LIMIT", "库存完整场景及Prompt超过8MiB请求上限，不发送或截断")
    if supply_mode:
        from app.ai.supply_contract import MAX_BYTES

        response_limit = MAX_BYTES
        if len(encode_json(payload).encode("utf-8")) > MAX_BYTES:
            raise AIExecutionError("SUPPLY_REQUEST_LIMIT", "物资完整原量及Prompt超过8MiB请求上限，不发送或截断")
    if surgery_mode:
        from app.ai.surgery_contract import MAX_BYTES

        response_limit = MAX_BYTES
        if len(encode_json(payload).encode("utf-8")) > MAX_BYTES:
            raise AIExecutionError("SURGERY_REQUEST_LIMIT", "手术完整场景及Prompt超过8MiB请求上限，不发送或截断")
    if bed_mode:
        from app.ai.bed_contract import MAX_BYTES

        response_limit = MAX_BYTES
        if len(encode_json(payload).encode("utf-8")) > MAX_BYTES:
            raise AIExecutionError("BED_REQUEST_LIMIT", "床位完整原件及Prompt超过8MiB请求上限，不发送或截断")
    if roster_mode:
        from app.ai.roster_contract import MAX_BYTES

        response_limit = MAX_BYTES
        if len(encode_json(payload).encode("utf-8")) > MAX_BYTES:
            raise AIExecutionError("ROSTER_REQUEST_LIMIT", "排班完整原件及Prompt超过8MiB请求上限，不发送或截断")
    if sofa_mode:
        from app.ai.sofa_contract import MAX_REQUEST_BYTES
        from app.ai.sofa_contract import MAX_RESPONSE_BYTES as SOFA_RESPONSE_BYTES

        response_limit = SOFA_RESPONSE_BYTES
        if len(encode_json(payload).encode("utf-8")) > MAX_REQUEST_BYTES:
            raise AIExecutionError("SOFA_REQUEST_LIMIT", "SOFA完整原件及Prompt超过8MiB请求上限，不发送或截断")
    if spec.number == 62 and (not forecast_source or provider.kind != "specialist"):
        raise AIExecutionError("FORECAST_SOURCE_REQUIRED", "运营预测需要已确认的原历史来源及专用统计适配器")
    if spec.number == 21:
        if audio is None or not source or source.get("extension") not in AUDIO_FORMATS or source.get("media_type") != AUDIO_FORMATS[source["extension"]][1]:
            raise AIExecutionError("AUDIO_FILE_REQUIRED", "缺少已核实的原录音附件，不能以文字资料冒充语音识别")
        request_body = {"data": {"task": encode_json(payload)}, "files": {"audio": ("recording" + source["extension"], audio, source["media_type"])}}
    elif spec.number == 36:
        if image is None or not image_source or image_source.get("image_metadata", {}).get("format") != "dicom_i32le_v1" or audio is not None or ecg is not None:
            raise AIExecutionError("IMAGE_FILE_REQUIRED", "须提供已核实的原像素附件，不以报告、调阅链接或其他患者文件代替")
        request_body = {"data": {"task": encode_json(payload)}, "files": {"image": ("pixels.i32le", image, "application/octet-stream")}}
    elif spec.number == 37:
        if ecg is None or not ecg_source or ecg_source.get("signal_metadata", {}).get("format") != "wfdb16" or audio is not None:
            raise AIExecutionError("ECG_FILE_REQUIRED", "须提供已核实的原始心电采样附件，不能以文字或外部链接代替")
        request_body = {"data": {"task": encode_json(payload)}, "files": {"waveform": ("signal.dat", ecg, "application/octet-stream")}}
    else:
        if audio is not None:
            raise AIExecutionError("UNEXPECTED_AUDIO_FILE", "该任务不接受录音附件")
        request_body = {"json": payload}
    if ecg is not None and spec.number != 37:
        raise AIExecutionError("UNEXPECTED_ECG_FILE", "该任务不接受原始心电附件")
    if image is not None and spec.number != 36:
        raise AIExecutionError("UNEXPECTED_IMAGE_FILE", "该任务不接受原始影像附件")
    if extraction_mode and len(encode_json(payload).encode("utf-8")) > MAX_RESPONSE_BYTES:
        raise AIExecutionError("DOCUMENT_REQUEST_LIMIT", "完整抽取原文及Prompt超过请求容量，未发送或裁剪")
    try:
        timeout = httpx.Timeout(provider.timeout_seconds, connect=min(provider.timeout_seconds, 10))
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=False, trust_env=False, transport=transport) as client:
            async with client.stream("POST", endpoint, **request_body, headers=headers) as response:
                if response.status_code != 200:
                    raise AIExecutionError("PROVIDER_HTTP_ERROR", f"模型服务返回 HTTP {response.status_code}，请联系管理员检查配置")
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > response_limit:
                        raise AIExecutionError("RESPONSE_TOO_LARGE", "模型响应超过允许大小")
        parsed = json.loads(body, object_pairs_hook=_unique_response_pairs, parse_constant=_finite_response_constant)
        if not isinstance(parsed, dict):
            raise ValueError("response must be an object")
        if extraction_mode:
            from app.ai.document_extraction_contract import DocumentExtractionSource
            from app.ai.document_extraction_prompt import instructions_digest
            from app.ai.document_extraction_protocol import DocumentReplyError, parse_provider_draft
            from app.ai.document_extraction_result import result_for_draft

            document_source = DocumentExtractionSource.model_validate(data["context"]["document_source"])
            try:
                draft, inputs, outputs = parse_provider_draft(provider.kind, parsed, document_source, instructions_digest(task_prompt))
            except DocumentReplyError as exc:
                inputs, outputs = exc.input_tokens, exc.output_tokens
                error = AIExecutionError("DOCUMENT_PROVIDER_REPLY_INVALID", "模型未返回完整可核对的原文区间草稿，未保存候选或发布知识")
                error.usage_receipt = {"input_tokens": inputs, "output_tokens": outputs, "complete": inputs is not None and outputs is not None}
                raise error from exc
            try:
                return result_for_draft(draft, document_source, instructions_digest(task_prompt)), inputs, outputs
            except (ValueError, TypeError, KeyError, UnicodeError) as exc:
                raise AIExecutionError("DOCUMENT_RESULT_REJECTED", "完整草稿及说明无法核对或超过原TEXT容量，未保存或截断") from exc
        output, inputs, outputs = _parse_response(provider, spec, parsed)
        if min(inputs, outputs) < 0 or max(inputs, outputs) > 2000000:
            raise ValueError("invalid token accounting")
        result = validate_generation(
            output,
            data.get("evidence", []),
            spec.requires_knowledge,
            audio_source=source,
            ecg_source=ecg_source,
            image_source=image_source,
            forecast_source=forecast_source,
            news2_source=news2_source,
            aki_source=aki_source,
            qsofa_source=qsofa_source,
            sofa_source=sofa_source,
            sofa_change_source=sofa_change_source,
            roster_source=roster_source,
            bed_source=bed_source,
            surgery_source=surgery_source,
            inventory_source=inventory_source,
            supply_source=supply_source,
            supply_horizon=data.get("input", {}).get("horizon_days") if supply_mode else None,
            bed_horizon=data.get("input", {}).get("horizon_days") if bed_mode else None,
            forecast_horizon=data.get("input", {}).get("horizon_days") if spec.number == 62 else None,
            instructions_digest=hashlib.sha256(payload.get("instructions", "").encode()).hexdigest(),
            model_version=provider.model,
        )
        return result, inputs, outputs
    except AIExecutionError as exc:
        exc.input_tokens, exc.output_tokens = inputs, outputs
        raise
    except httpx.TimeoutException as exc:
        raise AIExecutionError("PROVIDER_TIMEOUT", "模型服务响应超时，请稍后重试或调整模型配置") from exc
    except httpx.HTTPError as exc:
        raise AIExecutionError("PROVIDER_UNAVAILABLE", "无法连接模型服务，请联系管理员检查部署") from exc
    except (ValueError, TypeError, KeyError, IndexError, UnicodeError) as exc:
        raise AIExecutionError("INVALID_PROVIDER_RESPONSE", "模型返回了无法解析的响应，未生成可用建议") from exc
