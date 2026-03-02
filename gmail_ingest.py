"""Ingesta de notificaciones Gmail para bancos chilenos."""

from __future__ import annotations

import base64
import html as _html_stdlib
import logging
import re
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

import config
from db import Database
from models import TransactionRecord
from parsers import BCIParser, BancoEstadoParser, SecurityParser

LOGGER = logging.getLogger(__name__)
SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]


class GmailIngestor:
    """Conector de Gmail API para extraer y persistir transacciones."""

    def __init__(self, db: Database) -> None:
        self.db = db
        self.parsers = [BCIParser(), BancoEstadoParser(), SecurityParser()]
        self.service = self._build_service()

    def _build_service(self):
        """Autentica y construye cliente Gmail. Renueva token automáticamente si expira."""

        token_path = config.GOOGLE_TOKEN_PATH
        credentials_path = config.GOOGLE_CREDENTIALS_PATH

        creds: Credentials | None = None
        if Path(token_path).exists():
            creds = Credentials.from_authorized_user_file(token_path, SCOPES)
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
                LOGGER.info("Token Gmail renovado exitosamente")
            else:
                flow = InstalledAppFlow.from_client_secrets_file(credentials_path, SCOPES)
                creds = flow.run_local_server(port=0)
            Path(token_path).write_text(creds.to_json(), encoding="utf-8")

        return build("gmail", "v1", credentials=creds)

    def ingest(self) -> dict[str, int]:
        """Procesa correos Gmail. Retorna resumen con conteos por estado."""

        messages = self._list_all_messages()
        LOGGER.info("Correos encontrados para procesar: %s", len(messages))

        label_id = self._ensure_processed_label(config.PROCESSED_LABEL)
        parsed_transactions: list[TransactionRecord] = []
        summary = {
            "found": len(messages),
            "processed": 0,
            "no_parser": 0,
            "failed": 0,
            "saved": 0,
        }

        for msg in messages:
            message_id = msg["id"]
            # Inicializar antes del try para que el except siempre tenga valores válidos
            sender = subject = body = ""
            try:
                payload = (
                    self.service.users()
                    .messages()
                    .get(userId="me", id=message_id, format="full")
                    .execute()
                )
                headers = {
                    h["name"].lower(): h["value"]
                    for h in payload["payload"].get("headers", [])
                }
                sender = headers.get("from", "")
                subject = headers.get("subject", "")
                body = self._extract_body(payload)

                parser = next(
                    (p for p in self.parsers if p.can_parse(sender=sender, subject=subject, body=body)),
                    None,
                )
                if not parser:
                    summary["no_parser"] += 1
                    self.db.save_unprocessed_email(
                        message_id, sender, subject, body, "Sin parser compatible"
                    )
                    continue

                transaction = parser.parse(body=body, gmail_message_id=message_id)
                parsed_transactions.append(transaction)
                self._mark_as_processed(message_id=message_id, label_id=label_id)
                summary["processed"] += 1

            except Exception as exc:  # noqa: BLE001
                LOGGER.exception("Error procesando mensaje %s: %s", message_id, exc)
                summary["failed"] += 1
                self.db.save_unprocessed_email(message_id, sender, subject, body, str(exc))

        summary["saved"] = self.db.insert_transactions(parsed_transactions)
        LOGGER.info(
            "Ingesta completada — encontrados: %s | procesados: %s | "
            "sin parser: %s | fallidos: %s | guardados: %s",
            summary["found"],
            summary["processed"],
            summary["no_parser"],
            summary["failed"],
            summary["saved"],
        )
        return summary

    def _list_all_messages(self) -> list[dict]:
        """Obtiene mensajes con paginación completa hasta GMAIL_MAX_RESULTS."""

        messages: list[dict] = []
        request = self.service.users().messages().list(
            userId="me",
            q=config.GMAIL_QUERY,
            maxResults=min(config.GMAIL_MAX_RESULTS, 500),
        )
        while request and len(messages) < config.GMAIL_MAX_RESULTS:
            result = request.execute()
            messages.extend(result.get("messages", []))
            next_page = result.get("nextPageToken")
            if next_page:
                remaining = config.GMAIL_MAX_RESULTS - len(messages)
                request = self.service.users().messages().list(
                    userId="me",
                    q=config.GMAIL_QUERY,
                    maxResults=min(remaining, 500),
                    pageToken=next_page,
                )
            else:
                break
        return messages[: config.GMAIL_MAX_RESULTS]

    @staticmethod
    def _extract_body(payload: dict) -> str:
        """Extrae texto del payload Gmail.

        Busca recursivamente en partes anidadas (multipart/mixed, multipart/alternative).
        Prefiere text/plain; si no existe, convierte text/html a texto plano.
        """
        plain: list[str] = []
        html_parts: list[str] = []

        def _collect(part: dict) -> None:
            mime = part.get("mimeType", "")
            data = part.get("body", {}).get("data")
            if data:
                text = base64.urlsafe_b64decode(data).decode("utf-8", errors="ignore")
                if mime == "text/plain":
                    plain.append(text)
                elif mime == "text/html":
                    html_parts.append(text)
            for sub in part.get("parts", []):
                _collect(sub)

        _collect(payload.get("payload", {}))

        if plain:
            return plain[0]
        if html_parts:
            return GmailIngestor._html_to_text(html_parts[0])
        return ""

    @staticmethod
    def _html_to_text(html_body: str) -> str:
        """Convierte HTML a texto plano preservando estructura de líneas.

        Reemplaza etiquetas de bloque y celdas de tabla con saltos/espacios
        antes de eliminar el resto del markup.
        """
        # Etiquetas de cierre de bloque → salto de línea
        text = re.sub(
            r"<(?:br\s*/?|/p|/div|/tr|/li|/h[1-6])[^>]*>",
            "\n",
            html_body,
            flags=re.IGNORECASE,
        )
        # Apertura de celda → espacio (separa label de valor en tablas)
        text = re.sub(r"<t[dh][^>]*>", " ", text, flags=re.IGNORECASE)
        # Elimina etiquetas restantes
        text = re.sub(r"<[^>]+>", "", text)
        # Decodifica entidades (&amp; &nbsp; &gt; etc.)
        text = _html_stdlib.unescape(text)
        # Normaliza espacios dentro de cada línea, descarta líneas vacías
        lines = [" ".join(line.split()) for line in text.splitlines()]
        return "\n".join(line for line in lines if line)

    def _ensure_processed_label(self, label_name: str) -> str:
        """Obtiene o crea label para correos procesados (idempotente)."""

        labels = self.service.users().labels().list(userId="me").execute().get("labels", [])
        existing = next((label for label in labels if label["name"] == label_name), None)
        if existing:
            return existing["id"]
        created = self.service.users().labels().create(
            userId="me",
            body={
                "name": label_name,
                "labelListVisibility": "labelShow",
                "messageListVisibility": "show",
            },
        ).execute()
        return created["id"]

    def _mark_as_processed(self, message_id: str, label_id: str) -> None:
        """Asigna label de procesado al mensaje Gmail."""

        self.service.users().messages().modify(
            userId="me",
            id=message_id,
            body={"addLabelIds": [label_id]},
        ).execute()
