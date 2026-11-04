"""The agent loop with a fake model instead of a real one: no network and no API key."""

import json
import pytest

from fakes import ScriptedLLM, answer, tool_calls
from citywheels import config
from citywheels.agent import Agent, fallback_answer
from citywheels.config import parse_datetime
from citywheels.tools.definitions import build_registry

NOW = parse_datetime("2026-06-10T09:00:00+02:00")
SYSTEM_PROMPT = "You are the CityWheels help desk."


@pytest.fixture
def tools(bookings, policies):
    return build_registry(bookings, policies, clock=lambda: NOW)


def last_tool_result(messages):
    return json.loads(messages[-1].content)


def test_answer_without_tools(tools):
    llm = ScriptedLLM([answer("We open at 08:00.")])
    result = Agent(llm, tools, SYSTEM_PROMPT).ask("When do you open?")

    assert result.answer == "We open at 08:00."
    assert result.tool_calls == []
    assert (result.steps, result.finished) == (1, True)
    first_request = llm.requests[0]
    assert [(m.role, m.content) for m in first_request] == [("system", SYSTEM_PROMPT), ("user", "When do you open?")]
    assert [tool["name"] for tool in llm.tools] == ["search_policies", "get_booking", "calculate_refund"]


def test_tool_result_goes_back_to_the_model_and_the_amount_comes_from_the_code(tools):
    llm = ScriptedLLM(
        [
            tool_calls(("calculate_refund", {"booking_id": "CW-1002"})),
            lambda messages: answer(f"You will get {last_tool_result(messages)['total_refund_eur']:.2f} EUR back."),
        ]
    )
    result = Agent(llm, tools, SYSTEM_PROMPT).ask("I want to cancel booking CW-1002. How much will I get back?")

    assert result.answer == "You will get 340.00 EUR back."
    assert [(call.name, call.arguments) for call in result.tool_calls] == [("calculate_refund", {"booking_id": "CW-1002"})]
    assert (result.steps, result.finished) == (2, True)
    second_request = llm.requests[1]
    assert [m.role for m in second_request] == ["system", "user", "assistant", "tool"]
    assert second_request[3].tool_call_id == second_request[2].tool_calls[0].id


def test_tools_can_be_called_over_several_steps(tools):
    llm = ScriptedLLM(
        [
            tool_calls(("search_policies", {"query": "cancel refund"})),
            tool_calls(("calculate_refund", {"booking_id": "CW-1001"})),
            answer("You get 90 EUR back."),
        ]
    )
    result = Agent(llm, tools, SYSTEM_PROMPT).ask("What if I cancel CW-1001?")

    assert [call.name for call in result.tool_calls] == ["search_policies", "calculate_refund"]
    assert result.steps == 3
    assert [m.role for m in result.messages] == ["system", "user", "assistant", "tool", "assistant", "tool", "assistant"]


def test_several_tool_calls_in_one_reply_each_get_their_result(tools):
    llm = ScriptedLLM(
        [
            tool_calls(("get_booking", {"booking_id": "CW-1004"}), ("calculate_refund", {"booking_id": "CW-1004"})),
            answer("You get 73 EUR back as a voucher."),
        ]
    )
    Agent(llm, tools, SYSTEM_PROMPT).ask("Cancel CW-1004?")

    tool_messages = [m for m in llm.requests[1] if m.role == "tool"]
    assert [m.tool_call_id for m in tool_messages] == ["call_1", "call_2"]
    assert json.loads(tool_messages[0].content)["booking"]["paid_with"] == "voucher"
    assert json.loads(tool_messages[1].content)["total_refund_eur"] == 73.0


def test_unknown_booking_does_not_crash(tools):
    llm = ScriptedLLM([tool_calls(("get_booking", {"booking_id": "CW-9999"})), answer("Booking CW-9999 was not found.")])
    result = Agent(llm, tools, SYSTEM_PROMPT).ask("What is booking CW-9999?")

    assert result.tool_calls[0].result["found"] is False
    assert result.answer == "Booking CW-9999 was not found."


@pytest.mark.parametrize(
    ("call", "error"),
    [
        (("cancel_booking", {"booking_id": "CW-1001"}), "Unknown tool 'cancel_booking'"),
        (("calculate_refund", {}), "Missing arguments"),
    ],
)
def test_bad_tool_call_error_goes_back_to_the_model(tools, call, error):
    llm = ScriptedLLM([tool_calls(call), lambda messages: answer(last_tool_result(messages)["error"])])
    result = Agent(llm, tools, SYSTEM_PROMPT).ask("Cancel CW-1001")

    assert error in result.answer
    assert result.finished


def test_gives_up_after_max_steps(tools):
    llm = ScriptedLLM([tool_calls(("search_policies", {"query": "opening hours"}))] * 3)
    result = Agent(llm, tools, SYSTEM_PROMPT, max_steps=3).ask("When do you open?")

    assert result.answer == fallback_answer()
    assert (result.steps, result.finished) == (3, False)
    assert len(llm.requests) == 3
    assert len(result.tool_calls) == 3


@pytest.mark.parametrize("text", [None, "", "   "])
def test_empty_reply_falls_back_to_contacting_the_staff(tools, text):
    llm = ScriptedLLM([answer(text)])
    result = Agent(llm, tools, SYSTEM_PROMPT).ask("Hello?")

    assert result.answer == fallback_answer()
    assert "help@citywheels.example" in result.answer


def test_fallback_uses_the_staff_contact_from_config_at_the_time_it_is_given(tools, monkeypatch):
    monkeypatch.setattr(config, "STAFF_CONTACT", "desk@example.org")
    result = Agent(ScriptedLLM([answer("")]), tools, SYSTEM_PROMPT).ask("Hello?")
    assert "desk@example.org" in result.answer
