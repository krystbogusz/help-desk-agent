"""calculate_refund: one test per rule in data/policies/cancellations.md, plus the edge cases around them."""

import json
import pytest

from datetime import timedelta
from decimal import Decimal

from citywheels.config import parse_datetime
from citywheels.tools.refund import calculate_refund, compute_refund

NOW = parse_datetime("2026-06-10T09:00:00+02:00")  # the fixed "now" from the assignment
CONFIRMED = ["CW-1001", "CW-1002", "CW-1003", "CW-1004", "CW-1007", "CW-1009", "CW-1010"]
NOT_CANCELLABLE = {"CW-1005": "cancelled", "CW-1006": "completed", "CW-1008": "in_progress"}


def refund(bookings, booking_id, cancel_at=None):
    return calculate_refund(bookings, booking_id, cancel_at, now=NOW)


def amounts(result):
    return (
        result["refund_percent_of_rental"],
        result["rental_refund_eur"],
        result["deposit_refund_eur"],
        result["total_refund_eur"],
    )


# Rule: 48 hours or more before the start -> 100% of the rental price.


def test_48_hours_or_more_before_start_refunds_the_whole_rental_price(bookings):
    result = refund(bookings, "CW-1001")  # 73 h before the start
    assert result["cancellable"] is True
    assert amounts(result) == (100, 40.0, 50.0, 90.0)


def test_exactly_48_hours_before_start_still_refunds_the_whole_rental_price(bookings):
    result = refund(bookings, "CW-1007")  # starts 2026-06-12 09:00, exactly 48 h from now
    assert result["hours_before_start"] == 48
    assert amounts(result) == (100, 36.0, 150.0, 186.0)


# Rule: less than 48 hours, but 24 hours or more -> 50%.


def test_between_24_and_48_hours_before_start_refunds_half(bookings):
    result = refund(bookings, "CW-1002")  # 33 h before the start
    assert amounts(result) == (50, 40.0, 300.0, 340.0)


def test_one_second_under_48_hours_refunds_half(bookings):
    start = parse_datetime("2026-06-13T10:00:00+02:00")  # CW-1001
    result = refund(bookings, "CW-1001", (start - timedelta(hours=48) + timedelta(seconds=1)).isoformat())
    assert result["refund_percent_of_rental"] == 50


def test_exactly_24_hours_before_start_still_refunds_half(bookings):
    result = refund(bookings, "CW-1010")  # starts 2026-06-11 09:00, exactly 24 h from now
    assert result["hours_before_start"] == 24
    assert amounts(result) == (50, 20.0, 150.0, 170.0)


# Rule: less than 24 hours -> 0%.


def test_less_than_24_hours_before_start_refunds_nothing_of_the_rental(bookings):
    result = refund(bookings, "CW-1003")  # 6 h before the start
    assert result["cancellable"] is True
    assert amounts(result) == (0, 0.0, 50.0, 50.0)


def test_one_second_under_24_hours_refunds_nothing_of_the_rental(bookings):
    start = parse_datetime("2026-06-13T10:00:00+02:00")  # CW-1001
    result = refund(bookings, "CW-1001", (start - timedelta(hours=24) + timedelta(seconds=1)).isoformat())
    assert result["refund_percent_of_rental"] == 0


# Rule: the booking fee is never refunded.


@pytest.mark.parametrize("booking_id", CONFIRMED)
def test_booking_fee_is_never_refunded(bookings, booking_id):
    result = refund(bookings, booking_id)
    assert result["booking_fee_refund_eur"] == 0.0


# Rule: the deposit is always refunded in full when a booking is cancelled.


@pytest.mark.parametrize("booking_id", CONFIRMED)
def test_deposit_is_always_refunded_in_full(bookings, booking_id):
    result = refund(bookings, booking_id)
    assert result["deposit_refund_eur"] == result["deposit_eur"]


# Rule: in_progress, completed and cancelled bookings cannot be cancelled, and nothing is refunded.


@pytest.mark.parametrize(("booking_id", "status"), NOT_CANCELLABLE.items())
def test_only_confirmed_bookings_can_be_cancelled(bookings, booking_id, status):
    result = refund(bookings, booking_id)
    assert result["cancellable"] is False
    assert result["status"] == status
    assert status in result["reason"]
    assert amounts(result) == (0, 0.0, 0.0, 0.0)
    assert result["refund_method"] is None


# Rule: how the money comes back.


def test_card_payment_is_refunded_to_the_same_card(bookings):
    assert "same card within 5 working days" in refund(bookings, "CW-1001")["refund_method"]


def test_voucher_payment_is_refunded_as_a_new_voucher(bookings):
    result = refund(bookings, "CW-1004")
    assert amounts(result) == (100, 23.0, 50.0, 73.0)
    assert "new CityWheels voucher" in result["refund_method"]
    assert "never as money" in result["refund_method"]


# Cancelling at another time than now.


def test_cancel_at_a_later_time(bookings):
    result = refund(bookings, "CW-1002", "2026-06-11T09:00:00+02:00")  # "tomorrow": 9 h before the start
    assert result["hours_before_start"] == 9
    assert amounts(result) == (0, 0.0, 300.0, 300.0)


def test_cancel_at_in_another_time_zone_is_converted(bookings):
    result = refund(bookings, "CW-1001", "2026-06-11T08:00:00Z")  # 10:00 in Warsaw: exactly 48 h
    assert result["hours_before_start"] == 48
    assert result["refund_percent_of_rental"] == 100


def test_cancel_at_without_time_zone_is_shop_time(bookings):
    assert refund(bookings, "CW-1001", "2026-06-11 10:00")["refund_percent_of_rental"] == 100
    assert refund(bookings, "CW-1001", "2026-06-11 10:00:01")["refund_percent_of_rental"] == 50


def test_empty_cancel_at_means_now(bookings):
    assert refund(bookings, "CW-1002", "") == refund(bookings, "CW-1002")


def test_cancelling_once_the_rental_has_started_is_not_possible(bookings):
    result = refund(bookings, "CW-1003", "2026-06-10T15:00:00+02:00")  # the start time itself
    assert result["cancellable"] is False
    assert "already started" in result["reason"]
    assert result["total_refund_eur"] == 0.0


def test_cancel_at_in_the_past_is_rejected(bookings):
    result = refund(bookings, "CW-1001", "2026-06-09T09:00:00+02:00")
    assert "in the past" in result["error"]


@pytest.mark.parametrize("cancel_at", ["tomorrow", "11/06/2026", 42])
def test_invalid_cancel_at_is_rejected(bookings, cancel_at):
    assert "not an ISO 8601 date-time" in refund(bookings, "CW-1001", cancel_at)["error"]


# Bookings that do not exist.


@pytest.mark.parametrize("booking_id", ["CW-9999", "not a booking"])
def test_unknown_booking_is_not_found(bookings, booking_id):
    result = refund(bookings, booking_id)
    assert result["found"] is False
    assert "total_refund_eur" not in result


# Amounts.


def test_amounts_are_rounded_to_cents():
    booking = {
        "id": "CW-0001",
        "status": "confirmed",
        "start": "2026-06-11T18:00:00+02:00",  # 33 h from now: 50%
        "rental_price_eur": 33.33,
        "booking_fee_eur": 2.0,
        "deposit_eur": 0.1,
        "paid_with": "card",
    }
    quote = compute_refund(booking, NOW)
    assert quote.rental_refund == Decimal("16.67")  # 16.665 rounded half up
    assert quote.total_refund == Decimal("16.77")


@pytest.mark.parametrize("booking_id", CONFIRMED + list(NOT_CANCELLABLE))
def test_result_is_json_and_total_is_the_sum_of_the_parts(bookings, booking_id):
    result = json.loads(json.dumps(refund(bookings, booking_id)))
    parts = result["rental_refund_eur"] + result["booking_fee_refund_eur"] + result["deposit_refund_eur"]
    assert result["total_refund_eur"] == pytest.approx(parts)
