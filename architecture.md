# Diagrama de arquitectura (texto)

```text
┌──────────────────────┐
│      Usuario         │
│ (CLI / Streamlit UI) │
└──────────┬───────────┘
           │
           ▼
┌────────────────────────────┐
│       app.py (Streamlit)   │
│ - KPIs y visualizaciones   │
│ - Categorización manual    │
│ - Vista reconciliación     │
└──────────┬─────────────────┘
           │ consultas/updates
           ▼
┌────────────────────────────┐
│      SQLite (finance.db)   │
│ transactions               │
│ categories                 │
│ category_rules             │
│ reconciliation_log         │
│ unprocessed_emails         │
└───────┬───────────┬────────┘
        │           │
        │           └───────────────────────────┐
        │                                       │
        ▼                                       ▼
┌────────────────────┐                ┌───────────────────────┐
│ gmail_ingest.py    │                │ statement_parser.py    │
│ - Gmail API        │                │ - PDF/CSV ingest       │
│ - Filtro remitente │                │ - Detección de banco   │
│ - Label procesado  │                │ - Normalización CLP    │
│ - Parser por banco │                └──────────┬────────────┘
│ - Deduplicación    │                           │
└─────────┬──────────┘                           │
          │                                      │
          ▼                                      ▼
┌─────────────────────────┐            ┌─────────────────────────┐
│ parsers/base.py         │            │ reconciler.py           │
│ parsers/bci.py          │            │ - Match banco+fecha±1   │
│ parsers/banco_estado.py │            │ - monto exacto          │
│ parsers/security.py     │            │ - estados de cruce      │
└─────────────────────────┘            └─────────────────────────┘

Flujo principal:
1) `gmail_ingest.py` lee correos de bancos y extrae transacciones (source=gmail).
2) `statement_parser.py` procesa cartolas PDF/CSV (source=cartola).
3) `categorizer.py` aplica reglas automáticas y registra reglas nuevas tras categorización manual.
4) `reconciler.py` cruza movimientos y registra resultado en `reconciliation_log`.
5) `app.py` / `daily_report.py` consumen SQLite para KPIs, gráficos y email.
```

## Gasto de consumo neto (preautorizaciones / anulaciones TC)

Comercios como Uber, estacionamientos y hoteles emiten:

1. **Preautorización** (cargo provisorio) → `Compra TC` amount > 0  
2. **Cargo final** real → `Compra TC` amount > 0  
3. **Anulación** del provisorio → `Anulación TC` amount < 0  

Parsers (BCI prioritario; BE y Security defensivos) detectan “anulación nacional”,
“reverso”, etc. y guardan `type="Anulación TC"` con monto **negativo**.

Totales de gasto real (`utils.is_consumption_type` / `CONSUMPTION_SQL_FILTER`):

- **Incluyen** Compra TC, Compra TC FX, Anulación TC (suman amount).  
- **Excluyen** Transferencia*, Pago TC, Pago Producto.  
- Resultado: provisorio + anulación se cancelan; queda solo el cargo final.

Migración one-shot de filas históricas mal parseadas:

```text
python scripts/fix_anulaciones.py --dry-run
python scripts/fix_anulaciones.py
```

## Ingesta incompleta / huecos de días

- Diario: `GMAIL_LOOKBACK_DAYS` (default 7) usa IMAP SINCE + dedup por
  `gmail_message_id` (no solo UNSEEN).  
- Histórico: `python backfill.py --since YYYY-MM-DD`.  
- Errores de parseo: tabla `unprocessed_emails` + `reprocess_unprocessed.py`.

