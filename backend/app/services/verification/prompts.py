"""Prompt + response schema for the vision model (spec §7.3).

Kept free of app imports so the Phase 0 bake-off script can reuse these strings verbatim.
"""

from __future__ import annotations

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
                "required": ["id", "answer", "confidence", "evidence"],
                "properties": {
                    "id": {"type": "integer"},
                    "answer": {"type": "string", "enum": ["yes", "no", "unclear"]},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    "evidence": {"type": "string"},
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


def build_task_prompt(
    *,
    chore_title: str,
    photo_label: str | None,
    checks: list[str],
    prompt_token: str | None = None,
) -> str:
    """The USER message body (spec §7.3). ``checks`` are plain yes/no questions."""
    lines = [f"Chore: {chore_title}"]
    if photo_label:
        lines.append(f"Photo label: {photo_label}")
    numbered = list(checks)
    if prompt_token:
        numbered.append(f"Is the number {prompt_token} clearly visible somewhere in this photo?")
    lines += ["", "Answer each check:"]
    lines += [f"{i}. {q} (yes/no/unclear)" for i, q in enumerate(numbered, start=1)]
    lines += [
        "",
        "For each: answer, confidence 0-1, and one sentence of evidence describing what you see.",
        "Then an overall summary in one friendly sentence addressed to a child.",
        "If the photo is too dark/blurry or shows the wrong thing, set image_quality_issue.",
    ]
    return "\n".join(lines)
