---
id: "FEAT-001"
title: "Especificación de Requerimientos — app-delivery"
status: "APROBADO"
version: "1.1.0"
owner: "Negocio / Equipo WIKA"
created_at: "2026-11-05"
updated_at: "2026-11-05"
audit_1_passed: true
---

# [02] Especificación de Características y Requerimientos Funcionales

> **Gate 1:** este documento se aprueba **junto con** `01-problem.md`.  
> **Equivalencia:** Auditoría de Documentación → `docs/auditoria-documentacion.md`.  
> El Gate 2 (Auditoría de Módulos) no se registra en este documento; vive en `03-module-discovery.md`.

## 1. Identificación y Control de Cambios

- **Nombre del Proyecto:** `app-delivery`
- **Documento base:** `idea/01-problem.md` (ID: `PROB-001`)
- **Estado de gatekeeping:** `AUDIT_1_APROBADO`

---

## 2. Matriz de Trazabilidad de Requerimientos (RTM 1:1)

| ID Feature | ID Problema (`01-problem.md`) | Nombre de la Característica | Prioridad | Módulo Destino (`03-module-discovery.md`) |
| :--- | :--- | :--- | :--- | :--- |
| `FEAT-01` | `ERR-01` | Sacar foto | `Crítica` | `mod-camera` |
| `FEAT-02` | `ERR-02` | Identificar la imagen con el número de orden | `Crítica` | `mod-order-name` |
| `FEAT-03` | `ERR-03` | Definir agregador | `Crítica` | `mod-aggregator` |
| `FEAT-04` | `ERR-04` | Enviar y guardar la imagen en Supabase | `Crítica` | `mod-evidence-api` |
| `FEAT-05` | `ERR-05` | Pedir la imagen por agregador y número de orden | `Crítica` | `mod-evidence-api` |

---

## 3. Funcionalidades Obligatorias

### Feature `FEAT-01`: Sacar foto

**Descripción:** La app abre la cámara del dispositivo y captura una foto del pedido. Esa foto es la evidencia para pelear la disputa de devolución.

#### Escenario 1.1: Flujo exitoso (Happy Path)

- **Dado que** la app tiene permiso de cámara y hay un pedido que el negocio va a disputar
- **Cuando** el operador toma la foto del pedido
- **Entonces** la app conserva esa imagen en la sesión, lista para enviarla

#### Escenario 1.2: Manejo de errores

- **Dado que** el permiso de cámara está denegado o la cámara no está disponible
- **Cuando** el operador intenta sacar la foto
- **Entonces** la app no se cierra, informa que no pudo capturar y no llama a la API con una imagen vacía

---

### Feature `FEAT-02`: Identificar la imagen con el número de orden

**Descripción:** Cada envío y cada consulta llevan el número de orden escrito por el operador, junto con el agregador. Esa pareja es el nombre lógico de la evidencia.

**Regla V1:** el número de orden se guarda sin espacios al inicio ni al final. Un envío nuevo con la misma pareja no borra las fotos anteriores.

#### Escenario 2.1: Flujo exitoso

- **Dado que** el operador ingresó un número de orden y ya sacó la foto
- **Cuando** envía la imagen
- **Entonces** el registro guardado contiene ese número de orden

#### Escenario 2.2: Validación de entrada

- **Dado que** el número de orden está vacío
- **Cuando** el operador confirma el envío
- **Entonces** la app no llama a la API y señala que falta el número de orden

---

### Feature `FEAT-03`: Definir agregador

**Descripción:** El operador indica el agregador del pedido antes de enviar o de pedir. El catálogo de la prueba es cerrado. Uber y PedidosYa comparten la misma base; el agregador es un dato del registro, no una base distinta.

**Catálogo V1:** `uber` | `pedidosya`.  
**Lectura del pedido de Negocio:** «pedya» se documenta como PedidosYa.

#### Escenario 3.1: Flujo exitoso

- **Dado que** el pedido pertenece a Uber o a PedidosYa
- **Cuando** el operador elige ese agregador y envía
- **Entonces** el registro en Supabase queda marcado con ese agregador

#### Escenario 3.2: Validación de entrada

- **Dado que** no hay agregador elegido, o el valor no está en el catálogo
- **Cuando** el operador confirma el envío o la consulta
- **Entonces** la API no guarda ni devuelve una imagen de otro agregador, y la app señala que falta un agregador válido

---

### Feature `FEAT-04`: Enviar y guardar la imagen en Supabase

**Descripción:** La app envía la foto a la API de prueba. La API la guarda en el proyecto Supabase de app-delivery, asociada al agregador y al número de orden.

**Destino:** proyecto Supabase `nfryurrhgaeepdwqtswo` (`DEC-04`). No se escribe en `mercado-publico` ni en los otros proyectos de otros productos.

**Almacenamiento:** fila en Postgres (`public.evidencia`) con agregador, número de orden, ruta del objeto y fecha; archivo en el bucket Storage `evidencia` del mismo proyecto. Lo especifica `03-module-discovery.md`.

#### Escenario 4.1: Flujo exitoso

- **Dado que** hay foto, número de orden, agregador del catálogo y la API puede escribir en Supabase
- **Cuando** el operador envía
- **Entonces** la API guarda la imagen bajo esa clave y la app confirma el envío solo después de esa respuesta

#### Escenario 4.2: Manejo de errores

- **Dado que** Supabase no está disponible o la API rechaza el guardado
- **Cuando** el operador envía
- **Entonces** la app no confirma el guardado, conserva la foto de la sesión y explica que la base no recibió la imagen

---

### Feature `FEAT-05`: Pedir la imagen por agregador y número de orden

**Descripción:** La API devuelve las imágenes guardadas para un agregador y un número de orden. Sirve para recuperar la evidencia de la disputa.

#### Escenario 5.1: Flujo exitoso

- **Dado que** ya se guardó al menos una imagen para `uber` o `pedidosya` y un número de orden
- **Cuando** se pide esa misma pareja
- **Entonces** la API devuelve esas imágenes y no incluye las de otro agregador ni las de otra orden

#### Escenario 5.2: Manejo de errores

- **Dado que** no hay imágenes para esa pareja, o faltan agregador o número de orden
- **Cuando** se hace la petición
- **Entonces** la API responde sin imagen y sin error de servidor, e indica que no hay evidencia para esa clave

---

## 4. Contrato de la API de prueba

La app y cualquier cliente de la prueba hablan solo con esta API. La clave `service_role` no sale del servidor.

| Operación | Qué hace | Entrada obligatoria | Resultado |
| :--- | :--- | :--- | :--- |
| Enviar | Sube la foto | `agregador`, `numero_orden`, imagen | Llama a guardar |
| Guardar | Persiste en Supabase | la misma clave y la imagen | Registro recuperable por esa clave |
| Pedir | Lee la evidencia | `agregador`, `numero_orden` | Imágenes de esa pareja, o ninguna |

`agregador` admite solo `uber` y `pedidosya`.

---

## 5. Funcionalidades Deseables (V1.1+)

| ID Feature | Nombre | Prioridad | Notas |
| :--- | :--- | :--- | :--- |
| `FEAT-06` | Leer el número de orden desde un código o QR | `Media` | En la prueba el número se escribe a mano |
| `FEAT-07` | Un destino distinto por agregador (carpeta o repositorio) | `Baja` | La prueba usa una sola base Supabase |

---

## 6. Fuera de Alcance

- Crear, redactar o enviar la disputa en Uber o PedidosYa.
- Traer pedidos desde el agregador.
- Carpeta local y repositorio git como destino de esta prueba.
- iOS, web, cuentas de usuario de la app y edición de la foto.
- Agregadores fuera de Uber y PedidosYa.
- Escribir en proyectos Supabase de otros productos.

---

## 7. Requerimientos No Funcionales (NFRs) Medibles

| ID NFR | Categoría | Criterio aceptable | Método de validación |
| :--- | :--- | :--- | :--- |
| `NFR-01` | **Captura** | Con permiso de cámara, una toma deja una imagen en la sesión y la app sigue abierta | Prueba manual en dispositivo |
| `NFR-02` | **Clave** | Todo registro confirmado contiene el agregador y el número de orden enviados | Lectura en Supabase |
| `NFR-03` | **Guardado** | La app confirma el envío solo si la API respondió que Supabase guardó la imagen | Prueba de envío con la API en marcha |
| `NFR-04` | **Consulta** | Pedir una pareja devuelve solo las imágenes de esa pareja | Prueba con dos agregadores y dos órdenes |
| `NFR-05` | **Build** | APK release compila sin Metro | `scripts/build-apk.sh` |
| `NFR-06` | **Permiso** | Sin permiso de cámara no hay captura y no hay crash | Prueba manual con permiso denegado |
| `NFR-07` | **Fidelidad visual** | 100% tokens documentados en la UI de captura | Revisión en `04-application-design.md` |
| `NFR-08` | **Secreto** | El cliente Android no contiene `service_role` | Revisión del build de la app |

Enviar y pedir se validan con red hacia el proyecto Supabase `nfryurrhgaeepdwqtswo`.

---

## 8. Mapeo de UI y Componentes (si aplica)

| Componente UI | Pantalla / Vista | Tokens (`standards/design-system.md`) | Estado mockup |
| :--- | :--- | :--- | :--- |
| `CameraCapture` | Captura | `surface`, `spacing.md` | `PENDIENTE` |
| `OrderNumberField` | Captura | `surface`, `spacing.sm` | `PENDIENTE` |
| `AggregatorPicker` | Captura | `accent`, `spacing.sm` | `PENDIENTE` |
| `SendEvidenceButton` | Captura | `accent`, `spacing.md` | `PENDIENTE` |
| `RequestEvidence` | Consulta | `surface`, `spacing.md` | `PENDIENTE` |

---

## 9. Puerta de Enlace y Firma de Auditoría de Documentación

### Checklist

- [x] Frontmatter YAML vinculado a `PROB-001`.
- [x] RTM 1:1 con IDs `ERR-XX` de `01-problem.md`.
- [x] Escenarios BDD por feature obligatoria.
- [x] NFRs con métricas verificables.
- [x] Deseables y fuera de alcance diferenciados.
- [x] `audits/auditoria-documentacion.md` en estado `[APROBADO]`.

### Registro de visto bueno

- **Aprobado por (Arquitecto):** `Negocio, instrucción explícita del 2026-11-05`
- **Fecha:** `2026-11-05`
- **audit_1_passed:** `true`
