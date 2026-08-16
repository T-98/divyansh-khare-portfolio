"""Thin async OpenAI wrapper: structured output, streaming, timing, fallback.

We call the Chat Completions API with a strict `json_schema` response format and
validate with Pydantic ourselves. That is the most portable structured-output
path across SDK versions, and it keeps the streaming case — which is what makes
the first line appear fast — on exactly the same code path as the blocking one.

The OpenAI Agents SDK is deliberately not used here: the whole runtime is three
calls with hand-written fan-out, so a session/handoff framework would add a
dependency and latency without removing any code. See README for the tradeoff.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from ..config import get_settings

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

_client: Any = None
_client_lock = asyncio.Lock()

# Substrings that mean "this model ID will never work on this account", as
# opposed to a transient failure worth surfacing as an error.
MODEL_ERROR_MARKERS = (
    "model_not_found",
    "does not exist",
    "do not have access",
    "not supported",
    "unsupported_model",
    "invalid_model",
    "unknown model",
)


class LLMError(RuntimeError):
    """A model call failed after its fallback was exhausted."""


@dataclass
class CallMeta:
    model: str
    latency_ms: int = 0
    fallback_used: bool = False
    notes: list[str] = field(default_factory=list)


async def get_client() -> Any:
    """Lazily build one shared AsyncOpenAI client."""
    global _client
    if _client is not None:
        return _client
    async with _client_lock:
        if _client is None:
            from openai import AsyncOpenAI

            settings = get_settings()
            if not settings.openai_api_key:
                raise LLMError("OPENAI_API_KEY is not set")
            _client = AsyncOpenAI(api_key=settings.openai_api_key)
    return _client


def reset_client() -> None:
    """Drop the cached client (tests, key rotation)."""
    global _client
    _client = None


def _is_model_error(exc: Exception) -> bool:
    text = str(exc).lower()
    return any(marker in text for marker in MODEL_ERROR_MARKERS)


def strictify(node: Any) -> Any:
    """Rewrite a Pydantic JSON schema into OpenAI strict-mode form.

    Strict mode requires every object to list all of its properties as required
    and to forbid additional properties, and rejects annotation keywords like
    `default` and `title`.
    """
    if isinstance(node, list):
        return [strictify(item) for item in node]
    if not isinstance(node, dict):
        return node

    cleaned = {
        key: strictify(value)
        for key, value in node.items()
        if key not in ("default", "title", "examples", "description", "format")
    }

    if "properties" in cleaned and isinstance(cleaned["properties"], dict):
        cleaned["type"] = "object"
        cleaned["additionalProperties"] = False
        cleaned["required"] = list(cleaned["properties"].keys())

    return cleaned


def schema_for(model: type[BaseModel], name: str) -> dict[str, Any]:
    return {
        "type": "json_schema",
        "json_schema": {
            "name": name,
            "strict": True,
            "schema": strictify(model.model_json_schema()),
        },
    }


def _messages(system: str, user: str) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


async def _create(client: Any, **kwargs: Any) -> Any:
    return await client.chat.completions.create(**kwargs)


async def _with_fallback(
    call: Callable[[str], Any],
    model: str,
    fallback: str,
    meta: CallMeta,
) -> Any:
    """Run `call(model)`, retrying once on `fallback` if the model ID is rejected."""
    try:
        return await call(model)
    except Exception as exc:  # noqa: BLE001 — classified below
        if not _is_model_error(exc) or model == fallback:
            raise
        logger.warning(
            "model_rejected", extra={"model": model, "fallback": fallback, "error": str(exc)}
        )
        meta.fallback_used = True
        meta.model = fallback
        meta.notes.append(f"{model} rejected, used {fallback}")
        return await call(fallback)


async def structured_call(
    *,
    model: str,
    system: str,
    user: str,
    schema_model: type[T],
    schema_name: str,
    timeout: float,
    max_tokens: int | None = None,
) -> tuple[T, CallMeta]:
    """One blocking structured-output call. Raises LLMError on failure."""
    client = await get_client()
    settings = get_settings()
    meta = CallMeta(model=model)
    started = time.perf_counter()

    async def run(model_id: str) -> Any:
        kwargs: dict[str, Any] = {
            "model": model_id,
            "messages": _messages(system, user),
            "response_format": schema_for(schema_model, schema_name),
        }
        if max_tokens is not None:
            kwargs["max_completion_tokens"] = max_tokens
        return await asyncio.wait_for(_create(client, **kwargs), timeout=timeout)

    try:
        completion = await _with_fallback(run, model, settings.fallback_model, meta)
    except asyncio.TimeoutError as exc:
        raise LLMError(f"{schema_name} timed out after {timeout}s") from exc
    except Exception as exc:  # noqa: BLE001
        raise LLMError(f"{schema_name} call failed: {exc}") from exc

    meta.latency_ms = int((time.perf_counter() - started) * 1000)
    content = completion.choices[0].message.content or ""
    try:
        return schema_model.model_validate_json(content), meta
    except ValidationError as exc:
        raise LLMError(f"{schema_name} returned invalid JSON: {exc}") from exc


async def text_call(
    *,
    model: str,
    system: str,
    user: str,
    timeout: float,
    max_tokens: int | None = None,
) -> tuple[str, CallMeta]:
    """One blocking plain-text call (used by specialists)."""
    client = await get_client()
    settings = get_settings()
    meta = CallMeta(model=model)
    started = time.perf_counter()

    async def run(model_id: str) -> Any:
        kwargs: dict[str, Any] = {"model": model_id, "messages": _messages(system, user)}
        if max_tokens is not None:
            kwargs["max_completion_tokens"] = max_tokens
        return await asyncio.wait_for(_create(client, **kwargs), timeout=timeout)

    try:
        completion = await _with_fallback(run, model, settings.fallback_model, meta)
    except asyncio.TimeoutError as exc:
        raise LLMError(f"text call timed out after {timeout}s") from exc
    except Exception as exc:  # noqa: BLE001
        raise LLMError(f"text call failed: {exc}") from exc

    meta.latency_ms = int((time.perf_counter() - started) * 1000)
    return (completion.choices[0].message.content or "").strip(), meta


async def stream_structured_call(
    *,
    model: str,
    system: str,
    user: str,
    schema_model: type[BaseModel],
    schema_name: str,
    timeout: float,
) -> AsyncIterator[tuple[str, str]]:
    """Yield `("chunk", text)` as JSON arrives, then `("done", full_json)`.

    The caller reassembles and validates. Streaming exists so the first spoken
    line can render before the rest of the object finishes.
    """
    client = await get_client()
    settings = get_settings()

    async def open_stream(model_id: str) -> Any:
        return await asyncio.wait_for(
            _create(
                client,
                model=model_id,
                messages=_messages(system, user),
                response_format=schema_for(schema_model, schema_name),
                stream=True,
            ),
            timeout=timeout,
        )

    meta = CallMeta(model=model)
    try:
        stream = await _with_fallback(open_stream, model, settings.fallback_model, meta)
    except asyncio.TimeoutError as exc:
        raise LLMError(f"{schema_name} stream timed out after {timeout}s") from exc
    except Exception as exc:  # noqa: BLE001
        raise LLMError(f"{schema_name} stream failed: {exc}") from exc

    buffer: list[str] = []
    try:
        async for event in stream:
            choices = getattr(event, "choices", None)
            if not choices:
                continue
            piece = getattr(choices[0].delta, "content", None)
            if piece:
                buffer.append(piece)
                yield "chunk", piece
    except Exception as exc:  # noqa: BLE001
        raise LLMError(f"{schema_name} stream broke: {exc}") from exc

    yield "done", "".join(buffer)


def parse_or_raise(schema_model: type[T], raw: str, schema_name: str) -> T:
    try:
        return schema_model.model_validate(json.loads(raw))
    except (json.JSONDecodeError, ValidationError) as exc:
        raise LLMError(f"{schema_name} returned invalid JSON: {exc}") from exc
