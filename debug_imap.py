import config
from db import Database
from gmail_ingest import GmailIngestor

db = Database(config.DB_PATH)
ingestor = GmailIngestor(db)
mail = ingestor._connect()

# Buscar en la carpeta donde están los correos procesados
mail.select('"Procesado/Finanzas"')
_, data = mail.uid("search", None, "ALL")
uids = data[0].split()
print(f"Procesado/Finanzas: {len(uids)} correos")

# Mostrar remitentes únicos
print("\n=== REMITENTES ===")
remitentes = set()
for uid in uids:
    _, msg_data = mail.uid("fetch", uid, "(BODY[HEADER.FIELDS (FROM)])")
    if msg_data and msg_data[0]:
        linea = msg_data[0][1].decode(errors="replace").strip()
        remitentes.add(linea)

for r in sorted(remitentes):
    print(r)

mail.logout()
