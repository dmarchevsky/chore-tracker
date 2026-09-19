"""`just eval-replay` entrypoint — re-decide stored verifications, print what moved."""

from __future__ import annotations

import argparse
import asyncio
import sys

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import get_settings
from eval.replay import as_json, format_report, replay


async def _main(url: str, limit: int, want_json: bool) -> int:
    engine = create_async_engine(url)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as db:
            rows, skipped = await replay(db, limit=limit)
    finally:
        await engine.dispose()
    print(as_json(rows, skipped) if want_json else format_report(rows, skipped))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--url", default=None, help="database URL (default: the app's)")
    ap.add_argument("--limit", type=int, default=500)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    return asyncio.run(_main(args.url or get_settings().database_url, args.limit, args.json))


if __name__ == "__main__":
    sys.exit(main())
