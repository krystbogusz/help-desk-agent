"""Run the agent on the questions in eval/questions.json, check the answers and write eval/results.md.

    python eval/run_eval.py                run every question and write eval/results.md
    python eval/run_eval.py --only ID ...  run some questions and only print how they went

What each question in questions.json checks:
    expected_tools        tools the agent must call
    expected_arguments    {tool: [argument, ...]}: arguments the agent must pass to that tool
    expected_section      a section that search_policies must find
    must_contain          terms the answer must contain; a list inside the list means any one of them
    must_not_contain      terms the answer must not contain
    expect_staff_contact  the answer must give the staff email or phone
A question passes when it passes all its checks. Terms are matched without regard to case. A term that
is a number matches only that number: "40" matches "40 EUR" and "40.00", but not "140" or "40.5".
"""

import argparse
import json
import os
import re
import sys
import time

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from citywheels import cli, config
from citywheels.agent import Agent, AgentResult
from citywheels.llm.base import ConfigurationError, LLMError, QuotaExceededError

EVAL_DIR = Path(__file__).resolve().parent
QUESTIONS_FILE = EVAL_DIR / "questions.json"
RESULTS_FILE = EVAL_DIR / "results.md"
NUMBER = re.compile(r"\d+(?:[.,]\d+)?")


@dataclass
class Outcome:
    """How the agent did on one question."""

    case: dict[str, Any]
    result: AgentResult | None  # None when the model gave no reply
    seconds: float
    failures: list[str] = field(default_factory=list)  # the checks the answer failed

    @property
    def passed(self) -> bool:
        return not self.failures


def main(argv: list[str] | None = None, agent: Agent | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the CityWheels evaluation.")
    parser.add_argument("--only", nargs="+", metavar="ID", help="run only these questions and only print the results")
    parser.add_argument("--questions", type=Path, default=QUESTIONS_FILE, help="the questions file")
    parser.add_argument(
        "--output", type=Path, help="where to write the results (default: eval/results.md when every question runs)"
    )
    args = parser.parse_args(argv)

    cases = load_cases(args.questions)
    if args.only:
        unknown = sorted(set(args.only) - {case["id"] for case in cases})
        if unknown:
            parser.error(f"unknown question ids: {', '.join(unknown)}")
        cases = [case for case in cases if case["id"] in args.only]
    output = args.output or (None if args.only else RESULTS_FILE)

    try:
        agent = agent or cli.build_agent()
    except ConfigurationError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2

    outcomes: list[Outcome] = []
    stopped = None
    for number, case in enumerate(cases, start=1):
        print(f"[{number}/{len(cases)}] {case['id']}: {case['question']}", flush=True)
        try:
            outcome = run_case(agent, case)
        except QuotaExceededError as exc:
            stopped = f"The run stopped after {len(outcomes)} questions, because the model's quota is used up: {exc}"
            print(stopped, file=sys.stderr)
            break
        outcomes.append(outcome)
        print(f"    {'PASS' if outcome.passed else 'FAIL'} in {outcome.seconds:.0f} s", flush=True)
        for failure in outcome.failures:
            print(f"    - {failure}", flush=True)

    passed = sum(outcome.passed for outcome in outcomes)
    print(f"\n{passed} of {len(cases)} questions passed.")
    if output:
        output.write_text(render_results(outcomes, len(cases), _model_name(agent), stopped), encoding="utf-8")
        print(f"Results written to {output}")
    return 0 if passed == len(cases) else 1


def load_cases(path: Path = QUESTIONS_FILE) -> list[dict[str, Any]]:
    return json.loads(path.read_text(encoding="utf-8"))


def run_case(agent: Agent, case: dict[str, Any]) -> Outcome:
    """Ask the agent one question and check its answer. QuotaExceededError is passed on, to stop the run."""
    started = time.monotonic()
    try:
        result = agent.ask(case["question"])
    except QuotaExceededError:
        raise
    except LLMError as exc:
        return Outcome(case, None, time.monotonic() - started, [f"the model gave no reply: {exc}"])
    return Outcome(case, result, time.monotonic() - started, check_answer(case, result))


def check_answer(case: dict[str, Any], result: AgentResult) -> list[str]:
    """The checks of `case` that the agent's result fails; empty when it passes them all."""
    failures = []
    answer = _normalize(result.answer)

    if not result.finished:
        failures.append(f"no answer after {result.steps} model calls")
    called = {call.name for call in result.tool_calls}
    expected_arguments = case.get("expected_arguments", {})
    expected_tools = dict.fromkeys([*case.get("expected_tools", []), *expected_arguments])
    failures += [f"did not call {tool}" for tool in expected_tools if tool not in called]
    for tool, arguments in expected_arguments.items():
        for argument in arguments:
            passed = any(call.name == tool and argument in call.arguments for call in result.tool_calls)
            if tool in called and not passed:
                failures.append(f"did not pass {argument} to {tool}")
    section = case.get("expected_section")
    if section and section not in _found_sections(result):
        failures.append(f"search_policies did not find the section '{section}'")

    for term in case.get("must_contain", []):
        options = term if isinstance(term, list) else [term]
        if not any(_contains(answer, option) for option in options):
            failures.append(f"answer does not contain {' or '.join(repr(option) for option in options)}")
    failures += [f"answer contains {term!r}" for term in case.get("must_not_contain", []) if _contains(answer, term)]
    contacts = config.STAFF_CONTACT.split(" or ")
    if case.get("expect_staff_contact") and not any(_contains(answer, contact) for contact in contacts):
        failures.append("answer does not give the staff contact")
    return failures


def render_results(outcomes: list[Outcome], total: int, model: str, stopped: str | None = None) -> str:
    """The results as Markdown: the score, a table of all questions, the failed checks and every answer."""
    passed = sum(outcome.passed for outcome in outcomes)
    lines = [
        "# Evaluation results",
        "",
        "The last run of `python eval/run_eval.py` on the questions in [questions.json](questions.json).",
        "",
        f"- Run on: {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC",
        f"- Model: {model}",
        f"- Shop time the agent works with: {config.current_time():%A, %d %B %Y, %H:%M} (fixed in config.py)",
        "",
        f"**{passed} of {total} questions passed.**",
    ]
    if stopped:
        lines += ["", stopped]

    lines += ["", "| Category | Passed |", "| --- | --- |"]
    for category in dict.fromkeys(outcome.case["category"] for outcome in outcomes):
        group = [outcome for outcome in outcomes if outcome.case["category"] == category]
        lines.append(f"| {category} | {sum(outcome.passed for outcome in group)} of {len(group)} |")

    lines += [
        "",
        "| # | Question | Category | Result | Tools called | Model calls | Seconds |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for number, outcome in enumerate(outcomes, start=1):
        tools = ", ".join(call.name for call in outcome.result.tool_calls) if outcome.result else ""
        steps = outcome.result.steps if outcome.result else "-"
        lines.append(
            f"| {number} | `{outcome.case['id']}`: {_cell(outcome.case['question'])} | {outcome.case['category']} "
            f"| {'PASS' if outcome.passed else '**FAIL**'} | {tools or '-'} | {steps} | {outcome.seconds:.0f} |"
        )

    failed = [outcome for outcome in outcomes if not outcome.passed]
    if failed:
        lines += ["", "## Failed checks"]
        for outcome in failed:
            lines += ["", f"`{outcome.case['id']}`:", ""] + [f"- {failure}" for failure in outcome.failures]

    lines += ["", "## Answers"]
    for number, outcome in enumerate(outcomes, start=1):
        lines += [
            "",
            f"### {number}. `{outcome.case['id']}`: {'PASS' if outcome.passed else 'FAIL'}",
            "",
            f"**Question:** {outcome.case['question']}",
        ]
        if outcome.case.get("note"):
            lines += ["", f"**Expected:** {outcome.case['note']}"]
        if outcome.result:
            if outcome.result.tool_calls:
                lines += ["", "**Tools:**", ""] + [
                    f"- `{call.name}({json.dumps(call.arguments, ensure_ascii=False)})`"
                    for call in outcome.result.tool_calls
                ]
            lines += ["", "**Answer:**", ""] + _quote(outcome.result.answer)
    return "\n".join(lines) + "\n"


def _normalize(text: str) -> str:
    """Lower case, with plain dashes, apostrophes and spaces, so that small differences in writing do not matter."""
    text = re.sub(r"[‐-―]", "-", text.lower().replace("’", "'"))
    return " ".join(text.split())


def _contains(text: str, term: str) -> bool:
    """Whether the normalized `text` contains `term`. A number matches only that number, see the docstring above."""
    term = _normalize(term)
    if NUMBER.fullmatch(term):
        return re.search(_number_pattern(term), text) is not None
    return term in text


def _number_pattern(number: str) -> str:
    """A pattern for `number` with any trailing zeros ("40" -> 40, 40.0, 40,00), not inside another number."""
    whole, _, fraction = number.replace(",", ".").partition(".")
    fraction = fraction.rstrip("0")
    decimals = rf"[.,]{fraction}0*" if fraction else r"(?:[.,]0+)?"
    return rf"(?<![\d.,]){whole}{decimals}(?![.,]?\d)"


def _found_sections(result: AgentResult) -> set[str]:
    """The sections that search_policies returned during the run."""
    return {
        item.get("section")
        for call in result.tool_calls
        if call.name == "search_policies"
        for item in call.result.get("results", [])
    }


def _model_name(agent: Agent) -> str:
    model = getattr(agent.llm, "model", type(agent.llm).__name__)
    host = urlparse(os.environ.get("LLM_BASE_URL") or "https://api.openai.com/v1").netloc
    return f"`{model}` at `{host}`"


def _cell(text: str) -> str:
    """Text that is safe inside a Markdown table cell."""
    return " ".join(text.split()).replace("|", "\\|")


def _quote(text: str) -> list[str]:
    """`text` as a Markdown quote, line by line."""
    return [f"> {line}" if line.strip() else ">" for line in text.strip().splitlines()]


if __name__ == "__main__":
    raise SystemExit(main())
