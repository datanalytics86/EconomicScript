"""Ingesta de notificaciones Gmail vía IMAP para bancos chilenos."""

from __future__ import annotations

import base64
import email
import html as _html_stdlib
import imaplib
import logging
import re
from datetime import date

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

import config
from db import Database
from models import TransactionRecord
from parsers import BCIParser, BancoEstadoParser, SecurityParser

LOGGER = logging.getLogger(__name__)
BANK_DOMAINS = ["@bci.cl", "@bancoestado.cl", "@security.cl"]


class GmailIngestor:
    """Conector IMAP para extraer y persistir transacciones desde Gmail."""

    def __init__(self, db: Database) -> None:
        self.db = db
        self.parsers = [BCIParser(), BancoEstadoParser(), SecurityParser()]

    def _connect(self) -> imaplib.IMAP4_SSL:
        """Crea y retorna una conexión IMAP autenticada via OAuth2 (XOAUTH2)."""
        if not config.IMAP_USER or not config.OAUTH_CLIENT_ID or not config.OAUTH_CLIENT_SECRET or not config.OAUTH_REFRESH_TOKEN:
            raise ValueError(
                "IMAP_USER, OAUTH_CLIENT_ID, OAUTH_CLIENT_SECRET y OAUTH_REFRESH_TOKEN "
                "deben estar definidos en el archivo .env"
            )
        creds = Credentials(
            token=None,
            refresh_token=config.OAUTH_REFRESH_TOKEN,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=config.OAUTH_CLIENT_ID,
            client_secret=config.OAUTH_CLIENT_SECRET,
            scopes=["https://mail.google.com/"],
        )
        creds.refresh(Request())
        auth_string = f"user={config.IMAP_USER}\x01auth=Bearer {creds.token}\x01\x01"
        mail = imaplib.IMAP4_SSL(config.IMAP_SERVER, config.IMAP_PORT)
        mail.authenticate("XOAUTH2", lambda _: auth_string.encode())
        LOGGER.info("Conexión IMAP OAuth2 establecida con %s", config.IMAP_SERVER)
        return mail

    def ingest(self, since_date: date | None = None) -> dict[str, int]:
        """Procesa correos Gmail vía IMAP. Retorna resumen con conteos por estado.

        Args:
            since_date: Si se indica, busca TODOS los correos (leídos y no leídos)
                        desde esa fecha en adelante. Útil para carga inicial histórica.
                        Si es None, busca solo correos no leídos (comportamiento diario).
        """

        mail = self._connect()
        try:
            mail.select("INBOX")
            uids = self._search_bank_emails(mail, since_date=since_date)
            LOGGER.info("Correos encontrados para procesar: %s", len(uids))

            self._ensure_processed_folder(mail)

            parsed_transactions: list[TransactionRecord] = []
            summary = {
                "found": len(uids),
                "processed": 0,
                "no_parser": 0,
                "failed": 0,
                "saved": 0,
            }

            for uid in uids:
                sender = subject = body = ""
                try:
                    _, data = mail.uid("fetch", uid, "(RFC822)")
                    raw_email = data[0][1]
                    msg = email.message_from_bytes(raw_email)
                    sender = msg.get("From", "")
                    subject = msg.get("Subject", "")
                    body = self._extract_body(msg)

                    parser = next(
                        (p for p in self.parsers if p.can_parse(sender=sender, subject=subject, body=body)),
                        None,
                    )
                    if not parser:
                        summary["no_parser"] += 1
                        self.db.save_unprocessed_email(
                            uid.decode(), sender, subject, body, "Sin parser compatible"
                        )
                        continue

                    transaction = parser.parse(body=body, gmail_message_id=uid.decode())
                    parsed_transactions.append(transaction)
                    self._mark_as_processed(mail, uid)
                    summary["processed"] += 1

                except Exception as exc:  # noqa: BLE001
                    LOGGER.exception("Error procesando mensaje %s: %s", uid, exc)
                    summary["failed"] += 1
                    self.db.save_unprocessed_email(uid.decode(), sender, subject, body, str(exc))

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
        finally:
            try:
                mail.close()
                mail.logout()
            except Exception:  # noqa: BLE001
                pass

    def _search_bank_emails(
        self, mail: imaplib.IMAP4_SSL, since_date: date | None = None
    ) -> list[bytes]:
        """Busca correos de los dominios bancarios configurados.

        Si since_date está presente usa ALL SINCE <fecha> (incluye ya leídos).
        Si es None usa UNSEEN (solo correos nuevos — modo diario normal).
        """
        if since_date is not None:
            # Formato IMAP: DD-Mon-YYYY, ej: "24-Feb-2026"
            imap_date = since_date.strftime("%d-%b-%Y")
            criteria_prefix = f'(SINCE "{imap_date}"'
        else:
            criteria_prefix = "(UNSEEN"

        all_uids: set[bytes] = set()
        for domain in BANK_DOMAINS:
            criteria = f'{criteria_prefix} FROM "{domain}")'
            _, data = mail.uid("search", None, criteria)
            if data[0]:
                all_uids.update(data[0].split())
        return sorted(all_uids)[: config.GMAIL_MAX_RESULTS]

    def _ensure_processed_folder(self, mail: imaplib.IMAP4_SSL) -> None:
        """Crea la carpeta de procesados si no existe (idempotente)."""

        folder = config.PROCESSED_LABEL
        _, folders = mail.list()
        existing_names = [f.decode() for f in folders if f]
        if not any(folder in name for name in existing_names):
            mail.create(folder)
            LOGGER.info("Carpeta IMAP creada: %s", folder)

    def _mark_as_processed(self, mail: imaplib.IMAP4_SSL, uid: bytes) -> None:
        """Copia el correo a la carpeta de procesados y lo marca como leído."""

        mail.uid("copy", uid, config.PROCESSED_LABEL)
        mail.uid("store", uid, "+FLAGS", "\\Seen")

    @staticmethod
    def _extract_body(msg: email.message.Message) -> str:
        """Extrae texto del mensaje email.

        Busca recursivamente en partes multipart.
        Prefiere text/plain; si no existe, convierte text/html a texto plano.
        """
        plain: list[str] = []
        html_parts: list[str] = []

        if msg.is_multipart():
            for part in msg.walk():
                content_type = part.get_content_type()
                payload = part.get_payload(decode=True)
                if not payload:
                    continue
                text = payload.decode("utf-8", errors="ignore")
                if content_type == "text/plain":
                    plain.append(text)
                elif content_type == "text/html":
                    html_parts.append(text)
        else:
            payload = msg.get_payload(decode=True)
            if payload:
                text = payload.decode("utf-8", errors="ignore")
                if msg.get_content_type() == "text/plain":
                    plain.append(text)
                else:
                    html_parts.append(text)

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
