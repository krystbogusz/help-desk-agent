"""The tool registry on its own, with a made-up tool: schemas, argument checks and errors that never raise."""

import pytest

from citywheels.tools.registry import Tool, ToolRegistry


def echo(text, repeat=1):
    return {"echo": text * repeat}


ECHO = Tool(
    name="echo",
    description="Repeat a text.",
    parameters={
        "type": "object",
        "properties": {"text": {"type": "string"}, "repeat": {"type": "integer"}},
        "required": ["text"],
    },
    function=echo,
)


@pytest.fixture
def registry():
    return ToolRegistry([ECHO])


def test_schemas_describe_each_tool(registry):
    assert registry.names == ["echo"]
    assert registry.schemas() == [{"name": "echo", "description": "Repeat a text.", "parameters": ECHO.parameters}]


def test_runs_a_tool_with_arguments_as_a_dict_or_a_json_string(registry):
    assert registry.execute("echo", {"text": "hi", "repeat": 2}) == {"echo": "hihi"}
    assert registry.execute("echo", '{"text": "hi"}') == {"echo": "hi"}


@pytest.mark.parametrize(
    ("name", "arguments", "error"),
    [
        ("shout", {"text": "hi"}, "Unknown tool 'shout'. Available tools: echo."),
        ("echo", "{not json", "not valid JSON"),
        ("echo", "[1, 2]", "must be a JSON object"),
        ("echo", None, "Missing arguments for 'echo': text."),
        ("echo", {"text": "hi", "volume": 11}, "Unexpected arguments for 'echo': volume."),
    ],
)
def test_bad_calls_return_an_error_instead_of_raising(registry, name, arguments, error):
    assert error in registry.execute(name, arguments)["error"]


def test_failing_tool_returns_an_error_instead_of_raising():
    def broken():
        raise RuntimeError("boom")

    registry = ToolRegistry([Tool("broken", "Always fails.", {"type": "object", "properties": {}}, broken)])
    assert "boom" in registry.execute("broken", None)["error"]
