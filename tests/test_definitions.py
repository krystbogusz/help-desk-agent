"""The CityWheels tools as the model sees them, run through the registry."""

import pytest

from citywheels.config import parse_datetime
from citywheels.tools.definitions import build_registry

NOW = parse_datetime("2026-06-10T09:00:00+02:00")


@pytest.fixture
def registry(bookings, policies):
    return build_registry(bookings, policies, clock=lambda: NOW)


def test_exposes_the_three_tools_with_schemas(registry):
    assert registry.names == ["search_policies", "get_booking", "calculate_refund"]
    for schema in registry.schemas():
        assert schema["description"]
        assert schema["parameters"]["type"] == "object"
        assert set(schema["parameters"]["required"]) <= schema["parameters"]["properties"].keys()


def test_runs_each_tool(registry):
    assert registry.execute("search_policies", {"query": "opening hours"})["results"]
    assert registry.execute("get_booking", {"booking_id": "CW-1001"})["found"] is True
    assert registry.execute("calculate_refund", {"booking_id": "CW-1002"})["total_refund_eur"] == 340.0


def test_model_cannot_choose_how_many_sections_to_search(registry):
    search = next(schema for schema in registry.schemas() if schema["name"] == "search_policies")
    assert list(search["parameters"]["properties"]) == ["query"]
    assert len(registry.execute("search_policies", {"query": "bike"})["results"]) == 3
    result = registry.execute("search_policies", {"query": "bike", "top_k": 6})
    assert "Unexpected arguments for 'search_policies': top_k." in result["error"]


def test_refund_at_a_later_time(registry):
    result = registry.execute("calculate_refund", '{"booking_id": "CW-1002", "cancel_at": "2026-06-11T09:00:00+02:00"}')
    assert result["total_refund_eur"] == 300.0


def test_refund_uses_the_registry_clock(bookings, policies):
    later = build_registry(bookings, policies, clock=lambda: parse_datetime("2026-06-11T09:00:00+02:00"))
    assert later.execute("calculate_refund", {"booking_id": "CW-1002"})["total_refund_eur"] == 300.0


def test_model_cannot_choose_now_for_a_refund(registry):
    result = registry.execute("calculate_refund", {"booking_id": "CW-1002", "now": "2026-06-01T09:00:00+02:00"})
    assert "Unexpected arguments for 'calculate_refund': now." in result["error"]
