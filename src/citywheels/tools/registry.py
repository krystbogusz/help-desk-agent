"""The tools the model can call: their schemas, and a way to run them that never raises.

This module knows nothing about CityWheels; the CityWheels tools are defined in definitions.py.
"""

import json
import logging

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


def _parse_arguments(tool, arguments: dict[str, Any] | str | None) -> tuple[dict[str, Any], str | None]:
    """Decode the model's arguments and check them against the tool's required and known parameters."""
    if arguments is None or arguments == "":
        arguments = {}
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except json.JSONDecodeError:
            return {}, f"Arguments for '{tool.name}' are not valid JSON: {arguments!r}"
    if not isinstance(arguments, dict):
        return {}, f"Arguments for '{tool.name}' must be a JSON object."

    known = tool.parameters.get("properties", {})
    unexpected = sorted(set(arguments) - set(known))
    if unexpected:
        return {}, f"Unexpected arguments for '{tool.name}': {', '.join(unexpected)}."
    missing = [name for name in tool.parameters.get("required", []) if name not in arguments]
    if missing:
        return {}, f"Missing arguments for '{tool.name}': {', '.join(missing)}."
    return arguments, None


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]  # JSON Schema of the arguments
    function: Callable[..., dict[str, Any]]


class ToolRegistry:
    def __init__(self, tools: Iterable[Tool]) -> None:
        self._tools = {tool.name: tool for tool in tools}

    @property
    def names(self) -> list[str]:
        return list(self._tools)

    def schemas(self) -> list[dict[str, Any]]:
        """Provider-neutral tool definitions: name, description and JSON Schema of the parameters."""
        return [
            {"name": tool.name, "description": tool.description, "parameters": tool.parameters}
            for tool in self._tools.values()
        ]

    def execute(self, name: str, arguments: dict[str, Any] | str | None) -> dict[str, Any]:
        """Run a tool. Problems come back as {"error": ...}, so the model can react instead of the program crashing."""
        tool = self._tools.get(name)
        if tool is None:
            return {"error": f"Unknown tool '{name}'. Available tools: {', '.join(self._tools)}."}
        args, problem = _parse_arguments(tool, arguments)
        if problem:
            return {"error": problem}
        try:
            return tool.function(**args)
        except Exception as exc:  # a bug in one tool must not end the conversation
            logger.exception("Tool %s failed", name)
            return {"error": f"Tool '{name}' failed: {exc}"}
