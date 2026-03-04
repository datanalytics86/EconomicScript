import config
from db import Database
from gmail_ingest import GmailIngestor

db = Database(config.DB_PATH)
ingestor = GmailIngestor(db)
mail = ingestor._connect()

# 1. Listar todas las carpetas disponibles
print("=== CARPETAS ===")
_, folders = mail.list()
for f in folders:
    print(f.decode())

# 2. Ver cuántos correos hay en INBOX
mail.select("INBOX")
_, data = mail.uid("search", None, "ALL")
uids = data[0].split()
print(f"\n=== INBOX: {len(uids)} correos ===")

# 3. Mostrar remitentes de los últimos 10 correos
if uids:
    sample = uids[-10:]
    print("\n=== ÚLTIMOS REMITENTES ===")
    for uid in sample:
        _, msg_data = mail.uid("fetch", uid, "(BODY[HEADER.FIELDS (FROM SUBJECT)])")
        if msg_data and msg_data[0]:
            print(msg_data[0][1].decode(errors="replace").strip())
            print("---")

mail.logout()
