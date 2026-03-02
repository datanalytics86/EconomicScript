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
5) `app.py` consume SQLite para KPIs, gráficos y tareas manuales.
```
