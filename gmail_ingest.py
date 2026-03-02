"""Ingesta de notificaciones Gmail para bancos chilenos."""

from __future__ import annotations

import base64
import logging
import os
from typing import Iterable

from dotenv import load_dotenv
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from db import Database
from models import TransactionRecord
from parsers import BCIParser, BancoEstadoParser, SecurityParser

LOGGER = logging.getLogger(__name__)
SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]
PROCESSED_LABEL = "Procesado/Finanzas"
GMAIL_QUERY = "from:(*@bci.cl OR *@bancoestado.cl OR *@security.cl)"


class GmailIngestor:
    """Conector de Gmail API para extraer y persistir transacciones."""

    def __init__(self, db: Database) -> None:
        self.db = db
        self.parsers = [BCIParser(), BancoEstadoParser(), SecurityParser()]
        self.service = self._build_service()

    def _build_service(self):
        """Autentica y construye cliente Gmail usando .env y credentials.json."""

        load_dotenv()
        token_path = os.getenv("GOOGLE_TOKEN_PATH", "token.json")
        credentials_path = os.getenv("GOOGLE_CREDENTIALS_PATH", "credentials.json")

        creds: Credentials | None = None
        if os.path.exists(token_path):
            creds = Credentials.from_authorized_user_file(token_path, SCOPES)
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(credentials_path, SCOPES)
                creds = flow.run_local_server(port=0)
            with open(token_path, "w", encoding="utf-8") as token:
                token.write(creds.to_json())

        return build("gmail", "v1", credentials=creds)

    def ingest(self) -> int:
        """Procesa correos Gmail, persiste transacciones y etiqueta mensajes."""

        results = self.service.users().messages().list(userId="me", q=GMAIL_QUERY).execute()
        messages = results.get("messages", [])
        parsed_transactions: list[TransactionRecord] = []

        label_id = self._ensure_processed_label(PROCESSED_LABEL)

        for msg in messages:
            message_id = msg["id"]
            try:
                payload = self.service.users().messages().get(userId="me", id=message_id, format="full").execute()
                headers = {h["name"].lower(): h["value"] for h in payload["payload"].get("headers", [])}
                sender = headers.get("from", "")
                subject = headers.get("subject", "")
                body = self._extract_body(payload)

                parser = next(
                    (p for p in self.parsers if p.can_parse(sender=sender, subject=subject, body=body)),
                    None,
                )
                if not parser:
                    raise ValueError("No existe parser compatible para el correo")

                transaction = parser.parse(body=body, gmail_message_id=message_id)
                parsed_transactions.append(transaction)
                self._mark_as_processed(message_id=message_id, label_id=label_id)
            except Exception as exc:  # noqa: BLE001
                LOGGER.exception("Error procesando mensaje %s", message_id)
                self.db.save_unprocessed_email(message_id, sender, subject, body if 'body' in locals() else "", str(exc))

        saved = self.db.insert_transactions(parsed_transactions)
        LOGGER.info("Transacciones guardadas desde Gmail: %s", saved)
        return saved

    @staticmethod
    def _extract_body(payload: dict) -> str:
        """Extrae texto plano del payload Gmail."""

        parts = payload.get("payload", {}).get("parts", [])
        data = payload.get("payload", {}).get("body", {}).get("data")
        if not data and parts:
            for part in parts:
                if part.get("mimeType") == "text/plain":
                    data = part.get("body", {}).get("data")
                    break
        if not data:
            return ""
        return base64.urlsafe_b64decode(data).decode("utf-8", errors="ignore")

    def _ensure_processed_label(self, label_name: str) -> str:
        """Obtiene o crea label para correos procesados."""

        labels = self.service.users().labels().list(userId="me").execute().get("labels", [])
        existing = next((label for label in labels if label["name"] == label_name), None)
        if existing:
            return existing["id"]
        created = self.service.users().labels().create(
            userId="me",
            body={"name": label_name, "labelListVisibility": "labelShow", "messageListVisibility": "show"},
        ).execute()
        return created["id"]

    def _mark_as_processed(self, message_id: str, label_id: str) -> None:
        """Asigna label de procesado al mensaje Gmail."""

        self.service.users().messages().modify(
            userId="me",
            id=message_id,
            body={"addLabelIds": [label_id]},
        ).execute()
