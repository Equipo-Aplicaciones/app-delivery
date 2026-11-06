# Registro — rama `cursor/panel-disputas-credenciales-8fe5`

Cierre: 2026-11-05 21:35 (hora de Chile). PR: https://github.com/juaking1312/app-delivery/pull/1 (contra `main`).
Proyecto: `panel-delivery-fuentes/delivery-monitor-servidor/`. Especificación: `especificacion-panel-delivery-cursor.md`.

## Resultado

Todos los módulos de la especificación (§5.2–5.8) quedaron habilitados en la API y en el panel, más Monitoreo, que ya existía.
Suite: **101 tests OK** (`python -m unittest discover -s tests`).

| Módulo | Archivos | Estado |
|---|---|---|
| Credenciales (§5.2) | `app/modules/credentials.py` | Semáforo por fuente; reposición con prueba en HOME aislado y reemplazo atómico; Rappi 501. |
| Tiendas (§5.3) | `app/modules/stores.py` | Listado del snapshot; prender/pausar vía `uber.py`/`pya.py`. |
| Disputas + media (§5.4) | `disputes.py`, `media.py`, `evidence.py` | Uber: listado, ficha, fotos y disputa en dry-run. PedidosYa: reclamos (no son disputas), envío 501. Fotos de la app delivery por proxy. |
| Reportes (§5.5) | `reports.py`, `jobs.py` | 13 reportes de los CLI + 18 VOS de PedidosYa + exportación del snapshot; JSON/CSV en `data/exports/`. |
| Catálogo (§5.6) | `catalog.py` | Agotados, agotar/reponer ítem, activar menú con exclusiones. |
| Automatizaciones (§5.7) | `automations.py` | Cron en hora de Chile para refresh y reportes; mínimo 15 min entre corridas. |
| Agentes (§5.8) | `agents.py`, `deps.py` | API keys `tdk_…` (solo hash en disco), Bearer con scope por ruta, límite por minuto, revocación inmediata. |

Reglas comunes en `app/modules/cli_helpers.py`:
- Toda escritura pasa `--dry-run` salvo que llegue `confirm: true` (booleano); en ese caso pasa `--yes`.
- Un solo comando de escritura a la vez.
- Todo intento queda en `data/acciones.jsonl`.
- Un 401/403 de la plataforma se informa como error, nunca como cero.

## Decisiones tomadas

- **Las escrituras manuales actúan en vivo tras confirmar.** Prender, pausar, agotar, reponer y activar menú solo exigen el dry-run previo y la doble confirmación del navegador; no hay un interruptor de servidor que las impida. La especificación no lo pide; si se quiere uno, agregarlo antes del deploy.
- **El envío real de disputas Uber está apagado.** `uber.py dispute --yes` solo corre con `ALLOW_UBER_DISPUTE_SUBMIT=true`, y la respuesta siempre dice `verified: false`.
- **Las escrituras programadas están bloqueadas.** Con `ALLOW_SCHEDULED_WRITES=false` se rechazan; aun con `true` responden 501 porque no están cableadas.
- **Hay scopes reservados a humanos.** `credentials.write` y `agents.admin` no se entregan a agentes: `/api/credentials` y `/api/agents` responden 403 a cualquier Bearer.
- **El límite de login cuenta solo los intentos fallidos.** Antes un login exitoso también sumaba y bloqueaba al operador detrás del túnel.
- **`data/exports/`, `data/*.json`, `media/` y `sessions/` quedan fuera de git y de la imagen Docker.**

## QA realizado (VM del agente, no es producción)

- Se probó con uvicorn en `127.0.0.1:8000` detrás de un Cloudflare Quick Tunnel, con las sesiones reales de Uber y PedidosYa cargadas en la VM.
- **Verificado:**
  - login con cookie `HttpOnly`/`Secure`;
  - 401 sin sesión;
  - prender una tienda en dry-run (Uber) devuelve el payload sin ejecutar nada;
  - agotar un ítem en dry-run responde por tienda;
  - la exportación del snapshot trae 234 tiendas;
  - una API key funciona con su scope, recibe 403 en credenciales y 401 tras revocarla;
  - no hay claves en logs ni en la auditoría.
- **No se ejecutó ninguna escritura real** en Uber ni en PedidosYa.
- Se tomaron capturas de escritorio y móvil de todas las vistas; están enlazadas en el PR.
- El túnel y la contraseña de QA son temporales y no se versionan. Hay que rotar la contraseña antes del deploy.

## Pendiente para la próxima rama

1. **Deploy al servidor común.** Usar `docker compose` y Caddy (README → «Arranque en el servidor») con un `.env` nuevo, que debe incluir `PANEL_PASSWORD`, `SESSION_SECRET` y `SESSION_SECURE=true`.
2. **Prueba autorizada en vivo de `uber.py dispute --yes`.** Hacerla con un pedido de bajo monto antes de activar `ALLOW_UBER_DISPUTE_SUBMIT`.
3. **`EVIDENCIA_API_KEY` en el servidor.** Así las fotos de la app delivery aparecen en la ficha.
4. **Escrituras programadas.** Si se quieren (pausar o agotar por cron), diseñarlas con dry-run registrado y una ventana de confirmación.
5. **Rappi.** Falta CLI y credenciales oficiales.
6. **`X-Forwarded-For`.** El límite de login lo toma tal cual; ajustarlo al proxy final.
7. **Un solo worker de uvicorn.** El candado de refresh, el programador y el límite de agentes viven en memoria.

## Commits

| Commit | Hora (Chile) | Qué |
|---|---|---|
| `da7597b` | 20:31 | Módulos de credenciales y disputas con fotos de la app delivery |
| `3f54d74` | 20:38 | Frontend: navegación por módulos, Disputas, Credenciales, responsive |
| `19ba135` | 20:38 | Tests; el límite de login solo cuenta intentos fallidos |
| `7c0a11f` | 20:44 | Fechas legibles, tablas apiladas en móvil, favicon |
| `eca90f7` | 20:44 | README: disputas, credenciales y evidencia |
| `c4ca539` | 21:10 | API: Tiendas, Catálogo, Reportes, Automatizaciones y Agentes |
| `2c668e2` | 21:10 | Frontend de los cinco módulos |
| `5c04c46` | 21:10 | Documentación; datos de ejecución fuera de git y de la imagen |
| `5db55f1` | 21:13 | Tiendas: acciones arriba, tabla con scroll, contador |
