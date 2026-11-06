# Panel de Delivery Tarragona — resumen y tarea para el agente en la nube

Fecha: 2026-11-05 (America/Santiago)

## Dónde está todo

| Qué | Dónde |
|---|---|
| Repositorio (GitHub, privado) | https://github.com/juaking1312/app-delivery — rama `main` |
| Copia local (PC de jleiva) | `C:\nuevas descargas\dev tarragona\proyectos-cursor-app-delivery-bootstrap-08a4\app\app-delivery` |
| Especificación del panel | `panel-delivery-fuentes/docs/especificacion-panel-delivery-cursor.md` |
| Guía de los CLI | `panel-delivery-fuentes/docs/scripts-uber-pedidosya.md`, `panel-delivery-fuentes/docs/API_Tarragona.md` |
| Panel base (FastAPI + Docker + Caddy) | `panel-delivery-fuentes/delivery-monitor-servidor/` |
| CLI completos Uber / PedidosYa | `panel-delivery-fuentes/clientes/uber/`, `panel-delivery-fuentes/clientes/pya/` |
| App delivery (Expo, Android) | `iterations/v1/` |
| API de evidencia (Supabase Edge Function) | `iterations/v1/supabase/functions/evidencia/index.ts` |
| Migraciones Supabase | `supabase/migrations/` |
| Documentación de producto de la app | `idea/`, `audits/` |

Origen: `app-delivery` sale del repositorio WIKA (`proyectos-cursor-app-delivery-bootstrap-08a4.zip`). Las fuentes del panel salen de `panel-delivery-fuentes-2026-11-05.zip`.

## Qué es cada parte

**App delivery.** Cámara Android para fotografiar el pedido cuando hay que disputar una devolución. Cada foto se identifica por agregador (`uber` | `pedidosya`) y número de orden. La app no toca la base directo: habla con la Edge Function `evidencia` del proyecto Supabase `nfryurrhgaeepdwqtswo`.

- `POST` multipart (`agregador`, `numero_orden`, `imagen`): guarda el JPEG en el bucket privado `evidencia` y una fila en `public.evidencia`. Puede haber varias fotos por pedido.
- `GET ?agregador=&numero_orden=` → `{ "images": [{ "id", "created_at", "url" }] }`, con URL firmada de 10 minutos, o `{ "images": [] }`.
- Auth: header `x-evidencia-key`. La clave vive en `public.evidencia_clave` y solo la lee `service_role`. No está en el repositorio.

**Panel web.** Hay que construir un panel FastAPI + frontend + Docker Compose + Caddy que fusiona dos cosas: el monitoreo de tiendas que ya existe (`delivery-monitor-servidor`) y los CLI `uber.py` / `pya.py`, invocados por subproceso. Módulos: credenciales, tiendas, disputas + imágenes, catálogo, reportes, automatizaciones y agentes por API key. Las reglas clave son lectura libre con sesión, escritura solo con dry-run primero y `confirm=true`, y nunca exponer secretos ni URLs firmadas.

**Conexión entre el panel y la app.** El módulo de disputas une por pedido tres fuentes:

1. el CLI de la plataforma (cobros Uber, reclamos PedidosYa);
2. las fotos del cliente que trae la plataforma (`dispute-photos` / `order --photos`);
3. las fotos que la tienda sacó con la app delivery (función `evidencia`).

La clave de unión es `platform` + `order_id` = `agregador` + `numero_orden`. El backend del panel llama a `evidencia`; el navegador nunca ve la clave ni la URL firmada.

## Estado actual

- **Actualización 2026-11-05 21:35 (hora de Chile).** La rama `cursor/panel-disputas-credenciales-8fe5` ([PR #1](https://github.com/juaking1312/app-delivery/pull/1)) habilita todos los módulos de la especificación: credenciales, tiendas, disputas + imágenes, catálogo, reportes, automatizaciones y agentes. Tiene 101 tests OK. Qué se hizo, las decisiones y lo pendiente están en `panel-delivery-fuentes/docs/registro-panel-delivery-rama-1.md`.
- En Windows hace falta `pip install tzdata`; en Linux/Docker no.
- No hay secretos en el repositorio: ni cookies, ni tokens, ni `.env`, ni fotos reales.
- `iterations/v1/apk/app-delivery.apk` es un puntero de Git LFS (133 bytes), no el APK real.
- Lo que sigue es el deploy al servidor común, la prueba autorizada de disputa Uber y la clave de evidencia (ver el registro).

## Fuera de alcance por ahora

Rappi con cifras, envío de disputas PedidosYa (no hay endpoint), `uber.py dispute --yes` en producción sin prueba autorizada, datos de cliente de PedidosYa, cambios de precio o estructura de menú, envíos no pedidos por email, Slack o WhatsApp.

---

## Tarea para el agente en la nube (copiar y pegar)

Trabajás en el repositorio GitHub privado `juaking1312/app-delivery` (rama base `main`). Leé primero `RESUMEN-PANEL-DELIVERY.md` (este archivo) y la especificación completa en `panel-delivery-fuentes/docs/especificacion-panel-delivery-cursor.md`. Respondé y escribí la UI y los logs en español. La zona horaria del producto es `America/Santiago`. Esto es QA en TU máquina virtual: construí, levantá el servidor ahí, verificá y al final exponelo con un túnel para que el dueño pruebe funcionalidades, diseño y mejoras desde su navegador. El deploy al servidor común es posterior; no despliegues en ningún otro lado.

### Alcance de esta ronda (orden de la especificación, §9)

1. **Credenciales (§5.2).**
   - Rutas: `GET /api/credentials/status`, `PUT /api/credentials/uber`, `PUT /api/credentials/pedidosya`, `PUT /api/credentials/rappi` → 501, y `DELETE /api/credentials/{source}` con confirmación.
   - Los PUT escriben de forma atómica (`.tmp` + `os.replace`), con modo 0600 y health check. Nunca devuelven el valor.
   - La UI es un formulario, sin localStorage.
2. **Disputas + media (§5.4).**
   - Uber: listado con `uber.py disputes --json`; detalle y fotos con `dispute-photos`, servidas por un proxy autenticado del panel.
   - Envío Uber: dry-run por defecto. Con `confirm=true` queda marcado "no verificado en vivo"; no inventar éxito.
   - PedidosYa: `complaint_tiles` desde `issues`. No son disputas y no se cuentan como tales.
   - `GET /api/orders/pedidosya/{id}?photos=true` usa `pya.py order <id> --photos`; una lista vacía es válida. El envío PedidosYa responde 501.
   - Media en `media/{platform}/{order_id}/` con nombre opaco, acceso autenticado y flag `sensitive`.
3. **Integración con la app delivery.**
   - En la ficha de cada pedido (Uber y PedidosYa), una sección "Fotos de la tienda (app delivery)". El backend las trae de `evidencia` con las variables `EVIDENCIA_URL` (default `https://nfryurrhgaeepdwqtswo.supabase.co/functions/v1/evidencia`) y `EVIDENCIA_API_KEY`.
   - El navegador solo ve un proxy autenticado: `/api/evidence/{agregador}/{numero_orden}/media/{id}`.
   - Sin clave → estado "evidencia sin configurar" (ni 500 ni lista vacía engañosa). Un 401 de Supabase → error de fuente.
   - Agregar ambas variables vacías a `.env.example`.
   - Buscador en la pestaña Disputas: agregador + número de orden muestra las fotos de la app aunque el pedido no esté en el listado de la plataforma.
4. **Frontend.**
   - Pestaña Disputas (§6.2) con sub-pestañas Uber y PedidosYa. La ficha del pedido muestra fotos de la plataforma y de la app; "Preparar disputa" (dry-run) en Uber, "no disponible por API" en PedidosYa.
   - Pestaña Credenciales (§6.7) con semáforos.
   - Mantener Monitoreo.
   - Navegación por módulos clara, diseño sobrio y responsive (se va a probar desde el celular). No imitar la UI de Uber ni de PedidosYa.
5. **Tests nuevos** (unittest, con los CLI y Supabase mockeados):
   - todas las rutas nuevas exigen auth;
   - un dry-run no llama `--yes`;
   - issues de PedidosYa no cuentan como disputas;
   - un 401 de plataforma no se vuelve cero;
   - las credenciales nunca se devuelven;
   - media y evidencia exigen sesión;
   - la clave de evidencia nunca aparece en las respuestas.

   Agregar `tzdata` a `requirements.txt`.

Principios obligatorios (§2): nunca imprimir, devolver ni loguear cookies, tokens, API keys ni URLs firmadas completas (redactar la query string). Las escrituras se auditan. No hay secretos en el repositorio.

### Levantar en la VM (QA)

- Generar en la VM un `.env` de QA, sin commitearlo: `PANEL_USER=qa`, y `PANEL_PASSWORD` y `SESSION_SECRET` aleatorios con `secrets.token_urlsafe`. Guardarlos en `~/qa-panel-credenciales.txt`, fuera del repositorio.
- Preferir `docker compose up --build -d`. Si no hay Docker, `uvicorn app.main:app --host 127.0.0.1 --port 8000`, como proceso persistente y explicando por qué.
- Sin sesiones de Uber/PedidosYa ni clave de evidencia, las fuentes se muestran "sin credenciales" / "evidencia sin configurar", nunca ceros. Si la VM tiene el secreto `EVIDENCIA_API_KEY`, usarlo sin imprimirlo.
- Verificar en el navegador login, Monitoreo, Disputas, la ficha de pedido, el buscador y Credenciales. Capturas en escritorio y en ancho de celular.

### Túnel (al final, con tests en verde)

- Cloudflare Quick Tunnel: `cloudflared tunnel --url http://127.0.0.1:<puerto>`, persistente con log a archivo. Si falla, usar una alternativa equivalente y decir cuál.
- Detrás del túnel HTTPS, `SESSION_SECURE=true` si la cookie funciona así. Si el panel valida el Host, agregar el host del túnel a la config de QA, sin commitear.
- No exponer shells ni puertos extra. Verificar contra la URL del túnel: `/api/snapshot` sin sesión → 401, `/healthz` → ok, y el login completo funciona.

### Entrega

- Commits en la rama del agente, push y PR contra `main` con resumen en español, sin credenciales ni URL del túnel.
- Respuesta final para el dueño:
  - URL pública del túnel;
  - usuario `qa` y la contraseña temporal de QA (descartable, se rota antes del deploy; nunca en commits, PR ni logs);
  - rutas nuevas y tests OK;
  - cómo quedó levantado y capturas;
  - cuánto dura el túnel o la VM;
  - pendientes de próximas rondas (tiendas, catálogo, reportes, agentes, automatizaciones) y bloqueos.
