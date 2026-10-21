"""Deterministic visible candidate counts, never detection/anonymous claims."""

from pydantic import TypeAdapter

from app.ai.deidentification_contract import LIMITATIONS
from app.ai.deidentification_draft import CATEGORIES, PARTIAL_NOTICE, bounded_json, checked_source, validate_draft
from app.ai.deidentification_spans import digest
from app.ai.research_cohort_contract import SHA


def build_result(source, draft, instructions_digest):
    source = checked_source(source)
    TypeAdapter(SHA).validate_python(instructions_digest, strict=True)
    draft = validate_draft(source, draft)
    documents = source["documents"]
    result = {
        "schema_version": "deidentification_result_v1",
        "source_id": source["source_id"],
        "source_projection_hash": digest(source),
        "instructions_digest": instructions_digest,
        "draft": draft,
        "assessment_status": "model_suggestions_not_reviewed",
        "coverage": "partial_candidates_only",
        "candidate_count": len(draft["candidates"]),
        "candidate_category_counts": [{"category": category, "count": sum(item["category"] == category for item in draft["candidates"])} for category in CATEGORIES],
        "selected_field_counts": {
            "total": len(documents),
            "null": sum(item["text"] is None for item in documents),
            "empty": sum(item["text"] == "" for item in documents),
            "nonempty": sum(item["text"] is not None and item["text"] != "" for item in documents),
        },
        "anonymity_guaranteed": False,
        "manual_selection_required": True,
        "review_created": False,
        "release_created": False,
        "partial_notice": PARTIAL_NOTICE,
        "limitations": list(LIMITATIONS),
    }
    bounded_json(result)
    return result


def validate_result(source, result, instructions_digest):
    if type(result) is not dict or "draft" not in result:
        raise ValueError("Closed complete candidate result required")
    expected = build_result(source, result["draft"], instructions_digest)
    # Canonical bytes also distinguish bool from int in server-fixed fields.
    if bounded_json(result) != bounded_json(expected):
        raise ValueError("Candidate result or deterministic counts differ")
    return result
