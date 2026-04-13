"""
NovaShift Talking Website — Backend API
Multi-calendar support: Google, Calendly, Outlook, or demo mode.
"""

import os
import json
import logging
from datetime import datetime
from functools import wraps

from flask import Flask, request, jsonify, Response
from flask_cors import CORS
import anthropic

from calendars import get_calendar

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------
app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

CORS(app, resources={r"/api/*": {"origins": "*"}})

claude = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY", ""))

# Cache calendar adapters per client (so demo mode tracks bookings in memory)
_calendar_cache = {}


# ---------------------------------------------------------------------------
# Client config loader
# ---------------------------------------------------------------------------
def load_client(client_id):
    path = os.path.join("clients", f"{client_id}.json")
    if not os.path.exists(path):
        return None
    with open(path, "r") as f:
        return json.load(f)


def get_client_calendar(client):
    """Get or create the calendar adapter for a client."""
    client_id = client.get("client_id", "demo")
    if client_id not in _calendar_cache:
        _calendar_cache[client_id] = get_calendar(client)
    return _calendar_cache[client_id]


def require_client(fn):
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
    services_block = "\n".join(
        f"- {s['name']}: ${s['price']} ({s['duration']} min)"
        for s in client.get("services", [])
    )

    staff_block = "\n".join(
        f"- {s['name']} — {s.get('specialty', 'all services')}"
        for s in client.get("staff", [])
    )

    hours_block = "\n".join(f"- {h}" for h in client.get("hours", []))

    cal_type = client.get("calendar_type", "demo")
    if cal_type == "demo":
        calendar_note = "Calendar is in DEMO MODE — use simulated availability when customers ask to book."
    else:
        calendar_note = (
            f"Calendar is connected via {cal_type.title()}. "
            "When the customer is ready to book, confirm their details and "
            "tell them you're locking it in. The system handles the rest."
        )

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

{calendar_note}

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
    cal = get_client_calendar(client)
    return jsonify({
        "business_name": client["business_name"],
        "greeting": client.get("greeting", "Hey there! How can I help you today?"),
        "accent_color": client.get("accent_color", "#c8a84e"),
        "position": client.get("widget_position", "bottom-right"),
        "calendar_provider": cal.provider_name,
    })


@app.route("/api/availability", methods=["POST"])
@require_client
def check_availability(client):
    data = request.get_json()
    date_str = data.get("date")

    if not date_str:
        return jsonify({"error": "Date required (YYYY-MM-DD)"}), 400

    cal = get_client_calendar(client)
    slots = cal.check_availability(date_str)

    return jsonify({
        "date": date_str,
        "provider": cal.provider_name,
        "available_slots": [
            {"start": s.start, "end": s.end, "display": s.display}
            for s in slots
        ]
    })


@app.route("/api/book", methods=["POST"])
@require_client
def book_appointment(client):
    data = request.get_json()
    required = ["customer_name", "phone", "service", "start_time"]
    missing = [f for f in required if f not in data]
    if missing:
        return jsonify({"error": f"Missing fields: {', '.join(missing)}"}), 400

    cal = get_client_calendar(client)
    result = cal.create_booking(
        service=data["service"],
        start_time=data["start_time"],
        customer_name=data["customer_name"],
        phone=data["phone"],
        staff=data.get("staff", "Any"),
        notes=data.get("notes", "")
    )

    status = 200 if result.success else 500
    return jsonify({
        "success": result.success,
        "event_id": result.event_id,
        "message": result.message,
        "provider": cal.provider_name,
        "details": result.details
    }), status


@app.route("/api/cancel", methods=["POST"])
@require_client
def cancel_appointment(client):
    data = request.get_json()
    event_id = data.get("event_id")
    if not event_id:
        return jsonify({"error": "event_id required"}), 400

    cal = get_client_calendar(client)
    result = cal.cancel_booking(event_id)

    status = 200 if result.success else 500
    return jsonify({
        "success": result.success,
        "message": result.message,
        "provider": cal.provider_name,
    }), status


@app.route("/api/health", methods=["GET"])
def health():
    return jsonify({
        "status": "ok",
        "providers": ["demo", "google", "calendly", "outlook"],
        "timestamp": datetime.utcnow().isoformat()
    })


# ---------------------------------------------------------------------------
# Widget JS server
# ---------------------------------------------------------------------------

@app.route("/widget.js", methods=["GET"])
def serve_widget():
    with open("static/widget.js", "r") as f:
        js = f.read()
    return Response(js, mimetype="application/javascript")


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=os.environ.get("FLASK_DEBUG", "false").lower() == "true")
