# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A multi-tenant embeddable AI chat widget. A single Flask backend serves many clients; each client drops one `<script>` tag on their site. The widget answers visitor questions with the Claude API and, depending on the client, either simulates appointment booking or captures sales leads.

## Commands

```bash
# Install (note: requirements.txt lists an already-present blinker on some systems;
# use --ignore-installed blinker if pip errors on uninstalling it)
pip install -r requirements.txt

# Run locally (serves on http://localhost:5000)
export ANTHROPIC_API_KEY=sk-ant-...
export FLASK_DEBUG=true
python app.py

# Production start (Railway uses this via Procfile)
gunicorn app:app --bind 0.0.0.0:$PORT --workers 2 --timeout 120
```

There is **no test framework, linter, or CI** in this repo. Verification is done with ad-hoc Python scripts (import `app`, stub `requests.post`, use `app.test_client()`) and by loading `test-page.html` in a browser against a local server. `node --check static/widget.js` is a useful syntax gate before committing widget changes.

## Environment variables

- `ANTHROPIC_API_KEY` — required for `/api/chat`.
- `ANTHROPIC_MODEL` — defaults to `claude-sonnet-4-20250514`.
- `WIDGET_IMPORT_SECRET` — required **only** for lead-capture clients; sent as the `X-Widget-Secret` header when POSTing leads. If unset, lead submission bails and logs (the visitor is still told someone will be in touch).
- `PORT`, `FLASK_DEBUG`.

Set these on the Railway service, not just locally — the repo is cloned into an ephemeral build container that does **not** carry the runtime env.

## Architecture

**Request tenancy.** Every `/api/*` request carries an `X-Client-ID` header (default `demo`). `require_client` (`app.py`) loads `clients/<id>.json` via `load_client()` and injects it as `client=`. Clients are **flat JSON files in `clients/`** — there is no database. Adding a client = adding a JSON file (Railway auto-deploys on push). Files prefixed `_example-*` are templates, not live clients.

**Two prompt modes** (`build_system_prompt` in `app.py`):
- Default: booking-assistant prompt built from `services`/`staff`/`hours`/`calendar_type`.
- `"mode": "sales"` → `build_sales_system_prompt`, a knowledge-base prompt built from `one_liner`/`tone`/`audience`/`pricing_tiers`/`faq`/`constraints`/`lead_capture`. `clients/novashift.json` is the reference.

**Calendar adapters** (`calendars/`). `base.py` defines the `CalendarAdapter` ABC (`check_availability`, `create_booking`, `cancel_booking`) plus `TimeSlot`/`BookingResult` dataclasses. `__init__.py` is a factory: the `ADAPTERS` registry maps `calendar_type` → adapter class, falling back to `DemoAdapter` on unknown type or init failure. Add a provider by implementing the ABC and registering it. Adapters are cached per client in `_calendar_cache`.

**Lead capture** (sales clients only). When a client config has `lead_capture.enabled`, `/api/chat` passes a `submit_lead` tool (Anthropic tool-use) to the model and runs a **tool-use loop** (up to 3 round-trips): the model answers, then calls `submit_lead`, the backend calls `post_lead_to_novashift()` which POSTs to `lead_capture.endpoint` with the `X-Widget-Secret` header, then the model emits the confirmation. Booking clients get no tools and a single-shot completion. `post_lead_to_novashift` validates the payload, omits empty optional fields, retries **once** on 5xx/network only (400/401 are non-retryable), and **never surfaces failure to the visitor** — failures are logged for manual pickup.

**The widget** (`static/widget.js`, served verbatim from `GET /widget.js`). Self-contained IIFE injected via one script tag; reads `data-client`/`data-accent`/`data-position`/`data-delay`; derives `API_BASE` from its own `src`. It only calls `/api/config` (on load) and `/api/chat` (per message) — **booking is entirely simulated in the conversation; the widget never calls `/api/book` or `/api/availability`.** It generates a per-page-load `session_id` UUID sent with each chat request (used to dedupe/correlate leads).

## Widget gotchas

- `/widget.js` is served with `Cache-Control: no-cache` so client sites pick up changes without editing their snippet. `WIDGET_VERSION` logs to the browser console on load — bump it on every `widget.js` change and use it to confirm which build a site actually loaded (vs. a stale cache) before debugging behavior.
- The widget embeds on arbitrary host pages (e.g. a React/Vite SPA), so its layout-critical CSS uses `!important` to resist the host page's global stylesheet. The scrollable message list depends on `#ns-chat-messages { min-height: 0 }` **and** `.ns-msg { flex: 0 0 auto }` — without the latter, flex rows get squished instead of overflowing and nothing scrolls.

## Deploy

Backend runs on Railway (`Procfile` → gunicorn). Client marketing sites live on Netlify/Cloudflare and only embed the widget script. Push to the deploy branch → Railway rebuilds; the widget file is read from disk per request, so a redeploy is enough (no server-side cache to bust — only browser/CDN caches, handled by the no-cache header).
