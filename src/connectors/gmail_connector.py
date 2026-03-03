"""
Gmail Connector — converts Gmail API data into IncomingMessages.

This is the ONLY file that knows about Gmail. If you replace Gmail with
Outlook tomorrow, you write a new connector and change one import.

Approach: Polling (not Push Notifications)
Why: Simpler to deploy, no public webhook URL needed, and for a hospital
that currently takes 13 DAYS to respond, polling every 5 minutes is
already a 3,700x improvement. Push can come later.

Setup required:
1. Enable Gmail API in Google Cloud Console
2. Create OAuth2 credentials (Desktop app type for MVP)
3. Run the auth flow once to generate token.json
4. Store credentials in config/gmail_credentials.json

Docs: https://developers.google.com/gmail/api/quickstart/python
"""

from __future__ import annotations

import base64
import hashlib
import re
from datetime import datetime, timezone
from email.utils import parseaddr
from typing import Any

from src.core.message import Channel, DraftedReply, IncomingMessage

# Gmail API imports — only needed in this file
# pip install google-auth-oauthlib google-api-python-client
try:
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    GMAIL_AVAILABLE = True
except ImportError:
    GMAIL_AVAILABLE = False


SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.modify",
]

# Label used to track which emails have been processed
PROCESSED_LABEL = "EMNavigator/Processed"


class GmailConnector:
    """Inbound + Outbound connector for Gmail.

    Usage:
        connector = GmailConnector("config/gmail_credentials.json")
        new_messages = await connector.fetch_new_messages()
        # ... process with intelligence core ...
        await connector.send_reply(drafted_reply)
    """

    def __init__(
        self,
        credentials_path: str = "config/gmail_credentials.json",
        token_path: str = "config/gmail_token.json",
        target_label: str = "INBOX",
    ):
        if not GMAIL_AVAILABLE:
            raise ImportError(
                "Gmail dependencies not installed. Run: "
                "pip install google-auth-oauthlib google-api-python-client"
            )
        self.credentials_path = credentials_path
        self.token_path = token_path
        self.target_label = target_label
        self._service = None

    def _get_service(self):
        """Authenticate and return Gmail API service (lazy init)."""
        if self._service:
            return self._service

        creds = None
        try:
            creds = Credentials.from_authorized_user_file(self.token_path, SCOPES)
        except FileNotFoundError:
            pass

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(
                    self.credentials_path, SCOPES
                )
                creds = flow.run_local_server(port=0)

            with open(self.token_path, "w") as f:
                f.write(creds.to_json())

        self._service = build("gmail", "v1", credentials=creds)
        return self._service

    async def fetch_new_messages(
        self, max_results: int = 20, query: str = "is:unread"
    ) -> list[IncomingMessage]:
        """Fetch unread emails and convert to IncomingMessages.

        Only fetches emails matching the query (default: unread).
        After processing, emails should be marked as read.
        """
        service = self._get_service()

        results = (
            service.users()
            .messages()
            .list(
                userId="me",
                q=query,
                labelIds=[self.target_label],
                maxResults=max_results,
            )
            .execute()
        )

        gmail_messages = results.get("messages", [])
        incoming: list[IncomingMessage] = []

        for msg_ref in gmail_messages:
            msg = (
                service.users()
                .messages()
                .get(userId="me", id=msg_ref["id"], format="full")
                .execute()
            )
            incoming_msg = self._parse_gmail_message(msg)
            if incoming_msg:
                incoming.append(incoming_msg)

        return incoming

    def _parse_gmail_message(self, gmail_msg: dict) -> IncomingMessage | None:
        """Convert a raw Gmail API message into an IncomingMessage."""
        headers = {
            h["name"].lower(): h["value"]
            for h in gmail_msg.get("payload", {}).get("headers", [])
        }

        sender_raw = headers.get("from", "")
        sender_name, sender_email = parseaddr(sender_raw)

        subject = headers.get("subject", "(sin asunto)")
        body = self._extract_body(gmail_msg.get("payload", {}))

        if not body.strip():
            return None

        # Deterministic ID for dedup
        content_hash = hashlib.sha256(
            f"{sender_email}:{subject}:{body[:200]}".encode()
        ).hexdigest()[:12]

        return IncomingMessage(
            id=f"gmail-{gmail_msg['id']}-{content_hash}",
            channel=Channel.EMAIL,
            sender_id=sender_email,
            sender_name=sender_name or sender_email.split("@")[0],
            body=f"Asunto: {subject}\n\n{body}",
            received_at=datetime.now(timezone.utc),
            metadata={
                "gmail_message_id": gmail_msg["id"],
                "gmail_thread_id": gmail_msg.get("threadId"),
                "subject": subject,
                "original_from": sender_raw,
            },
        )

    def _extract_body(self, payload: dict) -> str:
        """Extract plain text body from Gmail message payload.

        Handles both simple and multipart messages.
        """
        # Simple message
        if payload.get("mimeType") == "text/plain" and "data" in payload.get("body", {}):
            return base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", errors="replace")

        # Multipart — find text/plain part
        for part in payload.get("parts", []):
            if part.get("mimeType") == "text/plain" and "data" in part.get("body", {}):
                return base64.urlsafe_b64decode(part["body"]["data"]).decode("utf-8", errors="replace")
            # Nested multipart
            if part.get("parts"):
                result = self._extract_body(part)
                if result:
                    return result

        return ""

    async def send_reply(self, reply: DraftedReply) -> bool:
        """Send the approved reply as a Gmail response in the same thread.

        Uses the thread_id from metadata to keep the conversation threaded.
        """
        import email.mime.text

        service = self._get_service()

        message = email.mime.text.MIMEText(reply.body)
        message["to"] = reply.recipient_id
        message["subject"] = reply.subject

        # Thread the reply if we have the original thread ID
        thread_id = reply.metadata.get("gmail_thread_id")
        original_message_id = reply.metadata.get("gmail_message_id")

        if original_message_id:
            message["In-Reply-To"] = original_message_id
            message["References"] = original_message_id

        raw = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")

        body: dict[str, Any] = {"raw": raw}
        if thread_id:
            body["threadId"] = thread_id

        try:
            service.users().messages().send(userId="me", body=body).execute()
            return True
        except Exception as e:
            print(f"Error sending reply: {e}")
            return False

    async def mark_as_read(self, gmail_message_id: str) -> None:
        """Mark a processed email as read."""
        service = self._get_service()
        service.users().messages().modify(
            userId="me",
            id=gmail_message_id,
            body={"removeLabelIds": ["UNREAD"]},
        ).execute()
