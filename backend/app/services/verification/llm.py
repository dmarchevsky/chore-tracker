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
from app.services.verification.prompts import RESPONSE_SCHEMA, SYSTEM_PROMPT

TEMPERATURE = 0.1
MAX_TOKENS = 700

_REPAIR = (
    "Your previous message was not valid JSON matching the schema. "
    "Reply again with ONLY a JSON object matching the schema, nothing else."
)


class LLMError(RuntimeError):
    """Endpoint unreachable, timed out, or returned unparseable output after a retry."""


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
    settings: Settings | None = None,
) -> tuple[ModelResponse, dict, dict]:
    """Return (parsed, raw_request, raw_response). Raises LLMError on any infra failure."""
    s = settings or get_settings()
    user_content: list[dict] = [{"type": "text", "text": task_prompt}]
    user_content += [{"type": "image_url", "image_url": {"url": _data_url(b)}} for b in images]
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]
    body = _payload(s.llm_vision_model, messages)
    url = s.llm_vision_base_url.rstrip("/") + "/chat/completions"
    headers = {"Authorization": f"Bearer {s.llm_vision_api_key}"}

    raw_request = {**body, "messages": _redact(messages)}

    try:
        async with httpx.AsyncClient(timeout=s.llm_timeout_s) as client:
            raw = await _post_and_read(client, url, headers, body)
            try:
                return _parse(raw["_content"]), raw_request, raw
            except (ValidationError, ValueError, json.JSONDecodeError):
                pass
            # one repair round (spec §7.2)
            messages.append({"role": "assistant", "content": raw["_content"]})
            messages.append({"role": "user", "content": _REPAIR})
            raw2 = await _post_and_read(
                client, url, headers, _payload(s.llm_vision_model, messages)
            )
            try:
                return _parse(raw2["_content"]), raw_request, raw2
            except (ValidationError, ValueError, json.JSONDecodeError) as exc:
                raise LLMError(f"unparseable model output after repair: {exc}") from exc
    except httpx.HTTPError as exc:
        raise LLMError(f"vision endpoint error: {exc}") from exc


async def _post_and_read(client: httpx.AsyncClient, url: str, headers: dict, body: dict) -> dict:
    resp = await client.post(url, headers=headers, json=body)
    resp.raise_for_status()
    data = resp.json()
    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise LLMError(f"unexpected response shape: {exc}") from exc
    return {**data, "_content": content}


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
