"""Turn a model response + anti-cheat flags into a routed verdict (spec §6.3, §7.3).

Confidence banding, not thresholding — and symmetric: a required "no" has to clear the
same bar as a required "yes" before it is acted on, so an unsure model asks a human instead
of taking a kid's money. ``unclear`` on a required check caps confidence at 0.5, which
lands it in review. Any anti-cheat flag routes to review regardless of confidence. An
image-quality problem is a retake, never a fail.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.services.verification.llm import ModelResponse

UNCLEAR_CAP = 0.5


@dataclass
class VerdictResult:
    outcome: str  # "pass" | "fail" | "needs_review" | "retake"
    confidence: float
    child_message: str
    image_quality_issue: str = "none"
    reasoning: str = ""
    checks: list[dict] = field(default_factory=list)


def derive_verdict(
    response: ModelResponse,
    *,
    required_ids: set[int] | None,
    auto_pass_threshold: float,
    auto_fail_threshold: float,
    flags: list[str] | None = None,
    expected: dict[int, str] | None = None,
) -> VerdictResult:
    """``expected`` maps a check id to the answer that means the chore was done.

    Absent, every check expects "yes", which is what every checklist written before
    ChecklistItem.expect existed means. It lets a parent ask the question the direct way —
    "Are there dirty dishes in the sink basin?" (expect "no") — instead of inverting it into
    "Is the basin clear of dishes?" just to make yes mean done. Reporting a presence is much
    easier for a vision model than verifying an absence (spec §6.3 "checklists beat vibes").
    """
    flags = flags or []
    expected = expected or {}
    checks = [c.model_dump() for c in response.checks]

    def wanted(cid: int) -> str:
        return expected.get(cid, "yes")

    if response.image_quality_issue and response.image_quality_issue != "none":
        return VerdictResult(
            outcome="retake",
            confidence=0.0,
            child_message=response.child_message or "Please retake the photo.",
            image_quality_issue=response.image_quality_issue,
            reasoning=f"image quality: {response.image_quality_issue}",
            checks=checks,
        )

    considered = [c for c in response.checks if required_ids is None or c.id in required_ids]
    passed = all(c.answer == wanted(c.id) for c in considered) if considered else False
    any_unclear = any(c.answer == "unclear" for c in considered)
    # A definite answer that is not the one the chore needed. Not "== no": on a check that
    # expects "no", a "yes" is the failure.
    any_no = any(c.answer != wanted(c.id) and c.answer != "unclear" for c in considered)

    if considered:
        conf = min(c.confidence for c in considered)
        conf = min(conf, response.overall_confidence)
    else:
        conf = response.overall_confidence
    if any_unclear:
        conf = min(conf, UNCLEAR_CAP)

    reasoning = "; ".join(
        f"#{c.id}:{c.answer}({c.confidence:.2f})"
        + ("" if wanted(c.id) == "yes" else f"[wanted {wanted(c.id)}]")
        for c in response.checks
    )

    if flags:  # spec §6.3 rule 2 — any flag -> review regardless of confidence
        return VerdictResult(
            "needs_review",
            conf,
            response.child_message,
            reasoning=f"flags: {','.join(flags)}; {reasoning}",
            checks=checks,
        )

    # A required "no" is banded exactly like a required "yes": the model has to be as sure
    # to take money as it is to pay it.
    #
    # It used to be an unconditional fail, which trusted a negative more than a positive —
    # a "yes" at 0.6 went to review, a "no" at 0.6 debited the kid. That is backwards here.
    # A false pass costs a parent one unearned reward; a false fail costs a kid money they
    # did earn, and the belief that the thing is fair, which is harder to get back. It also
    # sat badly with spec §6.3: the model is an assistant, and everything uncertain is
    # supposed to fail open to a human.
    #
    # A required "unclear" (with no "no") still routes to review — its confidence is
    # already capped at 0.5 (spec §7.3).
    if any_no:
        outcome = "fail" if conf >= auto_pass_threshold else "needs_review"
    elif not passed:  # only "unclear" left
        outcome = "needs_review"
    elif conf >= auto_pass_threshold:
        outcome = "pass"
    elif conf <= auto_fail_threshold:
        outcome = "fail"
    else:
        outcome = "needs_review"

    return VerdictResult(outcome, conf, response.child_message, reasoning=reasoning, checks=checks)
