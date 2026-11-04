from datetime import timedelta

from citywheels import config


def test_current_time_is_the_date_fixed_by_the_assignment():
    assert config.current_time().isoformat() == "2026-06-10T09:00:00+02:00"


def test_current_time_cannot_be_changed_from_the_environment(monkeypatch):
    monkeypatch.setenv("CITYWHEELS_NOW", "2026-06-12T12:00:00+02:00")
    assert config.current_time().isoformat() == "2026-06-10T09:00:00+02:00"


def test_time_without_zone_is_shop_time_in_summer_and_winter():
    assert config.parse_datetime("2026-06-11 10:00").utcoffset() == timedelta(hours=2)
    assert config.parse_datetime("2026-01-11 10:00").utcoffset() == timedelta(hours=1)
