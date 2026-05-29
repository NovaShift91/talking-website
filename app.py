"""
NovaShift Talking Website — Backend API
Multi-calendar support: Google, Calendly, Outlook, or demo mode.
"""

import os
import re
import json
import logging
from datetime import datetime
from functools import wraps

import requests
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
    # Sales/knowledge-base clients (e.g. novashift) use a different prompt
    # shape than the booking-assistant template below.
    if client.get("mode") == "sales":
        return build_sales_system_prompt(client)

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


def build_sales_system_prompt(client):
    """Knowledge-base-driven prompt for sales clients like novashift."""
    audience_block = "\n".join(f"- {a}" for a in client.get("audience", []))

    tiers_block = ""
    for t in client.get("pricing_tiers", []):
        features = "\n".join(f"    - {f}" for f in t.get("features", []))
        tiers_block += (
            f"\n{t['name']} (id: {t['id']})\n"
            f"  - Monthly: {t.get('monthly', 'N/A')}\n"
            f"  - Setup option: {t.get('setup_option', 'N/A')}\n"
            f"  - Includes:\n{features}\n"
        )

    faq_block = "\n".join(
        f"Q: {f['q']}\nA: {f['a']}" for f in client.get("faq", [])
    )

    constraints_block = "\n".join(f"- {c}" for c in client.get("constraints", []))

    lc = client.get("lead_capture", {})
    intent_block = "\n".join(f"- {s}" for s in lc.get("intent_signals", []))
    lead_section = ""
    if lc.get("enabled"):
        lead_section = f"""

LEAD CAPTURE:
Answer the visitor's actual question FIRST (give the relevant tier, pricing, or info).
Do NOT pre-emptively ask for an email. Only after you've answered, if the visitor
shows lead intent, offer to capture their email.

Lead intent signals:
{intent_block}

When you see lead intent, after answering, offer exactly this:
"{lc.get('offer_message', '')}"

If the visitor says yes, collect: name, email, and practice type. Phone is a bonus —
don't push for it. Once you have at least a name and a valid email, call the
`submit_lead` tool with everything you've gathered (including a short
conversation_summary, any pain_points they mentioned, and interested_tier if they
asked about a specific tier).

After the tool runs, confirm to the visitor with exactly:
"{lc.get('confirm_message', '')}"
Then wrap up — do NOT keep selling. If they have follow-up questions, answer them,
but do not re-ask for their email or push for a booking. Never tell the visitor that
anything failed — always confirm someone will be in touch."""

    return f"""You are the chat assistant on the website of {client['business_name']}.
{client.get('one_liner', '')}

WHO YOU ARE TALKING TO / WHAT WE DO:
{client['business_name']} builds customer acquisition systems for solo professionals.
We typically work with:
{audience_block}

GEOGRAPHY:
{client.get('geography', '')}

TONE (follow this exactly):
{client.get('tone', '')}

PRICING TIERS (quote these accurately when asked):
{tiers_block}
NOTE: {client.get('pricing_note', '')}

FAQ (answer these confidently):
{faq_block}

HARD CONSTRAINTS — never break these:
{constraints_block}
{lead_section}

Keep responses short — a few sentences. Speak as "we" (we build, we'll review).
Never say you are an AI."""


# ---------------------------------------------------------------------------
# Lead capture — POST qualified leads to the NovaShift main app
# ---------------------------------------------------------------------------
_TIER_IDS = {"starter", "professional", "pro-leads", "growth", "full-service"}
_PRACTICE_TYPES = {"therapy", "law", "financial", "chiropractic", "coaching", "medical", "other"}
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def build_lead_tool():
    """Anthropic tool definition for submitting a qualified lead."""
    return {
        "name": "submit_lead",
        "description": (
            "Submit a qualified lead to NovaShift. Call this ONLY after the visitor "
            "has agreed to be contacted and you have collected at least their name and "
            "a valid email. Include as much context as you have."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "contact_name": {"type": "string", "description": "Visitor's name (required)."},
                "contact_email": {"type": "string", "description": "Valid email address (required)."},
                "contact_phone": {"type": "string", "description": "Phone number (optional, do not push for it)."},
                "practice_type": {
                    "type": "string",
                    "enum": sorted(_PRACTICE_TYPES),
                    "description": "Type of practice, if known.",
                },
                "conversation_summary": {
                    "type": "string",
                    "description": "Short summary of what the visitor asked about, their situation, urgency (<= 4000 chars).",
                },
                "pain_points": {
                    "type": "string",
                    "description": "What they explicitly said they're struggling with, if anything.",
                },
                "interested_tier": {
                    "type": "string",
                    "enum": sorted(_TIER_IDS),
                    "description": "A specific tier they asked about. Omit if they didn't ask about one.",
                },
            },
            "required": ["contact_name", "contact_email"],
        },
    }


def post_lead_to_novashift(client, session_id, lead_input):
    """
    POST a qualified lead to NovaShift's main app.

    Returns True on success (200/201), False otherwise. Never raises — the
    caller always confirms to the visitor regardless, and Carlos picks up
    failures from chat logs.
    """
    lc = client.get("lead_capture", {})
    endpoint = lc.get("endpoint")
    secret = os.environ.get(lc.get("secret_env", "WIDGET_IMPORT_SECRET"), "")

    if not endpoint:
        app.logger.error("Lead capture: no endpoint configured for client")
        return False
    if not secret:
        app.logger.error("Lead capture: WIDGET_IMPORT_SECRET env var is not set")
        # Still attempt — endpoint will 401 and we log it — but bail early to avoid noise.
        return False

    # Build payload — required fields plus any optional fields that are present.
    session_id = (session_id or "")[:255]
    if not session_id:
        app.logger.error("Lead capture: missing session_id, cannot submit lead")
        return False

    name = (lead_input.get("contact_name") or "").strip()
    email = (lead_input.get("contact_email") or "").strip()
    if not name or not _EMAIL_RE.match(email):
        app.logger.error("Lead capture: invalid name/email, not submitting")
        return False

    payload = {
        "session_id": session_id,
        "contact_name": name,
        "contact_email": email,
    }
    if lead_input.get("contact_phone"):
        payload["contact_phone"] = str(lead_input["contact_phone"]).strip()
    pt = lead_input.get("practice_type")
    if pt in _PRACTICE_TYPES:
        payload["practice_type"] = pt
    if lead_input.get("conversation_summary"):
        payload["conversation_summary"] = str(lead_input["conversation_summary"])[:4000]
    if lead_input.get("pain_points"):
        payload["pain_points"] = str(lead_input["pain_points"])
    tier = lead_input.get("interested_tier")
    if tier in _TIER_IDS:
        payload["interested_tier"] = tier

    headers = {
        "X-Widget-Secret": secret,
        "Content-Type": "application/json",
    }

    # One retry, only for transient (5xx / network) failures.
    for attempt in range(2):
        try:
            resp = requests.post(endpoint, json=payload, headers=headers, timeout=10)
        except requests.RequestException as e:
            app.logger.error(f"Lead capture: network error on attempt {attempt + 1}: {e}")
            continue  # retry

        if resp.status_code in (200, 201):
            app.logger.info(f"Lead capture: submitted lead for session {session_id}")
            return True
        if resp.status_code == 400:
            app.logger.error(f"Lead capture: 400 validation error (payload wrong): {resp.text[:500]}")
            return False  # our payload is wrong — retrying won't help
        if resp.status_code == 401:
            app.logger.error("Lead capture: 401 unauthorized — WIDGET_IMPORT_SECRET mismatch")
            return False  # secret won't change on retry
        if resp.status_code >= 500:
            app.logger.error(f"Lead capture: {resp.status_code} server error on attempt {attempt + 1}")
            continue  # retry once
        app.logger.error(f"Lead capture: unexpected status {resp.status_code}: {resp.text[:500]}")
        return False

    return False


# ---------------------------------------------------------------------------
# API Routes
# ---------------------------------------------------------------------------

@app.route("/api/chat", methods=["POST"])
@require_client
def chat(client):
    data = request.get_json()
    messages = data.get("messages", [])
    session_id = data.get("session_id")

    if not messages:
        return jsonify({"error": "No messages provided"}), 400

    system_prompt = build_system_prompt(client)
    model = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-20250514")

    # Lead-capture clients get the submit_lead tool. Others run plain chat.
    lead_capture_on = client.get("lead_capture", {}).get("enabled", False)
    tools = [build_lead_tool()] if lead_capture_on else None

    # Work on a copy so we can append tool-use turns without mutating input.
    convo = list(messages)
    total_in, total_out = 0, 0

    try:
        # Allow a couple of round-trips so a tool call can be followed by the
        # assistant's final confirmation message.
        for _ in range(3):
            kwargs = {
                "model": model,
                "max_tokens": 600,
                "system": system_prompt,
                "messages": convo,
            }
            if tools:
                kwargs["tools"] = tools

            response = claude.messages.create(**kwargs)
            total_in += response.usage.input_tokens
            total_out += response.usage.output_tokens

            if response.stop_reason != "tool_use":
                reply = "".join(b.text for b in response.content if b.type == "text")
                return jsonify({
                    "reply": reply,
                    "usage": {"input_tokens": total_in, "output_tokens": total_out},
                })

            # Execute any tool calls, then feed results back for a final reply.
            convo.append({"role": "assistant", "content": response.content})
            tool_results = []
            for block in response.content:
                if block.type != "tool_use":
                    continue
                if block.name == "submit_lead":
                    # Fire-and-confirm: succeed or fail, the visitor is told
                    # someone will be in touch. Failures are logged for Carlos.
                    post_lead_to_novashift(client, session_id, block.input or {})
                    result_text = (
                        "Lead recorded. Confirm to the visitor that Carlos or Annie "
                        "will reach out within 24 hours, then wrap up — do not keep selling."
                    )
                else:
                    result_text = "Unknown tool."
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": result_text,
                })
            convo.append({"role": "user", "content": tool_results})

        # Fell through the loop without a final text turn — graceful fallback.
        return jsonify({
            "reply": client.get("lead_capture", {}).get(
                "confirm_message", "Thanks — someone will be in touch shortly."
            ),
            "usage": {"input_tokens": total_in, "output_tokens": total_out},
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
    resp = Response(js, mimetype="application/javascript")
    # Always revalidate so widget updates reach client sites without anyone
    # having to edit (or cache-bust) the embed snippet.
    resp.headers["Cache-Control"] = "no-cache, must-revalidate"
    return resp


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=os.environ.get("FLASK_DEBUG", "false").lower() == "true")
