# EconomicScript — Consolidación financiera personal

Sistema modular en Python para consolidar transacciones de **BCI**, **Banco Estado** y **Security**, cruzando notificaciones Gmail y cartolas bancarias.

## Características

- Ingesta Gmail IMAP (OAuth2) con lookback de N días (no solo UNSEEN)
- Parsers por banco, incluyendo **Anulación TC** (preauth Uber, etc.)
- Gasto de **consumo neto**: compras + anulaciones (negativas); sin transferencias ni pagos de tarjeta
- Categorización automática + dashboard Streamlit + email diario
- Backfill y reproceso sin duplicar (`gmail_message_id` / `content_hash`)

## Convención de signos

| Tipo | Signo | Gasto de consumo |
|------|-------|------------------|
| Compra TC / Compra TC FX | `amount > 0` | Sí |
| **Anulación TC** | `amount < 0` | Sí (netea preauth) |
| Transferencia*, Pago TC | `amount > 0` | **No** |

Ejemplo Uber: `+8000` + `+8190` + `-8000` → **neto $8.190**.

Anulaciones se categorizan en **Ajustes/Anulaciones** (no en Transporte).

## Estructura

- `architecture.md` — arquitectura y política de neteo
- `CLAUDE.md` — contexto operativo completo
- `parsers/` — BCI, BancoEstado, Security
- `gmail_ingest.py`, `run_daily.py`, `run_poll.py`, `backfill.py`
- `scripts/fix_anulaciones.py` — migración de voids históricos
- `tests/` — parsers, neteo, categorizer

## Ejecución rápida

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -c "from db import Database; Database().init_schema()"
pytest
streamlit run app.py
```

### Job diario / backfill julio 2026

```bash
# Resumen (parcial de hoy o --yesterday)
python run_daily.py

# Rellenar huecos desde 2026-07-01 (idempotente)
python backfill.py --since 2026-07-01

# Tras mejorar parsers
python reprocess_unprocessed.py
python scripts/fix_anulaciones.py
```

## Variables de entorno

Copiar `.env.example` → `.env`. Claves principales:

- OAuth IMAP: `IMAP_USER`, `OAUTH_*`
- `GMAIL_LOOKBACK_DAYS=7` (0 = solo UNSEEN)
- `INSTANT_ALERTS_ENABLED=false` — **sin email por cada TX**
- SMTP: `SMTP_TO`, `SMTP_PASSWORD` (App Password)

## Seguridad

- No se hardcodean credenciales ni RUT en código.
- RUT solo opcional en `PDF_PASSWORD` del `.env` para abrir cartolas.

## Checklist de aceptación (manual)

1. Correo “anulación nacional” BCI → `Anulación TC` con monto negativo (no unprocessed).
2. Secuencia 8000 → 8190 → anulación 8000 → gasto neto del día **$8.190**.
3. KPI Streamlit, gráficos y email diario comparten la misma lógica de consumo neto.
4. Transferencias y pagos TC **fuera** del gasto de consumo.
5. Tras `backfill.py --since 2026-07-01`, no hay tramos de días en $0 sin motivo real.
6. `pytest` en verde; poll no manda alerta por cada movimiento.
