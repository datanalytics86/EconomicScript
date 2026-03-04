import config
from db import Database
from gmail_ingest import GmailIngestor

db = Database(config.DB_PATH)
ingestor = GmailIngestor(db)
mail = ingestor._connect()

mail.select("INBOX")

# Palabras clave financieras en español
keywords = [
    "cuenta", "saldo", "pago", "transferencia", "comprobante",
    "factura", "boleta", "resumen", "cartola", "movimiento",
    "tarjeta", "credito", "debito", "cuota"
]

print("=== BÚSQUEDA POR ASUNTO (español) ===")
found_any = False
for kw in keywords:
    _, data = mail.uid("search", None, f'SUBJECT "{kw}"')
    uids = data[0].split()
    if uids:
        found_any = True
        print(f"\n'{kw}': {len(uids)} correos")
        for uid in uids[:3]:
            _, msg_data = mail.uid("fetch", uid, "(BODY[HEADER.FIELDS (FROM SUBJECT DATE)])")
            if msg_data and msg_data[0]:
                print(" ", msg_data[0][1].decode(errors="replace").strip().replace("\n", " | "))

if not found_any:
    print("No se encontraron correos con esas palabras clave.")
    print("\n=== ÚLTIMOS 10 CORREOS EN INBOX ===")
    _, data = mail.uid("search", None, "ALL")
    all_uids = data[0].split()
    print(f"Total: {len(all_uids)} correos")
    for uid in all_uids[-10:]:
        _, msg_data = mail.uid("fetch", uid, "(BODY[HEADER.FIELDS (FROM SUBJECT)])")
        if msg_data and msg_data[0]:
            print(" ", msg_data[0][1].decode(errors="replace").strip().replace("\n", " | "))

mail.logout()
