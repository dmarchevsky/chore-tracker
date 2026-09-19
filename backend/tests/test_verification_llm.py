"""Phase 4: vision model call + verdict banding (spec §7.2, §7.3, §6.3)."""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from app.config import Settings
from app.services.verification import (
    RESPONSE_SCHEMA,
    CheckSpec,
    build_task_prompt,
    derive_verdict,
)
from app.services.verification.llm import (
    MAX_TOKENS,
    LLMError,
    ModelResponse,
    _payload,
    run_vision,
)

BASE = "http://vision.test/v1"
URL = f"{BASE}/chat/completions"


def _settings() -> Settings:
    return Settings(
        LLM_VISION_BASE_URL=BASE,
        LLM_VISION_MODEL="test-vlm",
        LLM_VISION_API_KEY="k",
        LLM_TIMEOUT_S=5,
    )


def _completion(payload: dict | str, finish_reason: str = "stop") -> httpx.Response:
    content = payload if isinstance(payload, str) else json.dumps(payload)
    return httpx.Response(
        200,
        json={"choices": [{"message": {"content": content}, "finish_reason": finish_reason}]},
    )


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
async def test_truncated_output_fails_without_a_repair_round():
    """A reasoning model can burn the whole token budget thinking and emit no JSON.

    That is an infra failure, not a formatting mistake — re-asking replays the same run,
    so it must cost exactly one generation and say what actually went wrong.
    """
    route = respx.post(URL).mock(return_value=_completion("", finish_reason="length"))
    with pytest.raises(LLMError) as excinfo:
        await run_vision(task_prompt="x", images=[b"img"], settings=_settings())
    assert route.call_count == 1
    assert "truncated at max_tokens" in str(excinfo.value)
    assert excinfo.value.raw_request is not None
    assert excinfo.value.raw_response is not None


@pytest.mark.asyncio
@respx.mock
async def test_empty_content_fails_without_a_repair_round():
    route = respx.post(URL).mock(return_value=_completion("   "))
    with pytest.raises(LLMError) as excinfo:
        await run_vision(task_prompt="x", images=[b"img"], settings=_settings())
    assert route.call_count == 1
    assert "empty content" in str(excinfo.value)


@pytest.mark.asyncio
@respx.mock
async def test_repair_round_echoes_the_real_content_not_an_empty_turn():
    route = respx.post(URL).mock(side_effect=[_completion("not json at all"), _completion(_GOOD)])
    await run_vision(task_prompt="x", images=[b"img"], settings=_settings())
    repair_messages = json.loads(route.calls[1].request.content)["messages"]
    assert repair_messages[-2] == {"role": "assistant", "content": "not json at all"}


def test_payload_suppresses_thinking_and_budgets_for_it():
    body = _payload("test-vlm", [])
    assert body["chat_template_kwargs"] == {"enable_thinking": False}
    assert body["max_tokens"] == MAX_TOKENS
    assert MAX_TOKENS >= 2000  # has to clear a reasoning pass, not just the answer


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


def test_an_unsure_no_asks_a_human_instead_of_taking_the_money():
    """A "no" is banded like a "yes" — the model must be as sure to charge as to pay.

    It used to be an unconditional fail, so a "yes" at 0.6 went to review while a "no" at
    0.6 debited the kid. A false pass costs one unearned reward; a false fail costs money
    that was earned, and the belief that the thing is fair.
    """
    r = derive_verdict(
        _resp([(1, "yes", 0.95), (2, "no", 0.6)], overall=0.95),
        required_ids={1, 2},
        auto_pass_threshold=0.85,
        auto_fail_threshold=0.35,
    )
    assert r.outcome == "needs_review"


def test_a_confident_no_still_fails_on_its_own():
    r = derive_verdict(
        _resp([(1, "yes", 0.95), (2, "no", 0.93)], overall=0.95),
        required_ids={1, 2},
        auto_pass_threshold=0.85,
        auto_fail_threshold=0.35,
    )
    assert r.outcome == "fail"


def test_a_no_on_a_check_nobody_requires_is_ignored():
    """Banding must not quietly promote an optional check into a blocking one."""
    r = derive_verdict(
        _resp([(1, "yes", 0.95), (2, "no", 0.2)], overall=0.95),
        required_ids={1},
        auto_pass_threshold=0.85,
        auto_fail_threshold=0.35,
    )
    assert r.outcome == "pass"


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


def test_the_model_must_describe_before_it_decides():
    """`evidence` is emitted before `answer`, and that ordering is the fix, not cosmetics.

    The schema goes out as `response_format: json_schema` and is decoded under a grammar
    built from it, so key order here is key order on the wire — and an autoregressive model
    cannot revise what it already wrote. With `answer` first, a check that said "a sponge or
    dish brush left in the basin is fine" came back failed, evidenced by "there are several
    items, including a dish brush and a sponge": the model saw correctly and judged first.
    """
    item = RESPONSE_SCHEMA["properties"]["checks"]["items"]
    assert list(item["properties"]) == ["id", "evidence", "answer", "confidence"]
    # `required` drives grammar order too on some servers, so it has to agree.
    assert item["required"] == ["id", "evidence", "answer", "confidence"]
    # additionalProperties:false is what makes the grammar closed, and so ordered at all.
    assert item["additionalProperties"] is False


def test_the_instructions_ask_for_evidence_first_too():
    """An instruction that contradicts the grammar just confuses a small model."""
    prompt = build_task_prompt(
        chore_title="Kitchen",
        photo_labels=["sink"],
        checks=[(1, "Is the sink basin clear?")],
    )
    assert prompt.index("evidence") < prompt.index("`answer`")
    assert "Decide the answer from the evidence you just wrote." in prompt


# --- checks that say what they expect (spec §6.3) ----------------------------


def test_a_check_can_expect_no_so_the_question_can_be_asked_the_direct_way():
    """ "Are there dirty dishes in the basin?" is answerable; "is it clear of dishes?"
    makes the model prove an absence. Only the app knows which answer means done."""
    ok = derive_verdict(
        _resp([(1, "no", 0.95)], overall=0.95),
        required_ids={1},
        auto_pass_threshold=0.85,
        auto_fail_threshold=0.35,
        expected={1: "no"},
    )
    assert ok.outcome == "pass"

    # And the mirror: on that same check a confident "yes" is the failure.
    bad = derive_verdict(
        _resp([(1, "yes", 0.95)], overall=0.95),
        required_ids={1},
        auto_pass_threshold=0.85,
        auto_fail_threshold=0.35,
        expected={1: "no"},
    )
    assert bad.outcome == "fail"


def test_a_checklist_written_before_expect_existed_is_unchanged():
    r = derive_verdict(
        _resp([(1, "yes", 0.95)], overall=0.95),
        required_ids={1},
        auto_pass_threshold=0.85,
        auto_fail_threshold=0.35,
    )
    assert r.outcome == "pass"


def test_unclear_still_routes_to_review_whatever_was_expected():
    r = derive_verdict(
        _resp([(1, "unclear", 0.9)], overall=0.9),
        required_ids={1},
        auto_pass_threshold=0.85,
        auto_fail_threshold=0.35,
        expected={1: "no"},
    )
    assert r.outcome == "needs_review"


def test_the_ignore_list_is_its_own_instruction_not_a_trailing_clause():
    """The exact failure this came from: "a sponge, dish brush, or drain strainer left in
    the basin is fine" tacked onto the question was dropped, and the chore was failed
    citing the sponge and the brush by name."""
    prompt = build_task_prompt(
        chore_title="Kitchen",
        photo_labels=["sink"],
        checks=[
            CheckSpec(
                id=1,
                text="Are there dirty dishes, cups, pans or utensils in the sink basin?",
                expect="no",
                ignore=("sponge", "dish brush", "drain strainer"),
            )
        ],
    )
    lines = prompt.splitlines()
    q = next(i for i, ln in enumerate(lines) if ln.startswith("1."))
    assert lines[q + 1].strip() == (
        "Do not count these as a problem: sponge, dish brush, drain strainer."
    )
    # `expect` is the app's rule, not a fact about the photo. Telling the model which
    # answer we want invites it to give us that answer.
    assert "expect" not in prompt and "Done when" not in prompt


def test_plain_id_text_pairs_still_build_a_prompt():
    """The bake-off script and older callers pass tuples."""
    prompt = build_task_prompt(chore_title="K", photo_labels=None, checks=[(1, "Clear?")])
    assert "1. Clear? (yes/no/unclear)" in prompt
