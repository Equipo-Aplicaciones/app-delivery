# app-delivery en esta máquina

Copia de `iterations/v1`. La cámara saca la foto y después el operador la rotula con número de orden y agregador (`uber`, `pedidosya`, `rappi`). El envío va a la API local `captura/api`, no a Supabase.

```bash
cp .env.example .env
# EXPO_PUBLIC_EVIDENCIA_API_KEY es captura/data/upload-key (solo sube).
# captura/data/read-key no se copia a la app: la usa el otro proyecto.
```

El APK de `iterations/v1/apk` es un puntero de Git LFS, no el binario. Para armar uno nuevo contra esta API hace falta JDK 17, Android SDK y Node: `npm install` y `npm run apk`.
