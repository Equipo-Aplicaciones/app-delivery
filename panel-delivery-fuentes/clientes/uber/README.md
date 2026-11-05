# uber.py — CLI Uber Eats Manager (Tarragona)

Auth: archivo `~/.uber_cookie` (preferido) o env `UBER_COOKIE`. Nunca se imprime la cookie.
Renovar: `python3 refresh_uber_cookie.py --check` (valida) / `--from-env` / `--from-file PATH`.
Hay una rutina cada 4 horas que refresca la sesión en el navegador y actualiza el archivo.
Python 3.9+ y `requests`.

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

## dispute-photos (solo lectura)
`python3 uber.py dispute-photos "Pajaritos:AA7A2" 3A8A2 [--start AAAA-MM-DD --end ...] [--out DIR] [--no-download] [--json]`
Busca el pedido en el historial (30 días por defecto) y consulta GraphQL `OrderDetails` (issueSummaryV2.imageFeedbacks = fotos del cliente,
aiExplanation, items[].supportV2.resolutionFeedback = comentario del cliente) y `DisputeStatus` (con orderUUID; disputeReason,
disputeDescription, evidenceUrls = evidencia subida por la tienda). Descarga las fotos a DIR/<pedido>/cliente/ y guarda detalle.json.
La evidencia de la tienda (mp4 en tb-static/contact_service) devuelve 401 fuera del navegador: solo se lista la URL. No envía ni modifica disputas.

## dispute (escritura; dry-run por defecto)
`python3 uber.py dispute --workflow <workflowUuid> --restaurant <storeUuid> --reason <REASON> [--description TXT] [--evidence f1.jpg ...] [--locale es] [--yes]`
GraphQL `mutation SubmitDispute($disputeSubmission: Dispute_Submission!)` → `{disputeUUID, disputeRiskCheck}`.
Campos: orderUuid, reason, description (obligatoria si OTHER), evidence (archivos), locale, disputeFlow, disputedItems[{uuid,name,quantity}], captchaToken.
Razones: CUSTOMER_MISTAKE, CUSTOMER_PROVIDED_EVIDENCE_INCORRECT, DELIVERY_DRIVER_RELATED, EVIDENCE_UNCONVINCING, INCORRECT_REFUND_AMOUNT, OTHER, STORE_EVIDENCE_AVAILABLE.
Evidencia: máx. 3 archivos, 100 MB c/u, jpg/jpeg/png/mp4/mpg/3gpp (+pdf si el flag está activo); se envían como File en las variables
(multipart GraphQL, NO probado). Elegibilidad: orderDetails.disputeEligibilityCheck (ELIGIBLE, PREVIOUSLY_DISPUTED, NO_CHARGEBACK,
ACCESS_DENIED, EXPIRED_7/14/21/30/45_DAYS). Nunca probado con --yes.
