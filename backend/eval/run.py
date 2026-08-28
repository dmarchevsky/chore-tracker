"""`just eval` entrypoint — run the calibration harness and print the report.

uv run python -m eval.run [--dir eval/labeled] [--auto-pass 0.85] [--auto-fail 0.35]
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from app.config import get_settings
from eval.harness import format_report, run


def main() -> int:
    ap = argparse.ArgumentParser(description="Vision-model calibration harness (spec §6.3).")
    ap.add_argument("--dir", default="eval/labeled", type=Path)
    ap.add_argument("--auto-pass", type=float, default=None)
    ap.add_argument("--auto-fail", type=float, default=None)
    args = ap.parse_args()

    if not args.dir.is_dir():
        print(f"no labeled set at {args.dir}/ — see eval/README.md for the folder layout")
        return 0

    s = get_settings()
    ap_thr = args.auto_pass if args.auto_pass is not None else s.auto_pass_threshold
    af_thr = args.auto_fail if args.auto_fail is not None else s.auto_fail_threshold
    print(f"model={s.llm_vision_model or '(unset)'} endpoint={s.llm_vision_base_url}")
    print(f"thresholds: auto_pass={ap_thr} auto_fail={af_thr}\n")

    results = asyncio.run(run(args.dir, auto_pass=ap_thr, auto_fail=af_thr))
    if not results:
        print(f"no labeled images found under {args.dir}/")
        return 0
    print(format_report(results))
    return 0


if __name__ == "__main__":
    sys.exit(main())
