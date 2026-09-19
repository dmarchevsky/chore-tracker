"""Prompt + response schema for the vision model (spec §7.3).

Kept free of app imports so the Phase 0 bake-off script can reuse these strings verbatim.
"""

from __future__ import annotations

from dataclasses import dataclass, field

SYSTEM_PROMPT = (
    "You are a household chore verification assistant. You examine photographs and answer "
    "specific factual questions about what is visible. You are strict about only reporting "
    'what you can actually see. If an area is not visible in the photo, answer "unclear" '
    "rather than guessing. You never speculate about who did the chore or make judgments "
    "about people. Respond only with JSON matching the provided schema."
)

RESPONSE_SCHEMA: dict = {
    "type": "object",
    "additionalProperties": False,
    "required": ["checks", "overall_confidence", "child_message", "image_quality_issue"],
    "properties": {
        "checks": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                # ORDER IS LOAD-BEARING. `response_format: json_schema` is decoded under a
                # grammar built from this schema, so the model emits these keys in exactly
                # this order — and an autoregressive model cannot revise what it already
                # wrote. With `answer` first it committed to yes/no before describing
                # anything, then wrote evidence to justify a guess. A parent's check that
                # said "a sponge or dish brush in the basin is fine" was failed with the
                # evidence "there are several items, including a dish brush and a sponge"
                # — the model saw correctly and judged first.
                #
                # Evidence first makes the answer conditional on the model's own
                # description. It is the cheapest chain-of-thought available to us and
                # costs nothing extra, which matters: `enable_thinking` is off (llm.py) and
                # the deployed model is 4B-class, so this is the only room it gets.
                "required": ["id", "evidence", "answer", "confidence"],
                "properties": {
                    "id": {"type": "integer"},
                    "evidence": {"type": "string"},
                    "answer": {"type": "string", "enum": ["yes", "no", "unclear"]},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                },
            },
        },
        "overall_confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "child_message": {"type": "string"},
        "image_quality_issue": {
            "type": "string",
            "enum": ["none", "too_dark", "too_blurry", "wrong_subject", "too_close", "too_far"],
        },
    },
}


@dataclass(frozen=True)
class CheckSpec:
    """One question as the parent wrote it.

    ``expect`` is NOT sent to the model. It is the app's rule, not a fact about the photo,
    and telling the model which answer is the good one invites it to please us. The model
    reports what it sees; ``derive_verdict`` decides what that means.
    """

    id: int
    text: str
    expect: str = "yes"
    ignore: tuple[str, ...] = field(default_factory=tuple)


def build_task_prompt(
    *,
    chore_title: str,
    photo_labels: list[str] | None,
    checks: list[CheckSpec] | list[tuple[int, str]],
) -> str:
    """The USER message body (spec §7.3).

    ``checks`` are ``(id, question)`` pairs and the id is what the model is asked to answer
    under — the verdict filters on those same ids (``required_ids`` in derive_verdict), so
    renumbering them here would silently mismatch a checklist whose ids aren't 1..N.

    ``photo_labels`` are in image order, matching the order the images are attached, so a
    multi-shot chore can tell the model which picture is which.
    """
    lines = [f"Chore: {chore_title}"]
    labels = [x for x in (photo_labels or []) if x]
    if len(labels) == 1:
        lines.append(f"Photo label: {labels[0]}")
    elif labels:
        lines.append("Photos, in order: " + ", ".join(f"{i}. {x}" for i, x in enumerate(labels, 1)))
    lines += ["", "Answer each check:"]
    for c in _as_specs(checks):
        lines.append(f"{c.id}. {c.text} (yes/no/unclear)")
        if c.ignore:
            # Its own line, in the imperative. The same words trailing the question — "a
            # sponge or dish brush left in the basin is fine" — were dropped by a 4B model,
            # which then failed the chore citing the sponge and the brush by name.
            lines.append(f"   Do not count these as a problem: {', '.join(c.ignore)}.")
    lines += [
        "",
        # Worded in the order the schema forces, so the instruction and the grammar agree.
        "For each check, in this order: first `evidence` — one sentence describing only "
        "what you can actually see that bears on the question — then `answer`, then "
        "`confidence` 0-1. Decide the answer from the evidence you just wrote.",
        "Then an overall summary in one friendly sentence addressed to a child.",
        "If the photo is too dark/blurry or shows the wrong thing, set image_quality_issue.",
    ]
    return "\n".join(lines)


def _as_specs(checks: list[CheckSpec] | list[tuple[int, str]]) -> list[CheckSpec]:
    """Accept the plain ``(id, text)`` pairs the bake-off script and older callers pass."""
    return [c if isinstance(c, CheckSpec) else CheckSpec(id=c[0], text=c[1]) for c in checks]
