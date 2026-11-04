"""Cancellation rules and the `calculate_refund` tool.

The amounts are computed here, in code, and never by the model. The rules come from
data/policies/cancellations.md; the numbers taken from it (refund tiers, cancellable status,
refund methods) are in config.py.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from citywheels import config
from citywheels.tools.bookings import BookingRepository, get_booking

UNKNOWN_REFUND_METHOD = "Contact the staff to find out how the money comes back."

_CENT = Decimal("0.01")
_ZERO = Decimal("0.00")


def calculate_refund(
    repository: BookingRepository,
    booking_id: str,
    cancel_at: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Tool: how much the customer gets back when cancelling now, or at `cancel_at` (ISO 8601)."""
    lookup = get_booking(repository, booking_id)
    if not lookup["found"]:
        return lookup

    now = now or config.current_time()
    if not cancel_at:
        when = now
    else:
        try:
            when = config.parse_datetime(cancel_at)
        except (AttributeError, TypeError, ValueError):
            return {
                "error": f"cancel_at '{cancel_at}' is not an ISO 8601 date-time, "
                "for example 2026-06-11T09:00:00+02:00."
            }
        if when < now:
            return {"error": f"cancel_at {when.isoformat()} is in the past. It is now {now.isoformat()}."}

    return {"found": True, **compute_refund(lookup["booking"], when).to_dict()}


def compute_refund(booking: dict[str, Any], cancel_at: datetime):
    """Apply the cancellation rules to one booking, as if it were cancelled."""
    status = booking["status"]
    start = config.parse_datetime(booking["start"])
    notice = start - cancel_at

    if status != config.CANCELLABLE_STATUS:
        cancellable, share = False, _ZERO
        reason = f"Bookings with the status '{status}' cannot be cancelled, and nothing is refunded for them."
    elif notice <= timedelta(0):
        cancellable, share = False, _ZERO
        reason = "The rental has already started at that time, so the booking can no longer be cancelled."
    else:
        cancellable = True
        share = next(tier_share for minimum, tier_share in config.REFUND_TIERS if notice >= minimum)
        reason = (
            f"Cancelled {notice / timedelta(hours=1):g} hours before the start, so {share:.0%} of the rental "
            "price is refunded. The booking fee is never refunded. The deposit is refunded in full."
        )

    deposit = _eur(booking["deposit_eur"])
    rental_price = _eur(booking["rental_price_eur"])
    return RefundQuote(
        booking_id=booking["id"],
        status=status,
        cancellable=cancellable,
        reason=reason,
        cancel_at=cancel_at,
        start=start,
        refund_percent=int(share * 100),
        rental_price=rental_price,
        rental_refund=_eur(rental_price * share),
        booking_fee=_eur(booking["booking_fee_eur"]),
        booking_fee_refund=_ZERO,
        deposit=deposit,
        deposit_refund=deposit if cancellable else _ZERO,
        refund_method=config.REFUND_METHODS.get(booking["paid_with"], UNKNOWN_REFUND_METHOD) if cancellable else None,
    )


def _eur(value: Any) -> Decimal:
    """An amount in EUR, rounded to cents. Goes through str() so floats like 0.1 stay exact."""
    return Decimal(str(value)).quantize(_CENT, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class RefundQuote:
    """What a customer gets back when cancelling one booking at one moment."""

    booking_id: str
    status: str
    cancellable: bool
    reason: str
    cancel_at: datetime
    start: datetime
    refund_percent: int
    rental_price: Decimal
    rental_refund: Decimal
    booking_fee: Decimal
    booking_fee_refund: Decimal
    deposit: Decimal
    deposit_refund: Decimal
    refund_method: str | None

    @property
    def total_refund(self) -> Decimal:
        return self.rental_refund + self.booking_fee_refund + self.deposit_refund

    @property
    def hours_before_start(self) -> float:
        return round((self.start - self.cancel_at) / timedelta(hours=1), 2)

    def to_dict(self) -> dict[str, Any]:
        """JSON-ready view for the model, with amounts in EUR."""
        return {
            "booking_id": self.booking_id,
            "status": self.status,
            "cancellable": self.cancellable,
            "reason": self.reason,
            "cancel_at": self.cancel_at.isoformat(),
            "rental_start": self.start.isoformat(),
            "hours_before_start": self.hours_before_start,
            "refund_percent_of_rental": self.refund_percent,
            "rental_price_eur": float(self.rental_price),
            "rental_refund_eur": float(self.rental_refund),
            "booking_fee_eur": float(self.booking_fee),
            "booking_fee_refund_eur": float(self.booking_fee_refund),
            "deposit_eur": float(self.deposit),
            "deposit_refund_eur": float(self.deposit_refund),
            "total_refund_eur": float(self.total_refund),
            "refund_method": self.refund_method,
        }
