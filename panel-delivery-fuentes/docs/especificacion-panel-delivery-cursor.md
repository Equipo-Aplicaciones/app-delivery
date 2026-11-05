# Especificación: Panel de Delivery Tarragona

Documento para construir (o ampliar) el proyecto **en Cursor**. Describe la base que ya existe, la API, las utilidades de plataforma y los módulos nuevos (credenciales, prender tiendas, disputas + imágenes, reportes, automatizaciones, apagados/prendidos masivos y conexión de agentes por API key).

Zona horaria del producto: `America/Santiago`. Idioma de UI y logs: español.

---

## 1. Qué hay que construir

Un panel web desplegable (FastAPI + frontend + Docker Compose + Caddy/HTTPS) que **fuse** dos líneas de trabajo:

1. **Proyecto de servidor actual** (`delivery-monitor-servidor`): monitoreo de tiendas + cobros/disputas sin abrir, snapshot, auth de panel, refresh de solo lectura.
2. **Clientes de plataforma** (`uber.py` y `pya.py`): lecturas y escrituras ya implementadas en CLI (monitor, menú, ventas, reportes, fotos de reclamo, pause/activate, soldout/instock, activate-menu, disputa Uber).

El panel debe dejar de ser solo lectura hacia las plataformas: expone **módulos** encima de esos CLI, con autenticación, confirmación para escrituras y sin imprimir secretos.

No es un rediseño desde cero: partir del ZIP `/workspace/delivery-monitor-servidor.zip` (o de `/workspace/delivery-monitor/` + copias de clientes) y sumar los módulos de esta especificación.

---

## 2. Principios (obligatorios)

- **Lectura libre** (si hay sesión válida). **Escritura solo con confirmación explícita** del operador o de un agente autorizado: primero dry-run, después `confirm=true`. Equivale al `--yes` de los CLI. Sin confirmación no se llama a ninguna mutation/PUT.
- Nunca imprimir ni devolver cookies, tokens, contraseñas, API keys, Authorization headers ni URLs firmadas completas (redactar query string).
- No copiar secretos al repositorio, al frontend ni a logs. Frontend habla solo con la API del panel (sesión o API key); nunca ve `UBER_COOKIE` ni tokens PedidosYa.
- Distinguir siempre: **habilitada** ≠ **abierta ahora**; **cerrada por horario** ≠ **pausada** ≠ **inactiva** ≠ **no visible**.
- PedidosYa: un **reclamo/descuento** (`issues`) **no** es una disputa pendiente. No inventar conteos.
- Rappi: integración **pendiente** (API vista en el portal con Bearer Auth0; no hay CLI ni `client_id`/`client_secret`). Sin cifras inventadas ni reuso de listados viejos como actuales.
- Datos de cliente (dirección, teléfono, nombre, cédulas, fotos de reclamo) son PII. Las fotos se sirven autenticadas, no se indexan en buscadores, y las de documentos de identidad se marcan como sensibles.
- Los CLI `uber.py` / `pya.py` se invocan por **subproceso** (tienen `api_client.py` homónimos). Rutas por env (`UBER_CLI`, `PYA_CLI`), no hardcodear `/workspace`.
- Un 401/403 de plataforma se reporta como error de fuente (`stores_count: null`), nunca como “0 tiendas”.
- Escrituras se registran (quién, cuándo, tienda, acción, dry-run/real, resultado). Exit distinto de 0 del CLI no se silencia.

---

## 3. Base existente (no reimplementar a ciegas)

### 3.1 Panel servidor (ya empaquetado)

Origen: `delivery-monitor-servidor/` (ZIP en `/workspace/delivery-monitor-servidor.zip`).

```
app/                  FastAPI + frontend estático (login, snapshot, refresh)
delivery_monitor/     adaptadores, classify, schema, sanitize, snapshot
clients/uber/         copia aislada de uber.py + api_client.py
clients/pya/          copia aislada de pya.py + api_client.py + gql/
data/                 snapshot.json (vacío en el paquete)
sessions/             secretos montados por el dueño (no van en el zip)
Dockerfile, compose.yaml, Caddyfile, .env.example, tests/
```

Auth actual del panel: usuario/contraseña (`PANEL_USER`, `PANEL_PASSWORD`), cookie HttpOnly, sin secretos en URL ni localStorage. Backend no publica puertos; Caddy termina TLS.

Sesiones de plataforma (hoy, archivos montados):

| Archivo montado | Consumido como | Notas |
|---|---|---|
| `sessions/uber_cookie` | `~/.uber_cookie` | Caduca; 401 exige cookie nueva. La rutina de navegador local no se migra sola. |
| `sessions/pya_tokens.json` | `~/.pya_tokens.json` | Puede refrescar el access token si el archivo es escribible. Si el refresh también caduca, hace falta login OTP. |

API HTTP **ya existente** (proteger igual que hoy):

| Método | Ruta | Auth | Qué hace |
|---|---|---|---|
| GET | `/healthz` | no | `{"status":"ok"}` — no revela tiendas ni secretos |
| GET/POST | `/login` | form | emite cookie de sesión |
| POST | `/logout` | sesión | limpia cookie |
| GET | `/api/snapshot` | sí | último snapshot sanitizado; si no hay, `available:false` y fuentes `pending` (no ceros) |
| POST | `/api/refresh` | sí | regenera snapshot (lock; 409 si ya corre; timeout ~420 s) |

Clasificación de tiendas (ya implementada en `delivery_monitor/classify.py`): abierta, abierta en alta demanda, cerrada por horario, pausada, cerrada (otro motivo), inactiva, no visible, check-in, desconocido. Exclusiones de reglas de oro se marcan, no se borran.

### 3.2 CLI Uber — `/workspace/uber_client/uber.py`

Auth: `~/.uber_cookie` (preferido) o env `UBER_COOKIE`. Validar: `refresh_uber_cookie.py --check`.

| Comando | Tipo | Estado | Uso |
|---|---|---|---|
| `monitor [-s] [--only] [--changes]` | lectura | verificado | abierta / cerrada / pausada / no visible |
| `hours` | lectura | verificado | horario + excepciones + feriados CL |
| `soldout-report` | lectura | verificado | productos agotados |
| `sales [--start --end]` | lectura | verificado | ventas; ops con ~1 día de desfase |
| `disputes [--status pending\|charged]` | lectura | verificado | cobros sin disputar (ventana explícita) |
| `dispute-photos <pedido>` | lectura | verificado | fotos del cliente + comentario; evidencia tienda (mp4) a menudo 401 fuera del navegador |
| `pause --duration 10\|20\|30\|60\|rest_of_day --reason …` | escritura | dry-run + real (portal GraphQL) | no hay pausa “indefinida” ni “hasta hora exacta” |
| `activate` | escritura | verificado | prende tienda |
| `soldout --item --until today\|indefinite` | escritura | dry-run / `--yes` | agotar producto |
| `instock --item` | escritura | dry-run / `--yes` | reponer producto |
| `activate-menu [--exclude]` | escritura | dry-run / `--yes` | enciende agotados salvo exclusiones (productos + customizations) |
| `dispute --workflow --restaurant --reason [--evidence]` | escritura | **solo dry-run**; `--yes` nunca probado en vivo | GraphQL `SubmitDispute`; evidencia multipart no verificada |

Motivos de pausa Uber: `CLOSING_EARLY`, `PROBLEM_IN_RESTAURANT`, `OUT_OF_ITEM`, `OTHER`.

### 3.3 CLI PedidosYa — `/workspace/pya_client/pya.py`

Auth: `~/.pya_tokens.json` + refresh `/auth/v5/token-refresh`. OTP si el refresh caduca. `gqld()` bloquea mutations GraphQL (las escrituras de menú/disponibilidad van por REST).

| Comando | Tipo | Estado | Uso |
|---|---|---|---|
| `monitor [--only CLOSED] [--changes]` | lectura | verificado | OPEN / CLOSED / HIGH_DEMAND / INACTIVE |
| `hours` | lectura | verificado | regular + especiales |
| `soldout-report` | lectura | verificado | agotados |
| `sales [--ops --by-store]` | lectura | verificado | ventas, cancelados, atrasados, 1★ |
| `reviews`, `ratings` | lectura | verificado | reseñas y notas |
| `orders [--issues]`, `order <id> [--photos]` | lectura | verificado | historial / detalle; `--photos` pide `hasPhotoEvidence=true` → `orderIssuePictures.urls` |
| `issues [--by-store]` | lectura | verificado | mosaicos de reclamos (no disputas) |
| `payouts`, `earnings`, `invoices` | lectura | verificado | finanzas |
| `report <nombre> [--by-store]` | lectura | verificado | ver lista en §7 |
| `pause [--minutes] --reason` | escritura | verificado en vivo (2026-11-04) | minutos o fin de turno |
| `activate` | escritura | verificado en vivo | prende tienda |
| `soldout --item --until indefinite\|tomorrow\|<min>` | escritura | verificado en vivo | agotar |
| `instock --item` | escritura | verificado en vivo | reponer |
| `activate-menu` | escritura | verificado (opciones 2026-11-05) | ver nota de opciones abajo |
| Enviar disputa | — | **no hay endpoint** | el portal abre Help Center (`cases-api`); no hay `SubmitDispute` en nuestros gql. Solo `UploadReceipt` (recibo). |

**Opciones PedidosYa (crítico):** no listar agotados con `GET .../product-options` (en menús CHAIN marca fantasma `available:false` y el PUT da `404`). Fuente correcta: `GET .../catalogs/items?isAvailable=false&sizeSupport=true` → `productOptions` con `status: COMMITTED`. `activate-menu` ya lo usa. PUT de encendido: `.../product-options/<grupo>/options/<opt>/availability` con `{"available":true,"context":"MENU_UPDATE"}` (HTTP 202).

**Fotos PedidosYa:** `pya.py order <id> --photos`. Ejemplo verificado: pedido `2355819567` (Tarragona 6 Oriente Talca) → 2 JPEG en `orderIssuePictures.urls[].original` (host `helpcenter-files-us.s3.amazonaws.com`, URL firmada). No todo reclamo trae foto. Ese ejemplo eran cédulas: tratar como PII sensible. URLs en logs: `?REDACTED`.

**Dirección / datos de cliente PedidosYa:** en `platform_delivery`, `delivery.location` viene vacío y `GetOrderCustomer` responde “Order Not Found”. No exponer un módulo de “datos del cliente” como si existiera.

**PerimeterX:** `ListOrders` / vagw puede devolver 403 si se pagina agresivo. Pausas entre páginas; no resolver captcha.

Exclusiones por defecto de `activate-menu` (ambos CLI): Papas Cheddar, Papas Cheddar Bacon, Salsa Tártara, Promo Super Basket Recargado, Promo Box Recargado, Combo Mundialero Coca-Cola; PedidosYa también Papas Bites con Salsa Cheddar.

### 3.4 Rappi (pendiente)

Base vista en portal: `https://services.rappi.cl/api/rs-platform-gateway`. Auth: Bearer Auth0 (`login.partners.rappi.com`). Cookies solas no alcanzan (401). Lecturas observadas en vivo (sesión del portal, HTTP 200, 65 tiendas):

- `POST .../stores-router/stores/info?country=CL`
- `POST .../rest-aliados-state-ms/v2/store-status-detail`
- `GET .../groot/partners/v2/stores/{id}/store-settings`

Filtro del portal: hay que elegir **marca** y **tienda** y Aplicar; sin eso muestra “0 Tiendas”. Marcas vistas: Tarragona, Pollo Stop, Elemental Burger, Elemental la Pintana.

API oficial POS (`dev-portal.rappi.com`) usa `client_id` + `client_secret`; no hay credenciales en vault. No inventar adapter con cifras.

---

## 4. Arquitectura objetivo

```
                    ┌─────────────┐
  Operador / UI  ───►│  Caddy TLS  │
  Agentes (API key)──►│  :443       │
                    └──────┬──────┘
                           ▼
                    ┌─────────────┐
                    │  FastAPI    │  auth: sesión cookie  O  API key de agente
                    │  app/       │  auditoría de escrituras
                    └──────┬──────┘
           ┌───────────────┼────────────────┐
           ▼               ▼                ▼
     delivery_monitor   modules/        clients/ (subproceso)
     (snapshot)         credentials     uber.py / pya.py
                        stores          (y rappi.py el día que exista)
                        disputes+media
                        reports
                        catalog (soldout/instock/activate-menu)
                        automations
                        agents
```

Capas:

1. **clients/** — copias versionadas de los CLI. No se invocan con `--yes` salvo que el módulo de escritura haya recibido `confirm=true` y el rol lo permita.
2. **delivery_monitor/** — normaliza snapshot de monitoreo (ya existe). Extender para listar también **todas** las tiendas abiertas (el ZIP de servidor ya lo hace).
3. **modules/** — cada módulo de esta especificación: orquesta CLI, valida input, aplica dry-run/confirm, guarda artefactos (CSV/XLSX/fotos) fuera de git.
4. **app/** — HTTP. Misma auth para UI y API. Roles: `operator` (humano del panel) y `agent` (API key).

Volúmenes: `data/` (snapshots, reportes, logs de acción), `sessions/` (secretos 0600), `media/` (fotos de reclamo, no en git, acceso autenticado).

---

## 5. API HTTP a implementar / ampliar

Prefijo `/api`. Todas las rutas salvo `/healthz` y login requieren sesión de panel **o** `Authorization: Bearer <agent_api_key>`.

Respuestas de error: `{ "error": "...", "code": "..." }` sin traceback ni secretos. Escrituras devuelven `{ "dry_run": true|false, "results": [...], "verified": ... }`.

### 5.1 Salud y snapshot (ya existe; mantener)

- `GET /healthz`
- `GET /api/snapshot` — tiendas + disputas sanitizadas + `coverage` + `sources[]`
- `POST /api/refresh` — lock + timeout; no escribe en plataformas

### 5.2 Módulo credenciales (`/api/credentials`)

Sirve para **reponer** sesiones cuando se pierden o caducan. El operador sube o pega en un formulario seguro (el valor no vuelve en GET).

- `GET /api/credentials/status` — por fuente: `configured` | `missing` | `expired` | `unknown`, `checked_at`, `detail` corto. **Nunca** el valor. Uber: health tipo `list_stores` sample. PedidosYa: token-refresh o `monitor` limitado. Rappi: `pending` hasta tener token/CLI.
- `PUT /api/credentials/uber` — body o archivo: header Cookie o valor crudo. Guardar atómico en `sessions/uber_cookie` modo `0600`. Validar con health check. Si falla, no dejar el archivo anterior destruido (escribir a `.tmp` y `os.replace` solo si el check pasa, o conservar backup `.bak`).
- `PUT /api/credentials/pedidosya` — archivo `pya_tokens.json` (estructura que ya entiende el cliente). Validar refresh o monitor. Mismo criterio atómico.
- `PUT /api/credentials/rappi` — reservado; 501 hasta que exista adapter. No aceptar tokens “por las dudas” sin health check.
- `DELETE /api/credentials/{source}` — borra el archivo de sesión (con confirmación). No borra el login del vault del operador.

Reglas: no loguear el body; no devolver el secreto en la respuesta (sí `ok`, `length` aproximada o `checked_at`). El frontend de este módulo es un formulario, no un textarea que persista en localStorage.

Flujo PedidosYa si el refresh caducó: el status debe decir “hace falta login OTP”; no reintentar logins en bucle. El alta OTP puede quedar fuera de v1 (el dueño pega un `pya_tokens.json` nuevo) o, más adelante, un flujo asistido equivalente al portal.

### 5.3 Módulo tiendas (`/api/stores`)

- `GET /api/stores` — query: `platform`, `brand`, `status`, `open_now`, `excluded`, `q`. Lista completa (abiertas incluidas).
- `GET /api/stores/{platform}/{id}` — detalle del snapshot + próxima apertura si viene.
- `POST /api/stores/activate` — body: `{ "platform": "uber"|"pedidosya", "store_ids"|"names": [...], "confirm": false }`. Sin `confirm` = dry-run (muestra payload/locales resueltos). Con `confirm=true` llama `uber.py activate` / `pya.py activate`. Verificar con lectura (`monitor`) y devolver estado resultante.
- `POST /api/stores/pause` — Uber: `duration` ∈ {10,20,30,60,`rest_of_day`} + `reason`. PedidosYa: `minutes` opcional (sin minutos = fin de turno) + `reason`. Misma regla dry-run / confirm. No inventar pausa indefinida en Uber.

Permiso: rol `operator` o agente con scope `stores.write`. Auditar cada intento.

### 5.4 Módulo disputas + imágenes (fusión)

Un solo módulo, no dos proyectos: el listado de cobros/reclamos y las fotos del mismo pedido conviven.

**Uber**

- `GET /api/disputes?platform=uber&status=pending&start=&end=` — envuelve `uber.py disputes --json`. Campos públicos: tienda, `order_id`, fecha, monto CLP, issue/tag, state, ventana, `eligibility` solo si vino.
- `GET /api/disputes/uber/{order_id}` — detalle + fotos: llama `dispute-photos` (lectura). Devuelve metadatos y URLs **del propio panel** (`/api/disputes/uber/{order_id}/media/{n}`), no las URLs firmadas crudas si se pueden proxificar. Comentario del cliente y explicación de Uber sí; PII extraída de imágenes no se OCR-ea salvo que se pida después.
- `POST /api/disputes/uber/{order_id}/submit` — envuelve `uber.py dispute`. Body: `workflow`, `restaurant`, `reason`, `description?`, `evidence_ids[]`, `confirm`. **v1: default dry-run.** `confirm=true` queda marcado como “no verificado en vivo” hasta que el dueño autorice una prueba real (pedido de bajo monto). Evidencia: máx. 3 archivos, 100 MB, jpg/png/mp4… según el CLI. Multipart GraphQL aún no probado: el endpoint debe fallar claro si Uber rechaza el upload, no inventar éxito.

**PedidosYa**

- `GET /api/disputes?platform=pedidosya` — **no** devolver un conteo de “disputas sin abrir”. Devolver `coverage` + mosaicos `issues` como `complaint_tiles` (reclamos/descuentos).
- `GET /api/orders/pedidosya/{order_id}?photos=true` — `pya.py order <id> --photos`. Incluir `isDisputeAllowed`, `dispute.status`, ítems, y fotos via proxy `/api/orders/pedidosya/{order_id}/media/{n}`. Si `urls: []`, responder lista vacía (es válido).
- `POST /api/disputes/pedidosya/{order_id}/submit` — **501** con mensaje: no hay endpoint de envío; el flujo real es Help Center / `cases-api`. No simular éxito. Futuro: capturar HAR de una disputa real en el portal y cablear `cases-api` (otro adapter), siempre dry-run primero.

**Media**

- Guardar descargas en `media/{platform}/{order_id}/` con nombre opaco.
- `GET /api/.../media/{n}` autenticado; `Content-Disposition: attachment` o inline según tipo; cache corto.
- Flag `sensitive: true` si el operador lo marca o si una heurística futura lo detecta. No adjuntar cédulas a chats ni a reportes exportados por defecto.

### 5.5 Módulo reportes (`/api/reports`)

Exporta lo que **ya** entregan los CLI, en JSON/CSV/XLSX.

`GET /api/reports` — catálogo (id, plataforma, descripción, parámetros, formatos).

`POST /api/reports/run` — `{ "report": "<id>", "platform", "start", "end", "stores?", "format": "json"|"csv"|"xlsx", "confirm" no aplica (es lectura) }`.

Reportes a cablear (nombres estables):

| id | Plataforma | CLI | Qué exporta |
|---|---|---|---|
| `stores_snapshot` | ambas | snapshot | tiendas + estados (el panel ya lo tiene) |
| `uber_disputes` | uber | `disputes --csv` | cobros / disputas |
| `uber_sales` | uber | `sales` | ventas y ops |
| `uber_soldout` | uber | `soldout-report` | agotados |
| `uber_hours` | uber | `hours` | horarios |
| `pya_sales` | pya | `sales` | ventas / cancelados / atrasados |
| `pya_soldout` | pya | `soldout-report` | agotados |
| `pya_reviews` | pya | `reviews` | reseñas (sin datos extra de cliente) |
| `pya_ratings` | pya | `ratings` | promedios |
| `pya_issues` | pya | `issues` | reclamos (etiquetar como reclamos) |
| `pya_orders` | pya | `orders` | historial; ojo PerimeterX |
| `pya_payouts` | pya | `payouts` | pagos |
| `pya_earnings` | pya | `earnings` | resumen de earnings |
| `pya_invoices` | pya | `invoices` | facturas |
| `pya_vos_<nombre>` | pya | `report <nombre>` | ver lista debajo |

Nombres válidos de `pya.py report`: `performance`, `performance/summary`, `ops/summary`, `dishes`, `heatmap`, `eod`, `area`, `avg_acceptance_time`, `awt`, `contact-rate`, `customer_conversion`, `customer_retention`, `customers/summary`, `offline_duration`, `order_rejection`, `orders-marked-as-ready`, `out-of-stock`, `prep_time`.

Los archivos quedan en `data/exports/` con timestamp Chile y se listan en `GET /api/reports/jobs/{id}`. No incluir fotos sensibles en un Excel de reportes.

### 5.6 Módulo catálogo / apagados y prendidos masivos (`/api/catalog`)

- `GET /api/catalog/soldout?platform=&store=` — `soldout-report`.
- `POST /api/catalog/soldout` — `{ platform, stores[], item, match: "exact"|"contains", until, confirm }`. Uber: `until=today|indefinite`. PedidosYa: `indefinite|tomorrow|<minutos>`. Dry-run lista locales + ids resueltos. `--yes` solo con confirm. Verificar con lectura.
- `POST /api/catalog/instock` — mismo shape, `instock`.
- `POST /api/catalog/activate-menu` — `{ platform, stores? , extra_excludes[], confirm }`. Usa exclusiones por defecto del CLI. Log CSV como hoy (`uber-activacion-AAAA-MM-DD.csv` / `pedya-activacion-AAAA-MM-DD.csv`), expuesto como artefacto del job. Benedictinos u otros agotados intencionales se respetan vía `--exclude` (nunca reactivar lo excluido).

Límite: no cambiar precios ni estructura de menú. Jobs con progreso (N tiendas) y resumen ok/error/omitido.

### 5.7 Automatizaciones (`/api/automations`)

Informes programables y, más adelante, acciones recurrentes.

Modelo:

```
{ "id", "name", "kind": "report"|"refresh_snapshot"|"catalog_activate_menu"|"catalog_soldout",
  "schedule": "cron 5 campos, TZ America/Santiago",
  "payload": { ... mismos campos que el endpoint manual ... },
  "enabled": true,
  "created_by": "user|agent:<id>",
  "last_run_at", "last_status", "last_error" }
```

- `GET/POST /api/automations`
- `PATCH /api/automations/{id}` (pausar/editar)
- `DELETE /api/automations/{id}`
- `POST /api/automations/{id}/run` — disparo manual

Reglas:

- `kind=report` y `refresh_snapshot` son lecturas: se pueden habilitar con rol `operator` o agente `automations.write`.
- `kind` de escritura (`activate-menu`, `soldout`, `pause`, `activate` tiendas) exige `confirm_writes: true` guardado en la automatización **y** que el creador tenga scope `catalog.write` / `stores.write`. En v1 se recomienda soportar solo reportes + refresh de snapshot; dejar escrituras programadas detrás de un flag `ALLOW_SCHEDULED_WRITES=false` por defecto.
- Mínimo 15 minutos entre corridas del mismo job.
- Entrega del informe: guardar archivo en `data/exports/` y, opcional, webhook URL configurada (no email no pedido). No enviar Slack/WhatsApp/correo salvo que el dueño lo pida después y se respeten las reglas de envío.
- Persistencia en `data/automations.json` o SQLite liviano. Un worker (mismo proceso o contenedor `worker`) con lock; no varias réplicas sin lock compartido (el README actual ya lo advierte).

### 5.8 Agentes por API key (`/api/agents`)

Para que Analista, Orquestador u otros bots hablen con el panel sin usar la cookie de persona.

- `GET /api/agents` — lista: nombre, scopes, `created_at`, `last_used_at`, prefijo de la key (`tdk_ab12…`). Nunca la key completa.
- `POST /api/agents` — `{ "name", "scopes": ["snapshot.read", "reports.read", "stores.write", ...] }`. Genera una key aleatoria (p. ej. 32+ bytes urlsafe), se muestra **una sola vez** en la respuesta de creación. Guardar solo hash (sha256) en `data/agents.json` modo 0600.
- `PATCH /api/agents/{id}` — revocar o cambiar scopes / nombre.
- `DELETE /api/agents/{id}` — revocar.

Auth de requests: header `Authorization: Bearer <key>`. Rate limit por key. Scopes sugeridos:

| scope | Permite |
|---|---|
| `snapshot.read` | GET snapshot, GET stores |
| `reports.read` | listar y correr reportes |
| `disputes.read` | listar disputas y ver media |
| `stores.write` | pause / activate (sigue exigiendo `confirm`) |
| `catalog.write` | soldout / instock / activate-menu |
| `disputes.write` | submit Uber (sigue exigiendo `confirm`; PYA 501) |
| `credentials.write` | reponer sesiones (solo operator humano en v1; no dar este scope a agentes salvo pedido explícito) |
| `automations.write` | crear jobs |
| `agents.admin` | emitir otras keys (solo operator) |

Un agente **no** bypassa dry-run: el body debe traer `confirm=true` para escribir. Las automatizaciones que cree un agente quedan auditadas con `created_by=agent:<id>`.

---

## 6. Frontend (módulos de UI)

Partir del HTML/JS/CSS del paquete servidor (login + snapshot + refresh). Añadir navegación por módulos:

1. **Monitoreo** — métricas + tabla de tiendas (todas, no solo “atención”) + filtros plataforma/marca/estado/exclusión. Salud de fuentes y hora del snapshot (Chile). Sin botón que finja “en vivo”: el botón es “Actualizar snapshot”.
2. **Disputas** — pestaña Uber (pendientes, monto, tienda, fecha) y pestaña PedidosYa (reclamos, con leyenda de que no son disputas). Al abrir un pedido: fotos + metadatos. Acción “Preparar disputa” (dry-run) en Uber; PedidosYa muestra “no disponible por API”.
3. **Tiendas** — buscar y **Prender** / **Pausar** con resumen dry-run y botón Confirmar.
4. **Catálogo** — informe de agotados; acciones masivas soldout / instock / activate-menu con exclusiones editables y log del job.
5. **Reportes** — catálogo, rango de fechas, descarga.
6. **Automatizaciones** — lista cron + último resultado.
7. **Credenciales** — semáforos por fuente + formulario para reemplazar archivo (sin mostrar el valor previo).
8. **Agentes** — crear/revocar API keys; la key cruda solo en el dialog de creación.

No imitar la UI de Uber/Rappi/PedidosYa. No pedir contraseñas de plataforma en texto plano reutilizable fuera del módulo de credenciales.

---

## 7. Modelo de datos mínimo

Extender el snapshot actual, no romperlo:

```
{
  "generated_at": "ISO con offset Chile",
  "timezone": "America/Santiago",
  "sources": {
    "uber": { "status", "fetched_at", "error", "stores_count",
              "disputes_status", "disputes_count", "disputes_window" },
    "pedidosya": { "...", "disputes_status": "no_direct_list" },
    "rappi": { "status": "pending", "stores_count": null }
  },
  "stores": [ { "platform", "store_id", "name", "brand", "status",
                "open_now", "enabled", "reason", "since", "until",
                "next_open", "next_close", "excluded" } ],
  "disputes": [ { "platform": "uber", "store_name", "order_id",
                  "ordered_at", "amount_clp", "issue", "tag", "state",
                  "eligibility", "window_start", "window_end" } ],
  "complaint_tiles": [ /* solo PYA, no sumar a disputes_count */ ],
  "coverage": { /* textos honestos ya usados en el panel */ }
}
```

Jobs de escritura / reporte:

```
{ "id", "kind", "created_at", "created_by", "dry_run", "status": "queued|running|done|error",
  "input_sanitized", "result_summary", "artifact_path?" }
```

---

## 8. Seguridad y despliegue

Conservar del paquete actual: `.env` (`DOMAIN`, `PANEL_USER`, `PANEL_PASSWORD`, `SESSION_SECRET`, `SESSION_SECURE`), Caddy público, app interna, volúmenes `data` y `sessions` modo 700, healthz ciego, tests de auth.

Añadir:

- `AGENT_KEYS_PATH` (default `data/agents.json`)
- `ALLOW_SCHEDULED_WRITES=false`
- `MEDIA_DIR=media`
- Headers de seguridad en Caddy (no CORS `*`)
- Rate limit de login (ya hay intento) y de API keys
- El contenedor no debe exponer una shell a terceros: los CLI todavía contienen `--yes`

README: mismos pasos de DNS A/AAAA, puertos 80/443, `docker compose up --build -d`. Documentar el módulo de credenciales como alternativa a `install -m 600` por SSH.

---

## 9. Plan de implementación en Cursor (orden sugerido)

1. Importar `delivery-monitor-servidor` como raíz del repo (sin `sessions/*` reales, sin `snapshot.json` real, sin `.env`).
2. Tests existentes en verde (`python3 -m unittest discover -s tests -v`).
3. Módulo **credenciales** + status/health (desbloquea todo lo demás cuando caduca Uber/PYA).
4. Extender snapshot/UI si hace falta (listado completo de abiertas: ya está en el ZIP).
5. Módulo **disputas + media** (Uber listado + fotos; PYA `order --photos`; submit Uber dry-run; submit PYA = 501).
6. Módulo **tiendas** activate/pause.
7. Módulo **catálogo** soldout/instock/activate-menu.
8. Módulo **reportes** (empezar por sales, soldout-report, disputes, issues, reports VOS de PYA).
9. Módulo **agentes** (API keys + scopes).
10. Módulo **automatizaciones** (solo reportes + refresh en v1).
11. README actualizado y tests nuevos: auth, dry-run no escribe, confirm escribe (mock del CLI), PYA issues ≠ disputa, 401 no se vuelve cero, keys hasheadas, media requiere auth.

No hace falta reescribir `uber.py` / `pya.py` salvo bugs descubiertos; el panel los orquesta.

---

## 10. Criterios de aceptación

- El operador entra por HTTPS, ve el snapshot con hora Chile y fuentes honestas (Rappi pending, PYA sin conteo falso de disputas).
- Puede reponer cookie Uber / tokens PYA desde el panel y el health check pasa o falla sin filtrar el secreto.
- Puede listar cobros Uber pendientes, abrir un pedido y ver fotos vía URL del panel.
- Puede ver un pedido PYA con `--photos` y, si no hay fotos, una lista vacía.
- “Enviar disputa” en PYA responde no disponible. En Uber, dry-run arma el payload; `--yes` no se dispara sin `confirm=true`.
- Prender/pausar tienda y soldout/instock/activate-menu respetan dry-run → confirm → verificación, con log por local.
- Un reporte exportable descarga CSV/XLSX generado desde el CLI real.
- Un agente con API key lee snapshot y no puede escribir sin scope ni sin `confirm`.
- Una automatización de informe corre según cron Chile y deja el archivo en `data/exports/`.
- Ningún test ni log contiene cookies, tokens o API keys en claro.

---

## 11. Fuera de alcance (v1)

- Comprar/configurar el dominio (lo hace el dueño con DNS + este Compose).
- Adapter Rappi con cifras (hasta token/CLI).
- Enviar disputas PedidosYa (Help Center no cableado).
- `uber.py dispute --yes` en producción sin una prueba real autorizada por el dueño.
- Datos de cliente (dirección/teléfono) en delivery de PedidosYa: la API del portal no los entrega en `platform_delivery`.
- Cambiar precios, nombres o estructura de catálogo.
- Migrar la rutina de navegador “Renovar cookie Uber” al servidor (el módulo de credenciales la sustituye de forma manual; automatizar el browser en el VPS es otro proyecto).
- Envío no solicitado de emails, Slack o WhatsApp.

---

## 12. Referencias locales

- `/workspace/delivery-monitor-servidor.zip` — paquete desplegable actual (solo lectura).
- `/workspace/delivery-monitor/` — capa de integración y tests del snapshot.
- `/workspace/uber_client/README.md` y `uber.py`
- `/workspace/pya_client/README.md` y `pya.py`
- Skills: `uber-eats-api`, `pedidosya-api`, `reglas-de-oro-monitoreo-delivery`
- `/workspace/docs/scripts-uber-pedidosya.md` — guía de alcance de los CLI
- `/workspace/rappi-api-probe/NOTES.md` y `stores-summary.json` — verificación de API Rappi (sin token persistido)
