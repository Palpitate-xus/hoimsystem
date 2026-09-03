"""Dedicated scheduler process entry point."""

import asyncio

from app.scheduler import scheduler_loop


def main() -> None:
    asyncio.run(scheduler_loop(run_immediately=True))


if __name__ == "__main__":
    main()
