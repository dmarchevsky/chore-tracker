"""Replay real verifications through the current decision logic (spec §6.3 rule 6).

The labelled-photo harness next door answers "is the model any good?" and needs the model,
a GPU and twenty minutes. This answers a narrower question much faster: **given what the
model already said, would today's code decide the same thing it decided then?**

Every verification row keeps the model's raw response, so the household's own history is a
regression set that nobody had to label. It needs no model, no GPU and no network, which
means it can run in CI — and it is the thing that would have caught a change like banding
a "no" turning yesterday's auto-fails into review items, before it reached anyone's phone.

    just eval-replay                 # against the dev stack's database
    just eval-replay --url <dsn>     # against a restored backup

It is read-only: it opens the database, reads verifications, and writes nothing.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Chore, ChoreOccurrence, Verification
from app.services.verification.llm import ModelResponse
from app.services.verification.verdict import derive_verdict
from app.worker.verify import _OUTCOME_TO_VERDICT as OUTCOME_TO_VERDICT


@dataclass
class Replayed:
    verification_id: str
    chore: str
    then: str
    now: str
    #: `now` expressed in the same vocabulary as `then`, which is what is compared.
    now_verdict: str

    @property
    def changed(self) -> bool:
        return self.then != self.now_verdict


def _model_response(raw: dict | None) -> ModelResponse | None:
    """Dig the model's JSON back out of a stored chat-completion envelope."""
    if not raw:
        return None
    try:
        content = raw["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        return None
    try:
        return ModelResponse.model_validate_json(content)
    except Exception:
        # A row stored before the schema settled, or a repair that never parsed. Not worth
        # failing the whole replay over — it is counted as skipped.
        return None


def _checklist(chore: Chore | None) -> tuple[set[int] | None, dict[int, str]]:
    items = (chore.verification_checklist if chore else None) or []
    required = {it["id"] for it in items if it.get("required", True)}
    expected = {it["id"]: it.get("expect", "yes") for it in items}
    return (required or None), expected


async def replay(db: AsyncSession, *, limit: int = 500) -> tuple[list[Replayed], int]:
    """Re-decide every stored verification. Returns (rows, skipped)."""
    rows = (
        (
            await db.execute(
                select(Verification, ChoreOccurrence, Chore)
                .join(ChoreOccurrence, ChoreOccurrence.id == Verification.occurrence_id)
                .outerjoin(Chore, Chore.id == ChoreOccurrence.chore_id)
                .where(Verification.raw_response.is_not(None))
                .order_by(Verification.created_at.desc())
                .limit(limit)
            )
        )
        .tuples()
        .all()
    )

    out: list[Replayed] = []
    skipped = 0
    for v, _occ, chore in rows:
        parsed = _model_response(v.raw_response)
        if parsed is None:
            skipped += 1
            continue
        required, expected = _checklist(chore)
        verdict = derive_verdict(
            parsed,
            required_ids=required,
            auto_pass_threshold=float(chore.auto_pass_threshold) if chore else 0.85,
            auto_fail_threshold=float(chore.auto_fail_threshold) if chore else 0.35,
            flags=[],  # the stored verdict already accounted for them; this isolates logic
            expected=expected,
        )
        out.append(
            Replayed(
                verification_id=str(v.id),
                chore=chore.title if chore else "(deleted chore)",
                then=str(v.verdict),
                now=verdict.outcome,
                # Compare like with like. What is stored on the row is a Verdict, and the
                # worker maps several outcomes onto one of those — "retake" and
                # "needs_review" are both Verdict.needs_review. Comparing the raw outcome
                # against the stored verdict reported a change on the very first real row
                # replayed, and it was not one.
                now_verdict=str(OUTCOME_TO_VERDICT[verdict.outcome]),
            )
        )
    return out, skipped


def format_report(rows: list[Replayed], skipped: int) -> str:
    if not rows:
        return f"nothing to replay (skipped {skipped})"
    moved = [r for r in rows if r.changed]
    shifts = Counter(f"{r.then} -> {r.now_verdict}" for r in moved)
    lines = [
        f"replayed {len(rows)} verifications, {len(moved)} would be decided differently "
        f"(skipped {skipped} unparseable)",
    ]
    for shift, n in shifts.most_common():
        lines.append(f"  {n:>4}  {shift}")
    if moved:
        lines.append("")
        lines.append("  first few:")
        for r in moved[:10]:
            lines.append(
                f"    {r.chore[:28]:<28} {r.then} -> {r.now_verdict}"
                f" (outcome {r.now})  {r.verification_id}"
            )
    return "\n".join(lines)


def as_json(rows: list[Replayed], skipped: int) -> str:
    return json.dumps(
        {
            "replayed": len(rows),
            "changed": sum(r.changed for r in rows),
            "skipped": skipped,
            "rows": [r.__dict__ | {"changed": r.changed} for r in rows if r.changed],
        },
        indent=2,
    )
