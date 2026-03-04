# EconomicScript — Contexto para Claude Code

> Lee este archivo primero en cada sesión nueva para retomar desde el último punto.

---

## ¿Qué es este proyecto?

Sistema personal de consolidación financiera para bancos chilenos. Extrae transacciones de correos de notificación bancaria (Gmail vía IMAP OAuth2), las almacena en SQLite, las reconcilia con cartolas PDF/CSV, las categoriza automáticamente y genera reportes diarios por email. Hay además un dashboard Streamlit.

**Bancos soportados:** BCI (`@bci.cl`), Banco Estado (`@bancoestado.cl`), Security (`@security.cl`)

---

## Estructura

```
parsers/
  base.py          # Clase abstracta BankParser
  bci.py           # Parser BCI: compra TC (3 layouts) + transferencias
  banco_estado.py  # Parser BancoEstado: compra TC, transferencias, pago producto
  security.py      # Parser Security: compra TC, transferencias entrante/saliente
gmail_ingest.py    # Conexión IMAP OAuth2, fetching y parseo de correos
statement_parser.py# Parseo de PDF/CSV (EECC tarjeta crédito + cartola cuenta corriente)
reconciler.py      # Matching gmail vs cartola (tolerancia ±1 día, mismo monto exacto)
categorizer.py     # Categorización automática por reglas LIKE + aprendizaje
daily_report.py    # Reporte HTML por email con KPIs del día y ciclo-a-la-fecha
run_daily.py       # Orquestador diario: ingest → categorizar → enviar reporte
app.py             # Dashboard Streamlit
db.py              # Capa SQLite3
models.py          # TransactionRecord (dataclass)
config.py          # Variables de entorno centralizadas
utils.py           # normalize_clp_amount, parse_chilean_date, get_cycle_start_date
dump_failing.py    # Script diagnóstico: muestra body real + resultado del parser
tests/
  test_parsers.py  # 40+ tests unitarios de parsers y utils
  conftest.py
samples/dropzone/  # PDFs de muestra sin password para tests
sql/schema.sql     # Esquema: transactions, categories, category_rules, reconciliation_log, unprocessed_emails
logs/              # Logs diarios daily_YYYY-MM-DD.log
```

---

## Base de datos (SQLite — `finance.db`)

| Tabla | Propósito |
|---|---|
| `transactions` | Transacciones (gmail + cartola). Unique en `gmail_message_id` y `content_hash` |
| `categories` | Categorías de gasto |
| `category_rules` | Patrones LIKE → categoría (auto-aprendizaje) |
| `reconciliation_log` | Log de matching gmail vs cartola |
| `unprocessed_emails` | Correos que ningún parser pudo procesar (para revisión manual) |

---

## Flujo diario (automático, 06:55 AM vía Task Scheduler Windows)

```
run_daily.py
  1. GmailIngestor.ingest()          → correos UNSEEN de los 3 bancos
  2. auto_categorize(conn)           → aplica reglas de category_rules
  3. send_daily_report(ayer)         → email HTML con transacciones y ciclo-a-la-fecha
```

---

## Estado actual del proyecto (actualizado 2026-03-04)

### ✅ Funcionando correctamente
- Parseo de correos BCI, Banco Estado y Security (incluyendo 3 layouts distintos de BCI)
- OAuth2 XOAUTH2 para IMAP Gmail
- Ingesta histórica (`ingest(since_date=...)`) y diaria (`ingest()` sin fecha)
- Parseo de PDF: cartola cuenta corriente BancoEstado + EECC tarjeta crédito (BCI, Security, BancoEstado)
- Reconciliación gmail vs cartola
- Categorización automática con aprendizaje
- Reporte diario HTML por email
- Dashboard Streamlit
- 40+ tests unitarios pasando
- `dump_failing.py`: herramienta de diagnóstico para revisar correos reales y resultado del parser

### ⚠️ Casos sin parser (esperados, NO son bugs)
- Correos de marketing/invitaciones bancarias (ej: charlas BCI)
- Cartolas adjuntas como PDF encriptado (el body de texto plano no contiene datos parseables)

### 🔧 Fixes recientes (últimos commits)
| Commit | Descripción |
|---|---|
| `e6f6f0c` | Mejora dump_failing.py: misma extracción de body que gmail_ingest + muestra resultado |
| `df1e184` | Fix: subject headers RFC 2047 encoded en correos BCI no se decodificaban |
| `9c0a15b` | Fix: stripping de CSS, HTML entities, soporte nuevos formatos de correo |
| `0a11272` | Agrega dump_failing.py como herramienta de diagnóstico |

---

## Comandos útiles para retomar

```powershell
# Directorio del proyecto
cd "C:\Users\T14 Gen 2\Documents\Proyectos_Trading\EconomicScript"

# Ver correos reales y resultado de parsers (diagnóstico)
python dump_failing.py

# Correr tests
pytest tests/ -v

# Ingesta manual de correos
python -c "from gmail_ingest import GmailIngestor; print(GmailIngestor().ingest())"

# Ingesta histórica desde una fecha
python -c "from datetime import date; from gmail_ingest import GmailIngestor; print(GmailIngestor().ingest(since_date=date(2026,1,1)))"

# Dashboard
streamlit run app.py

# Reporte diario manual
python run_daily.py
```

---

## Variables de entorno necesarias (`.env` o entorno del sistema)

```
IMAP_USER            # email Gmail
OAUTH_CLIENT_ID
OAUTH_CLIENT_SECRET
OAUTH_REFRESH_TOKEN
SMTP_TO              # destinatario del reporte diario
SMTP_PASSWORD        # App Password de Gmail
PDF_PASSWORD         # contraseña para cartolas PDF protegidas (si aplica)
DB_PATH              # por defecto: finance.db
```

---

## Rama de desarrollo activa

```
claude/code-review-production-eWODj
```

Siempre desarrollar en esa rama y hacer push con:
```bash
git push -u origin claude/code-review-production-eWODj
```

---

## Posibles mejoras futuras (no urgentes)

1. Agregar parser para correos de **Banco Santander** o **Scotiabank** si el usuario los usa
2. Soporte para cartolas PDF con contraseña por archivo (hoy es una sola variable global)
3. Filtrar automáticamente correos de marketing antes de intentar parsear (ahorrar entradas en `unprocessed_emails`)
4. Exportación a Google Sheets o Excel para revisión externa
5. Tests de integración con la base de datos real (hoy los tests son solo unitarios)
