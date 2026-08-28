"""Calibration harness (spec §6.3 rule 6).

Runs a labeled folder of photos through the current prompt + model and reports
precision / recall / accuracy and mean latency per chore type. Prompt or threshold
changes without this are guesswork.

Folder layout::

    eval/labeled/<chore_type>/pass/*.jpg      # the chore genuinely passed
    eval/labeled/<chore_type>/fail/*.jpg

Each ``<chore_type>`` needs an entry in ``checklists`` below (or a checklists.json in the
folder) giving the yes/no questions and which are required.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path

from app.services.verification import build_task_prompt, derive_verdict
from app.services.verification.llm import LLMError, run_vision

# Seeds for the four brief chores; override per-folder with checklists.json.
DEFAULT_CHECKLISTS: dict[str, dict] = {
    "sink": {
        "checks": [
            "Is the sink basin free of dishes, cups, pans and utensils?",
            "Is the counter around the sink free of dirty dishes?",
        ],
        "required": [1, 2],
    },
    "room": {
        "checks": [
            "Is the floor clear of clothes and clutter?",
            "Is the bed made?",
        ],
        "required": [1, 2],
    },
}

_LABEL_DIRS = {"pass": True, "fail": False}


@dataclass
class Counts:
    tp: int = 0
    fp: int = 0
    tn: int = 0
    fn: int = 0
    review: int = 0
    error: int = 0
    latencies_ms: list[float] = field(default_factory=list)

    @property
    def total(self) -> int:
        return self.tp + self.fp + self.tn + self.fn + self.review + self.error

    def precision(self) -> float | None:
        d = self.tp + self.fp
        return self.tp / d if d else None

    def recall(self) -> float | None:
        d = self.tp + self.fn
        return self.tp / d if d else None

    def accuracy(self) -> float | None:
        graded = self.tp + self.fp + self.tn + self.fn
        return (self.tp + self.tn) / graded if graded else None

    def mean_latency_ms(self) -> float | None:
        return sum(self.latencies_ms) / len(self.latencies_ms) if self.latencies_ms else None


def discover(root: Path) -> dict[str, list[tuple[Path, bool]]]:
    """chore_type -> [(image_path, expected_pass)]."""
    out: dict[str, list[tuple[Path, bool]]] = {}
    for chore_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        items: list[tuple[Path, bool]] = []
        for label, expected in _LABEL_DIRS.items():
            for img in sorted((chore_dir / label).glob("*.jp*g")):
                items.append((img, expected))
        if items:
            out[chore_dir.name] = items
    return out


def _checklist_for(chore_type: str, root: Path) -> dict:
    override = root / chore_type / "checklists.json"
    if override.is_file():
        return json.loads(override.read_text())
    return DEFAULT_CHECKLISTS.get(
        chore_type, {"checks": ["Does the photo show the chore is done?"], "required": [1]}
    )


def score_one(outcome: str, expected_pass: bool, counts: Counts) -> None:
    if outcome == "pass":
        counts.tp += expected_pass
        counts.fp += not expected_pass
    elif outcome == "fail":
        counts.tn += not expected_pass
        counts.fn += expected_pass
    elif outcome == "error":
        counts.error += 1
    else:  # needs_review / retake
        counts.review += 1


async def run(root: Path, *, auto_pass: float = 0.85, auto_fail: float = 0.35) -> dict[str, Counts]:
    results: dict[str, Counts] = {}
    for chore_type, items in discover(root).items():
        spec = _checklist_for(chore_type, root)
        required = set(spec.get("required") or range(1, len(spec["checks"]) + 1))
        counts = Counts()
        for img, expected in items:
            prompt = build_task_prompt(
                chore_title=chore_type, photo_label=None, checks=spec["checks"]
            )
            t0 = time.perf_counter()
            try:
                resp, _, _ = await run_vision(task_prompt=prompt, images=[img.read_bytes()])
            except LLMError:
                counts.error += 1
                continue
            counts.latencies_ms.append((time.perf_counter() - t0) * 1000)
            verdict = derive_verdict(
                resp,
                required_ids=required or None,
                auto_pass_threshold=auto_pass,
                auto_fail_threshold=auto_fail,
            )
            score_one(verdict.outcome, expected, counts)
        results[chore_type] = counts
    return results


def _f(v: float | None) -> str:
    return f"{v:.2f}" if v is not None else "  -"


def format_report(results: dict[str, Counts]) -> str:
    head = f"{'chore':<12} {'n':>4} {'prec':>6} {'recall':>7} {'acc':>6}"
    head += f" {'review':>7} {'err':>5} {'ms':>7}"
    lines = [head]
    for name, c in results.items():
        lines.append(
            f"{name:<12} {c.total:>4} {_f(c.precision()):>6} {_f(c.recall()):>7} "
            f"{_f(c.accuracy()):>6} {c.review:>7} {c.error:>5} "
            f"{(f'{c.mean_latency_ms():.0f}' if c.mean_latency_ms() else '-'):>7}"
        )
    return "\n".join(lines)
