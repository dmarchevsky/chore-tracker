"""Phase 4: vision model call + verdict banding (spec §7.2, §7.3, §6.3)."""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from app.config import Settings
from app.services.verification import build_task_prompt, derive_verdict
from app.services.verification.llm import LLMError, ModelResponse, run_vision

BASE = "http://vision.test/v1"
URL = f"{BASE}/chat/completions"


def _settings() -> Settings:
    return Settings(
        LLM_VISION_BASE_URL=BASE,
        LLM_VISION_MODEL="test-vlm",
        LLM_VISION_API_KEY="k",
        LLM_TIMEOUT_S=5,
    )


def _completion(payload: dict | str) -> httpx.Response:
    content = payload if isinstance(payload, str) else json.dumps(payload)
    return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})


_GOOD = {
    "checks": [
        {"id": 1, "answer": "yes", "confidence": 0.95, "evidence": "empty sink"},
        {"id": 2, "answer": "yes", "confidence": 0.9, "evidence": "clear counter"},
    ],
    "overall_confidence": 0.92,
    "child_message": "Nice work, the sink is sparkling!",
    "image_quality_issue": "none",
}


@pytest.mark.asyncio
@respx.mock
async def test_run_vision_parses_and_redacts_images():
    route = respx.post(URL).mock(return_value=_completion(_GOOD))
    parsed, raw_req, _raw_resp = await run_vision(
        task_prompt="check the sink", images=[b"\xff\xd8fakejpeg"], settings=_settings()
    )
    assert route.called
    assert isinstance(parsed, ModelResponse) and parsed.checks[0].answer == "yes"
    # stored request keeps the prompt but not the base64 blob
    user_msg = raw_req["messages"][1]["content"]
    assert any(p.get("type") == "text" for p in user_msg)
    assert all(p.get("image_url") == "<omitted>" for p in user_msg if p.get("type") != "text")


@pytest.mark.asyncio
@respx.mock
async def test_repair_retry_recovers_from_bad_json():
    respx.post(URL).mock(side_effect=[_completion("not json at all"), _completion(_GOOD)])
    parsed, _, _ = await run_vision(task_prompt="x", images=[b"img"], settings=_settings())
    assert parsed.overall_confidence == 0.92


@pytest.mark.asyncio
@respx.mock
async def test_unparseable_twice_raises_llmerror():
    respx.post(URL).mock(side_effect=[_completion("nope"), _completion("still nope")])
    with pytest.raises(LLMError):
        await run_vision(task_prompt="x", images=[b"img"], settings=_settings())


@pytest.mark.asyncio
@respx.mock
async def test_http_500_raises_llmerror():
    respx.post(URL).mock(return_value=httpx.Response(500))
    with pytest.raises(LLMError):
        await run_vision(task_prompt="x", images=[b"img"], settings=_settings())


@pytest.mark.asyncio
@respx.mock
async def test_connection_error_raises_llmerror():
    respx.post(URL).mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(LLMError):
        await run_vision(task_prompt="x", images=[b"img"], settings=_settings())


# --- verdict banding (pure) --------------------------------------------------


def _resp(checks, overall=0.9, iq="none", msg="ok") -> ModelResponse:
    return ModelResponse(
        checks=[{"id": i, "answer": a, "confidence": c, "evidence": ""} for i, a, c in checks],
        overall_confidence=overall,
        child_message=msg,
        image_quality_issue=iq,
    )


def test_all_yes_high_conf_passes():
    r = derive_verdict(
        _resp([(1, "yes", 0.95), (2, "yes", 0.9)]),
        required_ids={1, 2},
        auto_pass_threshold=0.85,
        auto_fail_threshold=0.35,
    )
    assert r.outcome == "pass"


def test_required_no_fails():
    r = derive_verdict(
        _resp([(1, "yes", 0.9), (2, "no", 0.9)]),
        required_ids={1, 2},
        auto_pass_threshold=0.85,
        auto_fail_threshold=0.35,
    )
    assert r.outcome == "fail"


def test_unclear_caps_confidence_and_routes_to_review():
    r = derive_verdict(
        _resp([(1, "yes", 0.95), (2, "unclear", 0.9)]),
        required_ids={1, 2},
        auto_pass_threshold=0.85,
        auto_fail_threshold=0.35,
    )
    assert r.outcome == "needs_review" and r.confidence == 0.5


def test_image_quality_issue_is_a_retake():
    r = derive_verdict(
        _resp([(1, "yes", 0.9)], iq="too_dark"),
        required_ids={1},
        auto_pass_threshold=0.85,
        auto_fail_threshold=0.35,
    )
    assert r.outcome == "retake" and r.image_quality_issue == "too_dark"


def test_any_flag_forces_review():
    r = derive_verdict(
        _resp([(1, "yes", 0.99)]),
        required_ids={1},
        auto_pass_threshold=0.85,
        auto_fail_threshold=0.35,
        flags=["DUPLICATE_SUSPECTED"],
    )
    assert r.outcome == "needs_review"


def test_build_task_prompt_renders_label_and_checks():
    p = build_task_prompt(
        chore_title="Kitchen",
        photo_labels=["sink close-up"],
        checks=[(1, "Is the sink empty?")],
    )
    assert "Is the sink empty?" in p and "yes/no/unclear" in p
    assert "Photo label: sink close-up" in p


def test_build_task_prompt_numbers_checks_by_their_real_ids():
    """derive_verdict filters on the checklist's own ids, so the model has to be asked
    under those ids — enumerating 1..N silently mismatched a checklist with a gap."""
    p = build_task_prompt(
        chore_title="Kitchen",
        photo_labels=[],
        checks=[(1, "Is the sink empty?"), (3, "Is the counter clear?")],
    )
    assert "1. Is the sink empty?" in p
    assert "3. Is the counter clear?" in p


def test_build_task_prompt_lists_every_photo_label_in_order():
    p = build_task_prompt(
        chore_title="Kitchen",
        photo_labels=["sink close-up", "wide kitchen"],
        checks=[(1, "Is the sink empty?")],
    )
    assert "Photos, in order: 1. sink close-up, 2. wide kitchen" in p
