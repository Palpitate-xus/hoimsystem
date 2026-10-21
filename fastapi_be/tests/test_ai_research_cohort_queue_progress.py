"""Actual bounded queue progress without terminating corrupt native artifacts."""

import pytest
from sqlalchemy import event, text

from app.ai import runtime
from app.ai.models import AIFeatureConfig, AIRun
from app.ai.research_cohort_artifact_models import AIResearchCohortRunArtifact
from app.ai.research_cohort_execution import ResearchClaim
from app.ai.research_cohort_runtime import create_research_run
from tests.test_ai_research_cohort_execution import runtime_case as runtime_case  # noqa: F401
from tests.test_ai_research_cohort_storage import artifact_foreign_keys as artifact_foreign_keys  # noqa: F401
from tests.test_ai_research_cohort_storage import configured as configured  # noqa: F401
from tests.test_ai_research_cohort_storage import research_case as research_case  # noqa: F401
from tests.test_ai_research_cohort_storage import storage_rows as storage_rows  # noqa: F401


def test_actual_128_erased_research_artifacts_do_not_starve_two_later_valid_jobs(runtime_case):
    case, db = runtime_case, runtime_case["db"]
    config = db.get(AIFeatureConfig, "research_cohort")
    config.daily_limit = 1000
    config.revision += 1
    db.commit()
    blocked = []
    for _ in range(128):
        identifier = create_research_run(db, case["actor"], {"research_cohort_case_id": case["case_id"]})
        blocked.append(identifier)
    db.execute(
        text("UPDATE hoimsystem_ai_run SET feature_key='operations_qa',create_time='2000-01-01 00:00:00' WHERE run_id IN (" + ",".join(":id" + str(i) for i in range(128)) + ")"),
        {"id" + str(i): v for i, v in enumerate(blocked)},
    )
    db.commit()
    expected = [create_research_run(db, case["actor"], {"research_cohort_case_id": case["case_id"]}) for _ in range(2)]
    outputs = []

    def observe(conn, cursor, sql, params, context, many):
        if sql.lstrip().lower().startswith("select"):
            outputs.extend(c[0] for c in cursor.description or ())

    event.listen(db.bind, "after_cursor_execute", observe)
    try:
        claimed = [runtime.claim_next_run(db), runtime.claim_next_run(db)]
    finally:
        event.remove(db.bind, "after_cursor_execute", observe)
    actual = [value.run_id if isinstance(value, ResearchClaim) else value for value in claimed]
    assert set(actual) == set(expected), (actual, expected)
    assert not {"input_json", "context_metadata_json", "evidence_json", "result_json", "source_json"}.intersection(outputs)
    assert db.query(AIRun).filter(AIRun.run_id.in_(blocked), AIRun.status == "queued").count() == 128
    assert db.query(AIResearchCohortRunArtifact).filter(AIResearchCohortRunArtifact.run_id.in_(blocked), AIResearchCohortRunArtifact.usage_event_id.is_(None)).count() == 128


@pytest.mark.asyncio
async def test_valid_platform_patient_role_is_claimed_then_denied_by_real_research_authority_with_known_zero(runtime_case, monkeypatch):
    import httpx

    from app import database
    from app.ai.research_cohort_receipts import read_usage_event, usage

    case, db = runtime_case, runtime_case["db"]
    monkeypatch.setattr(database, "SessionLocal", case["factory"])
    identifier = create_research_run(db, case["actor"], {"research_cohort_case_id": case["case_id"]})
    # 'patient' is a legitimate platform role; queue qualification must not
    # replace the actual dedicated business/Source authorization with a filter.
    db.execute(text("UPDATE hoimsystem_users SET user_role='patient' WHERE user_id=:id"), {"id": case["actor_id"]})
    db.commit()
    claim = runtime.claim_next_run(db)
    assert isinstance(claim, ResearchClaim) and claim.run_id == identifier
    calls = []
    await runtime.execute_claimed(identifier, claim.lease_token, research_claim_event_id=claim.claim_event_id, transport=httpx.MockTransport(lambda r: calls.append(r)))
    assert calls == [] and read_usage_event(db, identifier)["usage"] == usage(0, 0, False)
    assert db.query(AIRun.status).filter_by(run_id=identifier).scalar() == "failed"


def test_128_unknown_platform_role_orphans_do_not_block_two_later_claims_or_invent_receipts(runtime_case):
    import uuid

    from app.models import User

    case, db = runtime_case, runtime_case["db"]
    unknown = User(username="unknown-queue-owner-" + uuid.uuid4().hex, user_role="unrecognized")
    db.add(unknown)
    db.flush()
    ids = [str(uuid.uuid4()) for _ in range(128)]
    for identifier in ids:
        db.add(
            AIRun(
                run_id=identifier, feature_key="research_cohort", requested_by=unknown.user_id, prompt_hash="1" * 64, context_digest="2" * 64, create_time=__import__("datetime").datetime(2000, 1, 1)
            )
        )
    db.commit()
    expected = [create_research_run(db, case["actor"], {"research_cohort_case_id": case["case_id"]}) for _ in range(2)]
    claims = [runtime.claim_next_run(db), runtime.claim_next_run(db)]
    assert {claim.run_id for claim in claims if isinstance(claim, ResearchClaim)} == set(expected)
    assert db.query(AIRun).filter(AIRun.run_id.in_(ids), AIRun.status == "queued", AIRun.error_code.is_(None)).count() == 128
    assert db.query(AIResearchCohortRunArtifact).filter(AIResearchCohortRunArtifact.run_id.in_(ids)).count() == 0
