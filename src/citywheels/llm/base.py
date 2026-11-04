"""What the agent loop and a model client share: messages, tool calls, the client interface and errors."""

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

# system: the instructions;
# user: the customer's question;
# assistant: the model's reply, with text or tool calls;
# tool: the result of one tool call.
Role = Literal["system", "user", "assistant", "tool"]


@dataclass(frozen=True)
class ToolCall:
    """The model asking to run one tool."""

    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class Message:
    role: Role
    content: str | None = None
    tool_calls: tuple[ToolCall, ...] = ()  # assistant: the tools the model asks to run
    tool_call_id: str | None = None  # tool: the id of the call this result answers
    # assistant: the reply exactly as the API returned it. It is sent back unchanged, so that fields
    # some providers add are kept (Gemini needs its thought signatures to go on after a tool call).
    raw: dict[str, Any] | None = field(default=None, compare=False, repr=False)


class LLMClient(ABC):
    @abstractmethod
    def complete(self, messages: Sequence[Message], tools: Sequence[dict[str, Any]]) -> Message:
        """Send the conversation and the tool schemas ({"name", "description", "parameters"}), and
        return the model's reply (role="assistant")."""


class ConfigurationError(RuntimeError):
    """A required setting is missing."""


class LLMError(RuntimeError):
    """The model gave no reply."""


class QuotaExceededError(LLMError):
    """The quota of the model's API is used up, and waiting a few minutes will not help."""
