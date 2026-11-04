"""A fake model for tests: no network and no API key."""

from collections.abc import Callable, Sequence
from typing import Any

from citywheels.llm.base import LLMClient, Message, ToolCall

Reply = Message | Callable[[list[Message]], Message]


class ScriptedLLM(LLMClient):
    """Returns prepared replies in order and records every request it gets.

    A reply is a Message, or a function of the conversation so far, so a test can answer from a tool result.
    """

    def __init__(self, replies: Sequence[Reply]) -> None:
        self._replies = list(replies)
        self.requests: list[list[Message]] = []
        self.tools: list[dict[str, Any]] = []

    def complete(self, messages: Sequence[Message], tools: Sequence[dict[str, Any]]) -> Message:
        self.requests.append(list(messages))
        self.tools = list(tools)
        if not self._replies:
            raise AssertionError("The agent called the model more often than the test expected.")
        reply = self._replies.pop(0)
        return reply(list(messages)) if callable(reply) else reply


def answer(text: str) -> Message:
    return Message(role="assistant", content=text)


def tool_calls(*calls: tuple[str, dict[str, Any]]) -> Message:
    """An assistant reply asking for the given (tool name, arguments) calls, with ids call_1, call_2, ..."""
    return Message(
        role="assistant",
        tool_calls=tuple(ToolCall(f"call_{i}", name, arguments) for i, (name, arguments) in enumerate(calls, start=1)),
    )
