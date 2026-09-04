"""OpenAI-compatible vision model call with one repair retry (spec §7.2).

Works unchanged against llama.cpp ``llama-server``, vLLM or Ollama. Any infra failure
(down, timeout, unparseable output after the retry) raises :class:`LLMError`; the caller
fails open to NEEDS_REVIEW — the kid never loses money because inference broke (spec §6.3).
"""

from __future__ import annotations

import base64
import json
from typing import Any

import httpx
from pydantic import BaseModel, Field, ValidationError

from app.config import Settings, get_settings
from app.services.llm_config import LlmConfig, LlmConfigError, validate_base_url
from app.services.verification.prompts import RESPONSE_SCHEMA, SYSTEM_PROMPT

TEMPERATURE = 0.1
# Reasoning models bill their thinking tokens against this budget even when the server
# hands the thinking back in a separate ``reasoning_content`` field. A 4B-class model
# spent all of a 700-token budget reasoning about three photos and never emitted the JSON
# at all, so the budget has to clear the thinking as well as the answer.
MAX_TOKENS = 2000

_REPAIR = (
    "Your previous message was not valid JSON matching the schema. "
    "Reply again with ONLY a JSON object matching the schema, nothing else."
)


class LLMError(RuntimeError):
    """Endpoint unreachable, timed out, or returned unparseable output after a retry.

    Carries the request/response payloads when they exist so the failure is inspectable
    from the verification record instead of only from the worker log.
    """

    def __init__(
        self,
        message: str,
        *,
        raw_request: dict | None = None,
        raw_response: dict | None = None,
    ) -> None:
        super().__init__(message)
        self.raw_request = raw_request
        self.raw_response = raw_response


class Check(BaseModel):
    id: int
    answer: str  # yes | no | unclear
    confidence: float = Field(ge=0, le=1)
    evidence: str = ""


class ModelResponse(BaseModel):
    checks: list[Check]
    overall_confidence: float = Field(ge=0, le=1)
    child_message: str = ""
    image_quality_issue: str = "none"


def _data_url(image_bytes: bytes) -> str:
    return "data:image/jpeg;base64," + base64.b64encode(image_bytes).decode()


def _payload(model: str, messages: list[dict]) -> dict[str, Any]:
    return {
        "model": model,
        "temperature": TEMPERATURE,
        "max_tokens": MAX_TOKENS,
        # Ask reasoning models to skip the thinking pass: we want schema-shaped JSON, not
        # deliberation, and the thinking otherwise eats the token budget. Servers that
        # don't know the key ignore it, so this stays portable across llama.cpp/vLLM/Ollama.
        "chat_template_kwargs": {"enable_thinking": False},
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": "chore_verification", "schema": RESPONSE_SCHEMA},
        },
        "messages": messages,
    }


def _parse(content: str) -> ModelResponse:
    return ModelResponse.model_validate_json(content)


async def run_vision(
    *,
    task_prompt: str,
    images: list[bytes],
    config: LlmConfig | None = None,
    settings: Settings | None = None,
) -> tuple[ModelResponse, dict, dict]:
    """Return (parsed, raw_request, raw_response). Raises LLMError on any infra failure.

    ``config`` (DB-resolved, spec §7.2) takes precedence; ``settings`` is the env-only
    fallback kept for callers without a DB session.
    """
    cfg = config or LlmConfig.from_settings(settings or get_settings())
    user_content: list[dict] = [{"type": "text", "text": task_prompt}]
    user_content += [{"type": "image_url", "image_url": {"url": _data_url(b)}} for b in images]
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]
    body = _payload(cfg.model, messages)
    try:
        validate_base_url(cfg.base_url)
    except LlmConfigError as exc:
        # Same fail-open contract as an unreachable endpoint: NEEDS_REVIEW, no ledger entry.
        # A misconfigured URL must not cost a kid money (spec §6.3).
        raise LLMError(str(exc)) from exc
    url = cfg.base_url.rstrip("/") + "/chat/completions"
    headers = {"Authorization": f"Bearer {cfg.api_key}"}

    raw_request = {**body, "messages": _redact(messages)}

    try:
        async with httpx.AsyncClient(timeout=cfg.timeout_s) as client:
            raw = await _post_and_read(client, url, headers, body)
            try:
                return _parse(raw["_content"]), raw_request, raw
            except (ValidationError, ValueError, json.JSONDecodeError):
                _reject_if_no_output(raw, raw_request)
            # one repair round (spec §7.2)
            messages.append({"role": "assistant", "content": raw["_content"]})
            messages.append({"role": "user", "content": _REPAIR})
            raw2 = await _post_and_read(client, url, headers, _payload(cfg.model, messages))
            try:
                return _parse(raw2["_content"]), raw_request, raw2
            except (ValidationError, ValueError, json.JSONDecodeError) as exc:
                _reject_if_no_output(raw2, raw_request)
                raise LLMError(
                    f"unparseable model output after repair: {exc}",
                    raw_request=raw_request,
                    raw_response=raw2,
                ) from exc
    except httpx.HTTPError as exc:
        raise LLMError(f"vision endpoint error: {exc}", raw_request=raw_request) from exc


def _reject_if_no_output(raw: dict, raw_request: dict) -> None:
    """Bail out when the model emitted no JSON at all, rather than asking it to try again.

    The repair round is for a model that answered in the wrong *shape*. A truncated or
    empty completion is an infra failure: re-asking replays the same run and, on a slow
    local endpoint, costs another full generation for a guaranteed second failure. It also
    used to append ``{"role": "assistant", "content": ""}`` — an empty turn — to the
    conversation, which is not a prompt any server handles usefully.
    """
    content = raw.get("_content") or ""
    finish = raw.get("_finish_reason")
    if finish != "length" and content.strip():
        return
    detail = (
        f"truncated at max_tokens={MAX_TOKENS}"
        if finish == "length"
        else f"empty content with finish_reason={finish!r}"
    )
    raise LLMError(
        f"model returned no usable output: {detail}. A reasoning model's thinking tokens "
        "can consume the whole budget before it emits the JSON.",
        raw_request=raw_request,
        raw_response=raw,
    )


async def _post_and_read(client: httpx.AsyncClient, url: str, headers: dict, body: dict) -> dict:
    resp = await client.post(url, headers=headers, json=body)
    resp.raise_for_status()
    data = resp.json()
    try:
        choice = data["choices"][0]
        content = choice["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise LLMError(f"unexpected response shape: {exc}") from exc
    return {**data, "_content": content, "_finish_reason": choice.get("finish_reason")}


def _redact(messages: list[dict]) -> list[dict]:
    """Drop base64 image blobs from the stored request (keep the prompt text)."""
    out = []
    for m in messages:
        if isinstance(m.get("content"), list):
            parts = [
                p if p.get("type") == "text" else {"type": "image_url", "image_url": "<omitted>"}
                for p in m["content"]
            ]
            out.append({**m, "content": parts})
        else:
            out.append(m)
    return out
