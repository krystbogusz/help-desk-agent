"""Booking data and the `get_booking` tool."""

import copy
import json
import re

from pathlib import Path
from typing import Any

from citywheels import config

# Accepts "CW-1002", "cw1002", "CW 1002", "#1002" or just "1002".
_BOOKING_ID = re.compile(r"^(?:CW)?[\s#_-]*(\d+)$", re.IGNORECASE)


def get_booking(repository, booking_id: str) -> dict[str, Any]:
    """Tool: the details of one booking, or found=False with a message the model can pass on."""
    normalized = normalize_booking_id(booking_id)
    if normalized is None:
        return {
            "found": False,
            "booking_id": booking_id,
            "message": "This is not a valid booking number. Booking numbers look like CW-1001.",
        }
    booking = repository.find(normalized)
    if booking is None:
        return {
            "found": False,
            "booking_id": normalized,
            "message": f"There is no booking with number {normalized}.",
        }
    return {"found": True, "booking": booking}


def normalize_booking_id(raw: Any) -> str | None:
    """Return the canonical booking number (CW-1002), or None if `raw` does not look like one."""
    if not isinstance(raw, str):
        return None
    match = _BOOKING_ID.match(raw.strip())
    return f"CW-{match.group(1)}" if match else None


class BookingRepository:
    """Read-only access to the bookings in data/bookings.json."""

    def __init__(self, bookings: list[dict[str, Any]]) -> None:
        self._by_id = {booking["id"]: booking for booking in bookings}

    @classmethod
    def from_file(cls, path: Path | None = None):
        with open(path or config.BOOKINGS_FILE, encoding="utf-8") as file:
            return cls(json.load(file))

    def find(self, booking_id: str) -> dict[str, Any] | None:
        """A copy of the booking, so callers cannot change the stored data."""
        booking = self._by_id.get(booking_id)
        return copy.deepcopy(booking) if booking is not None else None
