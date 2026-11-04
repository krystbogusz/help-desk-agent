"""The evaluation: the questions file, the answer checks, and whole runs with a fake model."""

import json
import pytest
import run_eval

from fakes import ScriptedLLM, answer, tool_calls
from citywheels import config
from citywheels.agent import Agent, AgentResult, ToolCallRecord
from citywheels.config import parse_datetime
from citywheels.llm.base import LLMError, QuotaExceededError
from citywheels.tools.definitions import build_registry

NOW = parse_datetime("2026-06-10T09:00:00+02:00")
FIELDS = {
    "id",
    "category",
    "question",
    "note",
    "expected_tools",
    "expected_arguments",
    "expected_section",
    "must_contain",
    "must_not_contain",
    "expect_staff_contact",
}
REFUND_CASE = {
    "id": "refund",
    "category": "refund",
    "question": "How much do I get back for CW-1002 tomorrow?",
    "expected_tools": ["calculate_refund"],
    "expected_arguments": {"calculate_refund": ["cancel_at"]},
    "must_contain": ["300", ["card", "voucher"]],
    "must_not_contain": ["340"],
    "expect_staff_contact": True,
}
GOOD_ANSWER = "You would get 300.00 EUR back to your card. To cancel, contact help@citywheels.example."


def result(answer_text, calls=(), finished=True):
    return AgentResult(answer=answer_text, tool_calls=list(calls), messages=[], steps=2, finished=finished)


def refund_call(arguments=None):
    return ToolCallRecord("calculate_refund", arguments or {"booking_id": "CW-1002", "cancel_at": "2026-06-11T10:00"}, {})


@pytest.fixture
def make_agent(bookings, policies):
    def make(*replies):
        return Agent(ScriptedLLM(replies), build_registry(bookings, policies, clock=lambda: NOW), "Help desk.")

    return make


# The questions file.


def test_questions_meet_the_assignment():
    cases = run_eval.load_cases()
    categories = [case["category"] for case in cases]
    assert len(cases) >= 10
    assert categories.count("refund") >= 2
    assert categories.count("refuse") >= 2
    assert len({case["id"] for case in cases}) == len(cases)


def test_questions_use_known_fields_tools_and_sections(policies):
    tools = set(build_registry().names)
    sections = {section.title for section in policies.sections}
    for case in run_eval.load_cases():
        assert {"id", "category", "question"} <= set(case) <= FIELDS, case["id"]
        assert set(case.get("expected_tools", [])) | set(case.get("expected_arguments", {})) <= tools, case["id"]
        if "expected_section" in case:
            assert case["expected_section"] in sections, case["id"]


# Matching terms.


@pytest.mark.parametrize(
    ("term", "text", "found"),
    [
        ("340", "You get 340 EUR back.", True),
        ("340", "That is 340.00 EUR.", True),
        ("340", "That is 340,00 EUR.", True),
        ("90", "In total 90.", True),
        ("340", "That is 1340 EUR.", False),
        ("340", "That is 340.5 EUR.", False),
        ("40", "A deposit of 140 EUR.", False),
        ("13.5", "13.50 EUR per started hour.", True),
        ("4", "4 EUR za godzinę.", True),
        ("4", "Doba to 24 godziny.", False),
        ("Canberra", "The capital is CANBERRA.", True),
        ("can't take", "You can’t take it abroad.", True),
        ("08:00-20:00", "Open 08:00–20:00.", True),
        ("+48 000 000 000", "Call +48 000 000 000.", True),
    ],
)
def test_terms_are_matched_loosely_but_numbers_exactly(term, text, found):
    assert run_eval._contains(run_eval._normalize(text), term) is found


# Checking an answer.


def test_good_answer_passes_every_check():
    assert run_eval.check_answer(REFUND_CASE, result(GOOD_ANSWER, [refund_call()])) == []


@pytest.mark.parametrize(
    ("answer_text", "calls", "failure"),
    [
        (GOOD_ANSWER, [], "did not call calculate_refund"),
        (GOOD_ANSWER, [refund_call({"booking_id": "CW-1002"})], "did not pass cancel_at to calculate_refund"),
        (GOOD_ANSWER.replace("300.00", "380"), [refund_call()], "answer does not contain '300'"),
        (GOOD_ANSWER.replace("card", "bank"), [refund_call()], "answer does not contain 'card' or 'voucher'"),
        (GOOD_ANSWER + " Now it would be 340 EUR.", [refund_call()], "answer contains '340'"),
        (GOOD_ANSWER.replace("help@citywheels.example", "us"), [refund_call()], "answer does not give the staff contact"),
    ],
)
def test_each_failed_check_is_reported(answer_text, calls, failure):
    assert run_eval.check_answer(REFUND_CASE, result(answer_text, calls)) == [failure]


def test_staff_contact_is_the_one_in_config_at_check_time(monkeypatch):
    monkeypatch.setattr(config, "STAFF_CONTACT", "desk@other.example or +48 111 111 111")
    failures = run_eval.check_answer(REFUND_CASE, result(GOOD_ANSWER, [refund_call()]))
    assert failures == ["answer does not give the staff contact"]
    assert run_eval.check_answer(REFUND_CASE, result(GOOD_ANSWER + " Or +48 111 111 111.", [refund_call()])) == []


def test_section_must_be_among_the_search_results():
    case = {"id": "hours", "category": "policy", "question": "?", "expected_section": "FAQ > When are you open?"}
    found = ToolCallRecord("search_policies", {"query": "hours"}, {"results": [{"section": "FAQ > When are you open?"}]})
    other = ToolCallRecord("search_policies", {"query": "hours"}, {"results": [{"section": "Prices > Deposit"}]})
    assert run_eval.check_answer(case, result("08:00", [found])) == []
    assert run_eval.check_answer(case, result("08:00", [other])) == [
        "search_policies did not find the section 'FAQ > When are you open?'"
    ]


def test_agent_that_gave_up_fails():
    case = {"id": "x", "category": "policy", "question": "?"}
    assert run_eval.check_answer(case, result("Sorry.", finished=False)) == ["no answer after 2 model calls"]


# Whole runs with a fake model.


@pytest.fixture
def questions_file(tmp_path):
    cases = [
        {**REFUND_CASE, "question": "If I cancel CW-1002 tomorrow at 10:00?"},
        {"id": "capital", "category": "refuse", "question": "Capital of Australia?", "must_not_contain": ["canberra"]},
    ]
    path = tmp_path / "questions.json"
    path.write_text(json.dumps(cases), encoding="utf-8")
    return path


def test_run_writes_the_results(make_agent, questions_file, tmp_path, capsys):
    agent = make_agent(
        tool_calls(("calculate_refund", {"booking_id": "CW-1002", "cancel_at": "2026-06-11T10:00"})),
        lambda messages: answer(f"You get {json.loads(messages[-1].content)['total_refund_eur']} EUR to your card. "
                                "Contact help@citywheels.example to cancel."),
        answer("It is Canberra."),
    )
    output = tmp_path / "results.md"

    assert run_eval.main(["--questions", str(questions_file), "--output", str(output)], agent=agent) == 1

    printed = capsys.readouterr().out
    assert "1 of 2 questions passed." in printed
    results = output.read_text(encoding="utf-8")
    assert "**1 of 2 questions passed.**" in results
    assert "| refund | 1 of 1 |" in results
    assert "| 2 | `capital`: Capital of Australia? | refuse | **FAIL** | - | 1 |" in results
    assert "- answer contains 'canberra'" in results
    assert '- `calculate_refund({"booking_id": "CW-1002", "cancel_at": "2026-06-11T10:00"})`' in results
    assert "> You get 300.0 EUR to your card." in results


def test_only_runs_the_chosen_questions_and_writes_nothing(make_agent, questions_file, tmp_path, capsys):
    agent = make_agent(answer("I cannot help with that."))
    assert run_eval.main(["--questions", str(questions_file), "--only", "capital"], agent=agent) == 0
    assert "1 of 1 questions passed." in capsys.readouterr().out
    assert sorted(path.name for path in tmp_path.iterdir()) == ["questions.json"]


def test_unknown_question_id_is_an_error(make_agent, questions_file):
    with pytest.raises(SystemExit):
        run_eval.main(["--questions", str(questions_file), "--only", "nope"], agent=make_agent())


def test_model_error_fails_only_that_question(make_agent, questions_file, tmp_path):
    def unreachable(messages):
        raise LLMError("Error 503: The model is overloaded.")

    agent = make_agent(unreachable, answer("I cannot help with that."))
    output = tmp_path / "results.md"
    run_eval.main(["--questions", str(questions_file), "--output", str(output)], agent=agent)
    results = output.read_text(encoding="utf-8")
    assert "**1 of 2 questions passed.**" in results
    assert "- the model gave no reply: Error 503: The model is overloaded." in results


def test_used_up_quota_stops_the_run(make_agent, questions_file, tmp_path):
    def used_up(messages):
        raise QuotaExceededError("limit: 500 requests per day")

    output = tmp_path / "results.md"
    run_eval.main(["--questions", str(questions_file), "--output", str(output)], agent=make_agent(used_up))
    results = output.read_text(encoding="utf-8")
    assert "**0 of 2 questions passed.**" in results
    assert "The run stopped after 0 questions, because the model's quota is used up: limit: 500" in results
