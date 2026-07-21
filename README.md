# EconomicScript — Consolidación financiera personal

Python modular para consolidar gastos de **BCI**, **BancoEstado** y **Security** (Gmail + cartolas), con gasto real de consumo, categorización que aprende y reportes por email.

## Qué hace
- Ingesta notificaciones Gmail (OAuth2 IMAP)
- Parsea cartolas/EECC PDF-CSV
- Reconcilia gmail vs cartola (evita doble conteo)
- Auto-categoriza y aprende reglas por comercio
- Dashboard Streamlit + reportes diarios (local y/o GitHub Actions)

## Estructura principal
| Ruta | Rol |
|------|-----|
| `app.py` | Dashboard Streamlit |
| `run_poll.py` | Poll Gmail + alerta (cada 10 min) |
| `run_daily.py` | Ingesta + reporte diario local |
| `run_cloud.py` | Alertas en GitHub Actions (7/14/21 Chile) |
| `gmail_ingest.py` / `parsers/` | Extracción de transacciones |
| `categorizer.py` | Categorías y reglas |
| `daily_report.py` / `report_utils.py` | Email HTML (gasto real + pendientes) |
| `auth_setup.py` | Genera OAUTH_* una sola vez |
| `setup_scheduler.ps1` | Tareas Windows |
| `check_db.py`, `diagnose_failures.py`, `dump_failing.py`, `debug_imap.py` | Diagnóstico manual |
| `backfill.py` | Re-ingesta histórica Gmail |

## Setup rápido
```powershell
cd C:\Users\nicolas.andrade\EconomicScript
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# 1) Copia y rellena credenciales (ver .env.example)
copy .env.example .env
# 2) credentials.json desde Google Cloud (OAuth desktop)
# 3) python auth_setup.py  → pega OAUTH_* en .env
# 4) App Password de Gmail → SMTP_PASSWORD

python -c "from db import Database; import config; Database(config.DB_PATH).init_schema(config.SCHEMA_PATH)"
pytest
streamlit run app.py
```

## Operación continua
| Canal | Cómo |
|-------|------|
| **Nube** | Actions → `Scheduled Alerts` (secrets en GitHub) |
| **Local** | `setup_scheduler.ps1` → Poll / Daily 07:00 / Evening 20:00 |
| **UI** | `streamlit run app.py` → http://localhost:8501 |

Deep-link categorización: `http://localhost:8501?view=categorizar`

## Seguridad
- No hardcodear secretos; `.env` y `credentials.json` están en `.gitignore`
- RUT no se persiste en schema ni parsers
