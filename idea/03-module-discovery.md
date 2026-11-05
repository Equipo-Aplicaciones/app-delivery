---
id: "MOD-001"
title: "Descubrimiento y Arquitectura de Módulos — app-delivery"
status: "APROBADO"
version: "1.0.0"
owner: "Negocio / Equipo WIKA"
created_at: "2026-11-05"
updated_at: "2026-11-05"
audit_1_passed: true
audit_2_passed: true
---

# [03] Descubrimiento y Especificación de Arquitectura Modular

> **Pre-requisito:** `audit_1_passed: true` en `01-problem.md` y `02-features.md`.  
> **Equivalencia:** Auditoría de Módulos → `docs/auditoria-modulos.md`.

## 1. Identificación y Documentos Base

- **Nombre del Proyecto:** `app-delivery`
- **Especificaciones base:** `01-problem.md` (`PROB-001`) | `02-features.md` (`FEAT-001`)
- **Estado de gatekeeping:** `AUDIT_2_APROBADO`
- **Proyecto Supabase (`DEC-04`):** `nfryurrhgaeepdwqtswo`, región `sa-east-1`, URL `https://nfryurrhgaeepdwqtswo.supabase.co`
- **Migración reproducible:** `supabase/migrations/20261105190131_create_evidencia.sql` (versión ya aplicada en ese proyecto)

---

## 2. Matriz de Trazabilidad Modular (RTM 1:1)

| ID Módulo | ID Feature (`02-features.md`) | ID Problema (`01-problem.md`) | Nombre del Módulo | Tipo | Responsabilidad Principal |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `MOD-01` | `FEAT-01` | `ERR-01` | `mod-camera` | `UI / dispositivo` | Capturar la foto del pedido y dejarla en la sesión |
| `MOD-02` | `FEAT-02` | `ERR-02` | `mod-order-name` | `UI / presentación` | Recoger y validar el número de orden |
| `MOD-03` | `FEAT-03` | `ERR-03` | `mod-aggregator` | `UI / presentación` | Elegir un agregador del catálogo cerrado |
| `MOD-04` | `FEAT-04`, `FEAT-05` | `ERR-04`, `ERR-05` | `mod-evidence-api` | `servicio / API` | Enviar, guardar y pedir la evidencia en Supabase |

`FEAT-06` y `FEAT-07` son deseables. No tienen módulo en V1.

---

## 3. Desglose de Arquitectura Modular

### Módulo `MOD-01`: mod-camera

**Patrón:** Feature module de captura. La regla «no enviar imagen vacía» es una función pura.  
**Ruta en repositorio:** `src/modules/camera/` (vista) y `src/engine/camera.ts` (pura, sin React)

#### Contrato

- **Entradas:** permiso de cámara del dispositivo; acción de tomar la foto
- **Salidas:** imagen de la sesión, o un error de captura sin llamar a la API
- **Dependencias:** permiso de cámara Android. No depende de Supabase
- **Reutilizable:** No como módulo de dominio. La prueba es específica de la disputa

#### Reglas de aislamiento

- No importa `mod-evidence-api` ni claves de Supabase
- `src/engine/camera.ts` no importa React ni componentes de UI
- Si no hay imagen, el módulo no arma un envío

---

### Módulo `MOD-02`: mod-order-name

**Patrón:** Campo de UI más función pura de normalización.  
**Ruta:** `src/modules/order-name/` y `src/engine/order-number.ts`

#### Contrato

- **Entradas:** texto escrito por el operador
- **Salidas:** `numero_orden` recortado (`btrim`), o el error «falta el número de orden» si queda vacío
- **Dependencias:** ninguna de red. No lee el agregador ni la cámara
- **Reutilizable:** No

#### Reglas de aislamiento

- La función pura recorta extremos y rechaza vacío. No persiste
- No importa React en `src/engine/order-number.ts`
- No llama a la API

---

### Módulo `MOD-03`: mod-aggregator

**Patrón:** Selector de catálogo cerrado.  
**Ruta:** `src/modules/aggregator/` y `src/engine/aggregator.ts`

#### Contrato

- **Entradas:** elección del operador
- **Salidas:** `agregador` con valor `uber` o `pedidosya`, o error si falta o no está en el catálogo
- **Dependencias:** ninguna de red. «pedya» se documenta como PedidosYa; el valor persistido es `pedidosya`
- **Reutilizable:** No

#### Reglas de aislamiento

- El catálogo vive en la función pura. La UI solo lo muestra
- No crea una base distinta por agregador
- No llama a la API ni importa la cámara

---

### Módulo `MOD-04`: mod-evidence-api

**Patrón:** Única frontera de lectura y escritura. El cliente solo hace HTTP. El proceso servidor usa `service_role`.  
**Ruta del cliente (sin secretos):** `src/modules/evidence-api/`  
**Ruta del servidor:** proceso de la API, fuera del APK. El runtime concreto (Edge Function u otro) no lo eligió Negocio; queda para `05-build-plan.md`. Este gate no crea ese código.

#### Contrato

- **Operaciones:** `enviar`, `guardar`, `pedir`
- **Entradas de enviar y guardar:** `agregador`, `numero_orden`, imagen
- **Entradas de pedir:** `agregador`, `numero_orden`
- **Salidas:** confirmación de guardado, o las imágenes de esa pareja, o «no hay evidencia» sin error de servidor
- **Dependencias:** proyecto `nfryurrhgaeepdwqtswo`. Postgres `public.evidencia` y bucket Storage `evidencia`
- **Reutilizable:** No. No se reutiliza el proyecto Supabase de otro producto

#### Reglas de aislamiento

- Ningún otro módulo abre Postgres ni Storage
- El APK no contiene `service_role` ni la clave secreta
- `guardar` inserta una fila nueva y sube el objeto. No borra fotos anteriores de la misma pareja
- `pedir` devuelve solo las filas de esa pareja, ordenadas por `created_at`
- Si el guardado no se confirma, la app no declara éxito y conserva la foto de la sesión

#### Contrato de datos

Una sola base para `uber` y `pedidosya`. La clave lógica es (`agregador`, `numero_orden`). Varias filas por esa pareja están permitidas: no hay unicidad sobre el par.

| Pieza | Dónde | Regla |
| :--- | :--- | :--- |
| Metadatos | `public.evidencia` | `agregador` (`uber` \| `pedidosya`), `numero_orden` (texto recortado, no vacío), `storage_path` (clave del objeto, única), `created_at` |
| Bytes | Bucket `evidencia` | Mismo proyecto. Bucket privado (`public = false`). `storage_path` es la clave dentro de ese bucket, no una URL pública |
| Escritura y lectura de la app | Solo la API | `anon` y `authenticated` no tienen `GRANT` sobre `public.evidencia`. RLS está activo. Las políticas de esos roles son denegación explícita (`USING (false)` / `WITH CHECK (false)`). Lo mismo para `storage.objects` cuando `bucket_id = 'evidencia'` |
| Rol de servidor | `service_role` | Tiene `BYPASSRLS` y los grants de la tabla. Vive solo en el proceso de la API. No hace falta una política permisiva para ese rol: las políticas no se evalúan cuando el rol bypasea RLS |

Índice de consulta: `evidencia_clave_idx` sobre (`agregador`, `numero_orden`, `created_at`).

No hay política de upsert para `anon` o `authenticated`. Reemplazar un objeto exigiría `INSERT` + `SELECT` + `UPDATE` en Storage; el cliente no las tiene. Un envío nuevo usa un `storage_path` nuevo.

---

## 4. Grafo de Dependencias y Reglas de Importación

```text
[app/ screens — expo-router]
       │
       ▼ consume
[MOD-01 mod-camera]  [MOD-02 mod-order-name]  [MOD-03 mod-aggregator]
       │                      │                         │
       └──────── payload: imagen, numero_orden, agregador ────────┘
                                │
                                ▼ solo HTTP
                       [MOD-04 cliente]
                                │
                                ▼ service_role, solo servidor
                       [MOD-04 API]
                                │
                ┌───────────────┴───────────────┐
                ▼                               ▼
     [public.evidencia]              [bucket evidencia]
```

Las funciones puras (`src/engine/camera.ts`, `order-number.ts`, `aggregator.ts`) las consumen sus módulos de UI. No importan la API ni React.

**Reglas:**

- Prohibidas importaciones circulares. La API no importa las pantallas.
- `src/engine/` sin imports de React.
- Estilos solo vía tokens de `standards/design-system.md` o el theme que documente `04-application-design.md`.
- El cliente no importa el cliente de Supabase con `service_role`.

---

## 5. Matriz de Riesgos Arquitectónicos

| ID Módulo | Riesgo | Impacto | Mitigación |
| :--- | :--- | :--- | :--- |
| `MOD-01` | Permiso de cámara denegado o captura vacía | `Alto` | La app sigue abierta, informa el fallo y no llama a la API |
| `MOD-02` | Número de orden con espacios o vacío | `Alto` | Recorte en el cliente y `CHECK` en Postgres (`numero_orden = btrim(numero_orden)`) |
| `MOD-03` | Valor fuera de `uber` \| `pedidosya`, incluido «pedya» | `Alto` | Catálogo en el cliente y `CHECK` en Postgres. El valor guardado es `pedidosya` |
| `MOD-04` | Un guardado nuevo borra fotos de la misma clave | `Alto` | Sin `UNIQUE (agregador, numero_orden)`. `guardar` solo inserta |
| `MOD-04` | `service_role` dentro del APK, o escritura anónima | `Alto` | Grants revocados a `anon` y `authenticated`. RLS activo. Políticas de denegación. La clave no entra al cliente |
| `MOD-04` | Fila sin objeto, u objeto sin fila | `Alto` | La API confirma el envío solo si metadatos y bytes quedaron guardados |

---

## 6. Evaluación de Reutilización WIKA

| Módulo | ¿Existe equivalente WIKA? | Decisión |
| :--- | :--- | :--- |
| `MOD-01` | `app/bby app` usa `expo-camera` para el torch, no para guardar fotos de una orden | `Crear nuevo`. La librería se fija en `05` con versión `~` |
| `MOD-02` | No hay un campo de número de orden de disputa reutilizable | `Crear nuevo` |
| `MOD-03` | No hay catálogo `uber` \| `pedidosya` en otro módulo | `Crear nuevo` |
| `MOD-04` | No hay API de evidencia. Los proyectos Supabase de otros productos no se reutilizan | `Crear nuevo` |
| UI / theme | Tokens de `standards/design-system.md`. El repo `design-system/` es V3+ | `Theme local V1`. Diferir el pipeline de `design-system/` a V3+ |

---

## 7. Puerta de Enlace y Firma de Auditoría de Módulos

### Checklist

- [x] Toda feature obligatoria tiene al menos un módulo.
- [x] Sin módulos duplicados ni responsabilidades superpuestas.
- [x] Dependencias y riesgos documentados.
- [x] Reutilización WIKA evaluada.
- [x] Grafo sin ciclos.
- [x] `audits/auditoria-modulos.md` en estado `[APROBADO]`.

### Registro de visto bueno

- **Aprobado por (Arquitecto):** Negocio, instrucción «seguimos con el flujo» del 2026-11-05
- **Fecha:** `2026-11-05`
- **audit_2_passed:** `true`
