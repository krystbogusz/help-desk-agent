"""The CityWheels tools as the model sees them: name, description and parameters, bound to their data.

To add a tool: write its function, add a `..._tool()` definition below and list it in `build_registry`.
"""

from collections.abc import Callable
from datetime import datetime

from citywheels import config
from citywheels.tools.bookings import BookingRepository, get_booking
from citywheels.tools.policies import PolicyIndex, search_policies
from citywheels.tools.refund import calculate_refund
from citywheels.tools.registry import Tool, ToolRegistry


def build_registry(
    bookings: BookingRepository | None = None,
    policies: PolicyIndex | None = None,
    clock: Callable[[], datetime] = config.current_time,
) -> ToolRegistry:
    """All CityWheels tools, reading data/ unless other data is passed in (as tests do)."""
    bookings = bookings or BookingRepository.from_file()
    policies = policies or PolicyIndex.from_directory()
    return ToolRegistry(
        [
            search_policies_tool(policies),
            get_booking_tool(bookings),
            calculate_refund_tool(bookings, clock),
        ]
    )


def search_policies_tool(policies: PolicyIndex) -> Tool:
    return Tool(
        name="search_policies",
        description=(
            "Search the CityWheels policy documents: bike types and prices, add-ons, deposits, "
            "late return fees, cancellations and refunds, changing a booking, bad weather, opening hours, "
            "location, what you need to rent, payment, age limits, helmets, accidents, theft. "
            "Returns the most relevant sections with the file and heading they come from. "
            "Write the query as English keywords, even when the customer writes in another language. "
            "If no section matches, try other keywords once; if still nothing matches, "
            "the documents do not cover the question."
        ),
        parameters={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "English keywords, for example 'opening hours Saturday'.",
                },
            },
            "required": ["query"],
        },
        function=lambda query: search_policies(policies, query),
    )


def get_booking_tool(bookings: BookingRepository) -> Tool:
    return Tool(
        name="get_booking",
        description=(
            "Get the details of one booking by its number: status, bike type, number of bikes, "
            "start and end, add-ons, rental price, booking fee, deposit, payment method. "
            "Returns found=false when no booking has that number."
        ),
        parameters={
            "type": "object",
            "properties": {
                "booking_id": {"type": "string", "description": "Booking number, for example CW-1001."},
            },
            "required": ["booking_id"],
        },
        function=lambda booking_id: get_booking(bookings, booking_id),
    )


def calculate_refund_tool(bookings: BookingRepository, clock: Callable[[], datetime]) -> Tool:
    return Tool(
        name="calculate_refund",
        description=(
            "Calculate how much the customer gets back if they cancel a booking, following the "
            "CityWheels cancellation rules: the refunded share of the rental price, the booking fee, "
            "the deposit, the total and how the money comes back. Always use this tool for refund "
            "amounts and never calculate them yourself. It does not cancel the booking. "
            "By default the cancellation time is now; pass cancel_at for a later time "
            "(for example when the customer asks 'what if I cancel tomorrow?')."
        ),
        parameters={
            "type": "object",
            "properties": {
                "booking_id": {"type": "string", "description": "Booking number, for example CW-1001."},
                "cancel_at": {
                    "type": "string",
                    "description": (
                        "Optional. When the customer would cancel, as an ISO 8601 date-time, for example "
                        f"2026-06-11T09:00:00+02:00. A time without a zone is {config.SHOP_TIMEZONE.key} time. "
                        "Leave it out to cancel now."
                    ),
                },
            },
            "required": ["booking_id"],
        },
        function=lambda booking_id, cancel_at=None: calculate_refund(bookings, booking_id, cancel_at, now=clock()),
    )
