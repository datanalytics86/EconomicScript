import config
from db import Database
from gmail_ingest import GmailIngestor

db = Database(config.DB_PATH)
ingestor = GmailIngestor(db)
mail = ingestor._connect()

mail.select("INBOX")

# Buscar por palabras clave bancarias en el asunto
keywords = ["cartola", "estado de cuenta", "movimiento", "transacci", "bci", "bancoestado", "security", "banco"]

print("=== BÚSQUEDA POR ASUNTO ===")
for kw in keywords:
    _, data = mail.uid("search", None, f'SUBJECT "{kw}"')
    uids = data[0].split()
    if uids:
        print(f"\n'{kw}': {len(uids)} correos")
        # Mostrar los primeros 3
        for uid in uids[:3]:
            _, msg_data = mail.uid("fetch", uid, "(BODY[HEADER.FIELDS (FROM SUBJECT)])")
            if msg_data and msg_data[0]:
                print(" ", msg_data[0][1].decode(errors="replace").strip().replace("\n", " | "))

mail.logout()
