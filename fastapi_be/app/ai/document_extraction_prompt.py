"""Fixed original-span system boundary with a versioned administrator task."""

import hashlib

from app.ai.document_extraction_prompt_constants import EXTRACTION_SYSTEM_PROMPT


def system_prompt_for(context):
    if "research_variable_binding" in context:
        from app.ai.research_variables_prompt import SYSTEM_PROMPT

        return SYSTEM_PROMPT
    from app.ai.coding_evidence_prompt import system_prompt_for as coding_system_prompt_for

    return EXTRACTION_SYSTEM_PROMPT if "document_binding" in context else coding_system_prompt_for(context)


def instructions_digest(task_prompt):
    return hashlib.sha256((EXTRACTION_SYSTEM_PROMPT + "\n\n" + task_prompt).encode("utf-8")).hexdigest()
