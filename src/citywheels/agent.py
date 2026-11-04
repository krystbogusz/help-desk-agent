"""The agent loop: the model decides which tools to call, the code runs them, until the model answers."""

import json
import logging

from dataclasses import dataclass
from typing import Any

from citywheels import config
from citywheels.llm.base import LLMClient, Message
from citywheels.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


def fallback_answer() -> str:
    """The answer when the model gives none. Built on each call, so it always has the current staff contact."""
    return (
        "Sorry, I could not find an answer to your question. "
        f"Please contact the CityWheels staff: {config.STAFF_CONTACT}."
    )


@dataclass(frozen=True)
class ToolCallRecord:
    name: str
    arguments: dict[str, Any]
    result: dict[str, Any]


@dataclass
class AgentResult:
    answer: str
    tool_calls: list[ToolCallRecord]
    messages: list[Message]  # the whole conversation, for debugging and follow-up questions
    steps: int  # how many times the model was called
    finished: bool  # False when the agent gave up after max_steps


class Agent:
    def __init__(self, llm: LLMClient, tools: ToolRegistry, system_prompt: str, max_steps: int = 6) -> None:
        self.llm = llm
        self.tools = tools
        self.system_prompt = system_prompt
        self.max_steps = max_steps

    def ask(self, question: str) -> AgentResult:
        messages = [Message(role="system", content=self.system_prompt), Message(role="user", content=question)]
        records: list[ToolCallRecord] = []
        schemas = self.tools.schemas()

        for step in range(1, self.max_steps + 1):
            reply = self.llm.complete(messages, schemas)
            messages.append(reply)
            if not reply.tool_calls:
                answer = (reply.content or "").strip() or fallback_answer()
                return AgentResult(answer, records, messages, steps=step, finished=True)

            for call in reply.tool_calls:
                result = self.tools.execute(call.name, call.arguments)
                logger.info("Tool %s(%s) -> %s", call.name, call.arguments, result)
                records.append(ToolCallRecord(call.name, call.arguments, result))
                messages.append(
                    Message(role="tool", tool_call_id=call.id, content=json.dumps(result, ensure_ascii=False))
                )

        # The model kept calling tools; stop rather than loop forever, and send the customer to the staff.
        logger.warning("No answer after %d model calls", self.max_steps)
        return AgentResult(fallback_answer(), records, messages, steps=self.max_steps, finished=False)
