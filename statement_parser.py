"""Parseo de cartolas PDF/CSV para bancos chilenos."""

from __future__ import annotations

import csv
import logging
from pathlib import Path

import pdfplumber

import config
from models import TransactionRecord
from utils import compute_content_hash, normalize_clp_amount, parse_chilean_date

LOGGER = logging.getLogger(__name__)

_REQUIRED_CSV_COLUMNS = {"fecha", "monto", "tipo", "descripcion"}

# Patrones de detección más precisos: orden importa (más específico primero)
_BANK_PATTERNS: dict[str, tuple[str, ...]] = {
    "BCI": ("banco de crédito e inversiones", "bci"),
    "BANCO_ESTADO": ("bancoestado", "banco estado"),
    "SECURITY": ("banco security",),
}


class StatementParser:
    """Procesa cartolas en PDF o CSV y extrae transacciones normalizadas."""

    def parse_file(self, file_path: str, password: str | None = None) -> list[TransactionRecord]:
        """Despacha parsing según extensión del archivo.

        Args:
            file_path: Ruta al archivo PDF o CSV.
            password: Contraseña para PDFs protegidos. Si es None usa PDF_PASSWORD del .env.
        """
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"Archivo no encontrado: {file_path}")
        if path.stat().st_size == 0:
            LOGGER.warning("Archivo vacío, se omite: %s", path.name)
            return []
        if path.suffix.lower() == ".csv":
            return self._parse_csv(path)
        if path.suffix.lower() == ".pdf":
            return self._parse_pdf(path, password=password)
        raise ValueError(f"Formato no soportado: {path.suffix!r}. Use PDF o CSV")

    def _parse_csv(self, path: Path) -> list[TransactionRecord]:
        raw = path.read_text(encoding="utf-8", errors="ignore")
        bank = self._detect_bank(raw)
        transactions: list[TransactionRecord] = []
        skipped = 0

        with path.open("r", encoding="utf-8", errors="ignore") as file:
            reader = csv.DictReader(file)
            if reader.fieldnames:
                actual_cols = {c.lower().strip() for c in reader.fieldnames}
                missing = _REQUIRED_CSV_COLUMNS - actual_cols
                if missing:
                    raise ValueError(
                        f"Columnas requeridas no encontradas en {path.name}: {missing}. "
                        f"Presentes: {actual_cols}"
                    )
            for i, row in enumerate(reader, start=2):
                try:
                    merchant = (row.get("descripcion") or "Sin descripción").strip()
                    tx = TransactionRecord(
                        bank=bank,
                        date=parse_chilean_date(row["fecha"]),
                        amount=normalize_clp_amount(row["monto"]),
                        type=row.get("tipo", "N/A"),
                        merchant=merchant,
                        source="cartola",
                        raw_text=str(row),
                        statement_ref=path.name,
                    )
                    tx.content_hash = compute_content_hash(
                        tx.bank, tx.date.isoformat(), tx.amount, tx.merchant
                    )
                    transactions.append(tx)
                except (ValueError, KeyError) as exc:
                    LOGGER.warning("Fila %s ignorada en %s: %s", i, path.name, exc)
                    skipped += 1

        LOGGER.info(
            "CSV %s: %s transacciones extraídas, %s filas ignoradas",
            path.name, len(transactions), skipped,
        )
        return transactions

    def _parse_pdf(self, path: Path, password: str | None = None) -> list[TransactionRecord]:
        effective_password = password or config.PDF_PASSWORD or None
        open_kwargs: dict = {"password": effective_password} if effective_password else {}
        text_chunks: list[str] = []
        with pdfplumber.open(path, **open_kwargs) as pdf:
            for page in pdf.pages:
                text_chunks.append(page.extract_text() or "")
        all_text = "\n".join(text_chunks)
        bank = self._detect_bank(all_text)

        # Formato base: líneas separadas por | → fecha|descripción|monto
        transactions: list[TransactionRecord] = []
        skipped = 0
        for line in all_text.splitlines():
            parts = [segment.strip() for segment in line.split("|")]
            if len(parts) < 3:
                continue
            try:
                date = parse_chilean_date(parts[0])
                amount = normalize_clp_amount(parts[2])
                merchant = parts[1] or "Sin descripción"
                tx = TransactionRecord(
                    bank=bank,
                    date=date,
                    amount=amount,
                    type="CARGO" if amount > 0 else "ABONO",
                    merchant=merchant,
                    source="cartola",
                    raw_text=line,
                    statement_ref=path.name,
                )
                tx.content_hash = compute_content_hash(
                    tx.bank, tx.date.isoformat(), tx.amount, tx.merchant
                )
                transactions.append(tx)
            except (ValueError, IndexError) as exc:
                LOGGER.debug("Línea ignorada en PDF %s: %r — %s", path.name, line[:60], exc)
                skipped += 1

        LOGGER.info(
            "PDF %s: %s transacciones extraídas, %s líneas ignoradas",
            path.name, len(transactions), skipped,
        )
        return transactions

    @staticmethod
    def _detect_bank(content: str) -> str:
        lowered = content.lower()
        for bank_code, patterns in _BANK_PATTERNS.items():
            if any(p in lowered for p in patterns):
                return bank_code
        raise ValueError(
            "No fue posible detectar el banco. "
            "Verifique que el documento contenga el nombre del banco (BCI, BancoEstado o Security)."
        )
