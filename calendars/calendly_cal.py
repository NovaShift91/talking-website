"""
Calendly adapter — availability + booking via Calendly Scheduling API.

Setup:
1. Client needs a paid Calendly plan (Standard+)
2. Generate a Personal Access Token at calendly.com/integrations
3. Set in client config:
   - calendar_type: "calendly"
   - calendly_token: "the PAT"
   - calendly_event_type: "https://api.calendly.com/event_types/XXXX"
     (get this from GET /event_types after auth)

The Scheduling API (POST /invitees) lets us book without redirects
or iframes — perfect for AI chat booking.
"""

import logging
from datetime import datetime, timedelta
from typing import List

import requests

from .base import CalendarAdapter, TimeSlot, BookingResult

logger = logging.getLogger(__name__)

CALENDLY_API = "https://api.calendly.com"


class CalendlyAdapter(CalendarAdapter):
    """Calendly integration via REST API v2 + Scheduling API."""

    def __init__(self, config: dict):
        super().__init__(config)
        self.token = config.get("calendly_token", "")
        self.event_type_uri = config.get("calendly_event_type", "")
        self.headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json"
        }

    def _get_user_uri(self):
        """Get the current user's URI (needed for some endpoints)."""
        try:
            r = requests.get(f"{CALENDLY_API}/users/me", headers=self.headers)
            r.raise_for_status()
            return r.json()["resource"]["uri"]
        except Exception as e:
            logger.error(f"Calendly user lookup failed: {e}")
            return None

    def check_availability(self, date_str: str) -> List[TimeSlot]:
        if not self.token or not self.event_type_uri:
            logger.warning("Calendly not configured — missing token or event_type")
            return []

        day_start = datetime.strptime(date_str, "%Y-%m-%d")
        day_end = day_start + timedelta(days=1)

        try:
            r = requests.get(
                f"{CALENDLY_API}/event_type_available_times",
                headers=self.headers,
                params={
                    "event_type": self.event_type_uri,
                    "start_time": day_start.strftime("%Y-%m-%dT00:00:00Z"),
                    "end_time": day_end.strftime("%Y-%m-%dT00:00:00Z"),
                }
            )
            r.raise_for_status()
            data = r.json()

            slots = []
            for slot in data.get("collection", []):
                start = slot.get("start_time", "")
                if not start:
                    continue

                start_dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
                # Convert to local display (naive approach — works for demo)
                local_dt = start_dt.replace(tzinfo=None)

                slots.append(TimeSlot(
                    start=start,
                    end=slot.get("end_time", ""),
                    display=local_dt.strftime("%-I:%M %p"),
                    provider_data={"invitees_remaining": slot.get("invitees_remaining")},
                ))

            return slots

        except requests.exceptions.HTTPError as e:
            logger.error(f"Calendly availability error: {e} — {e.response.text if e.response else ''}")
            return []
        except Exception as e:
            logger.error(f"Calendly availability error: {e}")
            return []

    def create_booking(self, service, start_time, customer_name, phone, staff="Any", notes=""):
        if not self.token or not self.event_type_uri:
            return BookingResult(success=False, message="Calendly not configured")

        # Split name for Calendly's first/last name fields
        name_parts = customer_name.strip().split(" ", 1)
        first_name = name_parts[0]
        last_name = name_parts[1] if len(name_parts) > 1 else ""

        try:
            # Use the Scheduling API — POST /invitees
            payload = {
                "event_type": self.event_type_uri,
                "start_time": start_time,
                "invitee": {
                    "name": customer_name,
                    "email": f"{first_name.lower()}@placeholder.novashift.local",
                    # Calendly requires email — use placeholder if not collected
                },
                "questions_and_answers": [
                    {"question": "Phone", "answer": phone},
                    {"question": "Service", "answer": service},
                    {"question": "Staff Preference", "answer": staff},
                ]
            }

            if notes:
                payload["questions_and_answers"].append(
                    {"question": "Notes", "answer": notes}
                )

            r = requests.post(
                f"{CALENDLY_API}/invitees",
                headers=self.headers,
                json=payload
            )
            r.raise_for_status()
            data = r.json()

            event_uri = data.get("resource", {}).get("event", "")
            event_id = event_uri.split("/")[-1] if event_uri else ""

            appt = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
            return BookingResult(
                success=True,
                event_id=event_id,
                message=f"Booked {service} for {customer_name} at {appt.strftime('%-I:%M %p on %A, %B %d')}",
                details={"provider": "calendly", "event_uri": event_uri}
            )

        except requests.exceptions.HTTPError as e:
            error_detail = ""
            if e.response is not None:
                try:
                    error_detail = e.response.json().get("message", e.response.text[:200])
                except Exception:
                    error_detail = e.response.text[:200]
            logger.error(f"Calendly booking error: {e} — {error_detail}")
            return BookingResult(success=False, message=f"Could not book: {error_detail}")
        except Exception as e:
            logger.error(f"Calendly booking error: {e}")
            return BookingResult(success=False, message="Could not create booking")

    def cancel_booking(self, event_id):
        if not self.token:
            return BookingResult(success=False, message="Calendly not configured")

        try:
            # Cancel by marking the invitee as cancelled
            r = requests.post(
                f"{CALENDLY_API}/scheduled_events/{event_id}/cancellation",
                headers=self.headers,
                json={"reason": "Cancelled via NovaShift Talking Website"}
            )
            r.raise_for_status()
            return BookingResult(success=True, message="Booking cancelled via Calendly")
        except Exception as e:
            logger.error(f"Calendly cancel error: {e}")
            return BookingResult(success=False, message="Could not cancel booking")
