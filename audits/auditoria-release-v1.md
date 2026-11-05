# Auditoría de Release — V1

## Proyecto
app-delivery

## Fecha
2026-11-05

## Objetivo
Borrador posterior a la construcción de `iterations/v1/`. No aprueba y no copia nada a `final/`.

## Entradas
- `idea/01` a `idea/05` con gates de construcción en `true`
- `iterations/v1/`
- `iterations/v1/review.md` (sin firma del arquitecto)
- `npm run smoke` y `npm run typecheck` en este entorno
- `npm run verify` no llegó a Gradle

## Referencia
`wika-fundaments` @ `wika-fundaments-v2` → `docs/auditoria-release-v1.md`

## Autor del borrador
wika-auditor (IA). El veredicto **APROBADO** lo escribe solo el Arquitecto.

---

## Validaciones

### Compilación y toolchain
- [x] `npm run typecheck` sin errores
- [x] `npm run smoke` cubre orden vacía, recorte, foto ausente, `pedya` rechazado y consulta sin foto
- [ ] `npm run verify` completo. Falta Android SDK y el JDK de esta máquina es 21, no 17
- [x] `expo` y `react-native` van con `~` o pin fijo, sin `^`

### Release
- [ ] APK release generado
- [x] Versión `1.0.0`, package `com.wika.appdelivery`
- [ ] Binario sin Metro. El script `build-apk.sh` lo arma con `assembleRelease`, y todavía no se ejecutó

### Funcionalidad y BDD
- [x] La Edge Function `evidencia` aceptó dos fotos de `uber` + `SMOKE-1`, las devolvió juntas, no las mezcló con PedidosYa y rechazó `pedya`. Las filas de prueba se borraron
- [ ] Los escenarios de cámara en un dispositivo Android no se recorrieron aquí
- [x] Estados de envío y consulta están en las pantallas

### Arquitectura
- [x] `src/engine/` no importa React
- [x] Las pantallas llaman a `prepareSend` y `prepareLookup`. No abren Supabase
- [x] Los componentes usan `theme.ts`. El hex vive solo en el theme

### Seguridad
- [x] Permiso de cámara declarado en `app.json`
- [x] `service_role` no está en el repositorio ni en el cliente
- [x] La clave de prueba no está en git. Vive en `public.evidencia_clave`, con RLS y políticas de denegación para `anon` y `authenticated`
- [ ] Esa clave sí entra al APK cuando se define `EXPO_PUBLIC_EVIDENCIA_API_KEY`. El plan de construcción lo acepta solo para esta prueba

### Documentación
- [ ] `review.md` sigue sin firma
- [x] Este borrador existe

---

## Hallazgos

1. No hay APK. `ANDROID_HOME` no está configurado y Java es OpenJDK 21.
2. `review.md` lo tiene que completar el arquitecto.
3. La prueba HTTP de enviar y pedir pasó el 2026-11-05 contra `nfryurrhgaeepdwqtswo` y la tabla quedó vacía después.

## Resultado

REQUIERE_CORRECCIONES

Falta el APK release con JDK 17 y el visto del arquitecto en `review.md`. `final/` sigue vacío.
