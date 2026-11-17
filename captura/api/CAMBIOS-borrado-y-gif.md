# API de evidencia: borrar fotos del día y aceptar GIF

Cambios de noviembre de 2026 en `captura/api/server.py`. Los usa el panel de delivery (módulo Captura) y ya corren en el VPS (`/home/dev/app-delivery/captura/api`, puerto 8787).

## Qué cambió

### 1. Borrar una foto: `DELETE /v1/evidencia/{id}`

La tienda puede borrar o cambiar las fotos que sacó **el mismo día**, desde «Fotos de hoy» en Captura.

- Requiere la **clave de subida** (`upload-key`). La clave de lectura no borra.
- Borra la fila de `evidencia.sqlite` **y** el archivo en `data/files/`.
- **Resguardo:** no borra fotos con más de **36 horas** (`DELETE_MAX_AGE`). El panel además limita al día calendario de Chile; desde el día siguiente la foto queda como evidencia para la disputa.

| Respuesta | Cuándo |
|---|---|
| `200 {"deleted": true}` | Se borró |
| `404 {"error": "No existe esa foto"}` | El id no existe |
| `409 {"error": "Solo se pueden borrar fotos del día"}` | Tiene más de 36 horas |
| `401 {"error": "no autorizado"}` | Sin clave de subida |

### 2. Aceptar GIF animado en `POST /v1/evidencia`

Para pedidos de **PedidosYa** la tienda puede subir un GIF (video de hasta 7 segundos convertido en el celular) en lugar de una foto.

- Acepta **JPEG** (`FF D8 FF`) o **GIF** (`GIF87a` / `GIF89a`). Cualquier otra cosa responde `400`.
- El GIF se guarda como `{id}.gif` con `content_type = image/gif`.
- `GET /v1/evidencia/{id}/imagen` responde con el `Content-Type` guardado (antes siempre `image/jpeg`).
- El tope sigue siendo `MAX_BYTES` (8 MB). El panel limita los GIF a 6 MB.
- **Uber no acepta GIF** como evidencia de disputa: el panel no los envía a Uber.

## Pruebas

`test_evidencia.py` suma 4 pruebas (9 en total):

- borra una foto reciente solo con la clave de subida, y el archivo desaparece;
- no borra fotos antiguas;
- acepta un GIF y lo sirve como `image/gif`;
- rechaza lo que no es foto ni GIF.

```bash
cd captura/api && python3 -m unittest test_evidencia
```

## Despliegue en el VPS

```bash
# Reiniciar la API (como dev)
kill $(ss -ltnp | grep ":8787 " | grep -o "pid=[0-9]*" | cut -d= -f2)
cd /home/dev/app-delivery/captura/api && setsid nohup python3 server.py >> ../data/server.log 2>&1 < /dev/null &
```

Respaldos de la versión anterior en el VPS:
`/home/dev/backups/evidencia-server-20261113-pre-delete.py` y `/home/dev/backups/evidencia-server-20261117-pre-gif.py`.

## Compatibilidad

- No cambia la base: `content_type` ya existía en la tabla.
- Las fotos JPEG y las rutas de lectura funcionan igual que antes.
