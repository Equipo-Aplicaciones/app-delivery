---
id: "DES-001"
title: "Diseño de Aplicación — app-delivery"
status: "APROBADO"
version: "1.0.0"
owner: "Negocio / Equipo WIKA"
created_at: "2026-11-05"
updated_at: "2026-11-05"
audit_1_passed: true
audit_2_passed: true
visual_approval_passed: true
audit_3_passed: true
---

# [04] Diseño de Aplicación, Navegación y Aprobación Visual

> **Pre-requisito:** `audit_2_passed: true` en `03-module-discovery.md`.  
> **Gate visual:** `visual_approval_passed: true` requiere visto bueno del arquitecto/stakeholder.  
> **Equivalencia:** Auditoría de Ensamblado (parte visual) → `docs/auditoria-ensamblado.md`.

## 1. Identificación y Antecedentes

- **Nombre del Proyecto:** `app-delivery`
- **Documentos base:** `01-problem.md` | `02-features.md` | `03-module-discovery.md`
- **Estado de gatekeeping:** `AUDIT_3_APROBADO`
- **Canal V1:** Android. La sección web no aplica.

---

## 2. Arquitectura General

Cuatro capas, alineadas a `03-module-discovery.md` y a `standards/coding-standards.md`:

| Capa | Dónde | Qué hace en V1 |
| :--- | :--- | :--- |
| Pantallas | `app/` con expo-router | Captura y consulta. Arman el payload y muestran estados |
| Módulos de UI | `src/modules/camera`, `order-name`, `aggregator` | Cámara, campo de orden y selector de agregador |
| Engine | `src/engine/` | Funciones puras: no enviar imagen vacía, recortar el número de orden, catálogo `uber` \| `pedidosya` |
| Theme | `src/constants/theme.ts` | Tokens de `standards/design-system.md`. Sin hex en componentes |
| API | `src/modules/evidence-api/` | Solo HTTP. No abre Postgres ni Storage |

`mod-evidence-api` en el servidor queda fuera del APK. Este diseño no elige Edge Function ni otro runtime: eso lo cierra `05-build-plan.md`.

---

## 3. Módulos Utilizados en V1

| ID Módulo | Nombre | Rol en V1 |
| :--- | :--- | :--- |
| `MOD-01` | `mod-camera` | Vista de cámara y foto en la sesión |
| `MOD-02` | `mod-order-name` | Campo del número de orden |
| `MOD-03` | `mod-aggregator` | Selector `uber` \| `pedidosya` |
| `MOD-04` | `mod-evidence-api` | Enviar, guardar y pedir. El cliente solo llama a la API |

---

## 4. Relaciones entre Módulos

```text
VIEW-01 Captura
  → MOD-01 deja la imagen en la sesión
  → MOD-02 entrega numero_orden recortado
  → MOD-03 entrega agregador del catálogo
  → la pantalla arma el payload
  → MOD-04 cliente hace HTTP (enviar / guardar)
  → la pantalla muestra éxito solo si la API confirmó

VIEW-02 Consulta
  → MOD-02 y MOD-03 entregan la misma clave
  → MOD-04 cliente hace HTTP (pedir)
  → la pantalla lista las imágenes de esa pareja, o el vacío
```

La pantalla no escribe en Supabase. Las funciones de `src/engine/` no importan React ni la API.

---

## 5. Flujo Principal de Usuario

```text
Cámara a pantalla casi completa → disparo → formulario que sube para rotular → Enviar
Traer (otra pantalla) → misma clave → lista de fotos, o «no hay evidencia»
```

Ajuste de Negocio el 2026-11-05, después de probar el teléfono: la captura no comparte pantalla con el formulario. El rótulo aparece recién cuando ya hay foto.

Estados de `VIEW-01`:

| Estado | Qué ve el operador |
| :--- | :--- |
| `idle` | Cámara a pantalla casi completa y el disparo. El disparo espera a que la cámara esté lista |
| `label` | La foto queda de fondo y sube el formulario: número de orden, agregador y enviar |
| `loading` | Envío en curso. El botón no se repite |
| `success` | La API confirmó el guardado. Vuelve la cámara y un aviso breve |
| `error` | Permiso denegado, cámara no lista, orden vacía, agregador inválido, o la base no recibió la imagen. Si el fallo es de red, la foto y el formulario siguen |

Estados de `VIEW-02`:

| Estado | Qué ve el operador |
| :--- | :--- |
| `idle` | Campo de orden, selector de agregador y acción de pedir |
| `loading` | Consulta en curso |
| `success` | Lista de las imágenes de esa pareja, de la más antigua a la más nueva (`created_at`) |
| `empty` | Texto de que no hay evidencia para esa clave. No es un error de servidor |
| `error` | Falta la clave, el agregador no está en el catálogo, o la API no respondió |

---

## 6. Navegación (expo-router)

| Ruta | Pantalla | ID Vista | Módulos | Feature |
| :--- | :--- | :--- | :--- | :--- |
| `/` | Captura | `VIEW-01` | `MOD-01`, `MOD-02`, `MOD-03`, `MOD-04` | `FEAT-01`, `FEAT-02`, `FEAT-03`, `FEAT-04` |
| `/consulta` | Consulta | `VIEW-02` | `MOD-02`, `MOD-03`, `MOD-04` | `FEAT-02`, `FEAT-03`, `FEAT-05` |

Desde Captura hay un enlace a Consulta. Desde Consulta hay vuelta a Captura. No hay otras rutas en V1.

---

## 6b. Navegación web

N/A. `delivery_channels` de V1 es solo `android`.

---

## 6c. Evidencia Gate 3A (preview)

| Campo | Valor |
| :--- | :--- |
| `preview_evidence_url` | `N/A` |
| Capturas | `N/A`. El visto de esta etapa es el wireframe de la sección 9 |
| Modo | Construcción. No hay `iterations/prototype/` |

---

## 7. Consumo de Tokens y Theme

Theme local V1 en `src/constants/theme.ts`. Los componentes usan estos nombres. No hay hex en la especificación ni en los componentes cuando el token existe. El pipeline de `design-system/` queda para V3+.

### Tokens clave V1

| Token semántico | Uso en app | Valor / referencia |
| :--- | :--- | :--- |
| `background` | Fondo de Captura y Consulta | `theme.colors.background` |
| `surface` | Recuadro de la cámara, campo de orden y lista de fotos | `theme.colors.surface` |
| `text` | Número de orden, etiquetas y confirmación | `theme.colors.text` |
| `text-muted` | Ayuda secundaria y estado vacío | `theme.colors.textMuted` |
| `accent` | Enviar, Pedir y el agregador elegido | `theme.colors.accent` |
| `error` | Permiso denegado, orden vacía, agregador inválido, fallo de API | `theme.colors.error` |
| `border` | Campo de orden y separadores de la lista | `theme.colors.border` |
| `spacing.md` | Padding de pantalla | `16 dp` |
| `spacing.sm` | Separación entre campo, selector y botones | `8 dp` |
| `spacing.lg` | Separación dentro del formulario que sube tras la foto | `24 dp` |
| `fontSize.md` | Campos y botones | `16` |
| `fontSize.sm` | Estado vacío y mensajes de error | `12–14` |
| `fontWeight.bold` | Enviar y Pedir | `700` |
| `radius.md` | Botones y campo | `12–16 dp` |

Touch target mínimo `44 dp`. Ancho máximo del botón de envío `340 dp`. Tipografía `fontFamily.base` (system).

---

## 8. Matriz Preview Visual vs Componentes de Código

| ID Vista | ID Módulo | Componente / Pantalla | Tokens | Referencia wireframe |
| :--- | :--- | :--- | :--- | :--- |
| `VIEW-01` | `MOD-01` | `CameraCapture` | `surface`, `spacing.lg` | Sección 9 |
| `VIEW-01` | `MOD-02` | `OrderNumberField` | `surface`, `text`, `border`, `spacing.sm` | Sección 9 |
| `VIEW-01` | `MOD-03` | `AggregatorPicker` | `accent`, `border`, `spacing.sm` | Sección 9 |
| `VIEW-01` | `MOD-04` | `SendEvidenceButton` | `accent`, `text`, `spacing.md` | Sección 9 |
| `VIEW-02` | `MOD-02`, `MOD-03` | `OrderNumberField`, `AggregatorPicker` | Los mismos de Captura | Sección 9 |
| `VIEW-02` | `MOD-04` | `RequestEvidence` | `accent`, `surface`, `text-muted` | Sección 9 |

No hay mockup PNG. El Gate 3A revisa este wireframe.

---

## 9. Layout Visual (wireframe / ASCII)

`VIEW-01` Captura, ruta `/`. Primero la cámara. Después de la foto sube el formulario:

```text
┌─────────────────────────────────────┐
│ aviso                      [ Traer ]│
│                                     │
│         cámara, casi toda           │
│         la pantalla                 │
│                                     │
│              ( o )                  │  disparo, surface + accent
└─────────────────────────────────────┘

┌─────────────────────────────────────┐
│ foto recién tomada, de fondo        │
├─────────────────────────────────────┤
│ Rotular                 Otra foto   │
│ [ Número de orden                 ] │
│ [ Uber ]  [ PedidosYa ]             │
│ [ Enviar                          ] │
└─────────────────────────────────────┘
```

`VIEW-02` Traer imagen, ruta `/consulta`. No hay cámara en esta pantalla:

```text
┌─────────────────────────────────────┐
│ Traer imagen                Captura │
├─────────────────────────────────────┤
│ Número de orden                     │
│ [ OrderNumberField                ] │
│ [ Uber ]  [ PedidosYa ]             │
│ [ Pedir evidencia                ]  │  accent
├─────────────────────────────────────┤
│ foto 1 · created_at                 │  surface
│ foto 2 · created_at                 │
│ — o «no hay evidencia» —            │  text-muted
└─────────────────────────────────────┘
```

Portrait. Una columna. La lista de la consulta hace scroll si hay varias fotos. Enviar y Pedir ocupan el ancho del contenido hasta `340 dp` y no bajan de `44 dp` de alto.

---

## 10. Riesgos de Diseño

| Riesgo | Impacto | Mitigación |
| :--- | :--- | :--- |
| El operador envía sin foto, sin orden o sin agregador | `Alto` | Enviar permanece deshabilitado. El engine rechaza vacío y el mensaje usa `error` |
| La confirmación aparece aunque la API no guardó | `Alto` | El estado `success` solo entra con la respuesta de confirmación. Si falla, se queda la foto de la sesión |
| Theme local distinto del pipeline V3+ | `Medio` | V1 usa solo los nombres de `standards/design-system.md`. La familia visual de `design-system/` espera a V3+ |
| Consulta muestra fotos de otra orden o de otro agregador | `Alto` | La lista pinta únicamente lo que devolvió `pedir` para esa pareja |

---

## 11. Puerta de Enlace — Aprobación Visual y Ensamblado

### Checklist aprobación visual (Gate 3A)

- [x] Navegación y flujo principal definidos.
- [x] Todos los módulos V1 incorporados sin huérfanos.
- [x] Tokens/theme documentados o N/A justificado.
- [x] Wireframe o preview revisado por arquitecto.
- [x] Sin dependencias circulares.

### Checklist auditoría de ensamblado (Gate 3B)

- [x] `05-build-plan.md` coherente con este diseño.
- [x] Estrategia de build y riesgos alineados.
- [x] `audits/auditoria-ensamblado.md` en estado `[APROBADO]`.

### Registro de visto bueno

- **Aprobación visual (Arquitecto / Stakeholder):** Negocio, «aprovado señor, sigue» del 2026-11-05
- **Fecha visual:** `2026-11-05`
- **visual_approval_passed:** `true`

- **Aprobación ensamblado (Arquitecto):** Negocio, «dale no mas aprobado» del 2026-11-05
- **Fecha ensamblado:** `2026-11-05`
- **audit_3_passed:** `true`
