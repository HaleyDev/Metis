from __future__ import annotations

import asyncio
import json
from typing import Any, Awaitable, Callable

from openai import AsyncOpenAI
from openai._exceptions import APIConnectionError, APIStatusError, RateLimitError

from metis.providers.base import (
    GenerationSettings,
    LLMProvider,
    LLMResponse,
    ToolCallRequest,
)


class OpenAICompatProvider(LLMProvider):
    """A compatibility layer for OpenAI's Chat Completions API.

    Works with any OpenAI-compatible endpoint (OpenAI, DeepSeek, Qwen,
    Together, vLLM, Ollama's OpenAI shim, etc.).
    """

    # Keys accepted by the OpenAI chat.completions messages payload.
    _ALLOWED_MESSAGE_KEYS = frozenset(
        {"role", "content", "name", "tool_calls", "tool_call_id"}
    )

    def __init__(
        self,
        api_key: str | None = None,
        api_base: str | None = None,
        default_model: str | None = None,
        extra_headers: dict[str, Any] | None = None,
        timeout: float | None = 60.0,
        max_retries: int = 0,
    ) -> None:
        super().__init__(api_key=api_key, api_base=api_base)
        self.default_model = default_model
        self.extra_headers = dict(extra_headers) if extra_headers else None
        self._client = AsyncOpenAI(
            api_key=api_key or "EMPTY",
            base_url=api_base,
            timeout=timeout,
            # Retry logic is handled manually via _CHAT_RETRY_DELAYS.
            max_retries=max_retries,
        )

    # ---------------------------------------------------------------- helpers

    def _resolve_model(self, model: str | None) -> str:
        resolved = model or self.default_model
        if not resolved:
            raise ValueError(
                "No model specified and no default_model configured on provider."
            )
        return resolved

    def _prepare_messages(
        self, messages: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        sanitized = self._sanitize_empty_content(messages)
        return self._sanitize_request_messages(sanitized, self._ALLOWED_MESSAGE_KEYS)

    @staticmethod
    def _parse_tool_calls(raw_tool_calls: list[Any] | None) -> list[ToolCallRequest]:
        if not raw_tool_calls:
            return []
        parsed: list[ToolCallRequest] = []
        for tc in raw_tool_calls:
            fn = getattr(tc, "function", None)
            name = getattr(fn, "name", None) if fn else None
            raw_args = getattr(fn, "arguments", "") if fn else ""
            try:
                arguments = json.loads(raw_args) if raw_args else {}
            except json.JSONDecodeError:
                arguments = {"_raw": raw_args}
            if not name:
                continue
            parsed.append(
                ToolCallRequest(
                    id=getattr(tc, "id", "") or "",
                    name=name,
                    arguments=arguments,
                )
            )
        return parsed

    @staticmethod
    def _usage_to_dict(usage: Any) -> dict[str, int]:
        if usage is None:
            return {}
        if hasattr(usage, "model_dump"):
            data = usage.model_dump(exclude_none=True)
        elif isinstance(usage, dict):
            data = usage
        else:
            return {}
        return {k: int(v) for k, v in data.items() if isinstance(v, (int, float))}

    def _build_request_kwargs(
        self,
        *,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        model: str,
        max_tokens: int,
        temperature: float,
        reasoning_effort: str | None,
        tool_choice: str | dict[str, Any] | None,
    ) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if tools:
            kwargs["tools"] = tools
            if tool_choice is not None:
                kwargs["tool_choice"] = tool_choice
        if reasoning_effort:
            kwargs["reasoning_effort"] = reasoning_effort
        if self.extra_headers:
            kwargs["extra_headers"] = self.extra_headers
        return kwargs

    # ------------------------------------------------------------------ chat

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        reasoning_effort: str | None = None,
        tool_choice: str | dict[str, Any] | None = None,
    ) -> LLMResponse:
        prepared = self._prepare_messages(messages)
        request_kwargs = self._build_request_kwargs(
            messages=prepared,
            tools=tools,
            model=self._resolve_model(model),
            max_tokens=max_tokens,
            temperature=temperature,
            reasoning_effort=reasoning_effort,
            tool_choice=tool_choice,
        )

        last_exc: Exception | None = None
        attempts = len(self._CHAT_RETRY_DELAYS) + 1
        for attempt in range(attempts):
            try:
                completion = await self._client.chat.completions.create(
                    **request_kwargs
                )
                return self._completion_to_response(completion)
            except asyncio.CancelledError:
                raise
            except (RateLimitError, APIConnectionError) as exc:
                last_exc = exc
            except APIStatusError as exc:
                if not self._is_transient_error(str(exc)):
                    raise
                last_exc = exc
            except Exception as exc:
                if not self._is_transient_error(str(exc)):
                    raise
                last_exc = exc

            if attempt < attempts - 1:
                await asyncio.sleep(self._CHAT_RETRY_DELAYS[attempt])

        raise last_exc if last_exc else RuntimeError("chat failed with no exception")

    def _completion_to_response(self, completion: Any) -> LLMResponse:
        choice = completion.choices[0]
        message = choice.message
        content = getattr(message, "content", None)
        reasoning_content = getattr(message, "reasoning_content", None) or getattr(
            message, "reasoning", None
        )
        tool_calls = self._parse_tool_calls(getattr(message, "tool_calls", None))
        return LLMResponse(
            content=content,
            tool_calls=tool_calls,
            finish_reason=getattr(choice, "finish_reason", "stop") or "stop",
            usage=self._usage_to_dict(getattr(completion, "usage", None)),
            reasoning_content=reasoning_content,
        )

    # --------------------------------------------------------------- stream

    async def chat_stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        reasoning_effort: str | None = None,
        tool_choice: str | dict[str, Any] | None = None,
        on_content_delta: Callable[[str], Awaitable[None]] | None = None,
    ) -> LLMResponse:
        prepared = self._prepare_messages(messages)
        request_kwargs = self._build_request_kwargs(
            messages=prepared,
            tools=tools,
            model=self._resolve_model(model),
            max_tokens=max_tokens,
            temperature=temperature,
            reasoning_effort=reasoning_effort,
            tool_choice=tool_choice,
        )
        request_kwargs["stream"] = True
        request_kwargs["stream_options"] = {"include_usage": True}

        content_parts: list[str] = []
        reasoning_parts: list[str] = []
        finish_reason = "stop"
        usage: dict[str, int] = {}
        # Accumulate tool calls keyed by index (OpenAI streams tool_call deltas).
        tool_buffers: dict[int, dict[str, Any]] = {}

        stream = await self._client.chat.completions.create(**request_kwargs)
        try:
            async for chunk in stream:
                if getattr(chunk, "usage", None):
                    usage = self._usage_to_dict(chunk.usage) or usage
                if not chunk.choices:
                    continue
                choice = chunk.choices[0]
                delta = getattr(choice, "delta", None)
                if delta is not None:
                    piece = getattr(delta, "content", None)
                    if piece:
                        content_parts.append(piece)
                        if on_content_delta:
                            await on_content_delta(piece)
                    r_piece = getattr(delta, "reasoning_content", None) or getattr(
                        delta, "reasoning", None
                    )
                    if r_piece:
                        reasoning_parts.append(r_piece)
                    for tc in getattr(delta, "tool_calls", None) or []:
                        idx = getattr(tc, "index", 0) or 0
                        buf = tool_buffers.setdefault(
                            idx, {"id": "", "name": "", "arguments": ""}
                        )
                        if getattr(tc, "id", None):
                            buf["id"] = tc.id
                        fn = getattr(tc, "function", None)
                        if fn:
                            if getattr(fn, "name", None):
                                buf["name"] = fn.name
                            if getattr(fn, "arguments", None):
                                buf["arguments"] += fn.arguments
                if getattr(choice, "finish_reason", None):
                    finish_reason = choice.finish_reason
        finally:
            close = getattr(stream, "close", None)
            if close:
                try:
                    result = close()
                    if asyncio.iscoroutine(result):
                        await result
                except Exception:
                    pass

        tool_calls: list[ToolCallRequest] = []
        for idx in sorted(tool_buffers.keys()):
            buf = tool_buffers[idx]
            if not buf["name"]:
                continue
            try:
                arguments = json.loads(buf["arguments"]) if buf["arguments"] else {}
            except json.JSONDecodeError:
                arguments = {"_raw": buf["arguments"]}
            tool_calls.append(
                ToolCallRequest(id=buf["id"], name=buf["name"], arguments=arguments)
            )

        return LLMResponse(
            content="".join(content_parts) if content_parts else None,
            tool_calls=tool_calls,
            finish_reason=finish_reason or "stop",
            usage=usage,
            reasoning_content="".join(reasoning_parts) if reasoning_parts else None,
        )

    # ----------------------------------------------------------------- misc

    def update_generation_settings(
        self,
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        reasoning_effort: str | None = None,
    ) -> None:
        """Replace the provider's default GenerationSettings."""
        current = self.generation
        self.generation = GenerationSettings(
            temperature=temperature if temperature is not None else current.temperature,
            max_tokens=max_tokens if max_tokens is not None else current.max_tokens,
            reasoning_effort=reasoning_effort
            if reasoning_effort is not None
            else current.reasoning_effort,
        )

    async def aclose(self) -> None:
        await self._client.close()
