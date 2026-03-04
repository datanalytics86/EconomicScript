import config
from db import Database
from gmail_ingest import GmailIngestor

db = Database(config.DB_PATH)
ingestor = GmailIngestor(db)
mail = ingestor._connect()
mail.select("INBOX")

_, data = mail.uid("search", None, 'FROM "@bci.cl"')
print("BCI:", data)

_, data = mail.uid("search", None, 'FROM "bancoestado.cl"')
print("BancoEstado:", data)

_, data = mail.uid("search", None, 'FROM "@security.cl"')
print("Security:", data)

mail.logout()
