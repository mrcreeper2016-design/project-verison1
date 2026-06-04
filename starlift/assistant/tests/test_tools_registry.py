import json

from django.test import TestCase, override_settings

from assistant.agent.tools import (
    TOOL_REGISTRY,
    ToolResultTooLargeError,
    assistant_tool,
)


@override_settings(ASSISTANT_TOOL_RESULT_MAX_BYTES=128)
class ToolDecoratorTests(TestCase):
    def setUp(self):
        # Snapshot the registry so we can restore it after each test.
        # Other test modules rely on the built-in tools being present.
        self._registry_snapshot = dict(TOOL_REGISTRY)

    def tearDown(self):
        TOOL_REGISTRY.clear()
        TOOL_REGISTRY.update(self._registry_snapshot)

    def test_registers_tool_with_schema(self):
        @assistant_tool(
            name="echo",
            description="Echo back",
            parameters={
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
            },
        )
        def echo(text, _user=None):
            return {"text": text}

        self.assertIn("echo", TOOL_REGISTRY)
        entry = TOOL_REGISTRY["echo"]
        self.assertEqual(entry.schema["name"], "echo")
        self.assertEqual(entry.schema["parameters"]["required"], ["text"])

    def test_invoke_passes_user_and_returns_result(self):
        @assistant_tool(name="who", description="who", parameters={"type": "object", "properties": {}})
        def who(_user=None):
            return {"username": _user.username if _user else None}

        class _U:
            username = "alice"

        result = TOOL_REGISTRY["who"].invoke({}, _user=_U())
        self.assertEqual(result, {"username": "alice"})

    def test_rejects_oversized_result(self):
        @assistant_tool(name="big", description="big", parameters={"type": "object", "properties": {}})
        def big(_user=None):
            return {"data": "x" * 1024}

        with self.assertRaises(ToolResultTooLargeError):
            TOOL_REGISTRY["big"].invoke({}, _user=None)
