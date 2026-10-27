"""System One decider as a photo verifier (spec §7.2 "Decider backend").

Halogen serves vLLM Semantic Router's Decision 3.0 models (``d3-nano``) on the NPU behind
``POST /v1/systemone``. A decider writes no text: it answers typed questions about a
``state`` string plus **one** picture with a probability for every option. So each check
becomes a ``choice`` of yes / no / unclear, each photo is its own request, and the answers
are folded into the same :class:`ModelResponse` the vision LLM produces — banding, flags,
``expect`` and retake all stay in ``derive_verdict``, unchanged.

Any failure raises :class:`DeciderError`; the worker falls back to the vision LLM, and
only then fails open to NEEDS_REVIEW (spec §6.3).
"""

from __future__ import annotations

import base64

import httpx
from pydantic import BaseModel, ValidationError

from app.services.llm_config import DeciderConfig, LlmConfigError, validate_base_url
from app.services.verification.llm import Check, LLMError, ModelResponse
from app.services.verification.prompts import CheckSpec

ANSWERS = {
    "yes": None,
    "no": None,
    "unclear": "the area the question is about is not visible in the photo",
}
QUALITY = {
    "none": "a clear, well-lit photo of the chore area",
    "too_dark": "too dark to see",
    "too_blurry": "too blurry to see",
    "wrong_subject": "shows something other than the chore area",
    "too_close": "too close to see the whole area",
    "too_far": "too far away to see detail",
}
# A 2B decider calling "too_blurry" at 0.55 is a coin toss, and a retake costs the kid a
# trip back to the sink. Only a confident quality call sends them back.
# TODO(decision): tune with `just eval --backend decider` once there is labeled data.
RETAKE_MIN_PROB = 0.8
QUALITY_KEY = "image_quality"


class DeciderError(LLMError):
    """Decider unreachable, errored, or answered in a shape we can't use.

    A subclass so everything that already fails open on :class:`LLMError` still does.
    """


class _Answer(BaseModel):
    type: str
    choice: str
    probabilities: dict[str, float]


class _Reply(BaseModel):
    answers: dict[str, _Answer]


def _key(check_id: int) -> str:
    return f"c{check_id}"


def build_state(chore_title: str, photo_label: str) -> str:
    lines = [f"Chore: {chore_title}"]
    if photo_label:
        lines.append(f"Photo label: {photo_label}")
    return "\n".join(lines)


def build_questions(checks: list[CheckSpec]) -> dict[str, dict]:
    """One yes/no/unclear ``choice`` per check, keyed by its real id, plus a quality check.

    ``expect`` is not sent, for the same reason as in the LLM prompt: the model reports
    what it sees; ``derive_verdict`` decides what that means.
    """
    questions: dict[str, dict] = {}
    for c in checks:
        text = c.text
        if c.ignore:
            text += f" Do not count these as a problem: {', '.join(c.ignore)}."
        questions[_key(c.id)] = {"type": "choice", "instructions": text, "criteria": ANSWERS}
    questions[QUALITY_KEY] = {
        "type": "choice",
        "instructions": "Is this photo good enough to judge the chore?",
        "criteria": QUALITY,
    }
    return questions


def _data_url(image_bytes: bytes) -> str:
    return "data:image/jpeg;base64," + base64.b64encode(image_bytes).decode()


def _top(answer: _Answer) -> tuple[str, float]:
    """The chosen option and *its probability* — the server's ``confidence`` is on a
    different scale, and the banding thresholds are probabilities."""
    return answer.choice, float(answer.probabilities.get(answer.choice, 0.0))


def _combine(per_image: list[tuple[str, float]]) -> tuple[str, float, int]:
    """Fold one check's per-photo answers into one: "is it in *any* of the photos?"

    Checks ask about presence ("Are there dishes in the basin?"), and each photo of a
    multi-shot chore shows a different area. Against the live d3-nano, a photo that does
    not show the thing answers a confident "no", not "unclear" — so "photos disagree ->
    review" sent every multi-photo chore to a parent. Instead a "yes" anywhere is the
    answer (its strongest), "no" only when no photo saw it (the weakest "no", so one
    unsure photo still holds it in review), and "unclear" only when every photo said so.
    A wrong "yes" on an ``expect: "no"`` check still has to clear auto-pass to fail.

    Returns the answer, its probability, and the index of the photo it came from.
    """
    for answer, pick in (("yes", max), ("no", min)):
        hits = [(p, i) for i, (a, p) in enumerate(per_image) if a == answer]
        if hits:
            p, i = pick(hits)
            return answer, p, i
    p, i = max((p, i) for i, (_, p) in enumerate(per_image))
    return "unclear", p, i


def _evidence(per_image: list[tuple[str, float]], labels: list[str], chosen: int) -> str:
    """Which photo decided, and what every photo said — a decider writes no evidence of
    its own, and a "yes" from the dishwasher photo to "dishes in the sink?" is only
    visible to a reviewer who can see where it came from (prod, 2026-10-27)."""

    def name(i: int) -> str:
        return f"photo {i + 1}" + (f" ({labels[i]})" if labels[i] else "")

    if len(per_image) == 1:
        return f"from {name(0)}"
    each = ", ".join(f"{i + 1} {a} {p:.2f}" for i, (a, p) in enumerate(per_image))
    return f"from {name(chosen)}; photos: {each}"


async def run_decider(
    *,
    chore_title: str,
    photo_labels: list[str],
    checks: list[CheckSpec],
    images: list[bytes],
    config: DeciderConfig,
) -> tuple[ModelResponse, dict, dict]:
    """Return (parsed, raw_request, raw_response). Raises DeciderError on any failure."""
    questions = build_questions(checks)
    labels = list(photo_labels) + [""] * (len(images) - len(photo_labels))
    bodies = [
        {
            "model": config.model,
            "state": build_state(chore_title, label),
            "questions": questions,
            "images": [_data_url(img)],
        }
        for img, label in zip(images, labels, strict=False)
    ]
    raw_request = {
        "backend": "decider",
        "per_image": [{**b, "images": ["<omitted>"]} for b in bodies],
    }
    if not images:
        raise DeciderError("no photos to score", raw_request=raw_request)
    if not checks:
        raise DeciderError("chore has no checklist to ask the decider", raw_request=raw_request)
    try:
        validate_base_url(config.base_url)
    except LlmConfigError as exc:
        raise DeciderError(str(exc), raw_request=raw_request) from exc

    url = config.base_url.rstrip("/") + "/systemone"
    replies: list[dict] = []
    parsed: list[_Reply] = []
    try:
        async with httpx.AsyncClient(timeout=config.timeout_s) as client:
            for body in bodies:
                resp = await client.post(url, json=body)
                data = resp.json() if resp.content else {}
                replies.append(data)
                resp.raise_for_status()
                reply = _Reply.model_validate(data)
                for key, crit in ((k, q["criteria"]) for k, q in questions.items()):
                    ans = reply.answers.get(key)
                    if ans is None or ans.choice not in crit:
                        raise DeciderError(
                            f"decider answer for {key!r} missing or not one of {list(crit)}",
                            raw_request=raw_request,
                            raw_response={"per_image": replies},
                        )
                parsed.append(reply)
    except DeciderError:
        raise
    except (httpx.HTTPError, ValueError, ValidationError) as exc:
        raise DeciderError(
            f"decider endpoint error: {exc}",
            raw_request=raw_request,
            raw_response={"per_image": replies} if replies else None,
        ) from exc

    out_checks = []
    for c in checks:
        per_image = [_top(r.answers[_key(c.id)]) for r in parsed]
        answer, conf, chosen = _combine(per_image)
        out_checks.append(
            Check(
                id=c.id,
                answer=answer,
                confidence=conf,
                evidence=_evidence(per_image, labels, chosen),
            )
        )

    quality = "none"
    for r in parsed:
        issue, prob = _top(r.answers[QUALITY_KEY])
        if issue != "none" and prob >= RETAKE_MIN_PROB:
            quality = issue
            break

    response = ModelResponse(
        checks=out_checks,
        # The checks' minimum already is the confidence; a stand-in self-rating would only
        # add noise to it.
        overall_confidence=1.0,
        child_message="",
        image_quality_issue=quality,
    )
    return response, raw_request, {"per_image": replies}
