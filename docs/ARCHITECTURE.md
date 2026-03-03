# Architecture Decision Record: Channel-Agnostic Design

## Decision: "Thin Connectors, Fat Core" Pattern

### The Principle
The intelligence core (`src/core/`) never imports from `src/connectors/`.
Connectors convert channel-specific formats into `IncomingMessage` (inbound)
and send `DraftedReply` back out (outbound). That's their entire job.

```
src/
├── core/                    # ZERO channel knowledge
│   ├── message.py           # IncomingMessage, DraftedReply (the contract)
│   └── intelligence.py      # Extract → Decide → Draft (the brain)
│
├── connectors/              # ONE file per channel
│   ├── gmail_connector.py   # Gmail API → IncomingMessage
│   ├── whatsapp_connector.py   # (Phase 2)
│   └── web_portal_connector.py # (Phase 3)
│
└── main.py                  # Orchestrator: connector → core → review → connector
```

### Why Not Interfaces/ABCs Upfront?
Python's Protocol (structural typing) is used instead of ABC inheritance.
The `InboundConnector` and `OutboundConnector` protocols in `message.py`
define the shape — any class with `fetch_new_messages()` or `send_reply()`
satisfies it automatically. No registration, no base classes.

When you add WhatsApp, you just write `whatsapp_connector.py` with those
two methods. The orchestrator picks which connector to use based on
`Channel` enum. That's it.

### Adding a New Channel (Checklist)
1. Create `src/connectors/new_channel_connector.py`
2. Implement `fetch_new_messages() → list[IncomingMessage]`
3. Implement `send_reply(DraftedReply) → bool`
4. Add the channel to `Channel` enum in `message.py`
5. Register it in `main.py`'s orchestrator

Intelligence core: UNTOUCHED. Extraction prompts: UNTOUCHED. Calendar logic: UNTOUCHED.

---

## Deployment Recommendation

### MVP (Now): Railway or Render
| Option | Cost | Why |
|--------|------|-----|
| **Railway** | ~$5/month | Git push deploy, cron jobs built-in, simple env vars |
| Render | $7/month | Similar to Railway, slightly more mature |
| Fly.io | $0-5/month | More control, but more setup |
| AWS Lambda | $0 (free tier) | Overkill for MVP; cold starts hurt polling |

**Recommendation: Railway.** 

Why: You push to GitHub, it deploys. You add a cron job (`*/5 * * * *`)
that runs `python -m src.main` every 5 minutes. Total setup: ~20 minutes.
It handles SSL, logs, env vars, and restarts. $5/month.

### Why NOT Serverless (Lambda/Cloud Functions) for MVP
- Cold starts add 3-8 seconds to each invocation (bad for polling)
- Gmail OAuth token refresh requires persistent file storage (awkward in Lambda)
- You'd need API Gateway + Lambda + CloudWatch Events + S3 for token storage
- That's 4 services to configure vs. 1 Railway deploy

Serverless makes sense at scale (Phase 3+), not for a solo dev MVP.

### Phase 2: Add a Review Dashboard
When you need the secretary dashboard, add Streamlit to the same Railway service:

```
# In your Railway cron job:
python -m src.main          # Process new emails

# As a separate Railway service (or same one, different port):
streamlit run dashboard.py  # Secretary reviews at https://your-app.railway.app
```

### Phase 3: Multi-Channel
When WhatsApp arrives, the architecture doesn't change. You add a connector
and a second webhook endpoint. The core stays identical.

```
Railway Service
├── Cron: Poll Gmail every 5 min
├── Webhook: /whatsapp (receives WhatsApp messages)
├── Web: Streamlit dashboard (secretary review)
└── Core: Same intelligence pipeline for all channels
```

---

## Human-in-the-Loop Strategy

### MVP: File-Based Queue
- Drafted replies are saved as JSON in `data/review_queue/`
- Secretary reviews files manually (or via a simple Streamlit viewer)
- Approved replies are moved to `data/processed/`
- The orchestrator checks for approved files and sends them

### Phase 2: Streamlit Dashboard
- Real-time table of pending reviews
- Click to approve/edit/reject
- Edited reply is saved and sent
- Simple auth (password in env var — it's one secretary)

### Phase 3: Notification
- Secretary gets a Slack/email notification when new drafts arrive
- Mobile-friendly dashboard for review on the go
