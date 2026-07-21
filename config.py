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

# ── Dashboard (deep-link en el email de pendientes) ────────────────────────────
# URL pública o local del Streamlit, ej: http://localhost:8501
DASHBOARD_URL: str = os.getenv("DASHBOARD_URL", "")

# ── Logging ───────────────────────────────────────────────────────────────────
LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
LOG_FILE: str = os.getenv("LOG_FILE", str(_BASE_DIR / "economicscript.log"))


def _is_placeholder(value: str) -> bool:
    """True si el valor está vacío o es un placeholder del .env.example."""
    v = (value or "").strip().lower()
    if not v:
        return True
    # Placeholders explícitos del template
    if v.startswith("tu_") or v.startswith("your_"):
        return True
    if "tu_client_id" in v or v in {
        "tu_client_secret",
        "tu_refresh_token",
        "changeme",
        "xxx",
        "replace_me",
    }:
        return True
    if v.endswith("@example.com") or "example.apps.googleusercontent.com" in v:
        return True
    return False


def missing_runtime_config(*, need_smtp: bool = False) -> list[str]:
    """Lista de variables de entorno faltantes o aún con placeholder.

    Args:
        need_smtp: Si True, exige SMTP_PASSWORD (envío de reportes/alertas).
    """
    missing: list[str] = []
    if _is_placeholder(IMAP_USER):
        missing.append("IMAP_USER")
    if _is_placeholder(OAUTH_CLIENT_ID):
        missing.append("OAUTH_CLIENT_ID")
    if _is_placeholder(OAUTH_CLIENT_SECRET):
        missing.append("OAUTH_CLIENT_SECRET")
    if _is_placeholder(OAUTH_REFRESH_TOKEN):
        missing.append("OAUTH_REFRESH_TOKEN")
    if need_smtp and _is_placeholder(SMTP_PASSWORD):
        missing.append("SMTP_PASSWORD")
    # El reporte exige SMTP_TO explícito (no cae a IMAP_USER como destinatario)
    if need_smtp and _is_placeholder(SMTP_TO):
        missing.append("SMTP_TO")
    return missing
