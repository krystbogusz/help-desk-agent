import pytest

from citywheels.tools.bookings import BookingRepository
from citywheels.tools.policies import PolicyIndex


@pytest.fixture(scope="session")
def bookings() -> BookingRepository:
    return BookingRepository.from_file()


@pytest.fixture(scope="session")
def policies() -> PolicyIndex:
    return PolicyIndex.from_directory()
