"""The command line, with a fake model."""

import pytest

from fakes import ScriptedLLM, answer, tool_calls
from citywheels import cli, config
from citywheels.agent import Agent
from citywheels.config import parse_datetime
from citywheels.llm.base import LLMError, QuotaExceededError
from citywheels.tools.definitions import build_registry

NOW = parse_datetime("2026-06-10T09:00:00+02:00")


@pytest.fixture
def make_agent(bookings, policies):
    def make(*replies):
        llm = ScriptedLLM(replies)
        return Agent(llm, build_registry(bookings, policies, clock=lambda: NOW), "Help desk."), llm

    return make


def test_question_from_the_command_line_prints_the_answer(make_agent, capsys):
    agent, llm = make_agent(answer("We open at 08:00."))
    assert cli.main(["When", "do", "you", "open?"], agent=agent) == 0
    assert capsys.readouterr().out == "We open at 08:00.\n"
    assert llm.requests[0][1].content == "When do you open?"


def test_verbose_shows_the_tool_calls(make_agent, capsys):
    agent, _ = make_agent(tool_calls(("calculate_refund", {"booking_id": "CW-1002"})), answer("340 EUR."))
    cli.main(["-v", "Cancel CW-1002"], agent=agent)
    err = capsys.readouterr().err
    assert '[tool] calculate_refund({"booking_id": "CW-1002"})' in err
    assert '"total_refund_eur": 340.0' in err
    assert "answered after 2 model call(s)" in err


def test_chat_answers_until_exit(make_agent, monkeypatch, capsys):
    agent, llm = make_agent(answer("We open at 08:00."), answer("Yes, 40 EUR."))
    typed = iter(["When do you open?", "", "e-bike for a day?", "exit", "never read"])
    monkeypatch.setattr("builtins.input", lambda prompt: next(typed))

    assert cli.main([], agent=agent) == 0
    out = capsys.readouterr().out
    assert "Agent: We open at 08:00." in out
    assert "Agent: Yes, 40 EUR." in out
    assert len(llm.requests) == 2


@pytest.mark.parametrize("stop", [EOFError, KeyboardInterrupt])
def test_chat_ends_on_end_of_input_or_ctrl_c(make_agent, monkeypatch, stop):
    agent, _ = make_agent()

    def press(prompt):
        raise stop

    monkeypatch.setattr("builtins.input", press)
    assert cli.main([], agent=agent) == 0


def test_model_errors_are_reported_instead_of_crashing(make_agent, capsys):
    agent, _ = make_agent()

    def unreachable(messages, tools):
        raise LLMError("Error 503: The model is overloaded.")

    agent.llm.complete = unreachable
    assert cli.main(["When do you open?"], agent=agent) == 1
    assert "did not answer: Error 503: The model is overloaded." in capsys.readouterr().err


def test_used_up_quota_is_reported_instead_of_crashing(make_agent, capsys):
    agent, _ = make_agent()

    def used_up(messages, tools):
        raise QuotaExceededError("limit: 20 requests per day")

    agent.llm.complete = used_up
    assert cli.main(["When do you open?"], agent=agent) == 1
    assert "quota is used up: limit: 20 requests per day" in capsys.readouterr().err


def test_missing_settings_are_reported(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)  # no .env there
    for name in ("LLM_API_KEY", "LLM_MODEL", "LLM_BASE_URL"):
        monkeypatch.delenv(name, raising=False)
    assert cli.main(["When do you open?"]) == 2
    assert "Missing settings: LLM_API_KEY, LLM_MODEL" in capsys.readouterr().err
