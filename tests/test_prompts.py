import pytest

from citywheels import config
from citywheels.config import parse_datetime
from citywheels.prompts import build_system_prompt


@pytest.mark.parametrize(
    ("now", "written"),
    [
        ("2026-06-10T09:00:00+02:00", "Wednesday, 10 June 2026, 09:00, Europe/Warsaw time (UTC+02:00)"),
        ("2026-06-10T07:00:00Z", "Wednesday, 10 June 2026, 09:00, Europe/Warsaw time (UTC+02:00)"),
        ("2026-01-10T09:00:00+01:00", "Saturday, 10 January 2026, 09:00, Europe/Warsaw time (UTC+01:00)"),
    ],
)
def test_prompt_gives_the_current_date_in_shop_time(now, written):
    assert f"The current date and time is {written}." in build_system_prompt(parse_datetime(now))


def test_prompt_uses_the_staff_contact_from_config_at_the_time_it_is_built(monkeypatch):
    monkeypatch.setattr(config, "STAFF_CONTACT", "desk@example.org")
    assert "desk@example.org" in build_system_prompt(parse_datetime("2026-06-10T09:00:00+02:00"))


def test_prompt_names_the_tools_and_the_staff_contact():
    prompt = build_system_prompt(parse_datetime("2026-06-10T09:00:00+02:00"))
    for text in ("search_policies", "get_booking", "calculate_refund", "help@citywheels.example", "+48 000 000 000"):
        assert text in prompt
