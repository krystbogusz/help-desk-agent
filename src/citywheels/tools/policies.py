"""Policy documents and the `search_policies` tool.

Each Markdown file is cut into one section per heading, and the sections are ranked with BM25,
a classic keyword-based ranking. The corpus is a few dozen short sections, so this runs in
memory, needs no embeddings model, and gives the same results on every run.
"""

import math
import re
import snowballstemmer

from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from citywheels import config

_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
_WORD = re.compile(r"[a-z0-9]+")
# Different spellings of the same thing, rewritten to one token before splitting into words.
_SYNONYMS = ((re.compile(r"\b(?:e[\s-]?bikes?|electric\s+bikes?)\b"), " ebike "),)
_STOPWORDS = frozenset(
    "a an and are as at be by can could do does for from have how i if in is it me my "
    "of on or our so that the there this to was we what when where which will with you your".split()
)
_STEMMER = snowballstemmer.stemmer("english")


def search_policies(index, query: str, top_k: int = 3) -> dict[str, Any]:
    """Tool: the policy sections most relevant to `query`, with the file and heading they come from."""
    if not isinstance(query, str) or not query.strip():
        return {"error": "query must be a non-empty string."}
    results = index.search(query, top_k)
    if not results:
        return {
            "query": query,
            "results": [],
            "message": "No policy section matches this query. The CityWheels documents may not cover it.",
        }
    return {
        "query": query,
        "results": [
            {"source": section.source, "section": section.title, "text": section.text, "score": round(score, 2)}
            for section, score in results
        ],
    }


def tokenize(text: str) -> list[str]:
    """Lowercase, unify synonyms, drop stopwords and stem: "Cancelled bookings" -> ["cancel", "book"]."""
    text = text.lower()
    for pattern, replacement in _SYNONYMS:
        text = pattern.sub(replacement, text)
    words = [word for word in _WORD.findall(text) if word not in _STOPWORDS]
    return _STEMMER.stemWords(words)


def split_markdown(source: str, markdown: str):
    """Cut a Markdown document into one section per heading. Headings without text of their own are skipped."""
    sections: list[PolicySection] = []
    headings: list[tuple[int, str]] = []
    body: list[str] = []

    def flush() -> None:
        text = "\n".join(body).strip()
        if text:
            title = " > ".join(heading for _, heading in headings) or source
            sections.append(PolicySection(source, title, text))
        body.clear()

    for line in markdown.splitlines():
        match = _HEADING.match(line)
        if match:
            flush()
            level = len(match.group(1))
            headings[:] = [heading for heading in headings if heading[0] < level]
            headings.append((level, match.group(2)))
        else:
            body.append(line)
    flush()
    return sections


@dataclass(frozen=True)
class PolicySection:
    source: str  # file name, for example "faq.md"
    title: str  # heading path, for example "Frequently asked questions > When are you open?"
    text: str


class PolicyIndex:
    """BM25 ranking over policy sections."""

    K1 = 1.5
    B = 0.75

    def __init__(self, sections: list[PolicySection]) -> None:
        self.sections = sections
        # The heading path is counted twice: a match in the title says more than one in the body.
        self._term_counts = [Counter(tokenize(f"{s.title}\n{s.title}\n{s.text}")) for s in sections]
        self._lengths = [sum(counts.values()) for counts in self._term_counts]
        self._average_length = sum(self._lengths) / len(sections) if sections else 0.0
        document_frequency = Counter(term for counts in self._term_counts for term in counts)
        n = len(sections)
        self._idf = {term: math.log(1 + (n - df + 0.5) / (df + 0.5)) for term, df in document_frequency.items()}

    @classmethod
    def from_directory(cls, directory: Path | None = None):
        sections: list[PolicySection] = []
        for path in sorted((directory or config.POLICIES_DIR).glob("*.md")):
            sections.extend(split_markdown(path.name, path.read_text(encoding="utf-8")))
        return cls(sections)

    def search(self, query: str, top_k: int = 3) -> list[tuple[PolicySection, float]]:
        """The best `top_k` sections with their scores. Sections that share no word with the query are left out."""
        terms = set(tokenize(query))
        scored = []
        for section, counts, length in zip(self.sections, self._term_counts, self._lengths):
            length_norm = 1 - self.B + self.B * length / self._average_length
            score = sum(
                self._idf[term] * counts[term] * (self.K1 + 1) / (counts[term] + self.K1 * length_norm)
                for term in terms & counts.keys()
            )
            if score > 0:
                scored.append((section, score))
        scored.sort(key=lambda item: item[1], reverse=True)
        return scored[:top_k]
