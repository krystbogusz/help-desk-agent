"""Command-line interface: ask one question, or chat until you type 'exit'."""

import argparse
import json
import sys

from dotenv import load_dotenv

from citywheels import config
from citywheels.agent import Agent, AgentResult
from citywheels.llm.base import ConfigurationError, LLMError, QuotaExceededError
from citywheels.llm.openai_compat import OpenAICompatibleClient
from citywheels.prompts import build_system_prompt
from citywheels.tools.definitions import build_registry

EXIT_WORDS = {"exit", "quit", "q"}


def build_agent() -> Agent:
    """The agent with the real model, configured from environment variables and the project's .env file."""
    load_dotenv(config.PROJECT_ROOT / ".env")
    return Agent(
        llm=OpenAICompatibleClient.from_env(),
        tools=build_registry(),
        system_prompt=build_system_prompt(config.current_time()),
    )


def main(argv: list[str] | None = None, agent: Agent | None = None) -> int:
    parser = argparse.ArgumentParser(prog="citywheels", description="Ask the CityWheels help desk a question.")
    parser.add_argument("question", nargs="*", help="the question; leave it out to chat until you type 'exit'")
    parser.add_argument("-v", "--verbose", action="store_true", help="show the tools the agent calls")
    args = parser.parse_args(argv)

    try:
        agent = agent or build_agent()
    except ConfigurationError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2

    if args.question:
        return 0 if _answer(agent, " ".join(args.question), args.verbose, prefix="") else 1

    print("CityWheels help desk. Ask a question, or type 'exit' to quit. Each question is answered on its own.")
    try:
        while True:
            question = input("\nYou: ").strip()
            if question.lower() in EXIT_WORDS:
                return 0
            if question:
                _answer(agent, question, args.verbose, prefix="Agent: ")
    except (EOFError, KeyboardInterrupt):
        print()
        return 0


def _answer(agent: Agent, question: str, verbose: bool, prefix: str) -> bool:
    """Print the agent's answer. Returns False when the model gave no reply."""
    try:
        result = agent.ask(question)
    except QuotaExceededError as exc:
        print(f"Sorry, the language model's quota is used up: {exc}", file=sys.stderr)
        return False
    except LLMError as exc:
        print(f"Sorry, the language model did not answer: {exc}", file=sys.stderr)
        return False
    if verbose:
        _print_trace(result)
    print(f"{prefix}{result.answer}", flush=True)
    return True


def _print_trace(result: AgentResult) -> None:
    for call in result.tool_calls:
        arguments = json.dumps(call.arguments, ensure_ascii=False)
        print(f"  [tool] {call.name}({arguments}) -> {json.dumps(_shorten(call.result), ensure_ascii=False)}", file=sys.stderr)
    status = "answered" if result.finished else "gave up"
    print(f"  [{status} after {result.steps} model call(s)]", file=sys.stderr, flush=True)


def _shorten(value: object, limit: int = 60) -> object:
    """Cut long texts (like policy sections) inside a tool result, but keep every field visible."""
    if isinstance(value, dict):
        return {key: _shorten(item, limit) for key, item in value.items()}
    if isinstance(value, list):
        return [_shorten(item, limit) for item in value]
    if isinstance(value, str) and len(value) > limit:
        return f"{value[:limit]}..."
    return value
