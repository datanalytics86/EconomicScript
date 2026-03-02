# Carpeta de carga de muestras sanitizadas

Deja aquí los archivos para calibrar parsers y reconciliación.

## Estructura

- `samples/inbox_emails/bci/`
- `samples/inbox_emails/banco_estado/`
- `samples/inbox_emails/security/`

Para correos, idealmente un `.txt` por correo con:
- asunto
- remitente
- cuerpo (texto plano o HTML pegado)

- `samples/statements/bci/pdf/`
- `samples/statements/bci/csv/`
- `samples/statements/banco_estado/pdf/`
- `samples/statements/banco_estado/csv/`
- `samples/statements/security/pdf/`
- `samples/statements/security/csv/`

## Convención sugerida de nombre

- Correos: `YYYYMMDD_<banco>_<tipo>_<n>.txt`
- Cartolas: `YYYYMM_<banco>_cartola.<pdf|csv>`

## Importante

- **Sanitiza datos sensibles** antes de subir (RUT, número completo de tarjeta, dirección, teléfono, etc.).
- Si puedes, agrega una breve nota por archivo con el resultado esperado (monto, fecha, comercio).
