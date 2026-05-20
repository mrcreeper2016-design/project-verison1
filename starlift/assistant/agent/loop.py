"""Single-turn agent loop.

The loop drives one user message to completion:
- Builds context from conversation history.
- Calls the LLM, streaming chunks back as ``AgentEvent`` objects.
- When the model emits a function call, executes the matching tool, records
  a ``Message(role='tool')``, and feeds the result back into the model.
- Stops when the model emits final text, when the iteration cap is hit, or
  when a tool errors out / a budget check fails.

The loop is **provider-agnostic**: any object exposing ``stream_chat`` with
the same signature as ``GigaChatClient`` works. Tests inject a fake.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Iterator

from django.conf import settings

from assistant.agent.budget import (
    BudgetExceeded,
    check_conversation_budget,
    check_daily_budget,
    check_global_budget,
)
from assistant.agent.prompts import build_context_messages, build_system_prompt
from assistant.agent.tools import TOOL_REGISTRY, ToolResultTooLargeError
from assistant.models import Conversation, Message


@dataclass
class AgentEvent:
    kind: str       # "delta" | "tool_start" | "tool_end" | "done" | "error"
    payload: dict


def _tool_schemas() -> list[dict]:
    return [t.schema for t in TOOL_REGISTRY.values()]


def run_turn(conversation: Conversation, *, client) -> Iterator[AgentEvent]:
    user = conversation.user

    try:
        check_global_budget()
        check_daily_budget(user)
        check_conversation_budget(conversation)
    except BudgetExceeded as e:
        yield AgentEvent("error", {"reason": "budget_exceeded", "scope": e.scope})
        return

    messages = [{"role": "system", "content": build_system_prompt(user)}]
    messages.extend(build_context_messages(conversation))

    assistant_text = ""
    turn_token_in = 0
    turn_token_out = 0
    iterations = 0
    max_iter = settings.ASSISTANT_MAX_TOOL_ITERATIONS

    while True:
        iterations += 1
        if iterations > max_iter:
            yield AgentEvent("error", {"reason": "max_tools_exceeded"})
            return

        pending_tool_name = ""
        pending_tool_args = ""
        chunk_in = chunk_out = 0
        try:
            for chunk in client.stream_chat(
                messages=messages,
                tools=_tool_schemas(),
                max_output_tokens=settings.ASSISTANT_MAX_OUTPUT_TOKENS_PER_TURN,
            ):
                chunk_in = chunk.prompt_tokens or chunk_in
                chunk_out = chunk.completion_tokens or chunk_out
                if chunk.delta_text:
                    assistant_text += chunk.delta_text
                    yield AgentEvent("delta", {"text": chunk.delta_text})
                if chunk.tool_call_name:
                    pending_tool_name = chunk.tool_call_name
                    pending_tool_args += chunk.tool_call_args_json
        except Exception as exc:  # noqa: BLE001 — surface provider errors as SSE events
            yield AgentEvent("error", {"reason": "provider_error", "detail": str(exc)[:300]})
            return
        turn_token_in += chunk_in
        turn_token_out += chunk_out

        if pending_tool_name:
            try:
                args = json.loads(pending_tool_args or "{}")
            except json.JSONDecodeError:
                args = {}
            entry = TOOL_REGISTRY.get(pending_tool_name)
            if not entry:
                yield AgentEvent("error", {"reason": "unknown_tool", "tool": pending_tool_name})
                return
            yield AgentEvent("tool_start", {"name": pending_tool_name, "args": args})
            try:
                result = entry.invoke(args, _user=user)
            except ToolResultTooLargeError:
                result = {"error": "result_too_large", "hint": "narrow your query"}
            except Exception as exc:  # noqa: BLE001 — tools are sandboxed by us
                result = {"error": "tool_failed", "detail": str(exc)[:200]}
            tool_msg = Message.objects.create(
                conversation=conversation,
                role=Message.ROLE_TOOL,
                tool_name=pending_tool_name,
                tool_args=args,
                tool_result=result,
                token_in=chunk_in,
                token_out=chunk_out,
            )
            summary = _summarize_tool_result(pending_tool_name, result)
            yield AgentEvent("tool_end", {"id": tool_msg.id, "summary": summary})
            messages.append({
                "role": "function",
                "name": pending_tool_name,
                "content": f"<<untrusted_data>>{json.dumps(result, ensure_ascii=False)}<</untrusted_data>>",
            })
            continue

        # final assistant message
        final_msg = Message.objects.create(
            conversation=conversation,
            role=Message.ROLE_ASSISTANT,
            content=assistant_text,
            token_in=turn_token_in,
            token_out=turn_token_out,
        )
        yield AgentEvent("done", {"message_id": final_msg.id})
        return


def _summarize_tool_result(name: str, result: Any) -> str:
    if isinstance(result, dict):
        for key in ("speakers", "events"):
            if key in result and isinstance(result[key], list):
                return f"{len(result[key])} {key}"
        if "error" in result:
            return f"error: {result['error']}"
    return name
