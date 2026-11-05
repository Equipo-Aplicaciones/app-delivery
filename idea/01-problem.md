---
id: "PROB-001"
title: "app-delivery"
status: "APROBADO"
version: "1.1.0"
owner: "Negocio / Equipo WIKA"
created_at: "2026-11-05"
updated_at: "2026-11-05"
audit_1_passed: true
solution_type: "mobile_app"
delivery_channels:
  - android
project_mode: "construction"
---

# [01] Definición del Problema, Alcance y Metas

> **Equivalencia de auditoría:** `audit_1_passed: true` requiere aprobación formal en `docs/auditoria-documentacion.md`.

## 1. Identificación y Control de Cambios

- **Nombre del Proyecto:** `app-delivery`
- **Repositorio de aplicación:** `proyectos/app/app-delivery/`
- **Stakeholders clave:** Negocio (operación que disputa devoluciones de pedidos delivery), personal del negocio (usuario de la app), Arquitecto WIKA (gates)
- **Estado de gatekeeping:** `AUDIT_1_APROBADO`
- **Cambio 1.1.0 (2026-11-05):** Negocio fijó el destino de la prueba en una base Supabase y una API para enviar, guardar y pedir la imagen por agregador y número de orden.
- **Gate 1 (2026-11-05):** aprobado por instrucción explícita de Negocio. `DEC-04` queda cerrada con el proyecto Supabase `nfryurrhgaeepdwqtswo`.

---

## 2. Definición del Problema y Justificación

- **¿Qué problema se intenta resolver?**  
  El negocio tiene que armar disputas de pedidos delivery y, para pelear la devolución con el cliente, debe subir imágenes del pedido. Hace falta una aplicación que sirva de cámara, que identifique cada imagen por agregador y número de orden, y una API de prueba que envíe, guarde y devuelva esas imágenes desde una base Supabase.

- **Impacto actual / costo de oportunidad:**  
  Sin una imagen recuperable por agregador y número de orden, el negocio no puede sostener la disputa de devolución con la foto del pedido que corresponde a esa orden.

- **Análisis de brecha (Gap Analysis):**
  - **Estado actual (hoy):** No existe la cámara ni una API que guarde y devuelva la evidencia según agregador y número de orden.
  - **Estado deseado (mañana):** App Android de prueba que saca la foto, elige Uber o PedidosYa, escribe el número de orden y llama a una API. La API guarda la imagen en Supabase y permite pedirla con esa misma clave.

---

## 3. Matriz de Trazabilidad de Requerimientos (RTM Inicial)

| ID Problema | Descripción del Dolor | Impacto | ID Feature (`02-features.md`) | Módulo Destino (`03-module-discovery.md`) |
| :--- | :--- | :--- | :--- | :--- |
| `ERR-01` | No hay una cámara de la app para fotografiar el pedido que se disputa | `Alto` | `FEAT-01` | `mod-camera` |
| `ERR-02` | La imagen no queda identificada con el número de orden | `Alto` | `FEAT-02` | `mod-order-name` |
| `ERR-03` | No se registra el agregador del pedido (Uber o PedidosYa) | `Alto` | `FEAT-03` | `mod-aggregator` |
| `ERR-04` | No hay dónde guardar la imagen ni una API que la envíe a la base | `Alto` | `FEAT-04` | `mod-evidence-api` |
| `ERR-05` | No se puede pedir la imagen ya guardada por agregador y número de orden | `Alto` | `FEAT-05` | `mod-evidence-api` |

Los módulos de la columna destino están especificados en `03-module-discovery.md`. El Gate 2 (`audit_2_passed`) sigue en `false`.

---

## 4. Audiencia y Casos de Uso Core

- **Usuarios principales:**
  - **Personal del negocio:** ante una disputa de devolución, fotografiar el pedido, indicar agregador y número de orden, enviar la imagen y, más tarde, pedirla con esa misma clave.

- **Fuera de alcance (Out of Scope explícito):**
  - Redactar la disputa, el motivo de la devolución o enviarla al portal o a la API de Uber o PedidosYa.
  - Importar el listado de pedidos desde el agregador.
  - Guardar en carpeta local o en un repositorio git. En esta prueba el destino es Supabase.
  - iOS y web en V1.
  - Cuentas de usuario de la app, recorte, filtros o anotaciones sobre la foto.
  - Agregadores distintos de Uber y PedidosYa.
  - Reutilizar los proyectos Supabase ya existentes (`mercado-publico`, `geo-empresa`, `ramon-david`, `memin-clothes`, `vissiusscomp's Project`).

---

## 5. Objetivo y Beneficios Esperados

- **Objetivo:** Entregar la prueba en Android (APK Release) más una API que envía, guarda y devuelve la imagen en Supabase, siempre bajo la clave agregador + número de orden.
- **Beneficios esperados:**
  - Evidencia fotográfica del pedido tomada en el momento de la disputa.
  - Cada imagen se guarda y se pide con el agregador y el número de orden.
  - Una sola base de prueba para Uber y PedidosYa, separada por esa clave.

---

## 6. Criterios de Éxito en Formato BDD (Gherkin)

### Escenario 1: Evidencia enviada y recuperable

- **Dado que** el personal del negocio abre la app en Android con un pedido en disputa de devolución
- **Cuando** elige el agregador, ingresa el número de orden, saca la foto y la envía
- **Entonces** la API guarda la imagen en Supabase bajo ese agregador y ese número de orden, y una petición con la misma clave devuelve esa imagen

### Escenario 2: Validación de estándares

- **Dado que** se renderizan la cámara, el campo de número de orden, el selector de agregador y la acción de enviar
- **Cuando** el agente compile la interfaz
- **Entonces** los estilos consumen tokens de `standards/design-system.md` o el theme documentado en `04-application-design.md`

---

## 7. Matriz de Restricciones Técnicas y Operativas

| Categoría | Restricción / Límite | Impacto | Estándar asociado |
| :--- | :--- | :--- | :--- |
| **Tiempo** | Sin fecha límite informada por Negocio | `Medio` | `ROADMAP.md` |
| **Tecnología** | `Expo SDK 52, RN 0.76.x, TypeScript` | `Alto` | `standards/coding-standards.md` |
| **Plataforma V1** | `Android APK release sin Metro` | `Alto` | WIKA-ARCH-03 |
| **Diseño / UX** | Tokens base; mockup pendiente en `04-application-design.md` | `Alto` | `standards/design-system.md` |
| **Destino de prueba** | Una base Supabase para Uber y PedidosYa. La clave de guardado y de consulta es agregador + número de orden. Proyecto `nfryurrhgaeepdwqtswo` (`sa-east-1`) | `Bloqueante` | WIKA-ARCH-01 |
| **Seguridad** | La app no lleva la clave `service_role`. Enviar y pedir pasan por la API. RLS activo en las tablas expuestas | `Alto` | `standards/coding-standards.md` |
| **Librerías prohibidas** | Versiones flotantes `^` en expo y react-native | `Bloqueante` | WIKA-ARCH-02 |
| **Red** | Enviar y pedir requieren conexión con Supabase. La foto puede quedar en la sesión hasta que el envío se confirme | `Alto` | `standards/coding-standards.md` |

---

## 8. Supuestos y Riesgos

- **Supuestos clave:**
  - «pedya» del pedido de Negocio se lee como **PedidosYa**.
  - El número de orden lo escribe el operador. No hay lectura de código ni consulta al agregador en V1.
  - Puede haber más de una foto para la misma clave. Un envío nuevo no borra las anteriores. Pedir devuelve las imágenes de ese agregador y ese número de orden.
  - **Supuesto de arquitectura, aceptado con el Gate 1:** el registro (agregador, número de orden, fecha, ruta del objeto) vive en Postgres y el archivo en Storage del mismo proyecto Supabase. Lo fija `03-module-discovery.md` (tabla `public.evidencia`, bucket `evidencia`).
  - El proyecto Supabase de esta prueba es `nfryurrhgaeepdwqtswo`. No se escribe en los proyectos de otros productos.
- **Riesgos identificados:** Un permiso de cámara denegado o una API caída deja la evidencia sin guardar.
- **Plan de mitigación:** La app no declara éxito de envío si la API no confirmó el guardado. La clave `service_role` no entra en el cliente Android.

### Decisiones de Negocio

| ID | Decisión | Estado |
| :--- | :--- | :--- |
| `DEC-01` | Dónde se guarda la prueba, para Uber y para PedidosYa | `CERRADA` — una base Supabase, la misma para ambos |
| `DEC-02` | Cómo se envía, se guarda y se pide | `CERRADA` — API con enviar, guardar y pedir |
| `DEC-03` | Con qué clave se nombra y se recupera la imagen | `CERRADA` — agregador + número de orden |
| `DEC-04` | Id del proyecto Supabase de app-delivery | `CERRADA` — `nfryurrhgaeepdwqtswo`, región `sa-east-1`, URL `https://nfryurrhgaeepdwqtswo.supabase.co` |

---

## 9. Puerta de Enlace y Firma de Auditoría de Documentación

### Checklist de criterios de aceptación

- [x] YAML frontmatter completado (`id`, `status`, `owner`, fechas).
- [x] Problemas `ERR-XX` mapeados a `FEAT-XX` y módulos sugeridos en RTM.
- [x] Criterios de éxito en formato BDD (Dado / Cuando / Entonces).
- [x] Out-of-scope explícito documentado.
- [x] Restricciones técnicas alineadas a `standards/coding-standards.md`.
- [x] Auditoría registrada en `audits/auditoria-documentacion.md` con resultado `[APROBADO]`.

### Registro de visto bueno

- **Aprobado por (Arquitecto):** `Negocio, instrucción explícita del 2026-11-05`
- **Fecha de aprobación:** `2026-11-05`
- **audit_1_passed:** `true`
