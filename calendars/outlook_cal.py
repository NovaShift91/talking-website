"""
Microsoft Outlook / Office 365 adapter — via Microsoft Graph API.

Setup:
1. Register an app at portal.azure.com → App registrations
2. Grant Calendars.ReadWrite permissions
3. Create a client secret
4. Set in client config:
   - calendar_type: "outlook"
   - outlook_tenant_id: "your-tenant-id"
   - outlook_client_id: "your-app-client-id"
   - outlook_client_secret: "your-client-secret"
   - outlook_user_email: "client@theirdomain.com"
   - calendar_id: (optional — defaults to primary calendar)
"""

import logging
from datetime import datetime, timedelta
from typing import List

import requests

from .base import CalendarAdapter, TimeSlot, BookingResult

logger = logging.getLogger(__name__)

GRAPH_API = "https://graph.microsoft.com/v1.0"


class OutlookAdapter(CalendarAdapter):
    """Microsoft Outlook/365 integration via Graph API."""

    def __init__(self, config: dict):
        super().__init__(config)
        self.tenant_id = config.get("outlook_tenant_id", "")
        self.client_id = config.get("outlook_client_id", "")
        self.client_secret = config.get("outlook_client_secret", "")
        self.user_email = config.get("outlook_user_email", "")
        self.calendar_id = config.get("calendar_id", "")
        self._token = None

    def _get_token(self):
        """Get an OAuth2 token via client credentials flow."""
        if self._token:
            return self._token

        try:
            r = requests.post(
                f"https://login.microsoftonline.com/{self.tenant_id}/oauth2/v2.0/token",
                data={
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "scope": "https://graph.microsoft.com/.default",
                    "grant_type": "client_credentials"
                }
            )
            r.raise_for_status()
            self._token = r.json()["access_token"]
            return self._token
        except Exception as e:
            logger.error(f"Outlook auth failed: {e}")
            return None

    def _headers(self):
        token = self._get_token()
        if not token:
            return None
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }

    def _calendar_path(self):
        """Build the Graph API path for the user's calendar."""
        base = f"{GRAPH_API}/users/{self.user_email}"
        if self.calendar_id:
            return f"{base}/calendars/{self.calendar_id}"
        return f"{base}/calendar"

    def check_availability(self, date_str: str) -> List[TimeSlot]:
        headers = self._headers()
        if not headers:
            return []

        day_start = datetime.strptime(date_str, "%Y-%m-%d")
        day_end = day_start + timedelta(days=1)
        tz = self.config.get("timezone", "America/Chicago")

        try:
            # Fetch events for the day
            r = requests.get(
                f"{self._calendar_path()}/calendarView",
                headers=headers,
                params={
                    "startDateTime": day_start.isoformat() + "Z",
                    "endDateTime": day_end.isoformat() + "Z",
                    "$orderby": "start/dateTime",
                    "$select": "start,end,subject"
                }
            )
            r.raise_for_status()
            events = r.json().get("value", [])

            booked = []
            for event in events:
                s = event["start"]["dateTime"]
                e = event["end"]["dateTime"]
                booked.append((
                    datetime.fromisoformat(s),
                    datetime.fromisoformat(e)
                ))

            # Generate available slots
            open_hour = self.config.get("open_hour", 9)
            close_hour = self.config.get("close_hour", 17)
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
            logger.error(f"Outlook availability error: {e}")
            return []

    def create_booking(self, service, start_time, customer_name, phone, staff="Any", notes=""):
        headers = self._headers()
        if not headers:
            return BookingResult(success=False, message="Outlook not connected")

        tz = self.config.get("timezone", "America/Chicago")

        duration = 30
        for s in self.config.get("services", []):
            if s["name"].lower() == service.lower():
                duration = s.get("duration", 30)
                break

        appt_time = datetime.fromisoformat(start_time)
        appt_end = appt_time + timedelta(minutes=duration)

        event = {
            "subject": f"{service} — {customer_name}",
            "body": {
                "contentType": "text",
                "content": (
                    f"Service: {service}\n"
                    f"Customer: {customer_name}\n"
                    f"Phone: {phone}\n"
                    f"Staff: {staff}\n"
                    f"Notes: {notes}\n"
                    f"Booked via: NovaShift Talking Website"
                )
            },
            "start": {"dateTime": appt_time.isoformat(), "timeZone": tz},
            "end": {"dateTime": appt_end.isoformat(), "timeZone": tz},
        }

        try:
            r = requests.post(
                f"{self._calendar_path()}/events",
                headers=headers,
                json=event
            )
            r.raise_for_status()
            data = r.json()

            return BookingResult(
                success=True,
                event_id=data.get("id"),
                message=f"Booked {service} for {customer_name} at {appt_time.strftime('%-I:%M %p on %A, %B %d')}",
                details={"provider": "outlook"}
            )
        except Exception as e:
            logger.error(f"Outlook booking error: {e}")
            return BookingResult(success=False, message="Could not create booking")

    def cancel_booking(self, event_id):
        headers = self._headers()
        if not headers:
            return BookingResult(success=False, message="Outlook not connected")

        try:
            r = requests.delete(
                f"{self._calendar_path()}/events/{event_id}",
                headers=headers
            )
            r.raise_for_status()
            return BookingResult(success=True, message="Booking cancelled")
        except Exception as e:
            logger.error(f"Outlook cancel error: {e}")
            return BookingResult(success=False, message="Could not cancel booking")
