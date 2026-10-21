"""Actual fixed feature contracts shared by governance and offline export."""

from types import MappingProxyType

from app.ai.catalog import COMMON_SYSTEM_PROMPT
from app.ai.charge_reconciliation_prompt import CHARGE_RECONCILIATION_SYSTEM_PROMPT
from app.ai.coding_evidence_prompt import CODING_SYSTEM_PROMPT
from app.ai.document_extraction_prompt import EXTRACTION_SYSTEM_PROMPT
from app.ai.drug_label_prompt import SYSTEM_PROMPT as DRUG_LABEL_SYSTEM_PROMPT
from app.ai.satisfaction_prompt import SATISFACTION_SYSTEM_PROMPT

SYSTEM_PROMPT_OVERRIDES = MappingProxyType(
    {
        "drg_evidence_review": CODING_SYSTEM_PROMPT,
        "charge_reconciliation": CHARGE_RECONCILIATION_SYSTEM_PROMPT,
        "feedback_analysis": SATISFACTION_SYSTEM_PROMPT,
        "guideline_ingestion": EXTRACTION_SYSTEM_PROMPT,
        "drug_label_extraction": DRUG_LABEL_SYSTEM_PROMPT,
    }
)


def system_prompt_for_feature(spec):
    return SYSTEM_PROMPT_OVERRIDES.get(spec.key, COMMON_SYSTEM_PROMPT)
