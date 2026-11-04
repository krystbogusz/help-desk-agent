"""Settings shared by the agent and its tools: data paths, the help desk's "now", and facts copied from data/."""

import os
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = Path(os.environ.get("CITYWHEELS_DATA_DIR", PROJECT_ROOT / "data"))
POLICIES_DIR = DATA_DIR / "policies"
BOOKINGS_FILE = DATA_DIR / "bookings.json"

# Facts copied by hand from the assignment data. They are hardcoded (mocked for this made-up shop)
# so that the model does not have to look them up on every question, and so that refund amounts
# are computed by code. They can change: when the files in data/ change, update them here too.

# The shop's time zone and the fixed "current" time from the assignment, so that answers are the
# same on every run.
SHOP_TIMEZONE = ZoneInfo("Europe/Warsaw")
NOW = "2026-06-10T09:00:00+02:00"

# data/policies/cancellations.md, "Contact the staff".
STAFF_CONTACT = "help@citywheels.example or +48 000 000 000"

# data/policies/cancellations.md, "Cancelling a booking": only bookings with this status can be cancelled.
CANCELLABLE_STATUS = "confirmed"

# data/policies/cancellations.md, "Cancelling a booking": share of the rental price refunded, by how
# long before the start the booking is cancelled. Checked from the top, so a notice of exactly 48 h
# or 24 h falls into the higher tier ("48 hours or more").
REFUND_TIERS: tuple[tuple[timedelta, Decimal], ...] = (
    (timedelta(hours=48), Decimal("1.00")),
    (timedelta(hours=24), Decimal("0.50")),
    (timedelta(0), Decimal("0.00")),
)

# data/policies/cancellations.md, "How the money comes back", by how the booking was paid.
REFUND_METHODS = {
    "card": "The refund goes back to the same card within 5 working days.",
    "voucher": "The rental refund comes back as a new CityWheels voucher of the same value, never as money. "
    "The deposit is refunded the same way it was paid.",
}


def parse_datetime(value: str) -> datetime:
    """Parse an ISO 8601 date-time. A value without a time zone is read as shop time."""
    parsed = datetime.fromisoformat(value.strip())
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=SHOP_TIMEZONE)
    return parsed


def current_time() -> datetime:
    """The help desk's "now": the date fixed by the assignment."""
    return parse_datetime(NOW)
