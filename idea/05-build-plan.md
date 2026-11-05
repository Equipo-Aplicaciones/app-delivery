---
id: "BUILD-001"
title: "Plan de Construcción V1 — app-delivery"
status: "APROBADO"
version: "1.0.0"
owner: "Negocio / Equipo WIKA"
created_at: "2026-11-05"
updated_at: "2026-11-05"
audit_1_passed: true
audit_2_passed: true
visual_approval_passed: true
audit_3_passed: true
ready_for_construction: true
---

# [05] Plan de Construcción V1 (Build Plan)

> **Bloqueo:** Si `ready_for_construction: false`, queda prohibido crear o modificar código en `iterations/v1/src/` y `iterations/v1/app/`.  
> **Activación:** `ready_for_construction: true` solo cuando los cuatro flags anteriores sean `true`.

## 1. Verificación de Pre-requisitos

- [x] Auditoría de Documentación: `audit_1_passed == true` (`auditoria-documentacion.md`)
- [x] Auditoría de Módulos: `audit_2_passed == true` (`auditoria-modulos.md`)
- [x] Aprobación visual: `visual_approval_passed == true` (`04-application-design.md`)
- [x] Auditoría de Ensamblado: `audit_3_passed == true` (`auditoria-ensamblado.md`)

---

## 2. Alcance de la V1

**Features incluidas:** `FEAT-01`, `FEAT-02`, `FEAT-03`, `FEAT-04`, `FEAT-05`  
**Features excluidas:** `FEAT-06` (leer la orden desde un código), `FEAT-07` (destino distinto por agregador)  
**Módulos incluidos:** `MOD-01` `mod-camera`, `MOD-02` `mod-order-name`, `MOD-03` `mod-aggregator`, `MOD-04` `mod-evidence-api`

La carpeta de la iteración es `iterations/v1/`. El proyecto Supabase ya existe: `nfryurrhgaeepdwqtswo`. La migración `supabase/migrations/20261105190131_create_evidencia.sql` ya está aplicada. Esta construcción no crea otro proyecto ni otra tabla.

---

## 2b. Prototipo (modo `exploration`)

N/A. `project_mode` en `01-problem.md` es `construction`. No se escribe `iterations/prototype/` ni `final/` en este plan.

---

## 2c. Canales de entrega

| Canal | Verify / artefacto | Estándar |
| :--- | :--- | :--- |
| `android` | APK release sin Metro, `com.wika.appdelivery` | `standards/coding-standards.md`, WIKA-ARCH-03 |
| `web` | N/A | Fuera de V1 |

Toolchain nativo (WIKA-ARCH-04): JDK 17, Kotlin 1.9.25, `minSdk` 24. El pin de Kotlin va en `scripts/post-prebuild.js`, como en `app/tower/iterations/v1/`.

---

## 3. Cronograma de Ejecución (Build Schedule)

| Paso | Módulo | ID Feature | Archivos a crear / modificar | Tokens / estándares | Estado |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `01` | `global` | N/A | `iterations/v1/package.json`, `app.json`, `tsconfig.json`, `scripts/verify-build.sh`, `scripts/build-apk.sh`, `scripts/post-prebuild.js` | WIKA-ARCH-02, 03, 04, 06. Base: `app/tower/iterations/v1/` | `[COMPLETADO]` |
| `02` | `MOD-02`, `MOD-03`, `MOD-01` | `FEAT-02`, `FEAT-03`, `FEAT-01` | `src/engine/order-number.ts`, `src/engine/aggregator.ts`, `src/engine/camera.ts`, `scripts/smoke-v1.ts` | Sin React en `src/engine/` | `[COMPLETADO]` |
| `03` | `global` | N/A | `src/constants/theme.ts` | Tokens de `04` y `standards/design-system.md`. 0% hex en componentes | `[COMPLETADO]` |
| `04` | `MOD-04` | `FEAT-04`, `FEAT-05` | `supabase/functions/evidencia/index.ts` | `service_role` solo en el runtime. Tabla `public.evidencia`, bucket `evidencia` | `[COMPLETADO]` |
| `05` | `MOD-04` | `FEAT-04`, `FEAT-05` | `src/modules/evidence-api/` | Cliente HTTP. Sin `service_role` y sin cliente Supabase en el APK | `[COMPLETADO]` |
| `06` | `MOD-01`, `MOD-02`, `MOD-03` | `FEAT-01`, `FEAT-02`, `FEAT-03` | `src/modules/camera/`, `src/modules/order-name/`, `src/modules/aggregator/` | `theme.ts` | `[COMPLETADO]` |
| `07` | `integración` | `FEAT-01`–`FEAT-04` | `app/index.tsx` (`VIEW-01`) | Wireframe de `04`. Estados idle, ready, loading, success, error | `[COMPLETADO]` |
| `08` | `integración` | `FEAT-05` | `app/consulta.tsx` (`VIEW-02`) | Estados idle, loading, success, empty, error | `[COMPLETADO]` |
| `09` | `global` | `FEAT-01`–`FEAT-05` | `npm run verify`, APK release | WIKA-ARCH-05 | `[PENDIENTE]` |

---

## 4. Orden de Implementación y Justificación

1. **Setup y toolchain.** Copiar la base de scripts de `app/tower/iterations/v1/` (WIKA-ARCH-06) y sumar `expo-camera` en la versión ya usada por `app/bby app` con Expo 52.
2. **Engine puro.** Recorte del número de orden, catálogo `uber` | `pedidosya` y rechazo de imagen vacía. Smoke tests sin UI.
3. **Theme.** `theme.ts` con los tokens de `04-application-design.md` antes de cualquier pantalla.
4. **API.** La Edge Function guarda y lee. El cliente solo hace HTTP. Así `VIEW-01` y `VIEW-02` no se acoplan a Supabase.
5. **Pantallas.** Captura y luego Consulta, en el orden del wireframe.
6. **Verify y APK.** Cierre de la iteración.

---

## 5. Desglose por Fases

### Fase 1: Setup y Design Tokens

- **Objetivo:** Expo SDK 52 en `iterations/v1/` con `theme.ts`, scripts de verify y el pin de Kotlin.
- **Referencia:** `proyectos/app/tower/iterations/v1/`
- **Criterio de parada:** `npm run typecheck` sin errores.

### Fase 2: Engine y Módulos de Lógica

- **Objetivo:** Contratos de `MOD-01`, `MOD-02` y `MOD-03` en `src/engine/`.
- **Regla:** Sin imports de React en `src/engine/`.
- **Criterio:** `npm run smoke` cubre orden vacía, orden con espacios, agregador fuera de catálogo (`pedya` no es un valor persistible; el valor guardado es `pedidosya`) e imagen ausente.

### Fase 3: API de evidencia

- **Objetivo:** Edge Function `evidencia` en el proyecto `nfryurrhgaeepdwqtswo`.
- **Enviar / guardar:** recibe `agregador`, `numero_orden` e imagen. Inserta una fila nueva y sube un objeto con `storage_path` nuevo. No borra fotos anteriores de la misma pareja. Responde confirmación solo si la fila y el objeto quedaron escritos.
- **Pedir:** recibe `agregador` y `numero_orden`. Devuelve las imágenes de esa pareja ordenadas por `created_at`, o una respuesta vacía si no hay filas. No devuelve otras órdenes ni el otro agregador.
- **Acceso:** la función usa `service_role`, que Supabase inyecta en el runtime. La clave de prueba está en `public.evidencia_clave` (RLS activo, `anon` y `authenticated` denegados) y no se commitea. El APK la manda en el header `x-evidencia-key`.
- **Criterio:** un envío de prueba y un pedir de esa misma clave contra el proyecto `nfryurrhgaeepdwqtswo`. Las filas de prueba se borran al terminar el chequeo.

### Fase 4: UI, Verify y APK

- **Objetivo:** `VIEW-01` y `VIEW-02` según `04-application-design.md`, más los escenarios BDD de `02-features.md`.
- **Regla:** estilos solo vía `theme.ts`. `npm run verify` y APK release sin Metro (WIKA-ARCH-05).

---

## 6. Dependencias Externas

| Dependencia | Versión | Propósito |
| :--- | :--- | :--- |
| `expo` | `~52.0.0` | Framework |
| `react-native` | `0.76.9` | Runtime. Pin exacto, igual que tower v1. Sin `^` |
| `react` | `18.3.1` | UI |
| `expo-router` | `~4.0.0` | Rutas `/` y `/consulta` |
| `expo-camera` | `~16.0.0` | Captura. Misma línea que `app/bby app` en SDK 52 |
| `expo-build-properties` | `~0.13.0` | `minSdk` 24 |
| `typescript` | `~5.3.0` | Typecheck |

No entra `@supabase/supabase-js` en el APK. La app habla HTTP con la Edge Function.

---

## 7. Estrategia de Pruebas

| Tipo | Alcance | Comando / método |
| :--- | :--- | :--- |
| Smoke engine | Orden, agregador, imagen vacía | `npm run smoke` |
| Typecheck | Proyecto completo | `npm run typecheck` |
| Build gate | Export + prebuild + APK | `npm run verify` |
| API | Enviar y pedir una pareja, y comprobar que otra pareja no aparece | Llamada a la Edge Function en `nfryurrhgaeepdwqtswo` |
| BDD manual | Escenarios de `02-features.md` en dispositivo | Checklist QA |
| Secreto | El APK no contiene `service_role` | Revisión del bundle |

---

## 8. Riesgos Técnicos

| Riesgo | Probabilidad | Mitigación |
| :--- | :--- | :--- |
| Prebuild Android falla por Kotlin | `Media` | `scripts/post-prebuild.js` deja Kotlin 1.9.25, como tower v1 |
| La clave de prueba queda dentro del APK y se puede extraer | `Media` | Aceptada para esta prueba. `service_role` no entra al APK. Producción cambiará este acceso |
| Un guardado deja fila sin objeto, u objeto sin fila | `Media` | La función confirma solo con ambas piezas. Si falla el objeto, no deja la fila confirmada |
| Scope creep hacia la disputa dentro de Uber o PedidosYa | `Alta` | Fuera de alcance de `01-problem.md`. `FEAT-06` y `FEAT-07` no entran |

---

## 9. Criterios de Aprobación V1

- [ ] `FEAT-01` a `FEAT-05` implementadas.
- [ ] `npm run verify` exitoso.
- [ ] APK release generado en `iterations/v1/`.
- [ ] `review.md` completado por el arquitecto.
- [ ] Listo para `auditoria-release-v1.md`.

---

## 10. Checklist por Incremento (Quality Gate)

Antes de marcar un paso como `[COMPLETADO]`:

- [ ] 0% estilos hardcoded fuera de theme/tokens.
- [ ] Trazabilidad RTM respetada (feature → módulo → archivo).
- [ ] Escenario BDD asociado verificado.
- [ ] Sin errores TypeScript ni linter bloqueante.

---

## 11. Cierre de Fase de Construcción

- **Revisado por (Arquitecto):** Negocio, «dale no mas aprobado» del 2026-11-05
- **Fecha de inicio de construcción:** `2026-11-05`
- **ready_for_construction:** `true`. Al cerrar V1 → `[LISTO_PARA_AUDITORIA_RELEASE]`
