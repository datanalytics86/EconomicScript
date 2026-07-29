"""Configuración centralizada del sistema financiero."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

_BASE_DIR = Path(__file__).parent
load_dotenv(_BASE_DIR / ".env")

# ── Base de datos ──────────────────────────────────────────────────────────────
DB_PATH: str = os.getenv("DB_PATH", str(_BASE_DIR / "finance.db"))
SCHEMA_PATH: str = os.getenv("SCHEMA_PATH", str(_BASE_DIR / "sql" / "schema.sql"))

# ── Gmail IMAP ─────────────────────────────────────────────────────────────────
IMAP_SERVER: str = os.getenv("IMAP_SERVER", "imap.gmail.com")
IMAP_PORT: int = int(os.getenv("IMAP_PORT", "993"))
IMAP_USER: str = os.getenv("IMAP_USER", "")
PROCESSED_LABEL: str = "Procesado/Finanzas"

# ── Gmail OAuth2 ───────────────────────────────────────────────────────────────
OAUTH_CLIENT_ID: str = os.getenv("OAUTH_CLIENT_ID", "")
OAUTH_CLIENT_SECRET: str = os.getenv("OAUTH_CLIENT_SECRET", "")
OAUTH_REFRESH_TOKEN: str = os.getenv("OAUTH_REFRESH_TOKEN", "")
# Máximo de correos a leer por ejecución (evita OOM con inbox grande)
GMAIL_MAX_RESULTS: int = int(os.getenv("GMAIL_MAX_RESULTS", "500"))
# Días hacia atrás a revisar en la corrida diaria (leídos y no leídos).
# 0 = solo UNSEEN. >=1 usa SINCE y deduplica por gmail_message_id.
# Mitiga correos abiertos en el móvil antes de que corra el job y huecos
# si el PC/scheduler estuvo apagado varios días. 7 es un default seguro.
GMAIL_LOOKBACK_DAYS: int = int(os.getenv("GMAIL_LOOKBACK_DAYS", "7"))

# ── Reconciliación ─────────────────────────────────────────────────────────────
# Días de tolerancia para cruzar fecha Gmail vs cartola (cargos pueden debitarse al día siguiente)
RECONCILIATION_DATE_TOLERANCE_DAYS: int = int(
    os.getenv("RECONCILIATION_DATE_TOLERANCE_DAYS", "1")
)

# ── Bancos soportados ─────────────────────────────────────────────────────────
SUPPORTED_BANKS: list[str] = ["BCI", "BANCO_ESTADO", "SECURITY"]

# ── Localización ──────────────────────────────────────────────────────────────
TIMEZONE: str = "America/Santiago"

# ── Cartolas PDF ──────────────────────────────────────────────────────────────
# Contraseña para abrir cartolas PDF protegidas (los bancos chilenos suelen usar el RUT)
PDF_PASSWORD: str = os.getenv("PDF_PASSWORD", "")

# ── SMTP — Reporte diario por email ───────────────────────────────────────────
# Destinatario del resumen diario (por defecto el mismo usuario de Gmail)
SMTP_TO: str = os.getenv("SMTP_TO", "")
# Servidor SMTP (Gmail por defecto)
SMTP_SERVER: str = os.getenv("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT: int = int(os.getenv("SMTP_PORT", "587"))
# Usuario/contraseña SMTP (por defecto usa las mismas credenciales que IMAP)
SMTP_USER: str = os.getenv("SMTP_USER", "")
SMTP_PASSWORD: str = os.getenv("SMTP_PASSWORD", "")

# ── Alertas instantáneas (poll) ───────────────────────────────────────────────
# False por defecto: el usuario no quiere un email por cada transacción.
# El reporte diario/parcial cubre el resumen. Poner true solo si se desea alertas.
INSTANT_ALERTS_ENABLED: bool = os.getenv(
    "INSTANT_ALERTS_ENABLED", "false"
).strip().lower() in ("1", "true", "yes", "on")

# ── Logging ───────────────────────────────────────────────────────────────────
LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
LOG_FILE: str = os.getenv("LOG_FILE", str(_BASE_DIR / "economicscript.log"))
