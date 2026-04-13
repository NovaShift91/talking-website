"""
Base calendar adapter — all providers implement this interface.
"""

from abc import ABC, abstractmethod
from typing import List, Optional
from dataclasses import dataclass


@dataclass
class TimeSlot:
    """A single available time slot."""
    start: str       # ISO 8601 datetime
    end: str         # ISO 8601 datetime
    display: str     # Human-readable, e.g. "10:00 AM"
    provider_data: dict = None  # Provider-specific metadata


@dataclass
class BookingResult:
    """Result of a booking attempt."""
    success: bool
    event_id: Optional[str] = None
    message: str = ""
    details: dict = None


class CalendarAdapter(ABC):
    """
    Abstract base for calendar integrations.
    Each provider (Google, Calendly, Outlook, Square, etc.)
    implements these three methods.
    """

    def __init__(self, config: dict):
        """
        Initialize with the client's calendar config.
        Config shape varies by provider — each adapter
        pulls what it needs.
        """
        self.config = config

    @abstractmethod
    def check_availability(self, date_str: str) -> List[TimeSlot]:
        """
        Return available time slots for a given date.
        date_str: YYYY-MM-DD format
        Returns: list of TimeSlot objects
        """
        pass

    @abstractmethod
    def create_booking(
        self,
        service: str,
        start_time: str,
        customer_name: str,
        phone: str,
        staff: str = "Any",
        notes: str = ""
    ) -> BookingResult:
        """
        Book an appointment.
        start_time: ISO 8601 datetime
        Returns: BookingResult with success/failure and event ID
        """
        pass

    @abstractmethod
    def cancel_booking(self, event_id: str) -> BookingResult:
        """
        Cancel an existing booking.
        Returns: BookingResult with success/failure
        """
        pass

    @property
    def provider_name(self) -> str:
        """Human-readable provider name for logs/responses."""
        return self.__class__.__name__.replace("Adapter", "")
