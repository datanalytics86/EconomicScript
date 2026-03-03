"""Script de autorización OAuth2 para Gmail IMAP.

Ejecutar UNA SOLA VEZ para obtener el refresh token:

    python auth_setup.py

Abrirá el navegador para autorizar acceso a Gmail.
Al finalizar imprime las variables para agregar al .env
"""

from __future__ import annotations

from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://mail.google.com/"]
CREDENTIALS_FILE = Path(__file__).parent / "credentials.json"


def main() -> None:
    if not CREDENTIALS_FILE.exists():
        print(
            f"ERROR: No se encontró {CREDENTIALS_FILE}\n"
            "Descarga el archivo desde Google Cloud Console:\n"
            "  APIs y servicios → Credenciales → ⬇️ Descargar JSON\n"
            "y colócalo en la misma carpeta que este script."
        )
        return

    flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_FILE), SCOPES)
    creds = flow.run_local_server(port=0)

    print("\n✓ Autorización exitosa. Agrega estas líneas a tu .env:\n")
    print(f"OAUTH_CLIENT_ID={creds.client_id}")
    print(f"OAUTH_CLIENT_SECRET={creds.client_secret}")
    print(f"OAUTH_REFRESH_TOKEN={creds.refresh_token}")
    print("\n(El IMAP_PASSWORD ya no es necesario, puedes eliminarlo del .env)")


if __name__ == "__main__":
    main()
