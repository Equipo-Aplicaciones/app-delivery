# app-delivery v1

Cámara Android para evidencias de disputa. La API es la Edge Function `evidencia` del proyecto `nfryurrhgaeepdwqtswo`.

```bash
cp .env.example .env
# EXPO_PUBLIC_EVIDENCIA_API_KEY sale de public.evidencia_clave y no se commitea
npm install
npm run typecheck
npm run smoke
```

El APK ya armado para el teléfono está en `apk/app-delivery.apk`. Para generarlo de nuevo hace falta JDK 17 y Android SDK: `npm run apk`.
