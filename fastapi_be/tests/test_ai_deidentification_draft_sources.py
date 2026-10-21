"""The pure candidate contract consumes an actual purpose-authorized Source.

This is still no provider call: external-model permission is checked separately
by the future dispatch and is not inferred from local source proof success.
"""

from app.ai.deidentification_draft import checked_source, validate_draft
from app.ai.deidentification_models import AIDeidentificationExportRelease, AIDeidentificationReview
from app.ai.deidentification_prompt import TASK_PROMPT, instructions_digest
from app.ai.deidentification_result import build_result, validate_result
from app.ai.deidentification_spans import digest
from tests.test_ai_deidentification_draft import draft_for
from tests.test_ai_deidentification_reviews import published_source
from tests.test_ai_deidentification_sources import deid_case as deid_case  # noqa: F401
from tests.test_ai_research_cohort_sources import research_case as research_case  # noqa: F401


def test_actual_complete_source_public_projection_yields_only_unreviewed_literal_model_candidates(db_session, deid_case):
    source = published_source(db_session, deid_case)
    public = checked_source(source["public_source"])
    assert public == source["public_source"]
    draft = validate_draft(public, draft_for(public))
    assert draft["source_projection_hash"] == digest(source["public_source"])
    result = build_result(public, draft, instructions_digest(TASK_PROMPT))
    assert validate_result(public, result, instructions_digest(TASK_PROMPT)) == result
    assert result["draft"]["candidates"][0]["quote"] == "张三"
    assert result["assessment_status"] == "model_suggestions_not_reviewed"
    assert db_session.query(AIDeidentificationReview).count() == 0
    assert db_session.query(AIDeidentificationExportRelease).count() == 0
    assert deid_case[-1][0].symptom.startswith("\ufeff张三\r\n😀é")
