# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A multi-tenant embeddable AI chat widget. A single Flask backend serves many clients; each client drops one `<script>` tag on their site. The widget answers visitor questions with the Claude API and, depending on the client, either simulates appointment booking or captures sales leads.

## Commands

```bash
# Install. requirements.txt pulls in blinker, which is already installed by
# Debian on some systems and pip cannot uninstall it — use the flag if it errors.
pip install --ignore-installed blinker -r requirements.txt

# Run locally (serves on http://localhost:5000). Must be run from the repo root:
# app.py opens clients/<id>.json and static/widget.js by relative path.
export ANTHROPIC_API_KEY=sk-ant-...
export FLASK_DEBUG=true
python app.py

# Production start (Railway uses this via Procfile)
gunicorn app:app --bind 0.0.0.0:$PORT --workers 2 --timeout 120

# Syntax gate before committing widget changes
node --check static/widget.js
```

There is **no test framework, linter, or CI** in this repo. Verify backend changes with an ad-hoc script that imports `app`, stubs the Claude call, and drives `app.test_client()`. Run it from the repo root:

```python
import os; os.environ.setdefault("ANTHROPIC_API_KEY", "test")
import app as a
from types import SimpleNamespace

a.claude.messages.create = lambda **kw: SimpleNamespace(
    stop_reason="end_turn",
    content=[SimpleNamespace(type="text", text="hi")],
    usage=SimpleNamespace(input_tokens=1, output_tokens=1),
)
c = a.app.test_client()
print(c.get("/api/config", headers={"X-Client-ID": "novashift"}).json)
print(c.post("/api/chat", json={"messages": [{"role": "user", "content": "hello"}], "session_id": "s1"},
             headers={"X-Client-ID": "novashift"}).json)
```

To exercise the tool-use loop, return `stop_reason="tool_use"` with a `tool_use` block named `submit_lead` on the first call, and stub `requests.post`. Verify widget changes by opening `test-page.html` in a browser against a local server (it is hardcoded to `http://localhost:5000` and client `haircutzforbreakupz`).

## Environment variables

- `ANTHROPIC_API_KEY` — required for `/api/chat`.
- `ANTHROPIC_MODEL` — defaults to `claude-sonnet-4-20250514`.
- `WIDGET_IMPORT_SECRET` — required **only** for lead-capture clients; sent as the `X-Widget-Secret` header when POSTing leads. If unset, lead submission bails and logs (the visitor is still told someone will be in touch). The env var name is configurable per client via `lead_capture.secret_env`.
- `GOOGLE_SERVICE_ACCOUNT_PATH` — path to the service-account JSON for `calendar_type: "google"`; defaults to `service-account.json` in the repo root (gitignored). One service account serves every Google client in the process.
- `PORT`, `FLASK_DEBUG`.

Set these on the Railway service, not just locally — the repo is cloned into an ephemeral build container that does **not** carry the runtime env.

## Architecture

**Request tenancy.** Every `/api/*` request carries an `X-Client-ID` header (default `demo`). `require_client` (`app.py`) loads `clients/<id>.json` via `load_client()` and injects it as `client=`. Clients are **flat JSON files in `clients/`** — there is no database. Adding a client = adding a JSON file (Railway auto-deploys on push). Files prefixed `_example-*` are templates, not live clients. The `client_id` field *inside* the JSON must match the filename: it is the key for `_calendar_cache`, so two files sharing a `client_id` would share one adapter instance.

**Two prompt modes** (`build_system_prompt` in `app.py`):
- Default: booking-assistant prompt built from `services`/`staff`/`hours`/`calendar_type`. `clients/haircutzforbreakupz.json` is the reference.
- `"mode": "sales"` → `build_sales_system_prompt`, a knowledge-base prompt built from `one_liner`/`what_we_do`/`tone`/`audience`/`pricing_tiers`/`faq`/`constraints`/`lead_capture`. `clients/novashift.json` is the reference; `clients/harper.json` is a second sales client with lead capture disabled. `what_we_do` defaults to NovaShift's line if omitted, so set it on every new sales client.

**Calendar adapters** (`calendars/`). `base.py` defines the `CalendarAdapter` ABC (`check_availability`, `create_booking`, `cancel_booking`) plus `TimeSlot`/`BookingResult` dataclasses. `__init__.py` is a factory: the `ADAPTERS` registry maps `calendar_type` → adapter class, falling back to `DemoAdapter` on unknown type or init failure. Add a provider by implementing the ABC and registering it. Each adapter reads its own credential keys straight off the client config (`calendar_id`, `calendly_token`, `outlook_*`, etc. — see `clients/_example-*.json`). `DemoAdapter` generates slots from `open_hour`/`close_hour`/`sat_open`/`sat_close`/`slot_duration`/`closed_days` and keeps bookings in process memory.

**Lead capture** (sales clients only). When a client config has `lead_capture.enabled`, `/api/chat` passes a `submit_lead` tool (Anthropic tool-use) to the model and runs a **tool-use loop** (up to 3 round-trips): the model answers, then calls `submit_lead`, the backend calls `post_lead_to_novashift()` which POSTs to `lead_capture.endpoint` with the `X-Widget-Secret` header, then the model emits the confirmation. Booking clients get no tools and a single-shot completion. `post_lead_to_novashift` validates the payload, omits empty optional fields, retries **once** on 5xx/network only (400/401 are non-retryable), and **never surfaces failure to the visitor** — failures are logged for manual pickup.

The lead pipeline is NovaShift-specific in places: `_TIER_IDS` and `_PRACTICE_TYPES` in `app.py` are the enums the NovaShift main app's lead endpoint accepts, and the `submit_lead` tool schema is built from them (the tool-result text uses the client's `lead_capture.confirm_message`). If `pricing_tiers` in `novashift.json` changes, or a second lead-capture client is added, those constants need to change with it.

**The widget** (`static/widget.js`, served verbatim from `GET /widget.js`). Self-contained IIFE injected via one script tag; reads `data-client`/`data-accent`/`data-position`/`data-delay`; derives `API_BASE` from its own `src`. It only calls `/api/config` (on load) and `/api/chat` (per message) — **booking is entirely simulated in the conversation; the widget never calls `/api/book` or `/api/availability`.** Those routes (plus `/api/cancel` and `/api/health`) exist and work against the adapters, but only via direct HTTP; the README's architecture diagram describing the widget as reading/writing Google Calendar is aspirational. The widget generates a per-page-load `session_id` UUID sent with each chat request (used to dedupe/correlate leads). Accent color comes **only** from the `data-accent` script attribute; `accent_color` in the client JSON is returned by `/api/config` but the widget does not apply it. `input_placeholder` from the config is applied.

**Demo pages** (`demos/<client_id>.html`, served at `GET /demo/<client_id>`). Full mock landing pages with the widget embedded via a relative `/widget.js` src, for showing the product off on the Railway domain. `demos/harper.html` is the reference; `test-page.html` at the repo root is the older local-only equivalent for `haircutzforbreakupz`.

## Widget gotchas

- `/widget.js` is served with `Cache-Control: no-cache` so client sites pick up changes without editing their snippet. `WIDGET_VERSION` logs to the browser console on load — bump it on every `widget.js` change and use it to confirm which build a site actually loaded (vs. a stale cache) before debugging behavior.
- The widget embeds on arbitrary host pages (e.g. a React/Vite SPA), so its layout-critical CSS uses `!important` to resist the host page's global stylesheet. The scrollable message list depends on `#ns-chat-messages { min-height: 0 }` **and** `.ns-msg { flex: 0 0 auto }` — without the latter, flex rows get squished instead of overflowing and nothing scrolls.

## Deploy

Backend runs on Railway (`Procfile` → gunicorn). Client marketing sites live on Netlify/Cloudflare and only embed the widget script. Push to the deploy branch → Railway rebuilds; the widget file is read from disk per request, so a redeploy is enough (no server-side cache to bust — only browser/CDN caches, handled by the no-cache header).
