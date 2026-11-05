# Panel de monitoreo de delivery (servidor)

Panel web de **solo lectura** para tiendas y cobros/disputas sin abrir de Uber y PedidosYa.
Rappi queda como integración pendiente, sin cifras inventadas.

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

No hay endpoints que pausen, activen, agoten productos ni envíen disputas.

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
mkdir -p data sessions
chmod 700 sessions data
# Si el contenedor no puede escribir el snapshot:
# sudo chown 1000:1000 data sessions
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

## Extender

Cada plataforma vive en `delivery_monitor/adapters/`. Las rutas de los CLI salen de `UBER_CLI` / `PYA_CLI` (por defecto `/app/clients/...`), no de `/workspace`. Los dos `api_client.py` se ejecutan en subprocesos distintos y no heredan `PANEL_PASSWORD` ni `SESSION_SECRET`.

Para sumar un proveedor: implementar `fetch()` → `ProviderResult`, registrarlo en `ADAPTERS` y volver a generar un snapshot.

## Límites

- No se despliegan remotamente ni se compra el dominio desde este paquete: eso lo hace el dueño con su DNS y este `compose`.
- Rappi: integración pendiente.
- PedidosYa: sin listado de disputas; no se recorre `order` pedido a pedido.
- Uber: la elegibilidad de disputa solo aparece si el JSON la trae.
- Las copias de `uber.py` y `pya.py` conservan comandos de escritura (`--yes`). **Este panel no los invoca.** No exponga una shell del contenedor a terceros.
- Un worker de Uvicorn. No escale `app` a varias réplicas si usa el candado de refresh en memoria.

## Estructura

```
app/                  FastAPI + frontend estático
delivery_monitor/     adaptadores y snapshot
clients/uber/         copia aislada de uber.py + api_client.py
clients/pya/          copia aislada de pya.py + api_client.py + gql/
data/                 snapshot (vacío en el paquete)
sessions/             secretos montados por el dueño (no vienen en el zip)
tests/
Dockerfile compose.yaml Caddyfile
```
