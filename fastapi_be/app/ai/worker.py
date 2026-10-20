"""Dedicated durable AI task worker: python -m app.ai.worker."""

import argparse
import asyncio
import logging

from app.ai.runtime import claim_next_run, execute_claimed, expire_interrupted_runs

logger = logging.getLogger("ai.worker")


async def process_one() -> bool:
    """Claim work transactionally and call the provider outside the SQL session."""
    from app import database

    with database.SessionLocal() as db:
        expire_interrupted_runs(db)
        claim = claim_next_run(db)
    if claim is None:
        return False
    await execute_claimed(*claim)
    return True


async def worker_loop(interval: float) -> None:
    """Retry queue polling after infrastructure failures, without replaying inference calls."""
    while True:
        try:
            worked = await process_one()
        except Exception:
            logger.warning("AI worker queue unavailable; retrying poll")
            worked = False
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
