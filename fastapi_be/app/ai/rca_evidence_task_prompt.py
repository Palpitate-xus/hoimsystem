"""Versioned RCA task prompts; offline catalog export remains stdlib-only."""

from app.ai.rca_evidence_prompt import SYSTEM_PROMPT as SYSTEM_PROMPT
from app.ai.rca_evidence_prompt import TASK_PROMPT as _DRAFT_CONTRACT

PROMPT_VERSION = "rca_evidence_task_v1"
TASK_PROMPT = (
    "任务协议版本："
    + PROMPT_VERSION
    + "。仅处理本次明确发布Case的有限资料。\n"
    + _DRAFT_CONTRACT
    + "\n表达要求：hypothesis 简要描述待调查的具体关联或条件，不把推测写成根因。evidence_needed、investigation_questions 和 clarification_questions 指向实际缺少的证据或需确认的事实，合并重复项，避免泛泛要求‘加强管理’或‘进一步调查’。"
    "每项通常一至三句，不在每项复述完整系统限制。逐字引文不作润色，冲突证据和重要未知不因精简而省略。"
)
