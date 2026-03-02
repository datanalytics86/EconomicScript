# EconomicScript - Consolidación financiera personal

Proyecto modular en Python para consolidar transacciones de BCI, Banco Estado y Security, cruzando notificaciones Gmail y cartolas bancarias.

## Estructura
- `architecture.md`: diagrama textual de arquitectura.
- `sql/schema.sql`: script de schema SQLite.
- `gmail_ingest.py`: ingesta Gmail API y extracción de transacciones.
- `parsers/`: clase base e implementaciones por banco.
- `statement_parser.py`: parseo de cartolas PDF/CSV.
- `reconciler.py`: motor de reconciliación Gmail vs cartola.
- `app.py`: dashboard Streamlit.
- `tests/test_parsers.py`: tests unitarios de parsing.

## Ejecución rápida
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -c "from db import Database; Database().init_schema()"
pytest
streamlit run app.py
```

## Variables de entorno
Crear `.env` con:
```env
GOOGLE_CREDENTIALS_PATH=credentials.json
GOOGLE_TOKEN_PATH=token.json
```

## Seguridad
- No se hardcodean credenciales.
- RUT no se persiste en schema ni parsers.
