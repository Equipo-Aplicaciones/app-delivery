# Panel de monitoreo de delivery (servidor)

Panel web para tiendas, cobros/disputas de Uber y reclamos de PedidosYa, con las fotos que la tienda
sube desde la app delivery. Lee en vivo o desde un snapshot; las escrituras (credenciales, disputa) van
siempre con chequeo previo o dry-run. Rappi queda como integración pendiente, sin cifras inventadas.

La Page del chat no se despliega: este paquete trae un frontend HTML/JS/CSS y un backend FastAPI
que leen un snapshot generado por los mismos adaptadores (copias aisladas de `uber.py` y `pya.py`).

Zona horaria: `America/Santiago`.

## Qué incluye

- Listado de **todas** las tiendas (también las abiertas), con filtros de plataforma, marca, vista, exclusión y búsqueda.
- Módulo de **disputas o cobros sin abrir** (Uber: pendientes de los últimos 30 días). PedidosYa no tiene listado equivalente: los mosaicos de reclamo **no** se cuentan como disputa.
- Salud de fuentes (estado, hora de lectura, errores). Si no hay snapshot, se muestra pendiente de configuración, no un cero.
- Refresh manual autenticado. Intervalo opcional (`REFRESH_INTERVAL_MINUTES`, mínimo 15; `0` lo deja apagado y no corre al arrancar).
- Autenticación obligatoria (usuario y contraseña por entorno o archivo). Cookie HttpOnly, sin secretos en la URL ni en localStorage.
- Reverse proxy Caddy con TLS. El backend no publica puertos al exterior.
- Módulo **Disputas** (pestañas Uber, PedidosYa y búsqueda de fotos de la app): ficha por pedido con fotos del cliente, evidencia de la tienda, fotos de la app delivery y preparación de disputa Uber en dry-run.
- Módulo **Credenciales**: semáforo por fuente y reposición de cookie/tokens con prueba previa.
- Módulos **Tiendas**, **Catálogo**, **Reportes**, **Automatizaciones** y **Agentes** (detalle abajo).

Toda escritura (prender/pausar tiendas, agotar/reponer, activar menú) corre primero en dry-run y solo
se envía con `confirm=true`; el navegador pide una segunda confirmación. El envío real de una disputa
Uber está apagado (`ALLOW_UBER_DISPUTE_SUBMIT=false`) hasta que el dueño autorice una prueba en vivo.

## Disputas e imágenes

| Ruta | Qué hace |
|---|---|
| `GET /api/disputes?platform=uber` | Cobros del snapshot; `&live=true` consulta `uber.py disputes --json` (filtros `status`, `start`, `end`, `store_id`). |
| `GET /api/disputes?platform=pedidosya` | `disputes_status: no_direct_list` y `complaint_tiles` (reclamos, no disputas). `&live=true` consulta `pya.py issues`. |
| `GET /api/disputes/uber/{pedido}` | Ficha: datos del cobro, fotos (`uber.py dispute-photos`, se guardan en `MEDIA_DIR`), fotos de la app y estado del envío. `&refresh=true` vuelve a descargar. |
| `POST /api/disputes/uber/{pedido}/submit` | `{reason, description, evidence_ids, app_evidence_ids, confirm}`. Sin `confirm` corre `uber.py dispute --dry-run`. Con `confirm=true` exige `ALLOW_UBER_DISPUTE_SUBMIT=true`; si no, 403. Máximo 3 evidencias. La respuesta siempre trae `verified: false`. |
| `POST /api/disputes/pedidosya/{pedido}/submit` | 501: PedidosYa no tiene envío por API. |
| `GET /api/orders/pedidosya/{pedido}?store_id=…&photos=true` | `pya.py order --photos --download`: pedido sin datos del cliente y fotos del reclamo. |
| `GET /api/evidence/{uber\|pedidosya}?numero_orden=…` | Fotos que la tienda subió con la app delivery (Edge Function `evidencia`). |
| `PATCH /api/media/{plataforma}/{pedido}/{id}` | `{sensitive: true}` difumina la imagen en el panel (por ejemplo, un documento de identidad). |

Las imágenes se sirven solo con sesión (`Cache-Control: private`). Las URLs firmadas de Supabase y la
clave `x-evidencia-key` nunca llegan al navegador: el panel hace de proxy y solo acepta URLs del mismo
host que `EVIDENCIA_URL`. Cada intento de escritura queda en `data/acciones.jsonl` (sin secretos).

La clave de evidencia se configura en el servidor: `EVIDENCIA_API_KEY` o `EVIDENCIA_API_KEY_FILE`
(por ejemplo `/sessions/evidencia_api_key`, modo 600). `EVIDENCIA_URL` por defecto apunta al proyecto
de la app delivery.

## Tiendas y catálogo

| Ruta | Qué hace |
|---|---|
| `GET /api/stores` | Tiendas del snapshot (`platform`, `brand`, `status`, `open_now`, `excluded`, `q`). |
| `GET /api/stores/meta/options` | Duraciones y motivos válidos de pausa por plataforma. |
| `POST /api/stores/activate` | `{platform, store_ids \| names, confirm}` → `uber.py\|pya.py activate`. |
| `POST /api/stores/pause` | Uber: `duration` (10, 20, 30, 60, `rest_of_day`) y `reason`. PedidosYa: `reason` y `minutes` opcional. |
| `GET /api/catalog/soldout?platform=…&store=…` | `soldout-report --json`. |
| `POST /api/catalog/soldout` / `instock` | `{platform, item, match: "contains", until, names, confirm}`. Sin tiendas aplica a todas. |
| `POST /api/catalog/activate-menu` | Activa ítems pausados respetando las exclusiones del CLI y `extra_excludes`. |

Sin `confirm: true` (booleano) se pasa `--dry-run`; con él, `--yes`. Un solo comando de escritura corre
a la vez. La respuesta trae `verified: false`: actualice el snapshot para ver el estado real.

## Reportes

`GET /api/reports` lista el catálogo (ventas, agotados, horarios, reseñas, ratings, reclamos, pedidos,
pagos, facturas y los 18 reportes VOS de PedidosYa, más la exportación del snapshot).
`POST /api/reports/run` `{report, format: json|csv, start, end, store, status, days}` crea un job;
el archivo queda en `data/exports/` (modo 600) y se descarga con sesión en
`GET /api/reports/jobs/{id}/download`. Las fechas van en `AAAA-MM-DD`.

## Automatizaciones

`/api/automations` guarda jobs `refresh_snapshot` o `report` con un cron de 5 campos en hora de Chile
(`0 8 * * 1-5`). El programador corre dentro del panel (`AUTOMATIONS_SCHEDULER=true`), con al menos
15 minutos entre corridas de un mismo job; «Ejecutar ahora» usa `POST /api/automations/{id}/run`.
Los tipos de escritura (`stores_pause`, `catalog_soldout`, …) se rechazan con
`ALLOW_SCHEDULED_WRITES=false` y no están cableados en v1.

## Agentes (API keys)

`POST /api/agents` `{name, scopes}` devuelve la clave `tdk_…` **una sola vez**; el servidor guarda solo
su SHA-256 en `data/agents.json`. El agente llama con `Authorization: Bearer tdk_…` y cada ruta exige un
scope:

| Scope | Rutas |
|---|---|
| `snapshot.read` | `/api/snapshot`, `/api/health`, `/api/refresh`, `GET /api/stores` |
| `reports.read` | `/api/reports/*`, `GET /api/catalog/soldout` |
| `disputes.read` / `disputes.write` | lectura de disputas, pedidos y evidencia / envío y marcado de fotos |
| `stores.write` / `catalog.write` | escrituras de Tiendas / Catálogo (con las mismas reglas de dry-run) |
| `automations.write` | `/api/automations` |

`/api/credentials` y `/api/agents` quedan solo para el operador humano (`credentials.write` y
`agents.admin` no se entregan). Límite por clave: `AGENT_RATE_LIMIT_PER_MIN` (120). Revocar con
`DELETE /api/agents/{id}`; la clave deja de servir de inmediato.

## Credenciales

- `GET /api/credentials/status` (`?check=true` fuerza el chequeo): `configured`, `missing`, `expired`, `unknown` o `pending` para Uber, PedidosYa, Rappi y la API de evidencia. El chequeo es una lectura mínima (lista de tiendas) y se guarda 10 minutos.
- `PUT /api/credentials/uber` y `/pedidosya` (campo `value` o archivo `file`, máx. 64 KB): prueba el valor en un HOME aislado y solo si pasa reemplaza `sessions/…` de forma atómica (queda un `.bak`). Si falla, 422 y la sesión anterior sigue intacta. La respuesta nunca devuelve el valor.
- `DELETE /api/credentials/{fuente}`: primero dry-run; `?confirm=true` borra.
- `PUT /api/credentials/evidencia` (campo `value`): prueba la clave contra la API de evidencia y solo
  si responde la guarda en `sessions/evidencia_api_key` (0600). 409 si la clave viene fijada por
  `EVIDENCIA_API_KEY` o `EVIDENCIA_API_KEY_FILE`. Nunca se devuelve.
- Rappi: 501 hasta tener CLI y credenciales oficiales.

## Panel exclusivo de disputas

App aparte (`app.disputas_app:app`) con solo dos secciones: Disputas y Credenciales. Menú
hamburguesa con Uber Eats y PedidosYa; el panel superior cambia según el agregador.

```bash
PANEL_AUTH=false uvicorn app.disputas_app:app --host 127.0.0.1 --port 8002
```

- `PANEL_AUTH=false` lo deja **sin inicio de sesión** (por defecto `true`, con el mismo login
  del panel principal). Sin login, cualquiera con la URL ve fotos de clientes y puede
  reemplazar credenciales: úselo solo detrás de una red privada, Cloudflare Access o similar.
  El panel principal (`app.main`) sigue exigiendo login salvo que se exporte esa variable.
- Filtros: pendiente, abierta, cerrada ganada y cerrada perdida.
  - Uber: el estado sale del tag de Uber (`ISSUE_CHARGED` = pendiente, `DISPUTE_*` en curso =
    abierta, `DISPUTE_ACCEPTED` = ganada, `DISPUTE_DENIED`/`REJECTED` = perdida).
  - PedidosYa no tiene disputas por API: los pedidos con problemas salen de `orders --issues`
    y el estado se lleva en un registro local (`data/disputas_registro.json`).
- Estadísticas: Uber muestra conteo y monto por estado, tasa de éxito y contadores de Uber;
  PedidosYa muestra los indicadores de «Problemas de pedidos».
- «Actualizar» (`POST /api/panel/refresh`) corre en segundo plano (hasta 30 días) y se consulta
  con `GET /api/panel/refresh`; el resultado queda en `data/disputas_cache.json`.
- «Buscar imagen manual»: con el número de pedido trae las fotos de la app delivery (API de
  evidencia) y, si se pide, las de la plataforma. Con las fotos elegidas arma el request:
  - Uber: dry-run de `uber.py dispute` (máx. 3 fotos); el envío real sigue tras
    `ALLOW_UBER_DISPUTE_SUBMIT`.
  - PedidosYa: paquete con el texto para pegar en el portal de socios; se marca enviada,
    ganada o perdida a mano.
- Si PedidosYa bloquea el listado por pedido (anti-bots, HTTP 403), los indicadores siguen y
  los pedidos se pueden abrir a mano por número.

Al arrancar, el panel enlaza `~/.uber_cookie` y `~/.pya_tokens.json` del usuario de los CLI
(`CLI_HOME`) a `SESSIONS_DIR`, sin pisar archivos propios.

## Arranque en el servidor

En el directorio de este proyecto, **en la terminal del servidor** (no en un chat):

```bash
cp .env.example .env
chmod 600 .env

# Genere secretos y péguelos en .env con un editor local:
python3 -c 'import secrets; print("PANEL_PASSWORD="+secrets.token_urlsafe(18)); print("SESSION_SECRET="+secrets.token_urlsafe(48))'
```

Edite `.env` y complete:

- `DOMAIN` — el nombre que apuntará a este servidor (por ejemplo `panel.midominio.cl`).
- `PANEL_USER` — usuario del panel.
- `PANEL_PASSWORD` — la clave generada (mínimo 12 caracteres; no se aceptan ejemplos ni claves débiles).
- `SESSION_SECRET` — el secreto generado (mínimo 32 caracteres).
- `SESSION_SECURE=true` cuando Caddy sirva HTTPS.

Cree los directorios de volumen y, si hace falta, dele permiso al usuario del contenedor (uid 1000):

```bash
mkdir -p data sessions media
chmod 700 sessions data media
# Si el contenedor no puede escribir el snapshot, las fotos o reponer sesiones:
# sudo chown 1000:1000 data sessions media
```

### Sesiones de Uber y PedidosYa

El panel **no** inicia sesión en los portales ni renueva cookies con un navegador.

El dueño copia en `sessions/` los archivos que ya existen en su máquina de trabajo:

```bash
# Desde una máquina donde ya funcionan los CLI, como el dueño:
install -m 600 /ruta/a/.uber_cookie sessions/uber_cookie
install -m 600 /ruta/a/.pya_tokens.json sessions/pya_tokens.json
```

- Uber lee `~/.uber_cookie` (el contenedor lo enlaza desde `/sessions/uber_cookie`). Caduca; un 401/403 exige una cookie nueva. No se incluye `refresh_uber_cookie.py` a propósito: esa rutina del navegador local no se migra sola.
- PedidosYa lee `~/.pya_tokens.json`. Su cliente puede refrescar el *access token* con el *refresh token* si el archivo es escribible. Eso no sustituye un login nuevo cuando el refresh también caduca.
- Nunca ponga cookies ni tokens en `.env` salvo que sepa lo que hace (`UBER_COOKIE` existe en el cliente original, pero el archivo montado es más seguro).
- El frontend nunca ve estos secretos: solo habla con la API del panel, ya autenticado.

### DNS y puertos

1. Cree un registro **A** (IPv4) y, si aplica, **AAAA** (IPv6) de `DOMAIN` hacia la IP pública del servidor.
2. Abra los puertos **80** y **443** hacia este equipo. Caddy usa el 80 para el desafío ACME y sirve HTTPS en el 443.
3. El servicio `app` no publica puertos: solo Caddy es alcanzable desde internet.

Para un ensayo local sin certificado público, ponga `DOMAIN=localhost` y `CADDY_TLS=internal` en `.env` (certificado interno de Caddy).

### Levantar

```bash
docker compose up --build -d
```

La primera vez Caddy pedirá el certificado de Let's Encrypt para `DOMAIN` (si `CADDY_TLS` está vacío y el DNS ya apunta aquí).

### Comprobar

```bash
# El backend, por dentro del compose, responde sin datos:
docker compose exec app python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8000/healthz').read())"

# Desde fuera, sin cookie, la API no entrega datos:
curl -sS -o /tmp/out -w '%{http_code}\n' https://$DOMAIN/api/snapshot
# debe ser 401

curl -sS -o /tmp/out -w '%{http_code}\n' https://$DOMAIN/healthz
# 200 {"status":"ok"} — no revela tiendas ni secretos
```

Entre al navegador en `https://DOMAIN`, inicie sesión y, cuando las sesiones estén montadas, pulse **Actualizar snapshot**.

Para detener: `docker compose down`.

## Qué ocurre si no hay snapshot

El panel muestra las fuentes en estado pendiente (o el error de lectura) **sin inventar ceros**.
Rappi siempre queda pendiente hasta que exista un cliente y credenciales.

## Refresh

- Manual: botón del panel o `POST /api/refresh` con la cookie de sesión.
- Si ya hay uno en curso: HTTP 409.
- Tiempo máximo: `REFRESH_TIMEOUT` (por defecto 420 s).
- Opcional: `REFRESH_INTERVAL_MINUTES=60` (mínimo 15). No sustituye un cron externo y **no se ejecuta al arrancar**.

Comando equivalente dentro del contenedor (también autenticación de plataforma, no del panel):

```bash
docker compose exec app python3 /app/refresh.py
```

## Desarrollo local (sin Docker)

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
export PANEL_USER=devuser
export PANEL_PASSWORD='una-clave-de-prueba-larga'
export SESSION_SECRET='un-secreto-de-al-menos-treinta-y-dos-xx'
export SESSION_SECURE=false
export SNAPSHOT_PATH="$PWD/data/snapshot.json"
export MEDIA_DIR="$PWD/media" SESSIONS_DIR="$PWD/sessions" CLI_HOME="$PWD/.cli-home"
export UBER_CLI="$PWD/clients/uber/uber.py"
export UBER_CLI_CWD="$PWD/clients/uber"
export PYA_CLI="$PWD/clients/pya/pya.py"
export PYA_CLI_CWD="$PWD/clients/pya"
python3 -m unittest discover -s tests -v
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

## Pruebas

```bash
python3 -m unittest discover -s tests -v
```

Cubren clasificación (horario vs pausa vs inactiva), esquema, errores 403 que no se convierten en cero, reclamos de PedidosYa que no son disputa, Rappi sin cifras inventadas, y autenticación del panel.

`tests/test_modules.py` cubre los módulos nuevos con subprocesos y HTTP simulados: sesión obligatoria
en todas las rutas, dry-run sin `--yes`, 403 al confirmar sin el flag, 501 de PedidosYa y Rappi,
credenciales que nunca vuelven en respuestas ni en la auditoría, reemplazo atómico que conserva la
sesión vigente si la nueva falla, fotos solo con sesión, y la clave/URLs firmadas de evidencia ocultas.

## Extender

Cada plataforma vive en `delivery_monitor/adapters/`. Las rutas de los CLI salen de `UBER_CLI` / `PYA_CLI` (por defecto `/app/clients/...`), no de `/workspace`. Los dos `api_client.py` se ejecutan en subprocesos distintos y no heredan `PANEL_PASSWORD` ni `SESSION_SECRET`.

Para sumar un proveedor: implementar `fetch()` → `ProviderResult`, registrarlo en `ADAPTERS` y volver a generar un snapshot.

## Límites

- No se despliegan remotamente ni se compra el dominio desde este paquete: eso lo hace el dueño con su DNS y este `compose`.
- Rappi: integración pendiente.
- PedidosYa: sin listado de disputas; no se recorre `order` pedido a pedido.
- Uber: la elegibilidad de disputa solo aparece si el JSON la trae.
- Las copias de `uber.py` y `pya.py` conservan comandos de escritura (`--yes`). El panel solo invoca `uber.py dispute --yes` si `ALLOW_UBER_DISPUTE_SUBMIT=true` y el operador confirma; ese envío **no está verificado en vivo**. No exponga una shell del contenedor a terceros.
- `pya.py order` necesita la tienda: el panel la pide explícitamente en vez de usar la primera.
- `X-Forwarded-For` se toma tal cual para el límite de intentos de login; detrás de un proxy que no lo reescriba, un cliente podría falsearlo.
- Un worker de Uvicorn. No escale `app` a varias réplicas si usa el candado de refresh en memoria.

## Estructura

```
app/                  FastAPI + frontend estático
delivery_monitor/     adaptadores y snapshot
clients/uber/         copia aislada de uber.py + api_client.py
clients/pya/          copia aislada de pya.py + api_client.py + gql/
app/modules/          credenciales, disputas, media, evidencia, tiendas, catálogo, reportes,
                      automatizaciones y agentes
data/                 snapshot, auditoría, jobs, exports, automatizaciones y agentes (no van a git)
media/                fotos de reclamo por plataforma/pedido (no van a git)
sessions/             secretos montados por el dueño (no vienen en el zip)
tests/
Dockerfile compose.yaml Caddyfile
```
