"""The reviewed classifier's exact native-input scope; calibration is never guessed."""

import hashlib
import uuid
from decimal import Decimal, InvalidOperation
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.ai.ecg_model import LEADS, canonical_json


class ECGLead(BaseModel):
    model_config = ConfigDict(extra="ignore")
    name: str = Field(min_length=1, max_length=5)
    gain: str = Field(min_length=1, max_length=40)
    baseline: int = Field(ge=-2147483647, le=2147483647, strict=True)
    unit: Literal["mV", "uV", "µV", "μV", "V"]
    missing_samples: int = Field(ge=0, le=1000, strict=True)

    @model_validator(mode="after")
    def explicit_calibration(self):
        try:
            gain = Decimal(self.gain)
            if not gain.is_finite() or gain <= 0 or not -12 <= gain.adjusted() <= 12:
                raise ValueError()
        except (InvalidOperation, ValueError) as exc:
            raise ValueError("原增益须为明确的有限正数") from exc
        if self.name not in LEADS or self.missing_samples:
            raise ValueError("该模型只接受实际标准12导联且无缺失采样，不替代导联或补值")
        return self


class ECGSignal(BaseModel):
    model_config = ConfigDict(extra="ignore")
    format: Literal["wfdb16"]
    sample_rate_hz: str = Field(min_length=1, max_length=40)
    sample_count: int = Field(ge=1000, le=1000, strict=True)
    channels: int = Field(ge=12, le=12, strict=True)
    duration_ms: int = Field(ge=10000, le=10000, strict=True)
    missing_sample_value: int = Field(ge=-32768, le=-32768, strict=True)
    leads: list[ECGLead] = Field(min_length=12, max_length=12)

    @model_validator(mode="after")
    def original_scope(self):
        try:
            if Decimal(self.sample_rate_hz) != Decimal(100):
                raise ValueError()
        except (InvalidOperation, ValueError) as exc:
            raise ValueError("该模型限原100Hz、1000样本、10秒，不自动重采样、裁剪或填充") from exc
        if set(lead.name for lead in self.leads) != set(LEADS):
            raise ValueError("实际导联须为完整且唯一的标准12导联，MLII不视为II")
        return self


class ECGSource(BaseModel):
    model_config = ConfigDict(extra="ignore")
    asset_id: str = Field(min_length=36, max_length=36)
    header_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    signal_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    content_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    signal_byte_size: int = Field(ge=24000, le=24000, strict=True)
    source_id: str = Field(min_length=1, max_length=100)
    signal_metadata: ECGSignal

    @model_validator(mode="after")
    def source_identity(self):
        if str(uuid.UUID(self.asset_id)) != self.asset_id or self.source_id != f"ecg:{self.asset_id}:{self.content_hash[:12]}":
            raise ValueError("原心电引用与原记录标识不一致")
        identity = {"format": self.signal_metadata.format, "header_hash": self.header_hash, "signal_hash": self.signal_hash}
        if hashlib.sha256(canonical_json(identity).encode()).hexdigest() != self.content_hash:
            raise ValueError("原心电组合哈希与原文件哈希声明不一致")
        return self
