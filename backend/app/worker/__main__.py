"""Worker entrypoint: scheduler ticks + verification queue consumer.

Phase 1 is a heartbeat only. Phase 2 adds `generate_occurrences` / `detect_missed`
(stateless reconciliation from the DB — no in-memory timers, spec §8.3); Phase 4 adds
the `FOR UPDATE SKIP LOCKED` verification queue.
"""

from __future__ import annotations

import asyncio
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("chorekeeper.worker")

TICK_SECONDS = 60


async def run() -> None:
    log.info("worker started (phase 1 heartbeat)")
    while True:
        # TODO(phase2): startup_reconcile(); generate_occurrences(); detect_missed()
        await asyncio.sleep(TICK_SECONDS)
        log.debug("tick")


def main() -> None:
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        log.info("worker stopped")


if __name__ == "__main__":
    main()
