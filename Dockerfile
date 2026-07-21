FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Inicializar esquema en la imagen (seguro: usa CREATE TABLE IF NOT EXISTS)
RUN python -c "from db import Database; Database('finance.db').init_schema('sql/schema.sql')" \
    2>/dev/null || true

EXPOSE 8501

# slim no trae curl; healthcheck con urllib de stdlib
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8501/_stcore/health')" || exit 1

CMD ["streamlit", "run", "app.py", \
     "--server.port=8501", \
     "--server.address=0.0.0.0", \
     "--server.headless=true"]
