# Documentación API Tarragona — PedidosYa y Uber Eats

_Generado el 04-11-2026. Credenciales y tokens no incluidos._

# pya.py — CLI PedidosYa Partner Portal (Tarragona)

Sesión: `~/.pya_tokens.json` (creado tras el login con OTP). El cliente lo carga solo y renueva el token
con `/auth/v5/token-refresh` cuando vence, guardando los tokens nuevos. Si el refresh también expira,
hay que volver a hacer login (`PYA_USER`/`PYA_PASS`) y pedir un OTP nuevo. El script nunca imprime tokens.

Filtros comunes: `-s/--store "texto"` (subcadena del nombre, repetible), `--id 616514` (platformVendorId).
Salida: tabla, `--json` o `--csv`. Horas en hora de Chile (America/Santiago).

## 1. Monitoreo
```
python3 pya.py monitor                      # todas: abierta / alta demanda / cerrada temporal / inactiva
python3 pya.py monitor --only CLOSED        # solo cerradas temporalmente (motivo, desde, hasta, autor)
python3 pya.py monitor --changes            # solo cambios vs ~/.pya_state/monitor_snapshot.json
```
Motivos de cierre que usa PedidosYa: TOO_BUSY_KITCHEN, TOO_BUSY_NO_DRIVERS, UPDATES_IN_MENU, TECHNICAL_PROBLEM,
ORDER_FAILURE (lo pone el monitor de PedidosYa por pedidos fallidos), TOO_MANY_REJECTED_ORDERS, UNREACHABLE,
BAD_WEATHER, HOLIDAY_SPECIAL_DAY, CHECK_IN_REQUIRED, OTHER. `author=log_vendor_monitor` = automático de PedidosYa;
`log_vendor_client` = lo cerró el local/portal.

## 2. Pausar / activar (VERIFICADO en vivo 04-11-2026)
`PUT vss.us.restaurant-partners.com/api/v3/globalEntities/PY_CL/vendors/<id>/availability`
(mismo cuerpo que usa el portal, plugin availability 1.29.2):
- Pausa por minutos: `{"state":"CLOSED","closure":{"mode":"MINUTES","minutes":10,"reason":"TOO_BUSY_KITCHEN","changeable":true}}`
- Cierre hasta fin del turno (sin `--minutes`): `{"state":"CLOSED","closure":{"mode":"END_OF_SLOT","reason":"OTHER","changeable":true}}`
- Activar: `{"state":"OPEN"}`

Sin `--yes` solo imprime (dry-run). Escribir solo cuando Joaquín lo pida.
```
python3 pya.py pause --id 597977 --minutes 10 --reason TOO_BUSY_KITCHEN          # dry-run
python3 pya.py pause --id 597977 --minutes 10 --reason TOO_BUSY_KITCHEN --yes    # real
python3 pya.py pause -s "El Llano" --reason TECHNICAL_PROBLEM --yes               # hasta fin del turno
python3 pya.py activate --id 597977 --yes
```
Prueba real: Tarragona El Llano -- (597977), pausa 16:11:14, verificada cerrada 16:11:18 (hasta 16:21),
activada 16:11:23, verificada abierta 16:11:27 (hora Chile).

## 3. Horarios
```
python3 pya.py hours -s Easton --csv        # horario regular por día + horarios especiales/cierres
python3 pya.py hours --id 67160 --raw       # JSON crudo
```
Nota: day 0 se interpreta como domingo (convención JS), pendiente de confirmar.

## 4. Agotar / reponer producto (VERIFICADO en vivo 04-11-2026)
`PUT vendor-api-cl.us.restaurant-partners.com/api/4/platforms/PY_CL/vendors/<id>/catalogs/products/<pid>/availability`
Cuerpo del portal (plugin menuManagementV2 1.18.23):
- Agotar indefinido: `{"available":false,"context":"MENU_UPDATE"}`
- Agotar hasta el próximo día hábil: `+ "schedules":[{"action":"ENABLE","type":"NEXT_BUSINESS_DAY"}]`
- Agotar N minutos: `+ "schedules":[{"action":"ENABLE","type":"AT_TIMESTAMP","timestamp":"<UTC ISO>"}]`
- Reponer: `{"available":true,"context":"MENU_UPDATE"}`
```
python3 pya.py soldout -s "Paseo Del Mar" --item "Bebida Lata" --until tomorrow       # dry-run
python3 pya.py soldout --id 616753 --item "Bebida Lata" --until 30 --yes
python3 pya.py instock --id 616753 --item "Bebida Lata" --yes
```
Prueba real: Tarragona - El Llano (553144), Bebida 1.5L (194000319). Agotado 16:16:27 (status REQUESTED, available=false),
repuesto 16:16:37, verificado disponible (COMMITTED) 16:16:42–16:16:51 (hora Chile). La API responde vacío; verificar con lectura.
Nota: El Llano -- (597977) no tiene catálogo en PedidosYa.

## 5. Informe de agotados (verificado)
```
python3 pya.py soldout-report --csv > agotados_pya.csv
```

## 6. Ventas, cancelados, atrasados, 1 estrella (verificado)
```
python3 pya.py sales                         # hoy, total
python3 pya.py sales --start 2026-11-03      # un día
python3 pya.py sales --start 2026-11-01 --end 2026-11-03 --by-store --csv
python3 pya.py sales --ops                   # + salud operacional (prep, % atraso, rechazos, offline)
```

## Pendiente / sin endpoint
- Reseñas (vrs-api) y disputas/reembolsos: endpoints no identificados todavía.

## activate-menu (enciende todo lo agotado salvo exclusiones)
`python3 pya.py activate-menu [-s TEXTO|--id ID] [--exclude NOMBRE]... [--exclude-file f.txt] [--no-default-exclude] [--yes] [--json|--csv]`
- Por defecto dry-run y todas las tiendas Tarragona (salta INACTIVE). Solo escribe con `--yes`.
- Productos (`PUT catalogs/products/<id>/availability`) y opciones/toppings (`PUT catalogs/product-options/<grupo>/options/<opt>/availability`), cuerpo `{"available":true,"context":"MENU_UPDATE"}` (respuesta 202).
- **Opciones:** no usar el listado crudo `GET .../product-options` para saber qué está agotado: en menús compartidos (CHAIN) marca muchas opciones como `available:false` aunque el local las tiene activas, y el PUT a esos ids responde `404 NOT_FOUND`. La fuente correcta es `GET .../catalogs/items?isAvailable=false&sizeSupport=true` → `productOptions[].options[]` (ahí vienen con `status: COMMITTED`). `activate-menu` ya usa ese endpoint.
- Mismas exclusiones por defecto que Uber. Log: `/workspace/pedya-activacion-AAAA-MM-DD.csv`. Con `--yes` relee y verifica; exit 1 si hay fallas.

## Reportería (solo lectura)
Todos estos comandos son lecturas (GET o POST de consulta). `gqld()` rechaza cualquier `mutation`. Fechas `--start/--end` en hora de Chile (por defecto los últimos 7 días). Todos aceptan `-s/--id`, `--json` y `--csv`.

| Comando | Fuente | Qué entrega |
|---|---|---|
| `reviews [--min-rating N --max-rating N --with-text]` | `POST vrs-api.us.prd.portal.restaurant/v1/reviews` `{global_vendor_codes:["PY_CL;<id>"],include_stats,pagination:{perPage,beforeId,beforeTimestamp},filter:{startDate,endDate,ratingMin,ratingMax,hasText}}` | reseñas: fecha, pedido, nota, texto, si tiene respuesta, notas por producto |
| `ratings` | `POST vrs-api/v1/ratings` | promedio y distribución 1–5 por tienda |
| `orders [--status CANCELLED] [--issues]` | GraphQL `ListOrders` (vagw) | historial: subtotal, comisión, neto, cargos/descuentos, problemas (reclamos, cancelación evitable, espera evitable) |
| `order <id>` | GraphQL `GetOrderDetails` | detalle: ítems, línea de tiempo, facturación, reembolsos, `isDisputeAllowed` y estado de disputa |
| `issues [--by-store]` | GraphQL `OrderIssueTiles` | reclamos de clientes (descuentos), cancelaciones evitables, espera evitable, con montos |
| `payouts` | GraphQL `ListPayouts` | pagos: fecha, estado, monto, pedidos, facturas y período |
| `earnings` | GraphQL `getPayoutEarningsSummary` | ventas brutas, comisiones, marketing/ads, vouchers, cargos por reclamos, impuestos, neto |
| `invoices` | GraphQL `ListOutstandingInvoices` + `ListAdditionalStatements` | facturas pendientes y estados adicionales |
| `report <nombre> [--by-store]` | `POST vos-api.us.prd.portal.restaurant/v1/vendors/reports/<nombre>` `{global_vendor_codes,from,to}` | performance, performance/summary, ops/summary, dishes (ventas por plato), heatmap, eod (efectivo/online), area, avg_acceptance_time, awt, contact-rate, customer_conversion, customer_retention, customers/summary, offline_duration, order_rejection, orders-marked-as-ready, out-of-stock, prep_time |

Notas:
- Finanzas necesita las cuentas de facturación (`billingParentId`). Se toman de `profile.accounts` del token-refresh y se guardan en `~/.pya_accounts.json` (sin secretos).
- El gateway vagw tiene PerimeterX: si haces muchos listados de pedidos seguidos responde 403 con captcha. Hay pausas entre páginas. Si aparece el 403, espera unos minutos. No se intenta resolver el captcha.
- Las disputas no tienen listado propio: se ven en `order <id>` (`isDisputeAllowed`, `dispute.status`) y en `orders --issues`. No se envían disputas.
- Los documentos GraphQL extraídos de los plugins están en `gql/*.graphql` (orders 4.17.8, finance, dashboard 2.4.0).

---

# uber.py — CLI Uber Eats Manager (Tarragona)

Requisito: `export UBER_COOKIE='<header Cookie de una sesión iniciada en merchants.ubereats.com>'`
(el script nunca imprime la cookie). Python 3.9+ y `requests`.

Filtros comunes: `-s/--store "texto"` (subcadena del nombre, repetible), `--id UUID` (repetible).
Salida: tabla legible por defecto, o `--json` / `--csv`. Horas en hora de Chile (America/Santiago).

## 1. Pausar / activar tiendas
Mutaciones GraphQL de la web (`/manager/graphql`): `SetStoresBusy` y `SetStoresOnline`.
Sin `--yes` solo muestra el payload (igual que `--dry-run`).
```
python3 uber.py pause -s "Lider Punta Arenas" --duration 30 --reason OUT_OF_ITEM --dry-run
python3 uber.py pause -s "Punta Arena" --duration rest_of_day --reason CLOSING_EARLY --yes
python3 uber.py activate -s "Zona Franca" --yes
```
Duraciones que acepta Uber: 10, 20, 30, 60 minutos o `rest_of_day` (fin del día). La web no tiene pausa
"indefinida" ni "hasta una hora exacta"; para eso se usan horarios especiales/feriados en el portal.
Motivos: CLOSING_EARLY, PROBLEM_IN_RESTAURANT, OUT_OF_ITEM, OTHER.

## 2. Monitoreo
```
python3 uber.py monitor -s Tarragona                 # abierta / cerrada / pausada / no visible
python3 uber.py monitor -s Tarragona --only paused --only closed
python3 uber.py monitor -s Tarragona --changes       # solo cambios vs ~/.uber_state/monitor_snapshot.json
```
Cada ejecución actualiza el snapshot.

## 3. Agotar / reponer producto
```
python3 uber.py soldout -s Tarragona --item "Promo Fajita - Coca Cola - Benedictino" --until today --dry-run
python3 uber.py soldout -s "Punta Arena" --item "Promo Fajita - Coca Cola - Benedictino" --until indefinite --yes
python3 uber.py instock -s Tarragona --item "Promo Fajita" --contains --yes
```
`today` = hasta mañana 04:00 hora local de la tienda (igual que "Agotado por hoy" de Menu Maker);
`indefinite` = hasta que se reactive. El nombre se compara exacto (sin mayúsculas/minúsculas) salvo `--contains`.
Después de cada cambio se vuelve a leer el menú para verificar.

## 4. Informe de agotados
```
python3 uber.py soldout-report -s Tarragona --csv > agotados.csv
```

## 5. Ventas y cancelados
```
python3 uber.py sales -s Tarragona                       # ayer
python3 uber.py sales -s Tarragona --start 2026-11-01 --end 2026-11-03 --csv
python3 uber.py sales -s Tarragona --start $(date +%F) --no-ops   # hoy, solo ventas y pedidos
```
Ventas y pedidos (`getStores`) están casi en tiempo real. Completados, cancelados, no cumplidos, con
errores, reembolsos, ventas perdidas y tiempo fuera de línea (`operationsSummary`) llegan con ~1 día de
desfase: para hoy salen en 0.

## 6. Disputas / incidencias
```
python3 uber.py disputes -s Tarragona                    # pendientes (cobradas, sin disputar), últimos 30 días
python3 uber.py disputes -s Tarragona --status charged --start 2026-10-01 --end 2026-10-31 --csv
```
En stderr también imprime los contadores de Uber (missed, canceled, disputeInProgress, disputeAccepted,
disputeRejected, issueCharged, issueReported, potentialDeduction).

## 7. Horarios
```
python3 uber.py hours -s Tarragona      # horario semanal por día + excepciones + feriados CL próximos
```

## activate-menu (enciende todo lo agotado salvo exclusiones)
`python3 uber.py activate-menu [-s TEXTO|--id UUID] [--exclude NOMBRE]... [--exclude-file f.txt] [--no-default-exclude] [--yes] [--json|--csv]`
- Por defecto dry-run y todas las tiendas Tarragona. Solo escribe con `--yes`.
- Productos y opciones de personalización suspendidas (`suspensionInfo` en `upsertMenus`, 1 upsert por tienda).
- Exclusiones por defecto (nombre exacto, sin mayúsculas/acentos): Papas Cheddar, Papas Cheddar Bacon, Salsa Tártara, Promo Super Basket Recargado, Promo Box Recargado, Combo Mundialero Coca-Cola.
- Log: `/workspace/uber-activacion-AAAA-MM-DD.csv` (timestamp, store, product, type, previous, action, result). Con `--yes` relee el menú y marca `ok verificado`/`error`. Exit 1 si hay fallas; resumen de 1 línea en stderr.
