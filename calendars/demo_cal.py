"""
Demo calendar adapter — simulated availability for testing.
No external API calls. Generates realistic-looking slots
based on client hours config.
"""

from datetime import datetime, timedelta
from typing import List

from .base import CalendarAdapter, TimeSlot, BookingResult


class DemoAdapter(CalendarAdapter):
    """Simulated calendar for demo mode — no API keys needed."""

    def __init__(self, config: dict):
        super().__init__(config)
        self._booked = []  # Track bookings in memory

    def check_availability(self, date_str: str) -> List[TimeSlot]:
        day = datetime.strptime(date_str, "%Y-%m-%d")

        # Respect closed days (Sun=6, Mon=0 by default for barbershops)
        if day.weekday() in self.config.get("closed_days", [6, 0]):
            return []

        open_hour = self.config.get("open_hour", 10)
        close_hour = self.config.get("close_hour", 19)

        # Saturday shorter hours
        if day.weekday() == 5:
            open_hour = self.config.get("sat_open", 9)
            close_hour = self.config.get("sat_close", 16)

        slot_duration = self.config.get("slot_duration", 30)

        slots = []
        current = day.replace(hour=open_hour, minute=0, second=0)
        while current.hour < close_hour:
            slot_end = current + timedelta(minutes=slot_duration)

            # Skip already-booked slots
            is_booked = any(
                b["start"] == current.isoformat()
                for b in self._booked
            )

            # Simulate some slots being taken (every 3rd slot)
            slot_index = (current.hour * 60 + current.minute - open_hour * 60) // slot_duration
            is_simulated_taken = slot_index % 3 == 1

            if not is_booked and not is_simulated_taken:
                slots.append(TimeSlot(
                    start=current.isoformat(),
                    end=slot_end.isoformat(),
                    display=current.strftime("%-I:%M %p"),
                ))

            current = slot_end

        return slots

    def create_booking(self, service, start_time, customer_name, phone, staff="Any", notes=""):
        self._booked.append({
            "start": start_time,
            "service": service,
            "customer": customer_name,
            "phone": phone,
            "staff": staff,
        })

        appt = datetime.fromisoformat(start_time)
        return BookingResult(
            success=True,
            event_id=f"demo-{len(self._booked)}",
            message=f"Booked {service} for {customer_name} at {appt.strftime('%-I:%M %p on %A, %B %d')}",
            details={"mode": "demo", "note": "Simulated booking — no calendar event created"}
        )

    def cancel_booking(self, event_id):
        self._booked = [b for i, b in enumerate(self._booked) if f"demo-{i+1}" != event_id]
        return BookingResult(success=True, message="Demo booking cancelled")
