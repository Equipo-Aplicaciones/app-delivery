app-delivery — proyecto WIKA

Fuente: wika-fundaments @ wika-fundaments-v2
Ruta: proyectos/app/app-delivery/

Producto de prueba (Negocio, 2026-11-05):
- Cámara para fotografiar el pedido en una disputa de devolución
- Clave de la evidencia: agregador (Uber o PedidosYa) + número de orden
- API para enviar, guardar y pedir la imagen
- Destino: proyecto Supabase nfryurrhgaeepdwqtswo

Estado:
- Gate 1, Gate 2, Gate 3A y Gate 3B APROBADOS
- ready_for_construction: true
- iterations/v1/ construido: Captura /, Consulta /consulta, engine y cliente HTTP
- Edge Function evidencia activa en https://nfryurrhgaeepdwqtswo.supabase.co/functions/v1/evidencia
- Tabla public.evidencia, bucket evidencia, clave en public.evidencia_clave
- npm run smoke y npm run typecheck OK
- APK release para sideload: iterations/v1/apk/app-delivery.apk
- Firmado con el certificado debug de esta máquina. El teléfono debe permitir orígenes desconocidos
- audits/auditoria-release-v1.md → REQUIERE_CORRECCIONES
- review.md sin firma
- final/ vacío

Siguiente: npm run apk en una máquina con JDK 17 y SDK. Después el arquitecto firma review.md y la release.
