# NovaShift Talking Website

AI-powered chat widget that reads a client's site info, answers customer questions, and books appointments directly to Google Calendar — no forms needed.

**One script tag. That's it.**

```html
<script src="https://your-app.up.railway.app/widget.js" data-client="haircutzforbreakupz"></script>
```

---

## Architecture

```
┌─────────────────────────────────────────────────┐
│  Client's Website (any HTML site)               │
│  └── <script src=".../widget.js" data-client>   │
│       └── Chat bubble → Chat window             │
└────────────────┬────────────────────────────────┘
                 │ POST /api/chat
                 │ X-Client-ID header
                 ▼
┌─────────────────────────────────────────────────┐
│  Flask Backend (Railway)                        │
│  ├── /api/chat    → Anthropic Claude API        │
│  ├── /api/config  → Client config (JSON)        │
│  ├── /api/availability → Google Calendar read   │
│  ├── /api/book    → Google Calendar write       │
│  └── /widget.js   → Serves embeddable script    │
└─────────────────────────────────────────────────┘
                 │
    ┌────────────┼────────────┐
    ▼            ▼            ▼
 Anthropic    Google       Client
  Claude     Calendar     Configs
   API        API        (JSON files)
```

---

## Project Structure

```
talking-website/
├── app.py                    # Flask backend
├── Procfile                  # Railway/gunicorn startup
├── requirements.txt          # Python dependencies
├── .env.example              # Environment variable template
├── clients/                  # Client configurations
│   ├── demo.json
│   └── haircutzforbreakupz.json
├── static/
│   └── widget.js             # Embeddable chat widget
├── test-page.html            # Local test page
└── service-account.json      # Google Calendar (optional, not committed)
```

---

## Local Development

### 1. Clone & install

```bash
git clone <your-repo>
cd talking-website
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Set environment variables

```bash
export ANTHROPIC_API_KEY=sk-ant-api03-xxxxxxxxxxxx
export FLASK_DEBUG=true
```

### 3. Run the server

```bash
python app.py
```

Server starts at `http://localhost:5000`.

### 4. Test the widget

Open `test-page.html` in your browser. The chat widget will appear and connect to your local Flask server.

---

## Deploy to Railway

NovaShift already runs a Railway Pro plan ($20/month with $20 usage credit).
This backend is lightweight (~$2–3/month resource usage) and fits within
the existing plan with no additional platform costs.

### 1. Push to GitHub

```bash
git init
git add .
git commit -m "initial: talking website backend"
git remote add origin https://github.com/YOUR_USER/talking-website.git
git push -u origin main
```

### 2. Add a new service to your existing Railway project

1. Open your Railway dashboard → select your existing project (or create a new project within your Pro workspace)
2. Click **+ New** → **GitHub Repo**
3. Select your `talking-website` repo
4. Railway auto-detects Python + Procfile — no build config needed

### 3. Set environment variables

Click into the new service → **Variables** tab → **+ New Variable**:

```
ANTHROPIC_API_KEY = sk-ant-api03-xxxxxxxxxxxx
ANTHROPIC_MODEL   = claude-sonnet-4-20250514
```

### 4. Add a domain

Service → **Settings** → **Networking** → **Generate Domain**

You'll get something like: `talking-website-production.up.railway.app`

Optional: Add a custom subdomain like `chat.novashiftautomations.com` via
Namecheap DNS (CNAME → your Railway domain).

### 5. Update client sites

Replace `localhost:5000` with your Railway URL in script tags:

```html
<script
  src="https://talking-website-production.up.railway.app/widget.js"
  data-client="haircutzforbreakupz"
></script>
```

---

## Adding a New Client

1. Create `clients/new-client-id.json` (copy from an existing config)
2. Fill in: business name, services, hours, staff, personality, accent color
3. Commit and push — Railway auto-deploys
4. Give the client their embed code:

```html
<script
  src="https://your-app.up.railway.app/widget.js"
  data-client="new-client-id"
></script>
```

### Widget Data Attributes

| Attribute        | Default          | Description                      |
|------------------|------------------|----------------------------------|
| `data-client`    | `demo`           | Client config ID                 |
| `data-accent`    | `#c8a84e`        | Override accent color            |
| `data-position`  | `bottom-right`   | `bottom-right` or `bottom-left`  |
| `data-delay`     | `5000`           | Auto-open delay (ms), 0=disable  |

---

## Google Calendar Integration (Optional)

The widget works in demo mode without Calendar. To enable real booking:

### 1. Create a Google Cloud project

- Go to [console.cloud.google.com](https://console.cloud.google.com)
- Create a project: "NovaShift Talking Website"
- Enable the **Google Calendar API**

### 2. Create a service account

- IAM & Admin → Service Accounts → Create
- Name: `talking-website`
- Download the JSON key → save as `service-account.json` in project root

### 3. Share the client's calendar

The client shares their Google Calendar with the service account email
(something like `talking-website@your-project.iam.gserviceaccount.com`)
with **"Make changes to events"** permission.

### 4. Add calendar ID to client config

In `clients/haircutzforbreakupz.json`:
```json
{
  "calendar_id": "client-calendar-id@group.calendar.google.com"
}
```

### 5. Upload service account to Railway

Railway → service → Variables:
- Upload `service-account.json` as a file, OR
- Base64-encode it and decode on startup (see app.py comments)

---

## Costs

NovaShift is already on Railway Pro ($20/month). This service adds minimal
resource usage within the existing plan.

| Component                | Monthly Cost                              |
|--------------------------|-------------------------------------------|
| Railway hosting          | ~$2–3 in resource usage (covered by Pro)  |
| Anthropic API            | ~$2–10/month*                             |
| Google Calendar          | Free                                      |
| **Net new cost**         | **~$2–10/month (Anthropic API only)**     |

*API costs depend on chat volume. Average barbershop might see 50–100 chat
sessions/month. At ~500 tokens per exchange, that's roughly $2–5/month on Sonnet.

### Client Pricing Suggestion

| Tier       | Monthly | What's Included                          |
|------------|---------|------------------------------------------|
| Basic      | $75/mo  | Chat widget + simulated booking          |
| Standard   | $125/mo | Chat widget + Google Calendar booking    |
| Premium    | $175/mo | Chat + Calendar + SMS confirmations      |

At $75/mo minimum per client, the first client covers all infrastructure costs.
Every client after that is nearly pure margin.

---

## NovaShift Workstream

This maps to a new workstream template: **1C — AI Booking Assistant**

**Stack:** Railway (existing Pro plan) + Anthropic API + Google Calendar API
Client sites remain on Netlify/Cloudflare — they just embed the widget script tag.

Deliverables:
1. Chat widget deployed and styled to client site
2. Client config JSON (services, hours, personality)
3. Google Calendar OAuth setup (Cowork prompt)
4. Welcome message + personality tuning
5. Fallback behavior config (phone/text handoff)

Cross-sell with: 4B (Missed Call Text-Back), 2A (Post-Job Follow-Up), 2B (Review Campaign)
