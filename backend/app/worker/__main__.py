"""Worker entrypoint: scheduler ticks + (Phase 4) verification queue consumer.

Phase 2 runs the stateless scheduler loop — reconcile desired occurrence state from the
DB, no in-memory timers (spec §8.3). Phase 4 adds the `FOR UPDATE SKIP LOCKED` queue.
"""

from __future__ import annotations

import asyncio
import logging

from app import obs
from app.worker.scheduler import run_forever

obs.configure_logging()
log = logging.getLogger("chorekeeper.worker")


async def run() -> None:
    log.info("worker started")
    await run_forever()


def main() -> None:
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        log.info("worker stopped")


if __name__ == "__main__":
    main()
