"""
NovaShift Talking Website — Backend API
Proxies chat messages to Anthropic, manages client configs,
and integrates with Google Calendar for real-time booking.
"""

import os
import json
import logging
from datetime import datetime, timedelta
from functools import wraps

from flask import Flask, request, jsonify, Response
from flask_cors import CORS
import anthropic
from google.oauth2 import service_account
from googleapiclient.discovery import build

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------
app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

# CORS — allow widget to call from any client site
CORS(app, resources={r"/api/*": {"origins": "*"}})

# Anthropic client
claude = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY", ""))

# Google Calendar setup (optional — works without it in demo mode)
GCAL_ENABLED = os.path.exists("service-account.json")
if GCAL_ENABLED:
    creds = service_account.Credentials.from_service_account_file(
        "service-account.json",
        scopes=["https://www.googleapis.com/auth/calendar"]
    )
    calendar_service = build("calendar", "v3", credentials=creds)
    app.logger.info("Google Calendar integration ENABLED")
else:
    calendar_service = None
    app.logger.info("Google Calendar integration DISABLED (no service-account.json)")


# ---------------------------------------------------------------------------
# Client config loader
# ---------------------------------------------------------------------------
def load_client(client_id):
    """Load a client config from the /clients folder."""
    path = os.path.join("clients", f"{client_id}.json")
    if not os.path.exists(path):
        return None
    with open(path, "r") as f:
        return json.load(f)


def require_client(fn):
    """Decorator — loads client config from X-Client-ID header."""
    @wraps(fn)
    def wrapper(*args, **kwargs):
        client_id = request.headers.get("X-Client-ID", "demo")
        client = load_client(client_id)
        if not client:
            return jsonify({"error": f"Unknown client: {client_id}"}), 404
        return fn(client=client, *args, **kwargs)
    return wrapper


# ---------------------------------------------------------------------------
# Build system prompt from client config
# ---------------------------------------------------------------------------
def build_system_prompt(client):
    """Assemble the system prompt from client config fields."""
    services_block = "\n".join(
        f"- {s['name']}: ${s['price']} ({s['duration']} min)"
        for s in client.get("services", [])
    )

    staff_block = "\n".join(
        f"- {s['name']} — {s.get('specialty', 'all services')}"
        for s in client.get("staff", [])
    )

    hours_block = "\n".join(
        f"- {h}" for h in client.get("hours", [])
    )

    calendar_instructions = ""
    if client.get("calendar_id") and GCAL_ENABLED:
        calendar_instructions = """
CALENDAR BOOKING:
When the customer is ready to book, you have access to the real calendar.
Tell them you're checking availability, and the system will provide open slots.
Once they confirm a time, the system will create the calendar event.
"""
    else:
        # Demo mode — simulated availability
        tomorrow = (datetime.now() + timedelta(days=1)).strftime("%A, %B %d")
        day_after = (datetime.now() + timedelta(days=2)).strftime("%A, %B %d")
        saturday = ""
        for i in range(1, 7):
            d = datetime.now() + timedelta(days=i)
            if d.weekday() == 5:
                saturday = d.strftime("%A, %B %d")
                break

        calendar_instructions = f"""
AVAILABILITY (demo mode):
- {tomorrow}: 10:00 AM, 11:30 AM, 1:00 PM, 3:00 PM, 5:00 PM
- {day_after}: 10:00 AM, 10:30 AM, 2:00 PM, 4:30 PM
{f'- {saturday}: 9:00 AM, 11:00 AM, 12:30 PM, 2:00 PM' if saturday else ''}
- If they ask for a time not listed, say it's taken and suggest nearby times.
"""

    return f"""You are the AI booking assistant for {client['business_name']}, a {client['business_type']} in {client['location']}.

BUSINESS INFO:
- Name: {client['business_name']}
- Location: {client['location']}
- Phone: {client.get('phone', 'N/A')}
- Hours:
{hours_block}

SERVICES & PRICING:
{services_block}

STAFF:
{staff_block}

YOUR PERSONALITY:
{client.get('personality', 'Friendly, professional, and helpful.')}

Keep responses SHORT — 1-3 sentences unless listing services or confirming a booking.
Never say you are an AI. You are the shop's booking assistant.

BOOKING FLOW:
When someone wants to book, collect these naturally (not all at once):
1. What service they want
2. Staff preference (or "whoever's available")
3. Preferred day and time
4. Their first name and phone number

Once you have all info, confirm the details clearly and say you're locking it in.

{calendar_instructions}

RULES:
- Stay on topic — redirect unrelated questions back to the business
- If someone seems unsure, suggest the most popular service
- Walk-ins are welcome but booking guarantees a spot
- Be warm and conversational, match the vibe of a {client['business_type']}"""


# ---------------------------------------------------------------------------
# API Routes
# ---------------------------------------------------------------------------

@app.route("/api/chat", methods=["POST"])
@require_client
def chat(client):
    """Main chat endpoint — proxies conversation to Anthropic."""
    data = request.get_json()
    messages = data.get("messages", [])

    if not messages:
        return jsonify({"error": "No messages provided"}), 400

    system_prompt = build_system_prompt(client)

    try:
        response = claude.messages.create(
            model=os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-20250514"),
            max_tokens=500,
            system=system_prompt,
            messages=messages
        )

        reply = ""
        for block in response.content:
            if block.type == "text":
                reply += block.text

        return jsonify({
            "reply": reply,
            "usage": {
                "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens
            }
        })

    except anthropic.APIError as e:
        app.logger.error(f"Anthropic API error: {e}")
        return jsonify({"error": "Chat service temporarily unavailable"}), 503


@app.route("/api/config", methods=["GET"])
@require_client
def get_config(client):
    """Returns public-safe client config for widget initialization."""
    return jsonify({
        "business_name": client["business_name"],
        "greeting": client.get("greeting", f"Hey there! 👋 How can I help you today?"),
        "accent_color": client.get("accent_color", "#c8a84e"),
        "position": client.get("widget_position", "bottom-right"),
    })


@app.route("/api/availability", methods=["POST"])
@require_client
def check_availability(client):
    """Check Google Calendar availability for a given date range."""
    if not GCAL_ENABLED or not client.get("calendar_id"):
        return jsonify({"mode": "demo", "message": "Calendar not connected — using simulated slots"}), 200

    data = request.get_json()
    date_str = data.get("date")  # Expected: YYYY-MM-DD

    if not date_str:
        return jsonify({"error": "Date required"}), 400

    try:
        # Build time range for the requested day
        day_start = datetime.strptime(date_str, "%Y-%m-%d")
        day_end = day_start + timedelta(days=1)

        # Fetch existing events
        events_result = calendar_service.events().list(
            calendarId=client["calendar_id"],
            timeMin=day_start.isoformat() + "Z",
            timeMax=day_end.isoformat() + "Z",
            singleEvents=True,
            orderBy="startTime"
        ).execute()

        booked_times = []
        for event in events_result.get("items", []):
            start = event["start"].get("dateTime", event["start"].get("date"))
            end = event["end"].get("dateTime", event["end"].get("date"))
            booked_times.append({"start": start, "end": end, "summary": event.get("summary", "")})

        # Generate available slots based on business hours
        # (simplified — production version would parse client hours config)
        slots = []
        open_hour = client.get("open_hour", 10)
        close_hour = client.get("close_hour", 19)
        slot_duration = 30  # minutes

        current = day_start.replace(hour=open_hour, minute=0)
        while current.hour < close_hour:
            slot_end = current + timedelta(minutes=slot_duration)
            # Check if slot overlaps any booked event
            is_free = True
            for booked in booked_times:
                b_start = datetime.fromisoformat(booked["start"].replace("Z", "+00:00")).replace(tzinfo=None)
                b_end = datetime.fromisoformat(booked["end"].replace("Z", "+00:00")).replace(tzinfo=None)
                if current < b_end and slot_end > b_start:
                    is_free = False
                    break
            if is_free:
                slots.append(current.strftime("%-I:%M %p"))
            current = slot_end

        return jsonify({"date": date_str, "available_slots": slots})

    except Exception as e:
        app.logger.error(f"Calendar error: {e}")
        return jsonify({"error": "Could not check availability"}), 500


@app.route("/api/book", methods=["POST"])
@require_client
def book_appointment(client):
    """Create a Google Calendar event for a confirmed booking."""
    if not GCAL_ENABLED or not client.get("calendar_id"):
        return jsonify({"mode": "demo", "message": "Booking simulated (calendar not connected)"}), 200

    data = request.get_json()
    required = ["customer_name", "phone", "service", "datetime"]
    missing = [f for f in required if f not in data]
    if missing:
        return jsonify({"error": f"Missing fields: {', '.join(missing)}"}), 400

    try:
        # Parse appointment time
        appt_time = datetime.fromisoformat(data["datetime"])
        # Find service duration
        duration = 30
        for s in client.get("services", []):
            if s["name"].lower() == data["service"].lower():
                duration = s.get("duration", 30)
                break
        appt_end = appt_time + timedelta(minutes=duration)

        event = {
            "summary": f"{data['service']} — {data['customer_name']}",
            "description": (
                f"Service: {data['service']}\n"
                f"Customer: {data['customer_name']}\n"
                f"Phone: {data['phone']}\n"
                f"Barber: {data.get('staff', 'Any')}\n"
                f"Booked via: NovaShift Talking Website"
            ),
            "start": {"dateTime": appt_time.isoformat(), "timeZone": client.get("timezone", "America/Chicago")},
            "end": {"dateTime": appt_end.isoformat(), "timeZone": client.get("timezone", "America/Chicago")},
        }

        created = calendar_service.events().insert(
            calendarId=client["calendar_id"],
            body=event
        ).execute()

        return jsonify({
            "success": True,
            "event_id": created.get("id"),
            "message": f"Booked {data['service']} for {data['customer_name']} at {appt_time.strftime('%-I:%M %p on %B %d')}"
        })

    except Exception as e:
        app.logger.error(f"Booking error: {e}")
        return jsonify({"error": "Could not create booking"}), 500


@app.route("/api/health", methods=["GET"])
def health():
    """Health check for Railway."""
    return jsonify({
        "status": "ok",
        "calendar": "enabled" if GCAL_ENABLED else "disabled",
        "timestamp": datetime.utcnow().isoformat()
    })


# ---------------------------------------------------------------------------
# Widget JS server (serves the embeddable script)
# ---------------------------------------------------------------------------

@app.route("/widget.js", methods=["GET"])
def serve_widget():
    """Serve the embeddable chat widget JavaScript."""
    with open("static/widget.js", "r") as f:
        js = f.read()
    return Response(js, mimetype="application/javascript")


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=os.environ.get("FLASK_DEBUG", "false").lower() == "true")
