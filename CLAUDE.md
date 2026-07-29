# EconomicScript — Contexto para Claude Code

> Lee este archivo primero en cada sesión nueva para retomar desde el último punto.

---

## ¿Qué es este proyecto?

Sistema personal de consolidación financiera para bancos chilenos. Extrae transacciones de correos de notificación bancaria (Gmail vía IMAP OAuth2), las almacena en SQLite, las reconcilia con cartolas PDF/CSV, las categoriza automáticamente y genera reportes diarios por email. Hay además un dashboard Streamlit.

**Bancos soportados:** BCI (`@bci.cl`), Banco Estado (`@bancoestado.cl`), Security (`@security.cl`)

---

## Convención de signos y gasto de consumo neto

| `type` | `amount` | Entra al gasto de consumo |
|---|---|---|
| `Compra TC` / `Compra TC FX` | **> 0** | Sí |
| `Anulación TC` / `Reverso TC` | **< 0** | Sí (netea el provisorio) |
| `Transferencia*` | > 0 | **No** |
| `Pago TC` / `Pago Producto` | > 0 | **No** |

**Flujo Uber / preauth:**

1. Preautorización `+8000` (`Compra TC`)
2. Cargo final `+8190` (`Compra TC`)
3. Anulación del provisorio `-8000` (`Anulación TC`)
4. **Neto = 8190** (sumar amounts de tipos de consumo)

API compartida:

- `utils.is_consumption_type` / `is_real_expense` / `CONSUMPTION_SQL_FILTER`
- `app._filter_real_expenses` (KPIs, charts, vista por categoría)
- `report_utils.fetch_transactions_grouped(expenses_only=True)` (email diario)

**No filtrar `amount > 0`** en gasto real: las anulaciones negativas deben entrar.

Categoría de voids: **`Ajustes/Anulaciones`** (no “Transporte” por keyword UBER).  
No se aprenden reglas de merchant desde anulaciones.

---

## Estructura

```
parsers/           # BCI, BancoEstado, Security (+ Anulación TC)
gmail_ingest.py    # IMAP OAuth2; UNSEEN o SINCE (lookback)
statement_parser.py
reconciler.py
categorizer.py     # merchant + type-first para Anulación TC
daily_report.py    # email HTML (día + ciclo + últimos 10 días)
run_daily.py       # lookback GMAIL_LOOKBACK_DAYS (default 7)
run_poll.py        # poll; INSTANT_ALERTS_ENABLED=false por defecto
backfill.py        # re-ingesta segura por rango (dedup gmail_message_id)
reprocess_unprocessed.py
scripts/fix_anulaciones.py  # corrige voids históricos mal tipados
utils.py           # signos, is_real_expense, get_cycle_start_date
app.py             # Streamlit
```

---

## Base de datos (`finance.db`)

| Tabla | Propósito |
|---|---|
| `transactions` | Unique en `gmail_message_id` y `content_hash` (dedupe) |
| `categories` / `category_rules` | Categorización |
| `reconciliation_log` | Match gmail vs cartola |
| `unprocessed_emails` | Fallos de parseo / sin parser |

---

## Flujo diario

```
run_daily.py
  1. ingest(since_date=hoy-LOOKBACK)  # no solo UNSEEN
  2. auto_categorize
  3. reconcile
  4. send_daily_report (hoy parcial o ayer)
```

**Huecos de días en $0:** suelen deberse a (a) solo UNSEEN + mails leídos en el móvil,  
(b) PC/scheduler apagado > lookback, (c) parsers que fallaban. Mitigación:

```bash
# Backfill seguro 2026-07-01 → hoy (no duplica por gmail_message_id)
python backfill.py --since 2026-07-01

# Reparsear unprocessed tras mejorar parsers
python reprocess_unprocessed.py --dry-run
python reprocess_unprocessed.py

# Corregir anulaciones ya guardadas como Compra TC positiva
python scripts/fix_anulaciones.py --dry-run
python scripts/fix_anulaciones.py
```

---

## Alertas

- **No** se envía un email por cada transacción por defecto.
- `INSTANT_ALERTS_ENABLED=false` en `.env` (recomendado).
- Si se activa, el poll excluye `Anulación TC`, transferencias y pagos TC.

---

## Tests

```bash
pytest
# Criterio: verde; incluye secuencia Uber neto=8190 y Anulación TC negativa
```

---

## Seguridad

- No hardcodear RUT ni secretos; solo `.env` / OAuth.
- No reescribir dedupe existente.
