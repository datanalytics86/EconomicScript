"""Parseo de cartolas y EECC en PDF/CSV para bancos chilenos."""

from __future__ import annotations

import csv
import logging
import re
from pathlib import Path

import pdfplumber

import config
from models import TransactionRecord
from utils import compute_content_hash, normalize_clp_amount, parse_chilean_date

LOGGER = logging.getLogger(__name__)

_REQUIRED_CSV_COLUMNS = {"fecha", "monto", "tipo", "descripcion"}

# Patrones de detección de banco: orden importa (más específico primero).
# Se incluyen indicadores presentes en EECC que no siempre mencionan el nombre del banco
# directamente en el texto extraído por pdfplumber.
_BANK_PATTERNS: dict[str, tuple[str, ...]] = {
    # Security: nombre explícito del banco o sección de puntos "Security Pesos"
    "SECURITY": ("banco security", "security pesos", "www.security.cl"),
    # BCI: número de atención o nombre completo (no siempre aparece "bci" en EECC)
    "BCI": ("banco de crédito e inversiones", "bci", "800 201 090"),
    # BancoEstado: texto propio de sus estados de cuenta o nombre directo
    "BANCO_ESTADO": ("bancoestado", "banco estado", "recuerda:paga"),
}

# Descripciones de resumen en EECC que no son transacciones reales
_EECC_SUMMARY_PREFIXES = (
    "total ",
    "monto pagado",
    "monto facturado",
    "saldo adeudado",
    "período anterior",
    "periodo anterior",
    "descripci",       # encabezados de columna
    "fecha\noperaci",
    "lugar de",
)


def _is_eecc_summary(desc: str) -> bool:
    """Retorna True si la descripción es una fila de resumen/encabezado en un EECC."""
    lower = desc.lower().strip()
    return any(lower.startswith(kw) for kw in _EECC_SUMMARY_PREFIXES)


def _clean_merchant(raw: str) -> str:
    """Elimina 'TASA INT. X,XX%' y ciudades al final del nombre de comercio."""
    cleaned = re.sub(r"\s+TASA\s+INT\.\s*[\d,]+%\s*$", "", raw, flags=re.IGNORECASE).strip()
    return cleaned or raw


class StatementParser:
    """Procesa cartolas y EECC en PDF o CSV y extrae transacciones normalizadas."""

    def parse_file(self, file_path: str, password: str | None = None) -> list[TransactionRecord]:
        """Despacha parsing según extensión del archivo.

        Args:
            file_path: Ruta al archivo PDF o CSV.
            password: Contraseña para PDFs protegidos. None usa PDF_PASSWORD del .env.
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

    # ------------------------------------------------------------------
    # CSV
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # PDF: despachador principal
    # ------------------------------------------------------------------

    def _parse_pdf(self, path: Path, password: str | None = None) -> list[TransactionRecord]:
        effective_password = password or config.PDF_PASSWORD or None
        open_kwargs: dict = {"password": effective_password} if effective_password else {}

        with pdfplumber.open(path, **open_kwargs) as pdf:
            text_chunks = [page.extract_text() or "" for page in pdf.pages]
            all_text = "\n".join(text_chunks)
            bank = self._detect_bank(all_text)
            lower = all_text.lower()

            # EECC: "estado de cuenta" + "tarjeta de cr"
            if "estado de cuenta" in lower and "tarjeta de cr" in lower:
                return self._parse_eecc(pdf, bank, path.name)

            # Cartola BancoEstado: tabla con columna DESCRIPCIÓN
            if "estado de movimientos" in lower or "nº docto." in lower:
                return self._parse_cartola_table(pdf, bank, path.name)

            # Fallback: formato pipe-separado (fecha|descripción|monto)
            return self._parse_pipe_format(all_text, bank, path.name)

    # ------------------------------------------------------------------
    # PDF: EECC (Estado de Cuenta Tarjeta de Crédito) — BCI, BEstado, Security
    # ------------------------------------------------------------------
    # Los PDFs tienen tablas con columnas:
    #   [LUGAR, FECHA OPERACIÓN, CÓDIGO REF, DESCRIPCIÓN, MONTO OP, MONTO TOTAL, CUOTA, …]
    # pdfplumber agrupa múltiples filas en una celda con '\n' como separador.
    # Se itera cada columna dividiendo por '\n' y se hace zip de las listas resultantes.

    def _parse_eecc(self, pdf, bank: str, ref: str) -> list[TransactionRecord]:
        transactions: list[TransactionRecord] = []
        seen: set[str] = set()
        skipped = 0

        for page in pdf.pages:
            for table in page.extract_tables():
                if not table:
                    continue
                for row in table:
                    if not row or len(row) < 5:
                        continue
                    fecha_cell = str(row[1] or "").strip()
                    desc_cell = str(row[3] or "").strip()
                    monto_cell = str(row[4] or "").strip()

                    if not fecha_cell or not desc_cell or not monto_cell:
                        continue

                    dates = [d.strip() for d in fecha_cell.split("\n") if d.strip()]
                    # Filtra resúmenes antes de hacer zip para mantener alineación
                    descs = [
                        d.strip() for d in desc_cell.split("\n")
                        if d.strip() and not _is_eecc_summary(d.strip())
                    ]
                    montos = [m.strip() for m in monto_cell.split("\n") if m.strip()]

                    if len(descs) != len(dates):
                        LOGGER.debug(
                            "EECC %s: desalineación en tabla (fechas=%d, descs=%d) — se usará zip",
                            ref, len(dates), len(descs),
                        )

                    for date_raw, desc, monto_raw in zip(dates, descs, montos):
                        try:
                            date = parse_chilean_date(date_raw)
                            amount = normalize_clp_amount(monto_raw)
                            merchant = _clean_merchant(desc)
                            tx_type = "Abono TC" if amount < 0 else "Cargo TC"
                            tx = TransactionRecord(
                                bank=bank,
                                date=date,
                                amount=amount,
                                type=tx_type,
                                merchant=merchant,
                                source="cartola",
                                raw_text=f"{date_raw}|{desc}|{monto_raw}",
                                statement_ref=ref,
                            )
                            tx.content_hash = compute_content_hash(
                                tx.bank, tx.date.isoformat(), tx.amount, tx.merchant
                            )
                            if tx.content_hash not in seen:
                                seen.add(tx.content_hash)
                                transactions.append(tx)
                        except (ValueError, IndexError) as exc:
                            LOGGER.debug("EECC fila ignorada %r: %s", desc[:40], exc)
                            skipped += 1

        LOGGER.info("EECC %s: %s transacciones, %s ignoradas", ref, len(transactions), skipped)
        return transactions

    # ------------------------------------------------------------------
    # PDF: Cartola con tabla (BancoEstado cuenta corriente)
    # ------------------------------------------------------------------
    # Columnas esperadas: Nº DOCTO. | DESCRIPCIÓN | SUC | CARGOS O GIROS | ABONOS O DEPOSITOS | FECHA | SALDO

    def _parse_cartola_table(self, pdf, bank: str, ref: str) -> list[TransactionRecord]:
        transactions: list[TransactionRecord] = []
        seen: set[str] = set()
        skipped = 0

        for page in pdf.pages:
            for table in page.extract_tables():
                if not table:
                    continue
                # Localiza la fila de encabezado con DESCRIPCIÓN y FECHA
                header_idx = -1
                header = []
                for i, row in enumerate(table):
                    if not row:
                        continue
                    cells_upper = [str(c or "").strip().upper() for c in row]
                    if any("DESCRIPCI" in c for c in cells_upper) and any("FECHA" in c for c in cells_upper):
                        header = cells_upper
                        header_idx = i
                        break

                if header_idx < 0:
                    continue

                # Mapea índices de columnas relevantes
                try:
                    desc_i = next(i for i, h in enumerate(header) if "DESCRIPCI" in h)
                    fecha_i = next(i for i, h in enumerate(header) if "FECHA" in h)
                    cargo_i = next(
                        (i for i, h in enumerate(header) if "CARGO" in h or "GIRO" in h), None
                    )
                    abono_i = next(
                        (i for i, h in enumerate(header) if "ABONO" in h or "DEPOSITO" in h), None
                    )
                except StopIteration:
                    continue

                for row in table[header_idx + 1:]:
                    if not row:
                        continue
                    cells = [str(c or "").strip() for c in row]
                    if len(cells) <= fecha_i:
                        continue

                    desc = cells[desc_i] if desc_i < len(cells) else ""
                    fecha_raw = cells[fecha_i] if fecha_i < len(cells) else ""
                    cargo_raw = cells[cargo_i] if cargo_i is not None and cargo_i < len(cells) else ""
                    abono_raw = cells[abono_i] if abono_i is not None and abono_i < len(cells) else ""

                    if not desc or not fecha_raw:
                        continue
                    # Omite filas de resumen
                    if any(kw in desc.upper() for kw in ("RESUMEN", "NUEVO SALDO", "INFÓRMESE")):
                        continue

                    try:
                        date = parse_chilean_date(fecha_raw)
                        if cargo_raw:
                            amount = normalize_clp_amount(cargo_raw)
                            tx_type = "Cargo"
                        elif abono_raw:
                            # Abonos son ingresos: se guardan como negativos
                            amount = -normalize_clp_amount(abono_raw)
                            tx_type = "Abono"
                        else:
                            continue

                        tx = TransactionRecord(
                            bank=bank,
                            date=date,
                            amount=amount,
                            type=tx_type,
                            merchant=desc,
                            source="cartola",
                            raw_text="|".join(cells),
                            statement_ref=ref,
                        )
                        tx.content_hash = compute_content_hash(
                            tx.bank, tx.date.isoformat(), tx.amount, tx.merchant
                        )
                        if tx.content_hash not in seen:
                            seen.add(tx.content_hash)
                            transactions.append(tx)
                    except (ValueError, IndexError) as exc:
                        LOGGER.debug("Cartola fila ignorada %r: %s", desc[:40], exc)
                        skipped += 1

        LOGGER.info("Cartola %s: %s transacciones, %s ignoradas", ref, len(transactions), skipped)
        return transactions

    # ------------------------------------------------------------------
    # PDF: formato pipe-separado (fallback genérico)
    # ------------------------------------------------------------------

    def _parse_pipe_format(self, all_text: str, bank: str, ref: str) -> list[TransactionRecord]:
        transactions: list[TransactionRecord] = []
        skipped = 0
        for line in all_text.splitlines():
            parts = [s.strip() for s in line.split("|")]
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
                    statement_ref=ref,
                )
                tx.content_hash = compute_content_hash(
                    tx.bank, tx.date.isoformat(), tx.amount, tx.merchant
                )
                transactions.append(tx)
            except (ValueError, IndexError) as exc:
                LOGGER.debug("Pipe-format línea ignorada %r: %s", line[:60], exc)
                skipped += 1

        LOGGER.info("PDF pipe %s: %s transacciones, %s ignoradas", ref, len(transactions), skipped)
        return transactions

    # ------------------------------------------------------------------
    # Utilidades
    # ------------------------------------------------------------------

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
