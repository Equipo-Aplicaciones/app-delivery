# Scripts Uber Eats y PedidosYa — qué hacen, cómo funcionan y alcances

Actualizado: 2026-11-05 (hora Chile).  
Para Tarragona. No tocan Rappi ni Justo.

| | Uber Eats | PedidosYa |
|---|---|---|
| Script | `/workspace/uber_client/uber.py` | `/workspace/pya_client/pya.py` |
| Auth | Cookie en `~/.uber_cookie` (o env `UBER_COOKIE`) | Tokens en `~/.pya_tokens.json` |
| Renovar sesión | Rutina cada 4 h + `refresh_uber_cookie.py` | Refresh automático; si caduca → login OTP |
| Secretos | Nunca se imprimen | Nunca se imprimen |

Correr desde la carpeta del cliente. Filtros: `-s "nombre"` o `--id …`. Salida: tabla, `--json` o `--csv`. Horas en America/Santiago.

---

## Cómo funciona (en corto)

Ambos hablan con la **API interna del portal** (las mismas llamadas que usa el navegador), no con una API pública oficial.

1. **Login / sesión** → cookie (Uber) o tokens (PedidosYa).
2. **Lectura** → listar tiendas, estado, menú, ventas, etc.
3. **Escritura** → solo si pedís el cambio: primero dry-run (sin `--yes`), después `--yes`, y se verifica con una lectura.

Regla de oro: **lectura libre; escritura solo con tu OK explícito**, dry-run → `--yes` → verificar.

---

## Auth

### Uber
- Preferido: archivo `~/.uber_cookie` (modo 0600).
- Fallback: variable de entorno `UBER_COOKIE`.
- Validar: `python3 refresh_uber_cookie.py --check`
- Guardar: `--from-env` o `--from-file PATH` (header Cookie; borra el archivo temporal).
- Renovación automática: rutina **Renovar cookie Uber** a las 02:00, 06:00, 10:00, 14:00, 18:00 y 22:00 (Chile, ±15 min). Abre el portal en el navegador del computador, exporta cookies (incluye HttpOnly) y actualiza el archivo.
- Si pide login/OTP: avisar (todavía no hay login de Uber en el vault).
- Fallo 401/403/redirect: renovar; si sigue fallando, cookie nueva por tarjeta segura.

### PedidosYa
- `~/.pya_tokens.json` tras login con OTP.
- Renueva solo con `/auth/v5/token-refresh`.
- Si el refresh también vence: reloguear con `PYA_USER`/`PYA_PASS` + OTP nuevo (no reintentar en bucle).

---

## Qué hace cada script

### Lectura (seguro)

| Capacidad | Uber `uber.py` | PedidosYa `pya.py` |
|---|---|---|
| Estado de locales | `monitor` (abierta / cerrada / pausada / no visible); `--only`; `--changes` | `monitor` (OPEN / CLOSED / HIGH_DEMAND / INACTIVE); `--only CLOSED`; `--changes` |
| Horarios | `hours` (semanal + excepciones + feriados CL) | `hours` (regular + especiales) |
| Agotados | `soldout-report` | `soldout-report` |
| Ventas / ops | `sales` (ayer por defecto; ops con ~1 día de desfase) | `sales` (+ cancelados, atrasados, 1★; `--ops`) |
| Disputas / incidencias | `disputes` (cobradas sin disputar); `dispute-photos` | `orders --issues`, `issues`, `order <id>` (no lista “disputas” aparte) |
| Reseñas / ratings | — | `reviews`, `ratings` |
| Finanzas / reportes | — | `payouts`, `earnings`, `invoices`, `report <nombre>` |

### Escritura (solo con tu OK)

| Capacidad | Uber | PedidosYa |
|---|---|---|
| Pausar local | `pause` — 10/20/30/60 min o `rest_of_day`; motivos CLOSING_EARLY, PROBLEM_IN_RESTAURANT, OUT_OF_ITEM, OTHER | `pause` — N minutos o fin de turno; motivos TOO_BUSY_*, TECHNICAL_PROBLEM, OTHER, etc. |
| Activar local | `activate` | `activate` |
| Agotar producto | `soldout --item "…" --until today\|indefinite` | `soldout --item "…" --until indefinite\|tomorrow\|<min>` |
| Reponer producto | `instock` | `instock` |
| Encender menú (masivo) | `activate-menu` (productos + customizations) | `activate-menu` (productos + opciones) |
| Abrir disputa | `dispute` (dry-run ok; **--yes nunca probado en vivo**) | No hay envío de disputas por script |

Exclusiones por defecto en `activate-menu` (ambos): Papas Cheddar, Papas Cheddar Bacon, Salsa Tártara, Promo Super Basket Recargado, Promo Box Recargado, Combo Mundialero Coca-Cola; en PedidosYa también Papas Bites con Salsa Cheddar. Se pueden sumar con `--exclude` / `--exclude-file`.

---

## Alcances y límites

### Cubierto
- Monitoreo de aperturas/cierres/pausas Tarragona.
- Informes de agotados y reactivación masiva de menú (con exclusiones).
- Pausar/activar un local o un producto cuando lo pedís.
- Ventas y métricas operativas básicas.
- Uber: listar disputas cobradas y armar disputa (fotos: multipart **no verificado** con `--yes`).
- PedidosYa: reseñas, pedidos, issues, payouts, earnings, reportes del portal.

### No cubierto / fuera de alcance
- **Rappi y Justo** (siguen por portal / conector Justo).
- Cambiar precios, nombres, horarios de menú o estructura del catálogo.
- PedidosYa: **enviar** disputas/reembolsos (solo lectura del estado en el pedido).
- Uber: pausa “hasta una hora exacta” o indefinida vía API (solo 10/20/30/60 o resto del día); feriados/horarios especiales → portal.
- Videos de evidencia de la tienda en Uber: URL sí, descarga fuera del navegador → 401.
- Captcha PerimeterX en PedidosYa si se paginan muchos pedidos: esperar; no se resuelve captcha.
- Login Uber en vault (pendiente): hoy la renovación depende de sesión viva en el navegador del computador.

### Opciones PedidosYa (detalle importante)
No usar el listado crudo `GET .../product-options` para decidir qué encender: en menús CHAIN marca fantasma `available:false` y el PUT da `404`.  
Fuente correcta: `GET .../catalogs/items?isAvailable=false` → `productOptions` (status COMMITTED). `activate-menu` ya usa eso (fix 2026-11-05 tras las 113 “fallas”).

---

## Comandos típicos

```bash
# Uber
cd /workspace/uber_client
python3 uber.py monitor -s Tarragona
python3 uber.py monitor -s Tarragona --only closed
python3 uber.py soldout-report -s Tarragona --csv
python3 uber.py activate-menu -s Tarragona          # dry-run
python3 refresh_uber_cookie.py --check

# PedidosYa
cd /workspace/pya_client
python3 pya.py monitor --only CLOSED
python3 pya.py soldout-report --csv
python3 pya.py activate-menu -s Tarragona           # dry-run
python3 pya.py sales --start 2026-11-01 --end 2026-11-05 --by-store
```

Logs de activación masiva:
- Uber: `/workspace/uber-activacion-AAAA-MM-DD.csv`
- PedidosYa: `/workspace/pedya-activacion-AAAA-MM-DD.csv`

---

## Quién lo usa
- **Analista / Analista de productos**: lectura primero; escritura solo con orden tuya; portal si el script falla.
- **Orquestador**: dispara rondas; no escribe menú solo.
- **Ingeniero (este bot)**: mantiene scripts, auth y skills `uber-eats-api` / `pedidosya-api`.

Para el detalle de endpoints y payloads: `README.md` en cada carpeta del cliente.
