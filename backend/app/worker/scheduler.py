"""Worker-side scheduler loop.

No timers: every tick is a fresh query over DB state (spec §8.3). A full pass
(generate + open + missed) runs on startup and hourly; the cheap OPEN/MISSED
transitions run every minute so a due chore is marked promptly.
"""

from __future__ import annotations

import asyncio
import logging

from app.db import SessionLocal
from app.services.scheduler import detect_missed, open_due_windows, reconcile

log = logging.getLogger("chorekeeper.worker.scheduler")

TICK_SECONDS = 60
TICKS_PER_FULL_PASS = 60  # hourly


async def scheduler_tick(*, full: bool) -> None:
    async with SessionLocal() as db:
        try:
            if full:
                await reconcile(db)
            else:
                opened = await open_due_windows(db)
                missed = await detect_missed(db)
                if opened or missed:
                    log.info("tick: opened=%d missed=%d", opened, missed)
            await db.commit()
        except Exception:
            await db.rollback()
            log.exception("scheduler tick failed")


async def run_forever(*, tick_seconds: int = TICK_SECONDS) -> None:
    log.info("scheduler loop started")
    await scheduler_tick(full=True)  # startup reconciliation
    tick = 0
    while True:
        await asyncio.sleep(tick_seconds)
        tick += 1
        await scheduler_tick(full=tick % TICKS_PER_FULL_PASS == 0)
