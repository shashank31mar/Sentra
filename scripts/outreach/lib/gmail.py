"""Gmail client — OAuth, create-draft-with-attachment, batch-send, read-Sent.

Thin wrapper over the Gmail API. All send/draft operations go through here so the
send-gate (dry_run, throttle) and idempotency live in one place.

Auth model: an installed-app OAuth flow. credentials.json (the OAuth client) is
provided by the founder; token.json is cached after the first consent. Both are
gitignored. See docs/outreach-automation.md §6.
"""
from __future__ import annotations

import base64
import mimetypes
from email.message import EmailMessage
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build


class GmailClient:
    def __init__(self, credentials_path: Path, token_path: Path, scopes: list[str]):
        self._credentials_path = Path(credentials_path)
        self._token_path = Path(token_path)
        self._scopes = list(scopes)
        self._service = None

    # --- auth -------------------------------------------------------------
    def _creds(self) -> Credentials:
        creds: Credentials | None = None
        if self._token_path.exists():
            creds = Credentials.from_authorized_user_file(str(self._token_path), self._scopes)
        if creds and creds.valid:
            return creds
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not self._credentials_path.exists():
                raise FileNotFoundError(
                    f"OAuth client not found at {self._credentials_path}. "
                    "Create it in Google Cloud Console (Gmail API, Desktop app) and download it. "
                    "See docs/outreach-automation.md §6."
                )
            flow = InstalledAppFlow.from_client_secrets_file(
                str(self._credentials_path), self._scopes
            )
            creds = flow.run_local_server(port=0)
        self._token_path.write_text(creds.to_json())
        return creds

    def service(self):
        if self._service is None:
            self._service = build("gmail", "v1", credentials=self._creds())
        return self._service

    # --- message building -------------------------------------------------
    @staticmethod
    def build_message(
        *,
        sender: str,
        to: str,
        subject: str,
        body: str,
        attachment: Path | None = None,
    ) -> dict:
        """Build a base64url-raw message dict for the Gmail API (plain text + optional attachment)."""
        msg = EmailMessage()
        msg["To"] = to
        msg["From"] = sender
        msg["Subject"] = subject
        msg.set_content(body)  # plain text — reads like a founder wrote it

        if attachment is not None:
            attachment = Path(attachment)
            if not attachment.exists():
                raise FileNotFoundError(f"attachment not found: {attachment}")
            ctype, _ = mimetypes.guess_type(attachment.name)
            maintype, _, subtype = (ctype or "application/octet-stream").partition("/")
            msg.add_attachment(
                attachment.read_bytes(),
                maintype=maintype,
                subtype=subtype or "octet-stream",
                filename=attachment.name,
            )
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        return {"raw": raw}

    # --- operations -------------------------------------------------------
    def create_draft(self, message: dict) -> dict:
        """Create a Gmail draft. Returns the draft resource (id, message.id)."""
        return (
            self.service()
            .users()
            .drafts()
            .create(userId="me", body={"message": message})
            .execute()
        )

    def send_draft(self, draft_id: str) -> dict:
        """Send an existing draft by id. Idempotent per draft_id at the caller."""
        return (
            self.service()
            .users()
            .drafts()
            .send(userId="me", body={"id": draft_id})
            .execute()
        )

    def list_sent(self, max_results: int = 50) -> list[dict]:
        """List recent Sent messages (for reconcile). Returns [{id, threadId}, ...]."""
        resp = (
            self.service()
            .users()
            .messages()
            .list(userId="me", labelIds=["SENT"], maxResults=max_results)
            .execute()
        )
        return resp.get("messages", [])

    def get_message_headers(self, message_id: str) -> dict[str, str]:
        """Fetch a message's To/Subject/Date headers (metadata only) for reconcile matching."""
        msg = (
            self.service()
            .users()
            .messages()
            .get(
                userId="me",
                id=message_id,
                format="metadata",
                metadataHeaders=["To", "Subject", "Date"],
            )
            .execute()
        )
        headers = msg.get("payload", {}).get("headers", [])
        return {h["name"]: h["value"] for h in headers}
