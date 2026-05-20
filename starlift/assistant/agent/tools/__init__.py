"""Tool registry and decorator.

All AI-callable functions live here. A tool is a plain Python function plus a
JSON-Schema describing its parameters. The decorator:

1. Registers the function under a name.
2. Builds a GigaChat-compatible ``function`` schema.
3. On invoke: passes ``_user`` (server-side identity) into the function but
   keeps it out of the LLM-facing schema, and enforces a hard ceiling on the
   serialized result size.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable

from django.conf import settings


class ToolResultTooLargeError(Exception):
    """Raised when a tool returns a payload larger than the configured limit."""


@dataclass
class ToolEntry:
    name: str
    schema: dict
    func: Callable

    def invoke(self, args: dict, _user) -> Any:
        result = self.func(**args, _user=_user)
        encoded = json.dumps(result, ensure_ascii=False, default=str)
        max_bytes = getattr(settings, "ASSISTANT_TOOL_RESULT_MAX_BYTES", 4096)
        if len(encoded.encode("utf-8")) > max_bytes:
            raise ToolResultTooLargeError(
                f"Tool {self.name!r} produced {len(encoded)} bytes (limit {max_bytes})."
            )
        return result


TOOL_REGISTRY: dict[str, ToolEntry] = {}


def assistant_tool(*, name: str, description: str, parameters: dict):
    def decorator(func: Callable) -> Callable:
        schema = {"name": name, "description": description, "parameters": parameters}
        TOOL_REGISTRY[name] = ToolEntry(name=name, schema=schema, func=func)
        return func
    return decorator


def _load_builtin_tools() -> None:
    # Imported for side-effects: each module registers its tools via @assistant_tool.
    from . import speakers   # noqa: F401
    from . import events     # noqa: F401
    from . import analytics  # noqa: F401


_load_builtin_tools()
