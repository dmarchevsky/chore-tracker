"""System One decider as a photo verifier (spec §7.2 "Decider backend")."""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from app.services.llm_config import DeciderConfig
from app.services.verification import CheckSpec, DeciderError, derive_verdict, run_decider
from app.services.verification.decider import (
    QUALITY_KEY,
    RETAKE_MIN_PROB,
    _combine,
    build_questions,
)

BASE = "http://decider.test/v1"
URL = f"{BASE}/systemone"
CFG = DeciderConfig(base_url=BASE, model="d3-nano", timeout_s=5)


def _choice(choice: str, prob: float, options: list[str]) -> dict:
    rest = (1 - prob) / (len(options) - 1)
    probs = {o: (prob if o == choice else rest) for o in options}
    return {"type": "choice", "choice": choice, "probabilities": probs, "confidence": prob}


def _reply(answers: dict[int, tuple[str, float]], quality: tuple[str, float] = ("none", 0.9)):
    out = {f"c{i}": _choice(a, p, ["yes", "no", "unclear"]) for i, (a, p) in answers.items()}
    qopts = ["none", "too_dark", "too_blurry", "wrong_subject", "too_close", "too_far"]
    out[QUALITY_KEY] = _choice(*quality, qopts)
    return httpx.Response(200, json={"model": "d3-nano", "answers": out, "usage": {}})


async def _run(checks, images=(b"img",), labels=("sink",)):
    return await run_decider(
        chore_title="Kitchen",
        photo_labels=list(labels),
        checks=checks,
        images=list(images),
        config=CFG,
    )


def test_questions_key_by_real_id_and_carry_ignore_but_not_expect():
    qs = build_questions(
        [
            CheckSpec(id=3, text="Are there dishes in the basin?", expect="no", ignore=("sponge",)),
            CheckSpec(id=7, text="Is the counter wiped?"),
        ]
    )
    assert set(qs) == {"c3", "c7", QUALITY_KEY}
    assert qs["c3"]["type"] == "choice"
    assert set(qs["c3"]["criteria"]) == {"yes", "no", "unclear"}
    assert "Do not count these as a problem: sponge." in qs["c3"]["instructions"]
    assert "expect" not in json.dumps(qs)


@pytest.mark.asyncio
@respx.mock
async def test_request_shape_and_images_redacted():
    route = respx.post(URL).mock(return_value=_reply({1: ("yes", 0.95)}))
    resp, raw_req, raw_resp = await _run([CheckSpec(id=1, text="Is the sink empty?")])

    body = json.loads(route.calls[0].request.content)
    assert body["model"] == "d3-nano"
    assert body["state"] == "Chore: Kitchen\nPhoto label: sink"
    assert body["images"][0].startswith("data:image/jpeg;base64,")
    assert raw_req["per_image"][0]["images"] == ["<omitted>"]
    assert raw_resp["per_image"][0]["answers"]["c1"]["choice"] == "yes"

    assert resp.checks[0].answer == "yes"
    assert resp.checks[0].confidence == pytest.approx(0.95)  # the choice's probability
    assert resp.image_quality_issue == "none"
    assert resp.child_message == ""


@pytest.mark.asyncio
@respx.mock
async def test_feeds_derive_verdict_with_expect_no():
    respx.post(URL).mock(return_value=_reply({1: ("no", 0.97)}))
    checks = [CheckSpec(id=1, text="Are there dishes in the basin?", expect="no")]
    resp, _, _ = await _run(checks)
    v = derive_verdict(
        resp,
        required_ids={1},
        auto_pass_threshold=0.85,
        auto_fail_threshold=0.35,
        expected={1: "no"},
    )
    assert v.outcome == "pass"


@pytest.mark.asyncio
@respx.mock
async def test_one_request_per_photo():
    route = respx.post(URL).mock(
        side_effect=[_reply({1: ("yes", 0.9)}), _reply({1: ("unclear", 0.8)})]
    )
    resp, raw_req, _ = await _run(
        [CheckSpec(id=1, text="Is the sink empty?")],
        images=[b"a", b"b"],
        labels=["sink", "counter"],
    )
    assert route.call_count == 2
    assert [b["state"].splitlines()[-1] for b in raw_req["per_image"]] == [
        "Photo label: sink",
        "Photo label: counter",
    ]
    # the photo that could not see the sink does not override the one that could
    assert (resp.checks[0].answer, resp.checks[0].confidence) == ("yes", pytest.approx(0.9))


def test_combine_is_any_photo():
    # each photo shows a different area: the one that saw it decides
    assert _combine([("yes", 0.9), ("no", 0.95)]) == ("yes", 0.9)
    assert _combine([("yes", 0.7), ("yes", 0.9)]) == ("yes", 0.9)
    assert _combine([("no", 0.9), ("no", 0.6)]) == ("no", 0.6)  # weakest "no" holds
    assert _combine([("no", 0.9), ("unclear", 0.99)]) == ("no", 0.9)
    assert _combine([("unclear", 0.6), ("unclear", 0.8)]) == ("unclear", 0.8)


@pytest.mark.asyncio
@respx.mock
async def test_quality_retake_only_above_the_bar():
    checks = [CheckSpec(id=1, text="Is the sink empty?")]
    respx.post(URL).mock(
        return_value=_reply({1: ("yes", 0.9)}, ("too_dark", RETAKE_MIN_PROB - 0.1))
    )
    resp, _, _ = await _run(checks)
    assert resp.image_quality_issue == "none"

    respx.post(URL).mock(return_value=_reply({1: ("yes", 0.9)}, ("too_dark", 0.95)))
    resp, _, _ = await _run(checks)
    assert resp.image_quality_issue == "too_dark"


@pytest.mark.asyncio
@respx.mock
async def test_http_500_raises_with_payloads():
    respx.post(URL).mock(return_value=httpx.Response(500, json={"error": {"message": "boom"}}))
    with pytest.raises(DeciderError) as ei:
        await _run([CheckSpec(id=1, text="Is the sink empty?")])
    assert ei.value.raw_request is not None
    assert ei.value.raw_response == {"per_image": [{"error": {"message": "boom"}}]}


@pytest.mark.asyncio
@respx.mock
async def test_connection_error_raises():
    respx.post(URL).mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(DeciderError, match="decider endpoint error"):
        await _run([CheckSpec(id=1, text="Is the sink empty?")])


@pytest.mark.asyncio
@respx.mock
async def test_missing_answer_raises():
    respx.post(URL).mock(return_value=_reply({2: ("yes", 0.9)}))
    with pytest.raises(DeciderError, match="'c1'"):
        await _run([CheckSpec(id=1, text="Is the sink empty?")])


@pytest.mark.asyncio
async def test_bad_url_and_empty_checklist_raise_without_calling_out():
    with pytest.raises(DeciderError, match="http"):
        await run_decider(
            chore_title="K",
            photo_labels=[],
            checks=[CheckSpec(id=1, text="q")],
            images=[b"x"],
            config=DeciderConfig(base_url="", model="d3-nano", timeout_s=5),
        )
    with pytest.raises(DeciderError, match="checklist"):
        await _run([])
