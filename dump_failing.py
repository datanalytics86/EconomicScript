"""Script de diagnóstico: muestra el body real que reciben los parsers.

Usa EXACTAMENTE el mismo extract_body que gmail_ingest.py (strips <style>,
html.unescape en plain text) y muestra el body COMPLETO sin truncar.
También corre el parser correspondiente y muestra si pasa o falla.

Uso:
    python dump_failing.py
"""

from __future__ import annotations

import email
import email.header
import imaplib

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

import config
from gmail_ingest import GmailIngestor
from parsers import BCIParser, BancoEstadoParser, SecurityParser

BANK_DOMAINS = ["@bci.cl", "@bancoestado.cl", "@security.cl"]
SAMPLE_PER_DOMAIN = 3

PARSERS = [BCIParser(), BancoEstadoParser(), SecurityParser()]


def main() -> None:
    creds = Credentials(
        token=None,
        refresh_token=config.OAUTH_REFRESH_TOKEN,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=config.OAUTH_CLIENT_ID,
        client_secret=config.OAUTH_CLIENT_SECRET,
        scopes=["https://mail.google.com/"],
    )
    creds.refresh(Request())
    auth_string = f"user={config.IMAP_USER}\x01auth=Bearer {creds.token}\x01\x01"
    mail = imaplib.IMAP4_SSL(config.IMAP_SERVER, config.IMAP_PORT)
    mail.authenticate("XOAUTH2", lambda _: auth_string.encode())
    print("Conexión OAuth2 OK\n")

    mail.select("INBOX", readonly=True)

    for domain in BANK_DOMAINS:
        criteria = f'(FROM "{domain}")'
        _, data = mail.uid("search", None, criteria)
        uids = data[0].split() if data[0] else []
        print(f"{'='*70}")
        print(f"DOMINIO: {domain}  →  {len(uids)} correos en INBOX")
        print(f"{'='*70}")
        if not uids:
            print("  (sin correos)\n")
            continue

        sample = uids[-SAMPLE_PER_DOMAIN:]
        for uid in sample:
            _, msg_data = mail.uid("fetch", uid, "(RFC822)")
            raw = msg_data[0][1]
            msg = email.message_from_bytes(raw)
            sender = msg.get("From", "")
            subject = str(
                email.header.make_header(
                    email.header.decode_header(msg.get("Subject", ""))
                )
            )
            # Mismo extract_body que gmail_ingest.py
            body = GmailIngestor._extract_body(msg)

            print(f"\n--- UID {uid.decode()} ---")
            print(f"From   : {sender}")
            print(f"Subject: {subject}")
            print(f"Body ({len(body)} chars):")
            print("<<<")
            print(body)
            print(">>>")

            # Intentar parsear
            parser = next(
                (p for p in PARSERS if p.can_parse(sender=sender, subject=subject, body=body)),
                None,
            )
            if not parser:
                print("  [RESULTADO] Sin parser compatible (can_parse=False para todos)")
            else:
                try:
                    tx = parser.parse(body=body, gmail_message_id=uid.decode())
                    print(f"  [OK] {parser.bank_name}: {tx.type} | {tx.date} | ${tx.amount:,.0f} | {tx.merchant}")
                except Exception as exc:
                    print(f"  [FALLA] {parser.bank_name}.parse() → {exc}")
        print()

    mail.logout()


if __name__ == "__main__":
    main()
