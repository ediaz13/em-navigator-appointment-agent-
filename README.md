# em-navigator-appointment-agent

AI-driven medical appointment agent for automating unstructured patient requests and scheduling logistics in a hospital's Demyelinating Diseases (Multiple Sclerosis) department.

## Architecture

**"Thin Connectors, Fat Core"** — the intelligence core knows nothing about channels. Connectors convert channel-specific formats into a universal `IncomingMessage`, and send `DraftedReply` back out.

```
src/
├── core/
│   ├── message.py           # IncomingMessage, DraftedReply (the contract)
│   └── intelligence.py      # Extract → Decide → Draft (the brain)
├── connectors/
│   └── gmail_connector.py   # Gmail API → IncomingMessage
└── main.py                  # Orchestrator: connector → core → review → connector
```

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for full details.

## Setup

### 1. Create a virtual environment

```bash
python -m venv venv
# Windows
venv\Scripts\activate
# macOS/Linux
source venv/bin/activate
```

### 2. Install dependencies

```bash
pip install anthropic python-dotenv
# Only needed for Gmail mode:
pip install google-auth-oauthlib google-api-python-client
```

### 3. Configure your API key

Create the config directory and `.env` file:

```bash
mkdir config
```

Add your Anthropic API key to `config/.env`:

```
ANTHROPIC_API_KEY=your-key-here
```

## Testing

### Demo mode (quickest way to try it)

No Gmail credentials needed — runs 3 realistic sample patient emails through the full pipeline:

```bash
python -m src.main --demo
```

This will:
- Extract patient data (name, DNI, doctor, date preferences) using Claude
- Match against mock calendar availability
- Draft professional replies in Argentine Spanish
- Save results to `data/review_queue/` as JSON files for secretary review

### Gmail mode

Requires Gmail API OAuth2 credentials in `config/gmail_credentials.json` (see [Google's quickstart guide](https://developers.google.com/gmail/api/quickstart/python)).

```bash
# Process new emails once
python -m src.main

# Poll every 5 minutes
python -m src.main --watch

# Custom polling interval (seconds)
python -m src.main --watch --interval 120
```

## Review Queue

Drafted replies are saved as JSON files in `data/review_queue/` for the secretary to review before sending. Each file includes the original message, extracted data, proposed appointment, and the drafted reply.
