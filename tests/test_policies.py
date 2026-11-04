import pytest

from citywheels.tools.policies import search_policies, split_markdown, tokenize


def test_documents_are_split_into_one_section_per_heading(policies):
    titles = {(section.source, section.title) for section in policies.sections}
    assert ("faq.md", "Frequently asked questions > When are you open?") in titles
    assert ("prices.md", "Prices > Bike rental") in titles
    assert ("cancellations.md", "Cancellations and refunds > Cancelling a booking") in titles


def test_heading_without_text_of_its_own_is_not_a_section():
    sections = split_markdown("x.md", "# Title\n\n## Part\n\nText.\n")
    assert [(section.title, section.text) for section in sections] == [("Title > Part", "Text.")]


def test_section_title_is_the_heading_path():
    markdown = "# A\nintro\n## B\ntext b\n### C\ntext c\n## D\ntext d\n"
    assert [section.title for section in split_markdown("x.md", markdown)] == ["A", "A > B", "A > B > C", "A > D"]


def test_spellings_of_e_bike_are_one_token():
    assert tokenize("e-bike") == tokenize("E-Bikes") == tokenize("electric bike") == tokenize("ebike")


@pytest.mark.parametrize(
    ("query", "expected_section"),
    [
        ("opening hours Saturday", "Frequently asked questions > When are you open?"),
        ("e-bike price whole day", "Prices > Bike rental"),
        ("cancel booking refund", "Cancellations and refunds > Cancelling a booking"),
        ("age limit e-bike 14 year old", "Frequently asked questions > Are there age limits?"),
        ("storm warning bad weather refund", "Cancellations and refunds > Bad weather"),
        ("late return fee", "Prices > Late return"),
        ("refund paid with voucher", "Cancellations and refunds > How the money comes back"),
        ("change booking dates", "Cancellations and refunds > Changing a booking"),
        ("helmet required", "Frequently asked questions > Do I have to wear a helmet?"),
        ("bike stolen", "Frequently asked questions > What if the bike is stolen or lost?"),
    ],
)
def test_top_result_is_the_relevant_section(policies, query, expected_section):
    assert policies.search(query)[0][0].title == expected_section


def test_unrelated_question_finds_nothing(policies):
    assert policies.search("What is the capital of Australia?") == []


def test_tool_returns_sections_with_their_source(policies):
    result = search_policies(policies, "deposit cash")
    assert result["query"] == "deposit cash"
    assert 1 <= len(result["results"]) <= 3
    assert {"source", "section", "text", "score"} <= result["results"][0].keys()
    assert any("We do not take deposits in cash" in item["text"] for item in result["results"])


def test_tool_says_when_nothing_matches(policies):
    result = search_policies(policies, "capital of Australia")
    assert result["results"] == []
    assert "may not cover it" in result["message"]


@pytest.mark.parametrize("query", ["", "   ", None])
def test_tool_rejects_empty_query(policies, query):
    assert "non-empty" in search_policies(policies, query)["error"]


@pytest.mark.parametrize("top_k", [1, 5, 10])
def test_tool_returns_up_to_top_k_sections(policies, top_k):
    assert len(search_policies(policies, "bike", top_k)["results"]) == top_k
