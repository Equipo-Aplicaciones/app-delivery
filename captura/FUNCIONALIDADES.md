# Evidencia de pedidos — versión 1.0.1

APK para el teléfono, sin Metro: `captura/app-delivery.apk`.  
Paquete `com.wika.appdelivery`, versión 1.0.1, arquitectura arm64.  
La API corre en esta máquina, puerto `8787`. Base: `http://comparador.tarrainnova.cloud:8787`.

La app solo saca la foto y la envía. Otro proyecto lee la evidencia. Son dos claves distintas. Las dos van en el header `Authorization: Bearer`. Ninguna va en la URL. Las claves no están en el repositorio: se crean en `captura/data/upload-key` y `captura/data/read-key` al arrancar la API.

## Funcionalidades

- Abrir la cámara trasera y tomar una foto del pedido.
- Guardar esa foto y, recién entonces, rotularla.
- El rótulo es el número de orden y el agregador: Uber, PedidosYa o Rappi.
- Enviar la foto rotulada a la API. La API la guarda en disco y anota la fila en SQLite.
- Varias fotos del mismo pedido se acumulan. Un envío nuevo no borra las anteriores.
- Pedir Uber no devuelve fotos de PedidosYa ni de Rappi, ni las de otra orden.
- La clave de la app solo puede subir. No puede listar ni bajar fotos.
- La clave de lectura solo puede extraer. No puede guardar fotos. Esa clave no viaja en el teléfono.
- La foto tiene que ser JPEG y pesar como máximo 8 MB.

## Flujo de acción

1. El operador abre la app. Ve la cámara a pantalla casi completa.
2. Dispara. La foto queda tomada. Si la cámara no está lista o no hay permiso, la app avisa y no llama a la API.
3. Sube el formulario **Rotular**: número de orden, agregador y **Enviar**.
4. La app recorta espacios del número de orden. Si falta la orden, el agregador o la foto, no llama a la API.
5. `POST /v1/evidencia` con la clave de subida. La API confirma con `201` y `{ "saved": true }`.
6. La pantalla vuelve a la cámara y muestra que la imagen quedó guardada. Si la red falla, la foto y el formulario siguen.
7. Más adelante, el otro proyecto pide la evidencia con la clave de lectura, por agregador y número de orden, y baja cada JPEG.

Arranque de la API en la máquina:

```bash
python3 captura/api/server.py
```

`GET /healthz` responde `{ "ok": true }` y no pide clave.

## API de envío

La usa la app. Header obligatorio:

```http
Authorization: Bearer <clave de subida>
```

`POST /v1/evidencia`  
`Content-Type: multipart/form-data`

| Campo | Valor |
|---|---|
| `agregador` | `uber`, `pedidosya` o `rappi` |
| `numero_orden` | texto, sin espacios al inicio ni al final, máximo 80 caracteres |
| `imagen` | archivo JPEG |

Respuesta `201`:

```json
{ "saved": true, "id": "uuid", "created_at": "2026-11-06T20:00:00Z" }
```

Errores: `401` si la clave no es la de subida, `400` si falta un dato o el archivo no es JPEG, `500` si la base no guardó la imagen.

La clave de lectura en este `POST` también responde `401`.

## API de extracción

La usa el otro proyecto. Header obligatorio:

```http
Authorization: Bearer <clave de lectura>
```

Listar las fotos de un pedido:

```http
GET /v1/evidencia?agregador=uber&numero_orden=88
```

`200` con las fotos de esa pareja, de la más antigua a la más nueva. Si no hay ninguna, `images` viene vacío. Eso no es un error.

```json
{
  "images": [
    {
      "id": "uuid",
      "created_at": "2026-11-06T20:00:00Z",
      "agregador": "uber",
      "numero_orden": "88",
      "url": "http://comparador.tarrainnova.cloud:8787/v1/evidencia/uuid/imagen"
    }
  ]
}
```

Ficha de una foto:

```http
GET /v1/evidencia/{id}
```

```json
{
  "id": "uuid",
  "agregador": "uber",
  "numero_orden": "88",
  "created_at": "2026-11-06T20:00:00Z",
  "content_type": "image/jpeg",
  "byte_size": 120034,
  "imagen_url": "http://comparador.tarrainnova.cloud:8787/v1/evidencia/uuid/imagen"
}
```

Bytes de la imagen. El otro proyecto manda la misma clave de lectura. La URL no lleva token.

```http
GET /v1/evidencia/{id}/imagen
```

Respuesta `200` con `Content-Type: image/jpeg`.

Errores: `401` con la clave de la app o sin clave, `400` si el agregador o la orden no sirven, `404` si ese id no existe.
