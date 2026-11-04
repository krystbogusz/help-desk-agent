"""A client for any chat API in the OpenAI format (chat completions with tool calling).

OpenAI, Google Gemini, Groq, OpenRouter, Mistral and local servers such as Ollama all offer this format,
so the model is chosen by settings alone: LLM_BASE_URL, LLM_API_KEY and LLM_MODEL.
"""

import json
import logging
import os
import time
import openai

from collections.abc import Callable, Sequence
from typing import Any
from openai.types.chat import ChatCompletionMessage

from citywheels.llm.base import ConfigurationError, LLMClient, LLMError, Message, QuotaExceededError, ToolCall

logger = logging.getLogger(__name__)

# Sampling temperature: 0 so that answers vary as little as possible between runs.
TEMPERATURE = 0.0
# Minimum seconds between requests. Gemini's free tier allows 15 requests per minute, one every
# 4 seconds; 4.5 leaves a margin.
MIN_INTERVAL = 4.5
# Seconds to wait before each new try after an error worth trying again, when the API does not say how long.
RETRY_WAITS = (15.0, 30.0, 60.0)
# The API asking to wait longer than this means a daily quota is used up: give up at once.
MAX_RETRY_WAIT = 120.0
REQUEST_TIMEOUT = 60.0
# Errors worth trying again after a wait: rate limits, an overloaded server, network failures and timeouts.
RETRYABLE_ERRORS = (openai.RateLimitError, openai.InternalServerError, openai.APIConnectionError)


class OpenAICompatibleClient(LLMClient):
    def __init__(
        self,
        model: str,
        api_key: str,
        base_url: str | None = None,
        temperature: float = TEMPERATURE,
        min_interval: float = MIN_INTERVAL,
        client: Any = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.model = model
        self.temperature = temperature
        self.min_interval = min_interval
        self._client = client or openai.OpenAI(
            api_key=api_key, base_url=base_url, timeout=REQUEST_TIMEOUT, max_retries=0
        )
        self._sleep = sleep
        self._clock = clock
        self._last_request: float | None = None

    @classmethod
    def from_env(cls):
        """Build the client from LLM_API_KEY, LLM_MODEL and LLM_BASE_URL (empty means OpenAI)."""
        settings = {name: os.environ.get(name, "").strip() for name in ("LLM_API_KEY", "LLM_MODEL", "LLM_BASE_URL")}
        missing = [name for name in ("LLM_API_KEY", "LLM_MODEL") if not settings[name]]
        if missing:
            raise ConfigurationError(
                f"Missing settings: {', '.join(missing)}. Copy .env.example to .env and fill them in."
            )
        return cls(model=settings["LLM_MODEL"], api_key=settings["LLM_API_KEY"], base_url=settings["LLM_BASE_URL"] or None)

    def complete(self, messages: Sequence[Message], tools: Sequence[dict[str, Any]]) -> Message:
        request: dict[str, Any] = {
            "model": self.model,
            "messages": [_to_api(message) for message in messages],
            "temperature": self.temperature,
        }
        if tools:
            request["tools"] = [_tool_schema(tool) for tool in tools]

        waits = iter(RETRY_WAITS)
        while True:
            self._wait_for_min_interval()
            try:
                response = self._client.chat.completions.create(**request)
            except RETRYABLE_ERRORS as error:
                asked = _retry_delay(error)
                if asked is not None and asked > MAX_RETRY_WAIT:
                    raise QuotaExceededError(_describe(error)) from error
                wait = next(waits, None)
                if wait is None:
                    raise LLMError(_describe(error)) from error
                wait = asked if asked is not None else wait
                logger.warning("%s Trying again in %.0f s.", _describe(error), wait)
                self._sleep(wait)
                continue
            except openai.APIError as error:
                raise LLMError(_describe(error)) from error
            if not response.choices:
                return Message(role="assistant")
            return _from_api(response.choices[0].message)

    def _wait_for_min_interval(self) -> None:
        """Space requests at least min_interval seconds apart, to stay under a requests-per-minute limit."""
        if self.min_interval and self._last_request is not None:
            remaining = self._last_request + self.min_interval - self._clock()
            if remaining > 0:
                self._sleep(remaining)
        self._last_request = self._clock()


def _tool_schema(tool: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {"name": tool["name"], "description": tool["description"], "parameters": tool["parameters"]},
    }


def _to_api(message: Message) -> dict[str, Any]:
    """A message in the OpenAI format."""
    if message.raw is not None:
        return message.raw
    if message.role == "tool":
        return {"role": "tool", "tool_call_id": message.tool_call_id, "content": message.content or ""}
    payload: dict[str, Any] = {"role": message.role, "content": message.content}
    if message.tool_calls:
        payload["tool_calls"] = [
            {
                "id": call.id,
                "type": "function",
                "function": {"name": call.name, "arguments": json.dumps(call.arguments, ensure_ascii=False)},
            }
            for call in message.tool_calls
        ]
    return payload


def _from_api(reply: ChatCompletionMessage) -> Message:
    tool_calls = tuple(
        ToolCall(id=call.id, name=call.function.name, arguments=_parse_arguments(call.function.arguments))
        for call in reply.tool_calls or []
    )
    return Message(
        role="assistant",
        content=reply.content or None,
        tool_calls=tool_calls,
        raw=reply.model_dump(exclude_none=True),
    )


def _parse_arguments(arguments: str | None) -> dict[str, Any]:
    """The model sends tool arguments as JSON text. Anything but a JSON object becomes no arguments,
    so the tool answers with an error about the missing ones and the model can try again."""
    try:
        parsed = json.loads(arguments or "{}")
    except json.JSONDecodeError:
        parsed = None
    if not isinstance(parsed, dict):
        logger.warning("Tool arguments are not a JSON object: %r", arguments)
        return {}
    return parsed


def _error_body(error: openai.APIError) -> dict[str, Any]:
    """The API's error object. The SDK unwraps {"error": {...}} itself, but Gemini sends it in a list."""
    body = error.body
    if isinstance(body, list) and body and isinstance(body[0], dict):
        body = body[0].get("error", body[0])
    return body if isinstance(body, dict) else {}


def _describe(error: openai.APIError) -> str:
    message = _error_body(error).get("message") or error.message
    status = getattr(error, "status_code", None)
    return f"Error {status}: {message}" if status else message


def _retry_delay(error: openai.APIError) -> float | None:
    """Seconds the API asks to wait: Gemini says it in the error ("retryDelay": "37s"), others in the
    standard Retry-After header."""
    details = _error_body(error).get("details") or []
    asked = next((item["retryDelay"] for item in details if isinstance(item, dict) and "retryDelay" in item), None)
    if asked is None and isinstance(error, openai.APIStatusError):
        asked = error.response.headers.get("retry-after")
    try:
        return float(str(asked).removesuffix("s")) if asked is not None else None
    except ValueError:
        return None
