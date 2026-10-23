"""Versioned RCA task prompts; offline catalog export remains stdlib-only."""

from app.ai.rca_evidence_prompt import SYSTEM_PROMPT as SYSTEM_PROMPT
from app.ai.rca_evidence_prompt import TASK_PROMPT as _DRAFT_CONTRACT

PROMPT_VERSION = "rca_evidence_task_v1"
TASK_PROMPT = "任务协议版本：" + PROMPT_VERSION + "。仅处理本次明确发布Case的有限资料。\n" + _DRAFT_CONTRACT
