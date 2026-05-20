"""Thin adapter around the GigaChat Python SDK.

We keep this layer minimal so tests can swap it out with a fake.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator

from django.conf import settings


@dataclass
class StreamChunk:
    """One piece of streamed output from the model."""
    delta_text: str = ""
    tool_call_name: str = ""
    tool_call_args_json: str = ""   # accumulated JSON string (may be partial)
    finish_reason: str = ""         # "stop" | "function_call" | ""
    prompt_tokens: int = 0
    completion_tokens: int = 0


class GigaChatClient:
    """Wraps the official ``gigachat`` SDK with a streaming-friendly API."""

    def __init__(self):
        from gigachat import GigaChat

        self._client = GigaChat(
            credentials=settings.GIGACHAT_AUTH_KEY,
            scope=settings.GIGACHAT_SCOPE,
            model=settings.GIGACHAT_MODEL,
            verify_ssl_certs=settings.GIGACHAT_VERIFY_SSL,
        )

    def stream_chat(
        self,
        *,
        messages: list[dict],
        tools: list[dict],
        max_output_tokens: int,
    ) -> Iterator[StreamChunk]:
        """Yield ``StreamChunk`` until the model emits stop or function_call."""
        from gigachat.models import Chat, Function, Messages

        payload = Chat(
            messages=[Messages(**m) for m in messages],
            functions=[Function(**t) for t in tools] if tools else None,
            max_tokens=max_output_tokens,
        )
        for chunk in self._client.stream(payload):
            choice = chunk.choices[0]
            delta = choice.delta
            fc = getattr(delta, "function_call", None)
            usage = getattr(chunk, "usage", None)
            yield StreamChunk(
                delta_text=getattr(delta, "content", "") or "",
                tool_call_name=getattr(fc, "name", "") if fc else "",
                tool_call_args_json=getattr(fc, "arguments", "") if fc else "",
                finish_reason=choice.finish_reason or "",
                prompt_tokens=usage.prompt_tokens if usage else 0,
                completion_tokens=usage.completion_tokens if usage else 0,
            )
