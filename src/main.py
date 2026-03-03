"""
Main Orchestrator — the glue between Connectors, Intelligence, and Outcome.

This is the script you run. It:
1. Polls Gmail for new messages
2. Runs each through the intelligence core
3. Saves drafted replies for human review
4. (Future) Sends approved replies

For MVP, the "review" step is a JSON file the secretary checks.
Phase 2 replaces this with a Streamlit dashboard.

Usage:
    python -m src.main                    # Process once
    python -m src.main --watch            # Poll every 5 minutes
    python -m src.main --demo             # Run with test emails (no Gmail needed)
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from src.core.intelligence import process_message
from src.core.message import Channel, DraftedReply, IncomingMessage

# ─────────────────────────────────────────────
# Review Queue (file-based for MVP)
# ─────────────────────────────────────────────
REVIEW_DIR = Path("data/review_queue")
PROCESSED_DIR = Path("data/processed")


def save_for_review(reply: DraftedReply, message: IncomingMessage) -> Path:
    """Save a drafted reply as a JSON file for the secretary to review."""
    REVIEW_DIR.mkdir(parents=True, exist_ok=True)

    filename = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{reply.request_id[:8]}.json"
    filepath = REVIEW_DIR / filename

    review_data = {
        "status": "pending_review",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "original_message": {
            "id": message.id,
            "channel": message.channel.value,
            "sender": message.sender_id,
            "sender_name": message.sender_name,
            "body": message.body,
            "received_at": message.received_at.isoformat(),
        },
        "extraction": reply.extracted_data,
        "proposed_appointment": reply.proposed_datetime,
        "confidence": reply.confidence,
        "drafted_reply": {
            "subject": reply.subject,
            "body": reply.body,
            "recipient": reply.recipient_id,
        },
        "secretary_notes": "",  # Secretary can add notes here
    }

    filepath.write_text(json.dumps(review_data, indent=2, ensure_ascii=False), encoding="utf-8")
    return filepath


# ─────────────────────────────────────────────
# Demo Mode: Test without Gmail
# ─────────────────────────────────────────────
DEMO_EMAILS = [
    IncomingMessage(
        id="demo-001",
        channel=Channel.EMAIL,
        sender_id="maria.lopez@gmail.com",
        sender_name="María Eugenia López",
        body="""Asunto: Solicitud de turno neurología

Buenas tardes, mi nombre es María Eugenia López, DNI 28.456.789.
Quisiera solicitar un turno con la Dra. Rosario Ansede del servicio de 
Enfermedades Desmielinizantes. Si es posible, preferiría un día martes 
después del 20 de marzo. Mi teléfono es 11-3456-7890.
Muchas gracias.""",
        received_at=datetime.now(timezone.utc),
        metadata={"subject": "Solicitud de turno neurología"},
    ),
    IncomingMessage(
        id="demo-002",
        channel=Channel.EMAIL,
        sender_id="jorge.r.32@hotmail.com",
        sender_name="jorge ramirez",
        body="""Asunto: turno

hola buen dia soy jorge ramirez dni 32567890 necesito 
un turno con neuro x favor, es para control de mi esclerosis.
si puede ser a la mañana mejor xq laburo a la tarde
gracias!!""",
        received_at=datetime.now(timezone.utc),
        metadata={"subject": "turno"},
    ),
    IncomingMessage(
        id="demo-003",
        channel=Channel.EMAIL,
        sender_id="carla.fernandez@yahoo.com.ar",
        sender_name="Carla Fernández",
        body="""Asunto: Turno para mi mamá

Buenas, le escribo por mi mamá Stella Maris Fernández, 
documento 18.234.567. Ella necesita renovar el turno con el Dr. que la 
atiende por la esclerosis, no me acuerdo el nombre pero atiende los miércoles 
en piso 9. Yo soy su hija Carla, mi cel es 1155667788.""",
        received_at=datetime.now(timezone.utc),
        metadata={"subject": "Turno para mi mamá"},
    ),
]


def run_demo():
    """Process demo emails through the full pipeline."""
    print("=" * 60)
    print("EM Navigator — Demo Mode (no Gmail)")
    print("=" * 60)

    for msg in DEMO_EMAILS:
        print(f"\n{'─' * 60}")
        print(f"📧 From: {msg.sender_name} <{msg.sender_id}>")
        print(f"   Body: {msg.body[:80]}...")
        print(f"{'─' * 60}")

        try:
            reply = process_message(msg)

            print(f"\n📋 Extracted Data:")
            for key, value in reply.extracted_data.items():
                if key != "confidence":
                    print(f"   • {key}: {value}")

            print(f"\n📅 Proposed: {reply.proposed_datetime or 'No slot found'}")
            print(f"🎯 Confidence: {reply.confidence}")

            print(f"\n✉️  Drafted Reply:")
            print(f"   Subject: {reply.subject}")
            for line in reply.body.split("\n"):
                print(f"   {line}")

            # Save for review
            filepath = save_for_review(reply, msg)
            print(f"\n💾 Saved for review: {filepath}")

        except Exception as e:
            print(f"❌ Error: {e}")

    print(f"\n{'=' * 60}")
    print(f"✅ Processed {len(DEMO_EMAILS)} emails")
    print(f"📂 Review queue: {REVIEW_DIR}")
    print(f"{'=' * 60}")


def run_gmail():
    """Process real emails from Gmail."""
    from src.connectors.gmail_connector import GmailConnector

    import asyncio

    async def _process():
        connector = GmailConnector()
        messages = await connector.fetch_new_messages()

        if not messages:
            print("📭 No new messages")
            return

        print(f"📬 Found {len(messages)} new messages")

        for msg in messages:
            print(f"\n📧 Processing: {msg.sender_name} — {msg.body[:60]}...")
            reply = process_message(msg)
            filepath = save_for_review(reply, msg)
            print(f"   💾 Saved: {filepath}")

            # Mark as read so we don't reprocess
            gmail_id = msg.metadata.get("gmail_message_id")
            if gmail_id:
                await connector.mark_as_read(gmail_id)

    asyncio.run(_process())


def run_watch(interval_seconds: int = 300):
    """Poll Gmail every N seconds (default: 5 minutes)."""
    print(f"👀 Watching Gmail every {interval_seconds}s. Ctrl+C to stop.")
    while True:
        try:
            run_gmail()
            time.sleep(interval_seconds)
        except KeyboardInterrupt:
            print("\n👋 Stopped watching.")
            break


# ─────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="EM Navigator — Appointment Agent")
    parser.add_argument("--demo", action="store_true", help="Run with test emails (no Gmail needed)")
    parser.add_argument("--watch", action="store_true", help="Poll Gmail every 5 minutes")
    parser.add_argument("--interval", type=int, default=300, help="Polling interval in seconds")
    args = parser.parse_args()

    if args.demo:
        run_demo()
    elif args.watch:
        run_watch(args.interval)
    else:
        run_gmail()


if __name__ == "__main__":
    main()
