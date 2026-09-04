"""Worker loop: scheduler reconciliation + verification queue drain.

No timers: every tick is a fresh query over DB state (spec §8.3). A full scheduler pass
(generate + open + remind + missed + settle) runs on startup and hourly; the cheap
OPEN/MISSED transitions, the T-30min reminder sweep, the settlement of misses whose delay
has elapsed, and the verification-queue drain run every minute. Stuck jobs are
requeued on startup.
"""

from __future__ import annotations

import asyncio
import logging

from app.db import SessionLocal
from app.services import retention
from app.services.heartbeat import record_tick
from app.services.scheduler import (
    detect_missed,
    open_due_windows,
    reconcile,
    send_due_reminders,
)
from app.services.settlement import settle_missed
from app.worker import verify
from app.worker.queue import requeue_stuck

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
                reminded = await send_due_reminders(db)
                missed = await detect_missed(db)
                settled = await settle_missed(db)
                if opened or reminded or missed or settled:
                    log.info(
                        "tick: opened=%d reminded=%d missed=%d settled=%d",
                        opened,
                        reminded,
                        missed,
                        settled,
                    )
            await record_tick(db)
            await db.commit()
        except Exception:
            await db.rollback()
            log.exception("scheduler tick failed")


async def retention_tick() -> None:
    """Stateless data-retention sweep (spec §5, §14 Q2); no-ops once caught up."""
    async with SessionLocal() as db:
        try:
            stats = await retention.run_all(db)
            await db.commit()
            if any(stats.values()):
                log.info("retention: %s", stats)
        except Exception:
            await db.rollback()
            log.exception("retention sweep failed")


async def verify_tick() -> None:
    async with SessionLocal() as db:
        try:
            n = await verify.drain(db)
            if n:
                log.info("verify: processed %d job(s)", n)
        except Exception:
            await db.rollback()
            log.exception("verify drain failed")


async def startup() -> None:
    async with SessionLocal() as db:
        moved = await requeue_stuck(db)
        await db.commit()
        if moved:
            log.info("startup: requeued %d stuck verification job(s)", moved)
    await scheduler_tick(full=True)
    await retention_tick()


async def run_forever(*, tick_seconds: int = TICK_SECONDS) -> None:
    log.info("scheduler loop started")
    await startup()
    tick = 0
    while True:
        await asyncio.sleep(tick_seconds)
        tick += 1
        full = tick % TICKS_PER_FULL_PASS == 0
        await scheduler_tick(full=full)
        await verify_tick()
        if full:
            await retention_tick()
