"""Ingesta de notificaciones Gmail vía IMAP para bancos chilenos."""

from __future__ import annotations

import email
import email.header
import html as _html_stdlib
import imaplib
import logging
import re
from collections.abc import Callable
from datetime import date

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

import config
from db import Database
from models import TransactionRecord
from parsers import BCIParser, BancoEstadoParser, SecurityParser

LOGGER = logging.getLogger(__name__)
# Dominios sin '@' — Gmail IMAP FROM matchea subcadenas (correo.bancoestado.cl, bancosecurity.cl, etc.)
BANK_DOMAINS = ["bci.cl", "bancoestado.cl", "security.cl", "bancosecurity.cl"]

# Correos bancarios sin transacción financiera — se marcan como procesados sin error
_SKIP_SUBJECT_KEYWORDS = (
    "no autorizada",
    "acceso a informacion",
    "acceso a información",
    "cambio de clave",
    "clave de internet",
    "bloqueo tdc",
    "certificado",
    "liquidacion deuda",
    "liquidación deuda",
    "paga tu patente",
    "beneficio",
    "descuento",
    "promocion",
    "promoción",
    "cuotas sin interés",
    "cuotas sin interes",
)
_SKIP_BODY_KEYWORDS = (
    "accediste a visualizar los datos de tu tarjeta",
    "notificación bloqueo tdc",
    "notificacion bloqueo tdc",
    "este mail es generado de manera automática, por favor no responda",
    "promoción exclusiva",
    "promocion exclusiva",
    "beneficios exclusivos",
)


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

    def ingest(
        self,
        since_date: date | None = None,
        progress_callback: Callable[[int, int, str], None] | None = None,
    ) -> dict[str, int]:
        """Procesa correos Gmail vía IMAP. Retorna resumen con conteos por estado.

        Args:
            since_date: Si se indica, busca TODOS los correos (leídos y no leídos)
                        desde esa fecha en adelante. Útil para carga inicial histórica.
                        Si es None, busca solo correos no leídos (comportamiento diario).
            progress_callback: Función opcional ``(current, total, message)`` llamada
                               después de procesar cada correo. Útil para barras de progreso.
        """

        mail = self._connect()
        try:
            mail.select("INBOX")
            uids = self._search_bank_emails(mail, since_date=since_date)
            LOGGER.info("Correos encontrados para procesar: %s", len(uids))

            self._ensure_processed_folder(mail)

            summary = {
                "found": len(uids),
                "processed": 0,
                "no_parser": 0,
                "failed": 0,
                "saved": 0,
                "skipped": 0,
                "duplicates": 0,
            }

            # Evita re-fetch y re-copias IMAP de mensajes ya persistidos (lookback / backfill)
            uid_ids = [u.decode() for u in uids]
            already_saved = self.db.known_gmail_ids(uid_ids)
            if already_saved:
                LOGGER.info(
                    "Omitiendo %s correos ya presentes en BD (dedup por gmail_message_id)",
                    len(already_saved),
                )

            if progress_callback and uids:
                progress_callback(0, len(uids), f"Encontrados {len(uids)} correos. Iniciando procesamiento…")

            for i, uid in enumerate(uids):
                sender = subject = body = ""
                uid_str = uid.decode()
                try:
                    if uid_str in already_saved:
                        summary["duplicates"] += 1
                        continue

                    try:
                        _, data = mail.uid("fetch", uid, "(RFC822)")
                    except (imaplib.IMAP4.abort, imaplib.IMAP4.error, OSError) as conn_exc:
                        LOGGER.warning(
                            "IMAP caído al fetch %s (%s) — reconectando…", uid_str, conn_exc
                        )
                        try:
                            mail.logout()
                        except Exception:  # noqa: BLE001
                            pass
                        mail = self._connect()
                        mail.select("INBOX")
                        self._ensure_processed_folder(mail)
                        _, data = mail.uid("fetch", uid, "(RFC822)")

                    if not data or not data[0] or data[0] is None:
                        raise ValueError(f"Fetch vacío para UID {uid_str}")

                    raw_email = data[0][1]
                    msg = email.message_from_bytes(raw_email)
                    sender = msg.get("From", "")
                    subject = str(
                        email.header.make_header(
                            email.header.decode_header(msg.get("Subject", ""))
                        )
                    )
                    body = self._extract_body(msg)

                    if self._should_skip_non_transaction(sender, subject, body):
                        self._mark_as_processed(mail, uid)
                        summary["skipped"] += 1
                        continue

                    parser = next(
                        (p for p in self.parsers if p.can_parse(sender=sender, subject=subject, body=body)),
                        None,
                    )
                    if not parser:
                        if self._looks_like_transaction(subject, body):
                            summary["no_parser"] += 1
                            self.db.save_unprocessed_email(
                                uid_str, sender, subject, body, "Sin parser compatible"
                            )
                        else:
                            self._mark_as_processed(mail, uid)
                            summary["skipped"] += 1
                        continue

                    transaction = parser.parse(body=body, gmail_message_id=uid_str)
                    # Guardar ANTES de marcar como leído: si cae la conexión, el correo
                    # sigue disponible y se reintenta en la próxima corrida.
                    inserted = self.db.insert_transaction(transaction)
                    if inserted:
                        summary["saved"] += 1
                        summary["processed"] += 1
                        already_saved.add(uid_str)
                        LOGGER.info(
                            "TX nueva %s | %s | %s | $%s | %s",
                            transaction.date.strftime("%Y-%m-%d"),
                            transaction.bank,
                            transaction.type,
                            f"{transaction.amount:,}".replace(",", "."),
                            (transaction.merchant or "")[:60],
                        )
                    else:
                        summary["duplicates"] += 1
                        already_saved.add(uid_str)
                    try:
                        self._mark_as_processed(mail, uid)
                    except (imaplib.IMAP4.abort, imaplib.IMAP4.error, OSError) as mark_exc:
                        LOGGER.warning(
                            "No se pudo marcar UID %s como procesado (%s); ya está en BD",
                            uid_str,
                            mark_exc,
                        )
                        try:
                            mail.logout()
                        except Exception:  # noqa: BLE001
                            pass
                        mail = self._connect()
                        mail.select("INBOX")
                        self._ensure_processed_folder(mail)

                except Exception as exc:  # noqa: BLE001
                    LOGGER.exception("Error procesando mensaje %s: %s", uid, exc)
                    summary["failed"] += 1
                    # No guardar errores de socket sin body (contaminan unprocessed)
                    err = str(exc)
                    if body or "socket" not in err.lower():
                        self.db.save_unprocessed_email(uid_str, sender, subject, body, err)
                finally:
                    if progress_callback:
                        try:
                            progress_callback(
                                i + 1,
                                len(uids),
                                f"Correo {i + 1} de {len(uids)} procesado…",
                            )
                        except Exception:  # noqa: BLE001
                            pass  # nunca dejar que la UI detenga el loop

            LOGGER.info(
                "Ingesta completada — encontrados: %s | procesados: %s | "
                "omitidos: %s | sin parser: %s | fallidos: %s | guardados: %s | "
                "duplicados: %s",
                summary["found"],
                summary["processed"],
                summary["skipped"],
                summary["no_parser"],
                summary["failed"],
                summary["saved"],
                summary["duplicates"],
            )
            return summary
        finally:
            try:
                mail.close()
                mail.logout()
            except Exception:  # noqa: BLE001
                pass

    @staticmethod
    def _should_skip_non_transaction(sender: str, subject: str, body: str) -> bool:
        """Detecta correos bancarios que no son transacciones (marketing, seguridad, etc.)."""
        sender_l = sender.lower()
        if "marketingbanco@" in sender_l or "asistencia.preferencial@" in sender_l:
            return True
        if subject.lower().startswith("re:"):
            return True
        subject_l = subject.lower()
        body_l = body.lower()
        if any(kw in subject_l for kw in _SKIP_SUBJECT_KEYWORDS):
            return True
        if any(kw in body_l for kw in _SKIP_BODY_KEYWORDS):
            return True
        return False

    @staticmethod
    def _looks_like_transaction(subject: str, body: str) -> bool:
        """Heurística: el correo parece contener un movimiento financiero."""
        text = f"{subject} {body}".lower()
        keywords = (
            "compra",
            "transferencia",
            "monto",
            "cargo",
            "abono",
            "giraste",
            "realizaste",
            "recibiste",
            "pago",
            "transacción",
            "transaccion",
            "tarjeta de crédito",
            "tarjeta de credito",
            "anulación",
            "anulacion",
            "reverso",
            "devolución",
            "devolucion",
        )
        return any(kw in text for kw in keywords)

    def _search_bank_emails(
        self, mail: imaplib.IMAP4_SSL, since_date: date | None = None
    ) -> list[bytes]:
        """Busca correos de los dominios bancarios configurados.

        Si since_date está presente usa ALL SINCE <fecha> (incluye ya leídos).
        Si es None usa UNSEEN (solo correos nuevos — modo diario normal).
        """
        if since_date is not None:
            # Formato IMAP siempre en inglés (evita locale ES: "jul." inválido)
            _months = (
                "Jan", "Feb", "Mar", "Apr", "May", "Jun",
                "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
            )
            imap_date = f"{since_date.day:02d}-{_months[since_date.month - 1]}-{since_date.year}"
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
            # Los correos text/plain de algunos bancos incluyen entidades HTML
            # (p.ej. &#x2F; en lugar de /) — decodificar antes de parsear
            return _html_stdlib.unescape(plain[0])
        if html_parts:
            return GmailIngestor._html_to_text(html_parts[0])
        return ""

    @staticmethod
    def _html_to_text(html_body: str) -> str:
        """Convierte HTML a texto plano preservando estructura de líneas.

        Reemplaza etiquetas de bloque y celdas de tabla con saltos/espacios
        antes de eliminar el resto del markup.
        """
        # Elimina bloques <style> y <script> completos (CSS/JS no aportan datos)
        text = re.sub(r"<style[^>]*>.*?</style>", "", html_body, flags=re.IGNORECASE | re.DOTALL)
        text = re.sub(r"<script[^>]*>.*?</script>", "", text, flags=re.IGNORECASE | re.DOTALL)
        # Etiquetas de cierre de bloque → salto de línea
        text = re.sub(
            r"<(?:br\s*/?|/p|/div|/tr|/li|/h[1-6])[^>]*>",
            "\n",
            text,
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
