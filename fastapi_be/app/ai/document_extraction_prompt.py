"""Fixed original-span system boundary with a versioned administrator task."""

import hashlib

from app.ai.catalog import COMMON_SYSTEM_PROMPT
from app.ai.document_extraction_contract import EXTRACTION_SYSTEM_PROMPT


def system_prompt_for(context):
    return EXTRACTION_SYSTEM_PROMPT if "document_binding" in context else COMMON_SYSTEM_PROMPT


def instructions_digest(task_prompt):
    return hashlib.sha256((EXTRACTION_SYSTEM_PROMPT + "\n\n" + task_prompt).encode("utf-8")).hexdigest()
