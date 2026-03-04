"""Script de diagnóstico: muestra el body extraído de correos que fallan al parsear.

Uso:
    python dump_failing.py

Conecta a Gmail, busca los correos de los dominios bancarios en INBOX (no leídos)
y muestra el body text de los primeros 2 de cada banco para que puedas ver
qué formato tiene el correo real y ajustar los patrones del parser.
"""

from __future__ import annotations

import email
import html as _html_stdlib
import imaplib
import re
import textwrap

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

import config

BANK_DOMAINS = ["@bci.cl", "@bancoestado.cl", "@security.cl"]
SAMPLE_PER_DOMAIN = 3  # cuántos correos mostrar por dominio


def html_to_text(html_body: str) -> str:
    text = re.sub(r"<(?:br\s*/?|/p|/div|/tr|/li|/h[1-6])[^>]*>", "\n", html_body, flags=re.IGNORECASE)
    text = re.sub(r"<t[dh][^>]*>", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    text = _html_stdlib.unescape(text)
    lines = [" ".join(line.split()) for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


def extract_body(msg: email.message.Message) -> str:
    plain: list[str] = []
    html_parts: list[str] = []
    if msg.is_multipart():
        for part in msg.walk():
            ct = part.get_content_type()
            payload = part.get_payload(decode=True)
            if not payload:
                continue
            text = payload.decode("utf-8", errors="ignore")
            if ct == "text/plain":
                plain.append(text)
            elif ct == "text/html":
                html_parts.append(text)
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            text = payload.decode("utf-8", errors="ignore")
            if msg.get_content_type() == "text/plain":
                plain.append(text)
            else:
                html_parts.append(text)
    if plain:
        return plain[0]
    if html_parts:
        return html_to_text(html_parts[0])
    return ""


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

        # Tomar los últimos N (más recientes)
        sample = uids[-SAMPLE_PER_DOMAIN:]
        for uid in sample:
            _, msg_data = mail.uid("fetch", uid, "(RFC822)")
            raw = msg_data[0][1]
            msg = email.message_from_bytes(raw)
            sender = msg.get("From", "")
            subject = msg.get("Subject", "")
            body = extract_body(msg)
            print(f"\n--- UID {uid.decode()} ---")
            print(f"From   : {sender}")
            print(f"Subject: {subject}")
            print(f"Body ({len(body)} chars):")
            # Mostrar primeros 120 chars de cada línea, hasta 60 líneas
            lines = body.splitlines()[:60]
            for line in lines:
                print(" ", textwrap.shorten(line, width=120, placeholder="…"))
            if len(body.splitlines()) > 60:
                print("  ... (truncado)")
        print()

    mail.logout()


if __name__ == "__main__":
    main()
