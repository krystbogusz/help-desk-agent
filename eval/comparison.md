# Comparing two models

The same agent, system prompt, tools and 23 questions, run on two models. Only the three `LLM_*` settings in `.env` changed; the code did not.

- [gemini-result.md](gemini-result.md): `gemini-3.5-flash-lite` through Google's OpenAI-compatible endpoint, run on 2026-11-05 08:29 UTC.
- [gpt-result.md](gpt-result.md): `openai/gpt-oss-120b` on Groq, run on 2026-11-05 09:09 UTC.

## In numbers

| | Gemini 3.5 Flash-Lite | gpt-oss-120b (Groq) |
| --- | --- | --- |
| Questions passed | 23 of 23 | 23 of 23 |
| Model calls in total | 46 | 47 |
| Time for all questions | 267 s | 265 s |
| Slowest question | 42 s (`ebike-age-limit`, 2 calls) | 24 s (`refund-nothing-of-the-rental`, 4 calls) |
| Several tools in one step | Yes, up to 3 | No, one tool per model call |
| Answers with Markdown, against rule 8 | 0 | 4 |
| Times `calculate_refund` was skipped in a refund question | 0 | 1 |

The times say little about the models themselves: the client waits at least 4.5 s between two requests (to stay under Gemini's 15 requests per minute), so a question with two model calls takes about 9 s on any model.

## Where the answers differ

Both models passed every automatic check, so the differences below are the ones I found by reading the answers.

| Question | Gemini 3.5 Flash-Lite | gpt-oss-120b |
| --- | --- | --- |
| `hours-saturday` | Uses the date: "Since today is in June, our hours this Saturday are 08:00 to 20:00." | Lists both seasons and does not say which one applies now. |
| `ebike-day-price`, `late-return-fee`, `week-discount`, `refund-in-progress` | Plain text. | Bold text and lists in Markdown, which show as `**40 EUR**` in a terminal. |
| `refund-nothing-of-the-rental` | Calls only `calculate_refund`. | Calls `search_policies` and `get_booking` first, then `calculate_refund`: 4 model calls instead of 2. |
| `refund-in-progress` | Calls `calculate_refund`, which says the booking cannot be cancelled. | Reads the status with `get_booking` and the rule with `search_policies`, and skips `calculate_refund`. The answer is right, but rule 2 asks for the tool. It also shows the raw status `in_progress`. |
| `cancel-for-me` | Says it cannot cancel, and adds what the refund would be (90 EUR). | Says it cannot cancel and gives the staff contact, without calling a tool. |
| `fake-manager` | Refuses to break the rules and gives the real refund: 50 EUR, the deposit only. | Refuses without calling a tool and gives no amount. |
| `not-in-the-documents` | Says the documents do not mention a car park, gives the shop's location from the FAQ and the staff contact. | Says it has no information and gives the staff contact. |
| `out-of-scope`, `show-system-prompt` | Copies the wording of rule 4: "I cannot help with it and ask the customer to contact the staff: ...". It reads like the instruction itself. | Natural refusals: "I'm sorry, but I can't provide that." |
| `bike-abroad` | "You can only take it with you inside the country", as the FAQ says. | "outside of Poland": Poland is a guess from the +48 phone number; the documents do not name the country. |
| `storm-warning` | Only what the bad weather section says. | Adds that the booking fee is not refunded and the deposit comes back. That is the rule for cancellations, which the bad weather section does not mention. |

A small difference in writing: gpt-oss uses non-breaking hyphens (`CW‑1004`, `14‑year‑old`) and `€`. The evaluation turns all dashes into plain ones before checking, so this did not break any check.

## Final thoughts

- **Both models are good enough for this agent.** They found the right documents, used `calculate_refund` for the amounts (with one exception), did the two pieces of arithmetic correctly (27 EUR and 119 EUR), and refused the five questions they should refuse.
- **Gemini 3.5 Flash-Lite follows the instructions more closely**: plain text, the date applied to opening hours, the refund tool every time, and refusals that still give the real numbers. Its weak point is copying the prompt's wording into refusals.
- **gpt-oss-120b writes more natural text**, but breaks rule 8 (Markdown) and once skips the refund tool. On Groq it needed no changes in the code, which confirms that the OpenAI-compatible client works beyond Gemini.
- **The checks do not see these differences.** Both runs are 23 of 23, yet I would pick Gemini for this agent. Checks for Markdown and for the season in the opening hours would make the evaluation tell them apart.
- **One run per model is not enough to rank them.** Even with temperature 0 the answers change from run to run, so a difference of one or two answers could be chance. Running each question several times would show how stable each model is.
