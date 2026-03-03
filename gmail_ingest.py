"""Ingesta de notificaciones Gmail vía IMAP para bancos chilenos."""

from __future__ import annotations

import email
import html as _html_stdlib
import imaplib
import logging
import re

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
        """Crea y retorna una conexión IMAP autenticada."""
        if not config.IMAP_USER or not config.IMAP_PASSWORD:
            raise ValueError(
                "IMAP_USER e IMAP_PASSWORD deben estar definidos en el archivo .env"
            )
        mail = imaplib.IMAP4_SSL(config.IMAP_SERVER, config.IMAP_PORT)
        mail.login(config.IMAP_USER, config.IMAP_PASSWORD)
        LOGGER.info("Conexión IMAP establecida con %s", config.IMAP_SERVER)
        return mail

    def ingest(self) -> dict[str, int]:
        """Procesa correos Gmail vía IMAP. Retorna resumen con conteos por estado."""

        mail = self._connect()
        try:
            mail.select("INBOX")
            uids = self._search_bank_emails(mail)
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

    def _search_bank_emails(self, mail: imaplib.IMAP4_SSL) -> list[bytes]:
        """Busca correos no leídos de los dominios bancarios configurados."""

        all_uids: set[bytes] = set()
        for domain in BANK_DOMAINS:
            _, data = mail.uid("search", None, f'(UNSEEN FROM "{domain}")')
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
