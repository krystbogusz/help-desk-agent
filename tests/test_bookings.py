import pytest

from citywheels.tools.bookings import get_booking


def test_returns_the_booking_details(bookings):
    result = get_booking(bookings, "CW-1002")
    assert result["found"] is True
    assert result["booking"] == {
        "id": "CW-1002",
        "status": "confirmed",
        "bike_type": "e-bike",
        "bikes": 2,
        "start": "2026-06-11T18:00:00+02:00",
        "end": "2026-06-12T18:00:00+02:00",
        "add_ons": [],
        "rental_price_eur": 80.0,
        "booking_fee_eur": 2.0,
        "deposit_eur": 300.0,
        "paid_with": "card",
    }


@pytest.mark.parametrize("raw", ["CW-1002", "cw-1002", "cw1002", " CW 1002 ", "#1002", "1002"])
def test_booking_number_is_normalized(bookings, raw):
    result = get_booking(bookings, raw)
    assert result["found"] is True
    assert result["booking"]["id"] == "CW-1002"


def test_unknown_booking_is_not_found(bookings):
    result = get_booking(bookings, "CW-9999")
    assert result["found"] is False
    assert result["booking_id"] == "CW-9999"
    assert "no booking" in result["message"]


@pytest.mark.parametrize("raw", ["", "hello", "CW-", "CW-10O2", None, 1002])
def test_invalid_booking_number_is_not_found_and_does_not_raise(bookings, raw):
    result = get_booking(bookings, raw)
    assert result["found"] is False
    assert "not a valid booking number" in result["message"]


def test_returned_booking_is_a_copy(bookings):
    get_booking(bookings, "CW-1004")["booking"]["add_ons"].append("extra_lock")
    assert get_booking(bookings, "CW-1004")["booking"]["add_ons"] == ["child_seat"]
