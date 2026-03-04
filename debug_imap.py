import imaplib
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
import config

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
print("Conexión OAuth2 OK")

# 1. Listar todas las carpetas
print("=== CARPETAS DISPONIBLES ===")
_, folders = mail.list()
for f in folders:
    print(" ", f.decode(errors="replace"))

# 2. Buscar por remitente real en INBOX y Spam
senders = [
    "transferencias@bci.cl",
    "contacto@bci.cl",
    "bci.cl",
    "bancoestado.cl",
    "bancosecurity.cl",
    "security.cl",
]

for folder in ["INBOX", "[Gmail]/Spam", "[Gmail]/All Mail", "Spam", "Junk"]:
    try:
        status, _ = mail.select(folder, readonly=True)
        if status != "OK":
            continue
        print(f"\n=== {folder} ===")
        for sender in senders:
            _, data = mail.uid("search", None, f'FROM "{sender}"')
            uids = data[0].split() if data[0] else []
            if uids:
                print(f"  FROM {sender}: {len(uids)} correos")
                for uid in uids[:2]:
                    _, msg_data = mail.uid("fetch", uid, "(BODY[HEADER.FIELDS (FROM SUBJECT DATE)])")
                    if msg_data and msg_data[0]:
                        print("   ", msg_data[0][1].decode(errors="replace").strip().replace("\n", " | "))
    except Exception as e:
        print(f"  {folder}: {e}")

mail.logout()
