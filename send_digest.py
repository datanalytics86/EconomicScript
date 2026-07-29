#!/usr/bin/env python3
"""Envía un digest único de gasto (por defecto: 1 ene del año actual → hoy).

Uso:
    python send_digest.py
    python send_digest.py --since 2026-01-01
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, datetime

from daily_report import send_digest_report

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s — %(message)s")


def main() -> None:
    p = argparse.ArgumentParser(description="Digest histórico EconomicScript (una sola vez)")
    p.add_argument(
        "--since",
        type=str,
        default=None,
        help="Fecha inicio ISO (default: 1 ene del año actual)",
    )
    p.add_argument(
        "--until",
        type=str,
        default=None,
        help="Fecha fin ISO (default: hoy)",
    )
    args = p.parse_args()
    until = (
        datetime.strptime(args.until, "%Y-%m-%d").date() if args.until else date.today()
    )
    since = (
        datetime.strptime(args.since, "%Y-%m-%d").date()
        if args.since
        else date(until.year, 1, 1)
    )
    print(f"Enviando digest {since} → {until} …")
    send_digest_report(since=since, until=until)
    print("Listo.")


if __name__ == "__main__":
    main()
    sys.exit(0)
