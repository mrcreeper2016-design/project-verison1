"""Reusable fakes for testing the agent loop without hitting GigaChat."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterator

from assistant.agent.gigachat_client import StreamChunk


@dataclass
class ScriptedTurn:
    """One scripted model turn. Either text or a tool call, not both."""
    text: str = ""
    tool_name: str = ""
    tool_args: dict = field(default_factory=dict)
    prompt_tokens: int = 100
    completion_tokens: int = 30


class FakeGigaChatClient:
    """Replays a pre-recorded sequence of ``ScriptedTurn`` objects.

    Each call to ``stream_chat`` consumes one turn from ``script``.
    """

    def __init__(self, script: list[ScriptedTurn]):
        self.script = list(script)
        self.calls: list[dict] = []

    def stream_chat(self, *, messages, tools, max_output_tokens) -> Iterator[StreamChunk]:
        self.calls.append({"messages": messages, "tools": tools})
        if not self.script:
            raise AssertionError("FakeGigaChatClient script exhausted")
        turn = self.script.pop(0)
        if turn.tool_name:
            yield StreamChunk(
                tool_call_name=turn.tool_name,
                tool_call_args=dict(turn.tool_args),
                finish_reason="function_call",
                prompt_tokens=turn.prompt_tokens,
                completion_tokens=turn.completion_tokens,
            )
        else:
            yield StreamChunk(
                delta_text=turn.text,
                finish_reason="stop",
                prompt_tokens=turn.prompt_tokens,
                completion_tokens=turn.completion_tokens,
            )
