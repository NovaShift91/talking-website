"""
Google Calendar adapter — real-time availability and booking
via Google Calendar API with a service account.

Setup:
1. Create a Google Cloud project + enable Calendar API
2. Create a service account, download JSON key
3. Client shares their calendar with the service account email
4. Set calendar_id in client config
"""

import os
import logging
from datetime import datetime, timedelta
from typing import List

from .base import CalendarAdapter, TimeSlot, BookingResult

logger = logging.getLogger(__name__)

# Lazy import — only loaded when this adapter is used
_service = None


def _get_service():
    """Lazy-init the Google Calendar API service."""
    global _service
    if _service is not None:
        return _service

    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build

        creds_path = os.environ.get("GOOGLE_SERVICE_ACCOUNT_PATH", "service-account.json")
        creds = service_account.Credentials.from_service_account_file(
            creds_path,
            scopes=["https://www.googleapis.com/auth/calendar"]
        )
        _service = build("calendar", "v3", credentials=creds)
        return _service
    except Exception as e:
        logger.error(f"Failed to init Google Calendar: {e}")
        return None


class GoogleAdapter(CalendarAdapter):
    """Google Calendar integration via service account."""

    def check_availability(self, date_str: str) -> List[TimeSlot]:
        service = _get_service()
        if not service:
            return []

        calendar_id = self.config.get("calendar_id")
        if not calendar_id:
            return []

        day_start = datetime.strptime(date_str, "%Y-%m-%d")
        day_end = day_start + timedelta(days=1)
        tz = self.config.get("timezone", "America/Chicago")

        try:
            events_result = service.events().list(
                calendarId=calendar_id,
                timeMin=day_start.isoformat() + "Z",
                timeMax=day_end.isoformat() + "Z",
                singleEvents=True,
                orderBy="startTime"
            ).execute()

            booked = []
            for event in events_result.get("items", []):
                start = event["start"].get("dateTime", event["start"].get("date"))
                end = event["end"].get("dateTime", event["end"].get("date"))
                booked.append((
                    datetime.fromisoformat(start.replace("Z", "+00:00")).replace(tzinfo=None),
                    datetime.fromisoformat(end.replace("Z", "+00:00")).replace(tzinfo=None)
                ))

            # Generate slots within business hours
            open_hour = self.config.get("open_hour", 10)
            close_hour = self.config.get("close_hour", 19)
            slot_duration = self.config.get("slot_duration", 30)

            slots = []
            current = day_start.replace(hour=open_hour, minute=0)
            while current.hour < close_hour:
                slot_end = current + timedelta(minutes=slot_duration)
                is_free = all(
                    not (current < b_end and slot_end > b_start)
                    for b_start, b_end in booked
                )
                if is_free:
                    slots.append(TimeSlot(
                        start=current.isoformat(),
                        end=slot_end.isoformat(),
                        display=current.strftime("%-I:%M %p"),
                    ))
                current = slot_end

            return slots

        except Exception as e:
            logger.error(f"Google Calendar availability error: {e}")
            return []

    def create_booking(self, service_name, start_time, customer_name, phone, staff="Any", notes=""):
        service = _get_service()
        if not service:
            return BookingResult(success=False, message="Google Calendar not connected")

        calendar_id = self.config.get("calendar_id")
        tz = self.config.get("timezone", "America/Chicago")

        # Find service duration
        duration = 30
        for s in self.config.get("services", []):
            if s["name"].lower() == service_name.lower():
                duration = s.get("duration", 30)
                break

        appt_time = datetime.fromisoformat(start_time)
        appt_end = appt_time + timedelta(minutes=duration)

        event = {
            "summary": f"{service_name} — {customer_name}",
            "description": (
                f"Service: {service_name}\n"
                f"Customer: {customer_name}\n"
                f"Phone: {phone}\n"
                f"Staff: {staff}\n"
                f"Notes: {notes}\n"
                f"Booked via: NovaShift Talking Website"
            ),
            "start": {"dateTime": appt_time.isoformat(), "timeZone": tz},
            "end": {"dateTime": appt_end.isoformat(), "timeZone": tz},
        }

        try:
            created = service.events().insert(
                calendarId=calendar_id,
                body=event
            ).execute()

            return BookingResult(
                success=True,
                event_id=created.get("id"),
                message=f"Booked {service_name} for {customer_name} at {appt_time.strftime('%-I:%M %p on %A, %B %d')}",
                details={"provider": "google", "calendar_id": calendar_id}
            )
        except Exception as e:
            logger.error(f"Google Calendar booking error: {e}")
            return BookingResult(success=False, message="Could not create booking")

    def cancel_booking(self, event_id):
        service = _get_service()
        calendar_id = self.config.get("calendar_id")
        if not service or not calendar_id:
            return BookingResult(success=False, message="Google Calendar not connected")

        try:
            service.events().delete(calendarId=calendar_id, eventId=event_id).execute()
            return BookingResult(success=True, message="Booking cancelled")
        except Exception as e:
            logger.error(f"Google Calendar cancel error: {e}")
            return BookingResult(success=False, message="Could not cancel booking")
