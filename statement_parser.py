"""Parseo de cartolas PDF/CSV para bancos chilenos."""

from __future__ import annotations

import csv
import logging
from pathlib import Path

import pdfplumber

from models import TransactionRecord
from utils import normalize_clp_amount, parse_chilean_date

LOGGER = logging.getLogger(__name__)


class StatementParser:
    """Procesa cartolas en PDF o CSV y extrae transacciones normalizadas."""

    def parse_file(self, file_path: str) -> list[TransactionRecord]:
        """Despacha parsing según extensión del archivo."""

        path = Path(file_path)
        if path.suffix.lower() == ".csv":
            return self._parse_csv(path)
        if path.suffix.lower() == ".pdf":
            return self._parse_pdf(path)
        raise ValueError("Formato no soportado. Use PDF o CSV")

    def _parse_csv(self, path: Path) -> list[TransactionRecord]:
        bank = self._detect_bank(path.read_text(encoding="utf-8", errors="ignore"))
        transactions: list[TransactionRecord] = []

        with path.open("r", encoding="utf-8", errors="ignore") as file:
            reader = csv.DictReader(file)
            for row in reader:
                transactions.append(
                    TransactionRecord(
                        bank=bank,
                        date=parse_chilean_date(row.get("fecha", "")),
                        amount=normalize_clp_amount(row.get("monto", "0")),
                        type=row.get("tipo", "N/A"),
                        merchant=row.get("descripcion", "Sin descripción"),
                        source="cartola",
                        raw_text=str(row),
                        statement_ref=path.name,
                    )
                )
        return transactions

    def _parse_pdf(self, path: Path) -> list[TransactionRecord]:
        text_chunks: list[str] = []
        with pdfplumber.open(path) as pdf:
            for page in pdf.pages:
                text_chunks.append(page.extract_text() or "")
        all_text = "\n".join(text_chunks)
        bank = self._detect_bank(all_text)

        # Implementación base: parseo por líneas tipo fecha|descripción|monto
        transactions: list[TransactionRecord] = []
        for line in all_text.splitlines():
            parts = [segment.strip() for segment in line.split("|")]
            if len(parts) < 3:
                continue
            try:
                date = parse_chilean_date(parts[0])
                amount = normalize_clp_amount(parts[2])
            except ValueError:
                continue
            transactions.append(
                TransactionRecord(
                    bank=bank,
                    date=date,
                    amount=amount,
                    type="CARGO" if amount > 0 else "ABONO",
                    merchant=parts[1],
                    source="cartola",
                    raw_text=line,
                    statement_ref=path.name,
                )
            )
        LOGGER.info("Cartola %s parseada con %s transacciones", path.name, len(transactions))
        return transactions

    @staticmethod
    def _detect_bank(content: str) -> str:
        lowered = content.lower()
        if "banco de chile inversiones" in lowered or "bci" in lowered:
            return "BCI"
        if "bancoestado" in lowered or "banco estado" in lowered:
            return "BANCO_ESTADO"
        if "banco security" in lowered or "security" in lowered:
            return "SECURITY"
        raise ValueError("No fue posible detectar banco de la cartola")
