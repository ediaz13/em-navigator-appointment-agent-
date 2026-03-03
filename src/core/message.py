"""
Core Message Protocol — the channel-agnostic contract.

Every connector (Gmail, WhatsApp, Web Portal) must convert its native
format into an IncomingMessage. The intelligence core only sees this.

This is the ONE abstraction worth building upfront because it's tiny,
stable, and prevents Gmail-specific code from leaking into your AI logic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Protocol
from uuid import uuid4


class Channel(str, Enum):
    EMAIL = "email"
    WHATSAPP = "whatsapp"
    WEB_PORTAL = "web_portal"


@dataclass(frozen=True)
class IncomingMessage:
    """The universal message format. Channel-agnostic.

    Every connector produces this. The intelligence core consumes this.
    That's the entire abstraction.
    """
    id: str                             # Unique ID (dedup key)
    channel: Channel                    # Where it came from
    sender_id: str                      # Phone number, email, user ID
    sender_name: str                    # Display name (if available)
    body: str                           # Plain text content
    received_at: datetime               # When it arrived
    attachments: list[str] = field(default_factory=list)  # File paths/URLs
    metadata: dict[str, Any] = field(default_factory=dict)
    # metadata stores channel-specific info the outcome layer needs to reply:
    #   email: {"subject": ..., "thread_id": ..., "message_id": ...}
    #   whatsapp: {"wa_message_id": ...}


@dataclass
class DraftedReply:
    """What the intelligence core produces. The outcome layer sends this."""
    request_id: str                     # Links back to IncomingMessage.id
    channel: Channel                    # Reply via same channel
    recipient_id: str                   # Email address, phone number, etc.
    subject: str                        # For email; ignored for WhatsApp
    body: str                           # The drafted reply text
    extracted_data: dict[str, Any]      # What the AI extracted (for dashboard)
    proposed_datetime: str | None       # The appointment slot proposed
    confidence: float                   # How confident the extraction was
    metadata: dict[str, Any] = field(default_factory=dict)  # Channel-specific reply info
    status: str = "pending_review"      # pending_review → approved → sent


# ─────────────────────────────────────────────
# Connector Protocol — what every channel adapter must implement
# ─────────────────────────────────────────────
class InboundConnector(Protocol):
    """Fetch new messages from a channel."""
    async def fetch_new_messages(self) -> list[IncomingMessage]: ...


class OutboundConnector(Protocol):
    """Send a reply through a channel."""
    async def send_reply(self, reply: DraftedReply) -> bool: ...
