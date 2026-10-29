"""Dedicated durable AI task worker: python -m app.ai.worker."""

import argparse
import asyncio
import logging

from app.ai.runtime import _log_execution_failure, claim_next_run, execute_claimed, expire_interrupted_runs

logger = logging.getLogger("ai.worker")


async def process_one() -> bool:
    """Claim work transactionally and call the provider outside the SQL session."""
    from app import database
    from app.ai.deidentification_dispatch import DeidentificationClaim
    from app.ai.deidentification_runtime import expire_interrupted_deidentification_runs
    from app.ai.research_cohort_execution import ResearchClaim, recover_interrupted_research_runs

    phase, run_id, feature = "recover_research", None, None
    try:
        # Research recovery requires a genuinely fresh RR view, not the generic
        # expiry Session which may already have read another native domain.
        with database.SessionLocal() as recovery_db:
            recover_interrupted_research_runs(recovery_db)
        phase = "recover_deidentification"
        with database.SessionLocal() as recovery_db:
            expire_interrupted_deidentification_runs(recovery_db)
        phase = "recover_tasks"
        with database.SessionLocal() as db:
            expire_interrupted_runs(db)
            phase = "claim"
            claim = claim_next_run(db)
        if claim is None:
            return False
        phase = "execute"
        if isinstance(claim, DeidentificationClaim):
            run_id, feature = claim.run_id, "deidentification"
            await execute_claimed(claim.run_id, claim.lease_token, deidentification_claim_event_id=claim.claim_event_id)
        elif isinstance(claim, ResearchClaim):
            run_id, feature = claim.run_id, "research_cohort"
            await execute_claimed(claim.run_id, claim.lease_token, research_claim_event_id=claim.claim_event_id)
        else:
            run_id = claim[0]
            await execute_claimed(*claim)
        return True
    except Exception as exc:
        _log_execution_failure(run_id, feature, phase, exc, event_logger=logger)
        raise


async def worker_loop(interval: float) -> None:
    """Retry queue polling after infrastructure failures, without replaying inference calls."""
    retry_base = min(max(interval, 1.0), 60.0)
    retry_delay = retry_base
    while True:
        try:
            worked = await process_one()
        except Exception as exc:
            # Exception messages can contain SQL parameters or clinical text.
            logger.warning(
                "AI worker poll failed run_id=- feature=- phase=poll error_type=%s retry_seconds=%s",
                type(exc).__name__,
                retry_delay,
            )
            await asyncio.sleep(retry_delay)
            retry_delay = min(retry_delay * 2, 60.0)
            continue
        retry_delay = retry_base
        if not worked:
            await asyncio.sleep(interval)


def main() -> None:
    """Run one worker per process; deployments may scale multiple processes safely."""
    parser = argparse.ArgumentParser(description="HOIM durable AI worker")
    parser.add_argument("--once", action="store_true", help="process at most one queued task")
    parser.add_argument("--interval", type=float, default=2.0)
    args = parser.parse_args()
    if not 0.1 <= args.interval <= 60:
        parser.error("interval must be between 0.1 and 60 seconds")
    asyncio.run(process_one() if args.once else worker_loop(args.interval))


if __name__ == "__main__":
    main()
