"""Turn a model response + anti-cheat flags into a routed verdict (spec §6.3, §7.3).

Confidence banding, not thresholding. ``unclear`` on a required check is a fail that also
caps confidence at 0.5, which lands it in review. Any anti-cheat flag routes to review
regardless of confidence. An image-quality problem is a retake, never a fail.
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
) -> VerdictResult:
    flags = flags or []
    checks = [c.model_dump() for c in response.checks]

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
    passed = all(c.answer == "yes" for c in considered) if considered else False
    any_unclear = any(c.answer == "unclear" for c in considered)
    any_no = any(c.answer == "no" for c in considered)

    if considered:
        conf = min(c.confidence for c in considered)
        conf = min(conf, response.overall_confidence)
    else:
        conf = response.overall_confidence
    if any_unclear:
        conf = min(conf, UNCLEAR_CAP)

    reasoning = "; ".join(f"#{c.id}:{c.answer}({c.confidence:.2f})" for c in response.checks)

    if flags:  # spec §6.3 rule 2 — any flag -> review regardless of confidence
        return VerdictResult(
            "needs_review",
            conf,
            response.child_message,
            reasoning=f"flags: {','.join(flags)}; {reasoning}",
            checks=checks,
        )

    # A required "no" is a clear fail. A required "unclear" (with no "no") routes to review
    # — its confidence is already capped at 0.5 (spec §7.3). When every required check is
    # "yes", band on confidence: high -> pass, low -> fail, middle -> review (spec §6.3).
    if any_no:
        outcome = "fail"
    elif not passed:  # only "unclear" left
        outcome = "needs_review"
    elif conf >= auto_pass_threshold:
        outcome = "pass"
    elif conf <= auto_fail_threshold:
        outcome = "fail"
    else:
        outcome = "needs_review"

    return VerdictResult(outcome, conf, response.child_message, reasoning=reasoning, checks=checks)
