"""Configuración centralizada del sistema financiero."""

from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()

# ── Base de datos ──────────────────────────────────────────────────────────────
DB_PATH: str = os.getenv("DB_PATH", "finance.db")
SCHEMA_PATH: str = os.getenv("SCHEMA_PATH", "sql/schema.sql")

# ── Gmail IMAP ─────────────────────────────────────────────────────────────────
IMAP_SERVER: str = os.getenv("IMAP_SERVER", "imap.gmail.com")
IMAP_PORT: int = int(os.getenv("IMAP_PORT", "993"))
IMAP_USER: str = os.getenv("IMAP_USER", "")
IMAP_PASSWORD: str = os.getenv("IMAP_PASSWORD", "")
PROCESSED_LABEL: str = "Procesado/Finanzas"
# Máximo de correos a leer por ejecución (evita OOM con inbox grande)
GMAIL_MAX_RESULTS: int = int(os.getenv("GMAIL_MAX_RESULTS", "500"))

# ── Reconciliación ─────────────────────────────────────────────────────────────
# Días de tolerancia para cruzar fecha Gmail vs cartola (cargos pueden debitarse al día siguiente)
RECONCILIATION_DATE_TOLERANCE_DAYS: int = int(
    os.getenv("RECONCILIATION_DATE_TOLERANCE_DAYS", "1")
)

# ── Localización ──────────────────────────────────────────────────────────────
TIMEZONE: str = "America/Santiago"

# ── Cartolas PDF ──────────────────────────────────────────────────────────────
# Contraseña para abrir cartolas PDF protegidas (los bancos chilenos suelen usar el RUT)
PDF_PASSWORD: str = os.getenv("PDF_PASSWORD", "")

# ── Logging ───────────────────────────────────────────────────────────────────
LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
LOG_FILE: str = os.getenv("LOG_FILE", "economicscript.log")
