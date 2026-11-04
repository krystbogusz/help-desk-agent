"""The OpenAI-format client with a fake SDK client: what we send and how we read the reply, without network."""


import openai
import pytest

from types import SimpleNamespace
from openai.types.chat import ChatCompletion

from citywheels.llm.base import ConfigurationError, LLMError, Message, QuotaExceededError, ToolCall
from citywheels.llm.openai_compat import MIN_INTERVAL, RETRY_WAITS, TEMPERATURE, OpenAICompatibleClient

TOOLS = [
    {
        "name": "get_booking",
        "description": "Get one booking.",
        "parameters": {"type": "object", "properties": {"booking_id": {"type": "string"}}, "required": ["booking_id"]},
    }
]
QUESTION = [Message(role="system", content="Be helpful."), Message(role="user", content="Booking CW-1001?")]
SIGNED_CALL = {
    "id": "t1",
    "type": "function",
    "function": {"name": "get_booking", "arguments": '{"booking_id": "CW-1001"}'},
    "extra_content": {"google": {"thought_signature": "sig-123"}},  # what Gemini adds to its tool calls
}


def completion(content=None, tool_calls=None) -> ChatCompletion:
    message = {"role": "assistant", "content": content}
    if tool_calls:
        message["tool_calls"] = tool_calls
    return ChatCompletion.model_validate(
        {
            "id": "c1",
            "object": "chat.completion",
            "created": 0,
            "model": "test-model",
            "choices": [{"index": 0, "finish_reason": "stop", "message": message}],
        }
    )


def status_error(error_class, status, body, headers=None):
    """An error as the SDK raises it. For {"error": {...}} the SDK keeps only the inner object as body."""
    response = SimpleNamespace(status_code=status, headers=headers or {}, request=None)
    return error_class(f"Error code: {status}", response=response, body=body)


def gemini_rate_limit(retry_delay=None):
    """Gemini's 429: its error object comes in a list, with a RetryInfo among the details."""
    details = [{"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": retry_delay}] if retry_delay else []
    message = "You exceeded your current quota. Quota exceeded for metric: free_tier_requests, limit: 20"
    body = [{"error": {"code": 429, "message": message, "status": "RESOURCE_EXHAUSTED", "details": details}}]
    return status_error(openai.RateLimitError, 429, body)


class FakeCompletions:
    """Stands in for client.chat.completions: raises the given errors first, then returns the replies."""

    def __init__(self, replies, fail_with=()):
        self.replies = list(replies)
        self.fail_with = list(fail_with)
        self.requests: list[dict] = []

    def create(self, **request):
        self.requests.append(request)
        if self.fail_with:
            raise self.fail_with.pop(0)
        return self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]


class FakeTime:
    """A clock that only moves when the code sleeps, and remembers how long it slept."""

    def __init__(self) -> None:
        self.now = 1000.0
        self.sleeps: list[float] = []

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds

    def clock(self) -> float:
        return self.now


def make_client(*replies, fail_with=(), min_interval=0.0, time=None):
    completions = FakeCompletions(replies or [completion("Hi")], fail_with)
    time = time or FakeTime()
    client = OpenAICompatibleClient(
        model="test-model",
        api_key="unused",
        min_interval=min_interval,
        client=SimpleNamespace(chat=SimpleNamespace(completions=completions)),
        sleep=time.sleep,
        clock=time.clock,
    )
    return client, completions


# What we send.


def test_sends_the_conversation_and_the_tools_in_the_openai_format():
    client, completions = make_client()
    client.complete(QUESTION, TOOLS)

    assert completions.requests[0] == {
        "model": "test-model",
        "messages": [
            {"role": "system", "content": "Be helpful."},
            {"role": "user", "content": "Booking CW-1001?"},
        ],
        "temperature": TEMPERATURE,
        "tools": [{"type": "function", "function": TOOLS[0]}],
    }


def test_sends_no_tools_without_tools():
    client, completions = make_client()
    client.complete(QUESTION, [])
    assert "tools" not in completions.requests[0]


def test_reply_goes_back_exactly_as_the_api_returned_it():
    client, completions = make_client(completion(tool_calls=[SIGNED_CALL]), completion("Confirmed."))
    first = client.complete(QUESTION, TOOLS)
    result = Message(role="tool", tool_call_id="t1", content='{"found": true}')
    client.complete([*QUESTION, first, result], TOOLS)

    sent = completions.requests[1]["messages"]
    assert sent[2] == {"role": "assistant", "tool_calls": [SIGNED_CALL]}  # the thought signature is kept
    assert sent[3] == {"role": "tool", "tool_call_id": "t1", "content": '{"found": true}'}


def test_reply_made_in_code_is_sent_in_the_openai_format():
    client, completions = make_client()
    made = Message(role="assistant", tool_calls=(ToolCall("c1", "get_booking", {"booking_id": "CW-1004"}),))
    client.complete([*QUESTION, made], TOOLS)

    assert completions.requests[0]["messages"][2] == {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {"id": "c1", "type": "function", "function": {"name": "get_booking", "arguments": '{"booking_id": "CW-1004"}'}}
        ],
    }


# How we read the reply.


def test_reads_a_text_reply():
    client, _ = make_client(completion("Booking CW-1001 is confirmed."))
    assert client.complete(QUESTION, TOOLS) == Message(role="assistant", content="Booking CW-1001 is confirmed.")


def test_reads_tool_calls():
    client, _ = make_client(completion(tool_calls=[SIGNED_CALL]))
    reply = client.complete(QUESTION, TOOLS)
    assert reply.content is None
    assert reply.tool_calls == (ToolCall("t1", "get_booking", {"booking_id": "CW-1001"}),)


@pytest.mark.parametrize("arguments", ["{not json", "[1, 2]", ""])
def test_arguments_that_are_not_a_json_object_become_no_arguments(arguments):
    call = {"id": "t1", "type": "function", "function": {"name": "get_booking", "arguments": arguments}}
    client, _ = make_client(completion(tool_calls=[call]))
    assert client.complete(QUESTION, TOOLS).tool_calls[0].arguments == {}


def test_reply_without_choices_is_an_empty_answer():
    empty = ChatCompletion.model_validate(
        {"id": "c1", "object": "chat.completion", "created": 0, "model": "test-model", "choices": []}
    )
    client, _ = make_client(empty)
    assert client.complete(QUESTION, TOOLS) == Message(role="assistant")


# Errors and waiting.


def test_rate_limit_is_waited_out():
    time = FakeTime()
    client, completions = make_client(fail_with=[gemini_rate_limit(), gemini_rate_limit()], time=time)
    assert client.complete(QUESTION, TOOLS).content == "Hi"
    assert len(completions.requests) == 3
    assert time.sleeps == list(RETRY_WAITS[:2])


def test_waits_as_long_as_gemini_asks():
    time = FakeTime()
    client, _ = make_client(fail_with=[gemini_rate_limit("7.5s")], time=time)
    client.complete(QUESTION, TOOLS)
    assert time.sleeps == [7.5]


def test_waits_as_long_as_the_retry_after_header_says():
    time = FakeTime()
    error = status_error(openai.RateLimitError, 429, {"message": "Rate limit reached."}, {"retry-after": "12"})
    client, _ = make_client(fail_with=[error], time=time)
    client.complete(QUESTION, TOOLS)
    assert time.sleeps == [12.0]


@pytest.mark.parametrize(
    "error",
    [
        status_error(openai.InternalServerError, 503, {"message": "The model is overloaded."}),
        openai.APIConnectionError(request=None),
        openai.APITimeoutError(request=None),
    ],
)
def test_overloaded_server_and_network_errors_are_tried_again(error):
    time = FakeTime()
    client, completions = make_client(fail_with=[error], time=time)
    assert client.complete(QUESTION, TOOLS).content == "Hi"
    assert (len(completions.requests), time.sleeps) == (2, [RETRY_WAITS[0]])


def test_gives_up_with_an_llm_error_when_waiting_does_not_help():
    time = FakeTime()
    client, completions = make_client(fail_with=[gemini_rate_limit()] * 9, time=time)
    with pytest.raises(LLMError, match="Error 429: You exceeded your current quota"):
        client.complete(QUESTION, TOOLS)
    assert len(completions.requests) == len(RETRY_WAITS) + 1
    assert time.sleeps == list(RETRY_WAITS)


def test_used_up_daily_quota_fails_at_once():
    time = FakeTime()
    client, completions = make_client(fail_with=[gemini_rate_limit("82175s")] * 9, time=time)
    with pytest.raises(QuotaExceededError, match="limit: 20"):
        client.complete(QUESTION, TOOLS)
    assert (len(completions.requests), time.sleeps) == (1, [])


@pytest.mark.parametrize(
    ("error_class", "status", "message"),
    [(openai.BadRequestError, 400, "Invalid schema."), (openai.AuthenticationError, 401, "Incorrect API key.")],
)
def test_other_errors_become_llm_errors_without_waiting(error_class, status, message):
    time = FakeTime()
    error = status_error(error_class, status, {"message": message})
    client, completions = make_client(fail_with=[error], time=time)
    with pytest.raises(LLMError, match=f"Error {status}: {message}") as raised:
        client.complete(QUESTION, TOOLS)
    assert raised.value.__cause__ is error  # the SDK's own error stays attached, for debugging
    assert (len(completions.requests), time.sleeps) == (1, [])


def test_requests_are_spaced_by_the_min_interval():
    time = FakeTime()
    client, _ = make_client(min_interval=12, time=time)
    client.complete(QUESTION, TOOLS)  # the first request does not wait
    time.now += 5  # 5 s pass, for example while a tool runs
    client.complete(QUESTION, TOOLS)
    assert time.sleeps == [7]


# Settings.


def test_from_env_names_the_missing_settings(monkeypatch):
    for name in ("LLM_API_KEY", "LLM_MODEL", "LLM_BASE_URL"):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(ConfigurationError, match="Missing settings: LLM_API_KEY, LLM_MODEL"):
        OpenAICompatibleClient.from_env()


def test_from_env_reads_the_settings(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setenv("LLM_MODEL", "some-model")
    monkeypatch.setenv("LLM_BASE_URL", "https://llm.example/v1/")
    client = OpenAICompatibleClient.from_env()
    assert (client.model, client.temperature, client.min_interval) == ("some-model", TEMPERATURE, MIN_INTERVAL)
    assert str(client._client.base_url) == "https://llm.example/v1/"
    assert client._client.max_retries == 0  # waiting is done here, not by the SDK


def test_empty_base_url_means_openai(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setenv("LLM_MODEL", "some-model")
    monkeypatch.setenv("LLM_BASE_URL", "")
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    assert str(OpenAICompatibleClient.from_env()._client.base_url) == "https://api.openai.com/v1/"
